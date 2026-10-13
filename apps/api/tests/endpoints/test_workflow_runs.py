"""Tests for the workflow run endpoints (ADR 0021).

These run against the live Postgres that ``root:services`` boots. The
engine is not running: a started run stays ``queued``.
"""

import asyncio
import collections.abc
import contextlib
import datetime
import typing
import uuid
from unittest import mock

import fastapi
import httpx

from apps.api.tests import support
from imbi.api import agent_tasks, email, models, workflows
from imbi.api.auth import organizations, permissions
from imbi.api.endpoints import project_deployments, workflow_runs
from imbi.common import graph
from imbi.common.plugins import base as plugin_base
from imbi.common.workflows import graph as wf

PERMISSIONS = frozenset(
    {
        'workflow:read',
        'workflow:create',
        'workflow:write',
        'workflow:delete',
        'workflow:run',
        'project:deployment:write',
    }
)

RUNTIME_TABLES = ('runs', 'step_runs', 'run_events', 'side_effects')


def _node(
    node_id: str, step: str, params: dict[str, typing.Any] | None = None
) -> dict[str, typing.Any]:
    return {
        'id': node_id,
        'key': node_id,
        'type': step,
        'title': node_id.title(),
        'position': {'x': 0, 'y': 0},
        'params': params or {},
    }


def _graph(team: str, project: str) -> dict[str, typing.Any]:
    """wait -> model decision -> deploy -> email, and an email branch."""
    email = {
        'to': [{'kind': 'team', 'id': team}],
        'subject': 'Shipped',
        'body': 'Shipped',
    }
    return {
        'nodes': [
            _node(
                'start',
                'manual',
                {'inputs': [{'name': 'version', 'type': 'string'}]},
            ),
            _node('pause', 'wait', {'duration': '10m'}),
            _node(
                'decide',
                'model_decision',
                {
                    'model_id': 'jev',
                    'prompt': 'Ship {{ trigger.version }}?',
                    'branches': ['ship', 'hold'],
                },
            ),
            _node(
                'ship',
                'deploy',
                {
                    'project_id': project,
                    'environment': 'staging',
                    'version': '{{ trigger.version }}',
                },
            ),
            _node('hold', 'email', email),
            _node('tell', 'email', email),
        ],
        'edges': [
            {'source': 'start', 'port': 0, 'target': 'pause'},
            {'source': 'pause', 'port': 0, 'target': 'decide'},
            {'source': 'decide', 'port': 0, 'target': 'ship'},
            {'source': 'decide', 'port': 1, 'target': 'hold'},
            {'source': 'ship', 'port': 0, 'target': 'tell'},
        ],
    }


class _OneConnection:
    """A pool that hands out one connection, inside its transaction."""

    def __init__(self, conn: typing.Any) -> None:
        self.conn = conn

    @contextlib.asynccontextmanager
    async def connection(self) -> collections.abc.AsyncIterator[typing.Any]:
        yield self.conn


class HeldRunStore(workflows.RunStore):
    """Leases each new run to no one in the transaction that writes it.

    Engines of other worktrees share the test database; without this
    they claim and execute the runs that these tests leave queued.
    """

    async def create(
        self, run: workflows.NewRun
    ) -> tuple[workflows.Row, bool]:
        async with self._pool.connection() as conn, conn.transaction():
            row, created = await workflows.RunStore(
                typing.cast(typing.Any, _OneConnection(conn))
            ).create(run)
            if created:
                await conn.execute(
                    'INSERT INTO workflow_runtime.leases'
                    ' (run_id, worker_id, expires_at)'
                    " VALUES (%s, 'test-hold', NOW() + INTERVAL '1 hour')",
                    (row['id'],),
                )
            return row, created


class WorkflowRunTestCase(support.SharedAppAsyncTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        suffix = uuid.uuid4().hex[:10]
        self.org = f'wfr-{suffix}'
        self.team = f'team-{suffix}'
        self.project = f'proj-{suffix}'
        self.email = f'dev-{suffix}@example.com'
        self.base = f'/organizations/{self.org}/workflows'
        await graph.initialize()
        await workflows.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.pool = workflows.create_pool()
        await self.pool.open()
        self.store = workflows.WorkflowStore(self.pool)
        self.runs = HeldRunStore(self.pool)
        self.addAsyncCleanup(self._cleanup)
        await self.graph.execute(
            """
            CREATE (o:Organization {{id: {org}, slug: {org}, name: {org}}})
            CREATE (t:Team {{id: {team}, slug: {team}, name: 'Ops'}})
            CREATE (t)-[:BELONGS_TO]->(o)
            CREATE (u:User {{id: {email}, email: {email},
                             display_name: 'Dev', is_active: true}})
            CREATE (u)-[:MEMBER_OF {{role: 'developer'}}]->(o)
            CREATE (u)-[:MEMBER_OF]->(t)
            CREATE (p:Project {{id: {project}, slug: {project}, name: 'P'}})
            CREATE (p)-[:OWNED_BY]->(t)
            RETURN o.id AS id
            """,
            {
                'org': self.org,
                'team': self.team,
                'email': self.email,
                'project': self.project,
            },
            ['id'],
        )
        user = models.User(
            id=self.email,
            email=self.email,
            display_name='Dev',
            is_active=True,
            is_admin=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        async def current_user() -> permissions.AuthContext:
            return permissions.AuthContext(
                user=user,
                session_id='test-session',
                auth_method='jwt',
                permissions=set(PERMISSIONS),
            )

        overrides = self.test_app.dependency_overrides
        overrides[permissions.get_current_user] = current_user
        overrides[graph._inject_graph] = lambda: self.graph
        overrides[workflows._inject_store] = lambda: self.store
        overrides[workflows.run_store] = lambda: self.runs
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.test_app),
            base_url='http://test',
        )

    async def _cleanup(self) -> None:
        await self.client.aclose()
        await self.graph.execute(
            """
            MATCH (n) WHERE n.id IN {ids}
            DETACH DELETE n
            RETURN 1 AS ok
            """,
            {'ids': [self.org, self.team, self.email, self.project]},
            ['ok'],
        )
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM workflow_runtime.runs WHERE organization_id = %s',
                (self.org,),
            )
            await conn.execute(
                'DELETE FROM workflows.workflows WHERE organization_id = %s',
                (self.org,),
            )
        await self.pool.close()
        await self.graph.close()

    async def _workflow(
        self,
        *,
        activate: bool = True,
        name: str = 'Deploy guard',
        settings: dict[str, typing.Any] | None = None,
    ) -> str:
        response = await self.client.post(
            self.base + '/',
            json={
                'name': name,
                'owner_team_slug': self.team,
                'graph': _graph(self.team, self.project),
                'settings': settings or {},
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        url = f'{self.base}/{response.json()["slug"]}'
        if activate:
            response = await self.client.post(f'{url}/activate')
            self.assertEqual(response.status_code, 200, response.text)
        return url

    async def _workflow_id(self, url: str) -> uuid.UUID:
        row = await self.store.get(self.org, url.rsplit('/', 1)[1])
        assert row is not None
        return row['id']

    async def _forget(self, key: str) -> None:
        """Delete the side effects whose caller key contains ``key``."""
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM workflow_runtime.side_effects WHERE key LIKE %s',
                (f'%{key}%',),
            )

    async def _counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        async with self.pool.connection() as conn:
            for table in RUNTIME_TABLES:
                cur = await conn.execute(
                    f'SELECT COUNT(*) FROM workflow_runtime.{table}'
                )
                row = await cur.fetchone()
                counts[table] = row[0] if row else 0
        return counts


class TestRunTestCase(WorkflowRunTestCase):
    async def test_test_run_sends_nothing_and_writes_nothing(self) -> None:
        url = await self._workflow()
        before = await self._counts()
        with (
            mock.patch('imbi.api.email.client.EmailClient.send_email') as send,
            mock.patch('imbi.common.llm.typesafe.decide') as decide,
            mock.patch.object(
                project_deployments, '_trigger_deployment'
            ) as deploy,
        ):
            response = await self.client.post(f'{url}/test-runs')
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(
                [s['node_id'] for s in body['steps']],
                ['start', 'pause', 'decide', 'ship', 'tell'],
            )
            self.assertEqual(body['skipped'], ['hold'])
            ship = body['steps'][3]
            self.assertEqual(ship['port_name'], 'Succeeded')
            self.assertEqual(ship['output']['deployment_id'], 'sample')

            response = await self.client.post(
                f'{url}/test-runs', json={'ports': {'decide': 1}}
            )
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(
                [s['node_id'] for s in body['steps']],
                ['start', 'pause', 'decide', 'hold'],
            )
            self.assertEqual(sorted(body['skipped']), ['ship', 'tell'])

            response = await self.client.post(
                f'{url}/test-runs', json={'ports': {'decide': 5}}
            )
            self.assertEqual(response.status_code, 422)
        send.assert_not_called()
        decide.assert_not_called()
        deploy.assert_not_called()
        self.assertEqual(await self._counts(), before)

    def test_simulate_without_a_trigger_is_422(self) -> None:
        with self.assertRaises(fastapi.HTTPException) as raised:
            workflow_runs.simulate(wf.Graph(), None, {})
        self.assertEqual(raised.exception.status_code, 422)

    async def test_test_run_refuses_errors(self) -> None:
        response = await self.client.post(
            self.base + '/',
            json={'name': 'Empty', 'owner_team_slug': self.team},
        )
        self.assertEqual(response.status_code, 201, response.text)
        response = await self.client.post(f'{self.base}/empty/test-runs')
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()['detail']['error'], 'validation_failed'
        )


class ManualRunTestCase(WorkflowRunTestCase):
    async def test_start_list_get_cancel(self) -> None:
        url = await self._workflow()
        headers = {'Idempotency-Key': 'k1'}
        response = await self.client.post(
            f'{url}/runs',
            json={'inputs': {'version': '1.2.3'}},
            headers=headers,
        )
        self.assertEqual(response.status_code, 202, response.text)
        run = response.json()
        self.assertEqual(run['status'], 'queued')
        self.assertEqual(run['payload'], {'version': '1.2.3'})
        self.assertEqual(run['origin_kind'], 'human')
        self.assertEqual(run['origin_id'], self.email)
        self.assertEqual(run['trigger_node_id'], 'start')
        self.assertEqual(run['version'], 1)

        response = await self.client.post(
            f'{url}/runs',
            json={'inputs': {'version': '9.9.9'}},
            headers=headers,
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['id'], run['id'])

        response = await self.client.get(f'{url}/runs')
        self.assertEqual([r['id'] for r in response.json()], [run['id']])

        response = await self.client.get(f'{url}/runs/{run["id"]}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['steps'], [])

        response = await self.client.get(f'{url}/runs/{uuid.uuid4()}')
        self.assertEqual(response.status_code, 404)

        response = await self.client.delete(url)
        self.assertEqual(response.status_code, 409)

        response = await self.client.post(f'{url}/runs/{run["id"]}/cancel')
        self.assertEqual(response.status_code, 202, response.text)
        self.assertTrue(response.json()['cancel_requested'])

        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE workflow_runtime.runs SET status = 'cancelled'"
                ' WHERE id = %s',
                (run['id'],),
            )
        response = await self.client.post(f'{url}/runs/{run["id"]}/cancel')
        self.assertEqual(response.status_code, 409)

    async def test_one_key_starts_one_run_per_workflow(self) -> None:
        """One webhook delivery can start runs of two workflows."""

        def new_run(workflow_id: uuid.UUID) -> workflows.NewRun:
            return workflows.NewRun(
                organization_id=self.org,
                workflow_id=workflow_id,
                version=1,
                trigger_node_id='hook',
                origin_kind='webhook',
                origin_id='wh-1',
                origin={},
                idempotency_key='delivery-1',
                payload={},
                concurrency_key=None,
                activated_by=self.email,
            )

        first = await self._workflow_id(await self._workflow(name='Guard A'))
        second = await self._workflow_id(await self._workflow(name='Guard B'))
        a, created_a = await self.runs.create(new_run(first))
        b, created_b = await self.runs.create(new_run(second))
        again, created_again = await self.runs.create(new_run(first))
        self.assertTrue(created_a and created_b)
        self.assertNotEqual(a['id'], b['id'])
        self.assertEqual(b['workflow_id'], second)
        self.assertFalse(created_again)
        self.assertEqual(again['id'], a['id'])

    async def test_delete_waits_for_a_run_being_written(self) -> None:
        """A delete and a new run serialize on the workflow row."""
        url = await self._workflow()
        workflow_id = await self._workflow_id(url)
        new_run = workflows.NewRun(
            organization_id=self.org,
            workflow_id=workflow_id,
            version=1,
            trigger_node_id='start',
            origin_kind='human',
            origin_id=self.email,
            origin={},
            idempotency_key=None,
            payload={'version': '1'},
            concurrency_key=None,
            activated_by=self.email,
        )
        async with self.pool.connection() as conn, conn.transaction():
            # The lock a delete takes before its open-run check.
            await conn.execute(
                'SELECT 1 FROM workflows.workflows WHERE id = %s FOR UPDATE',
                (workflow_id,),
            )
            create = asyncio.create_task(self.runs.create(new_run))
            await asyncio.sleep(0.3)
            self.assertFalse(create.done())
            await conn.execute(
                'DELETE FROM workflows.workflows WHERE id = %s', (workflow_id,)
            )
        with self.assertRaises(workflows.NotActive):
            await create

    async def test_empty_concurrency_key_input_is_422(self) -> None:
        url = await self._workflow(
            settings={
                'concurrency_mode': 'one_per_key',
                'concurrency_key': '{{ trigger.version }}',
            }
        )
        response = await self.client.post(
            f'{url}/runs', json={'inputs': {'version': ''}}
        )
        self.assertEqual(response.status_code, 422, response.text)

    async def test_cancel_needs_the_start_gate(self) -> None:
        url = await self._workflow()
        response = await self.client.post(
            f'{url}/runs', json={'inputs': {'version': '1'}}
        )
        run_id = response.json()['id']
        await self.graph.execute(
            """
            MATCH (:User {{email: {email}}})-[m:MEMBER_OF]->(:Team)
            DELETE m
            RETURN 1 AS ok
            """,
            {'email': self.email},
            ['ok'],
        )
        response = await self.client.post(f'{url}/runs/{run_id}/cancel')
        self.assertEqual(response.status_code, 403, response.text)
        run = await self.client.get(f'{url}/runs/{run_id}')
        self.assertFalse(run.json()['cancel_requested'])

        user = models.User(
            id=self.email,
            email=self.email,
            display_name='Dev',
            is_active=True,
            is_admin=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.test_app.dependency_overrides[permissions.get_current_user] = (
            lambda: permissions.AuthContext(
                user=user, auth_method='jwt', permissions=set(PERMISSIONS)
            )
        )
        response = await self.client.post(f'{url}/runs/{run_id}/cancel')
        self.assertEqual(response.status_code, 202, response.text)

    async def test_refusals(self) -> None:
        url = await self._workflow(activate=False)
        response = await self.client.post(
            f'{url}/runs', json={'inputs': {'version': '1'}}
        )
        self.assertEqual(response.status_code, 409)
        await self.client.post(f'{url}/activate')

        for inputs in ({}, {'version': 1}, {'version': '1', 'other': 'x'}):
            response = await self.client.post(
                f'{url}/runs', json={'inputs': inputs}
            )
            self.assertEqual(response.status_code, 422, inputs)

        response = await self.client.post(
            f'{url}/runs', json={'inputs': {'version': '1'}, 'trigger': 'x'}
        )
        self.assertEqual(response.status_code, 422)

        await self.graph.execute(
            """
            MATCH (:User {{email: {email}}})-[m:MEMBER_OF]->(:Team)
            DELETE m
            RETURN 1 AS ok
            """,
            {'email': self.email},
            ['ok'],
        )
        response = await self.client.post(
            f'{url}/runs', json={'inputs': {'version': '1'}}
        )
        self.assertEqual(response.status_code, 403, response.text)


class DeployIdempotencyTestCase(WorkflowRunTestCase):
    """The deploy endpoint's ``Idempotency-Key`` (ADR 0021)."""

    async def _deploy(
        self, key: str
    ) -> project_deployments.DeploymentTriggerResponse:
        return await project_deployments.trigger_deployment(
            org_slug=self.org,
            project_id='p1',
            body=project_deployments.DeployActionRequest(
                action='deploy', environment='staging', committish='abc'
            ),
            background=fastapi.BackgroundTasks(),
            db=typing.cast(typing.Any, None),
            valkey_client=None,
            auth=permissions.AuthContext(auth_method='client_credentials'),
            idempotency_key=key,
        )

    async def test_repeat_returns_first_response(self) -> None:
        key = f'run-{uuid.uuid4()}:ship'
        response = project_deployments.DeploymentTriggerResponse(
            run=plugin_base.DeploymentRun(run_id='r1', status='queued'),
            plugin_id='p',
            plugin_slug='github',
        )
        self.addAsyncCleanup(self._forget, key)
        with (
            mock.patch.object(
                project_deployments, 'run_store', return_value=self.runs
            ),
            mock.patch.object(
                project_deployments,
                '_trigger_deployment',
                mock.AsyncMock(return_value=response),
            ) as dispatch,
        ):
            first = await self._deploy(key)
            second = await self._deploy(key)
        self.assertEqual(dispatch.await_count, 1)
        self.assertEqual(second, first)

    async def test_key_released_during_a_repeat_is_409(self) -> None:
        """A repeat whose first call was refused between the repeat's
        INSERT and its SELECT gets outcome_unknown, not a 500."""
        key = f'run-{uuid.uuid4()}:ship'
        self.addAsyncCleanup(self._forget, key)
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO workflow_runtime.side_effects (key) VALUES (%s)',
                (workflows.runs.side_effect_key('a', 'deployment', key),),
            )
        call = mock.AsyncMock()
        with (
            mock.patch.object(workflows.RunStore, '_all', return_value=[]),
            self.assertRaises(fastapi.HTTPException) as raised,
        ):
            await self.runs.once('a', 'deployment', key, call)
        self.assertEqual(raised.exception.status_code, 409)
        call.assert_not_awaited()

    async def test_refusal_forgets_and_unknown_is_409(self) -> None:
        key = f'run-{uuid.uuid4()}:ship'
        self.addAsyncCleanup(self._forget, key)
        with (
            mock.patch.object(
                project_deployments, 'run_store', return_value=self.runs
            ),
            mock.patch.object(
                project_deployments,
                '_trigger_deployment',
                mock.AsyncMock(side_effect=fastapi.HTTPException(400)),
            ) as dispatch,
        ):
            for _ in range(2):
                with self.assertRaises(fastapi.HTTPException):
                    await self._deploy(key)
            self.assertEqual(dispatch.await_count, 2)

            dispatch.side_effect = fastapi.HTTPException(502)
            with self.assertRaises(fastapi.HTTPException):
                await self._deploy(key)
            with self.assertRaises(fastapi.HTTPException) as raised:
                await self._deploy(key)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            typing.cast(dict[str, str], raised.exception.detail)['error'],
            'outcome_unknown',
        )
        self.assertEqual(dispatch.await_count, 3)


class EngineEmailTestCase(WorkflowRunTestCase):
    """The engine-only email routes."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.url = await self._workflow()
        response = await self.client.post(
            f'{self.url}/runs', json={'inputs': {'version': '1'}}
        )
        self.run_id = response.json()['id']
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO workflow_runtime.step_runs (run_id, node_id,'
                ' node_key, node_type, title, status, input)'
                " VALUES (%s, 'tell', 'tell', 'email', 'Tell', 'running',"
                ' %s)',
                (
                    self.run_id,
                    workflows.runs.pg_json.Jsonb(
                        {
                            'to': [{'kind': 'team', 'id': self.team}],
                            'subject': 'Shipped 1',
                            'body': 'Deployment r1',
                        }
                    ),
                ),
            )
        self.sent: list[typing.Any] = []

        #: Addresses whose send fails.
        self.failing: set[str] = set()

        async def send_email(message: typing.Any) -> typing.Any:
            self.sent.append(message)
            failed = message.to_email in self.failing
            return mock.Mock(status='failed' if failed else 'sent')

        engine = permissions.AuthContext(
            service_account=models.ServiceAccount(
                slug='imbi-workflows', display_name='Imbi Workflows'
            ),
            auth_method='client_credentials',
        )
        overrides = self.test_app.dependency_overrides
        self.user_auth = overrides[permissions.get_current_user]
        overrides[permissions.get_current_user] = lambda: engine
        overrides[organizations.member_org_id] = lambda: self.org
        overrides[workflow_runs._email_client] = lambda: mock.Mock(
            send_email=send_email
        )
        patcher = mock.patch.object(email, '_save_audit', mock.AsyncMock())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addAsyncCleanup(self._forget, str(self.run_id))

    async def test_step_email_once(self) -> None:
        url = f'{self.url}/runs/{self.run_id}/steps/tell/email'
        headers = {'Idempotency-Key': f'{self.run_id}:k'}
        for _ in range(2):
            response = await self.client.post(url, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(
                response.json(), {'recipients': [self.email], 'failed': []}
            )
        self.assertEqual(
            [(m.to_email, m.subject, m.text_body) for m in self.sent],
            [(self.email, 'Shipped 1', 'Deployment r1')],
        )

        response = await self.client.post(
            f'{self.url}/runs/{self.run_id}/steps/start/email',
            headers=headers,
        )
        self.assertEqual(response.status_code, 404)

    async def test_partial_send_reaches_everyone_once(self) -> None:
        other = f'other-{uuid.uuid4().hex[:8]}@example.com'
        self.addAsyncCleanup(self._delete_user, other)
        await self.graph.execute(
            """
            MATCH (t:Team {{id: {team}}})
            CREATE (u:User {{id: {email}, email: {email},
                             display_name: 'Other', is_active: true}})
            CREATE (u)-[:MEMBER_OF]->(t)
            RETURN 1 AS ok
            """,
            {'team': self.team, 'email': other},
            ['ok'],
        )
        self.failing.add(self.email)
        url = f'{self.url}/runs/{self.run_id}/steps/tell/email'
        headers = {'Idempotency-Key': f'{self.run_id}:k'}
        for _ in range(2):
            response = await self.client.post(url, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(
                response.json(),
                {'recipients': [other], 'failed': [self.email]},
            )
        self.assertEqual(
            sorted(m.to_email for m in self.sent), sorted([self.email, other])
        )

    async def _delete_user(self, address: str) -> None:
        await self.graph.execute(
            'MATCH (u:User {{email: {email}}}) DETACH DELETE u RETURN 1 AS ok',
            {'email': address},
            ['ok'],
        )

    async def test_one_key_on_two_routes_does_not_meet(self) -> None:
        headers = {'Idempotency-Key': f'{self.run_id}:k'}
        response = await self.client.post(
            f'{self.url}/runs/{self.run_id}/steps/tell/email', headers=headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE workflow_runtime.runs SET status = 'failed'"
                ' WHERE id = %s',
                (self.run_id,),
            )
        response = await self.client.post(
            f'{self.url}/runs/{self.run_id}/failure-notice', headers=headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [m.subject for m in self.sent],
            ['Shipped 1', 'Workflow Deploy guard failed'],
        )

    async def test_only_the_engine(self) -> None:
        overrides = self.test_app.dependency_overrides
        overrides[permissions.get_current_user] = self.user_auth
        response = await self.client.post(
            f'{self.url}/runs/{self.run_id}/steps/tell/email',
            headers={'Idempotency-Key': 'x'},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.sent, [])

    async def test_failure_notice(self) -> None:
        url = f'{self.url}/runs/{self.run_id}/failure-notice'
        headers = {'Idempotency-Key': f'{self.run_id}:k'}
        response = await self.client.post(url, headers=headers)
        self.assertEqual(response.status_code, 409)
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE workflow_runtime.runs SET status = 'failed',"
                " error = 'outcome_unknown' WHERE id = %s",
                (self.run_id,),
            )
        response = await self.client.post(url, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(), {'recipients': [self.email], 'failed': []}
        )
        self.assertEqual(self.sent[0].subject, 'Workflow Deploy guard failed')


class EngineAgentTaskTestCase(WorkflowRunTestCase):
    """The engine-only agent task routes of an agent step."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.admin = f'admin-{uuid.uuid4().hex[:8]}@example.com'
        self.agent = f'agent-{uuid.uuid4().hex[:8]}'
        self.plain = f'plain-{uuid.uuid4().hex[:8]}@example.com'
        await self.graph.execute(
            """
            MATCH (o:Organization {{id: {org}}})
            CREATE (u:User {{id: {admin}, email: {admin},
                             display_name: 'Admin', is_active: true,
                             is_admin: true}})
            CREATE (u)-[:MEMBER_OF {{role: 'admin'}}]->(o)
            CREATE (p:User {{id: {plain}, email: {plain},
                             display_name: 'Plain', is_active: true}})
            CREATE (p)-[:MEMBER_OF {{role: 'no-such-role'}}]->(o)
            CREATE (a:Agent {{id: {agent}, slug: {agent}, name: 'Fixer',
                              enabled: true, settings: '{{"task_budget": 5}}',
                              version: 1, org_id: {org}}})
            CREATE (a)-[:BELONGS_TO]->(o)
            RETURN o.id AS id
            """,
            {
                'org': self.org,
                'admin': self.admin,
                'plain': self.plain,
                'agent': self.agent,
            },
            ['id'],
        )
        await agent_tasks.initialize()
        self.task_pool = agent_tasks.create_pool()
        await self.task_pool.open()
        self.tasks = agent_tasks.TaskStore(self.task_pool)
        self.addAsyncCleanup(self._cleanup_tasks)
        await self._agent_run({'agent_id': self.agent, 'instruction': 'Go.'})
        engine = permissions.AuthContext(
            service_account=models.ServiceAccount(
                slug='imbi-workflows', display_name='Imbi Workflows'
            ),
            auth_method='client_credentials',
        )
        overrides = self.test_app.dependency_overrides
        self.user_auth = overrides[permissions.get_current_user]
        overrides[permissions.get_current_user] = lambda: engine
        overrides[organizations.member_org_id] = lambda: self.org
        overrides[agent_tasks._inject_store] = lambda: self.tasks

    async def _agent_run(
        self,
        pinned: dict[str, typing.Any],
        params: dict[str, typing.Any] | None = None,
    ) -> None:
        """Start a run of a workflow whose agent step has ``pinned``.

        ``params`` is the rendered input of the step; it defaults to
        ``pinned``.
        """
        slug = f'agent-{uuid.uuid4().hex[:8]}'
        await self.store.create(
            self.org,
            slug,
            workflows.Definition(
                name='Agent guard',
                description='',
                owner_team_id=self.team,
                graph={
                    'nodes': [
                        _node('start', 'manual'),
                        _node('ask', 'agent', pinned),
                    ],
                    'edges': [{'source': 'start', 'port': 0, 'target': 'ask'}],
                },
                settings={},
                validation={'issues': []},
                author=self.email,
            ),
        )
        await self.store.activate(self.org, slug, 1, self.admin, [])
        workflow = await self.store.get(self.org, slug)
        assert workflow is not None
        run, _ = await self.runs.create(
            workflows.NewRun(
                organization_id=self.org,
                workflow_id=workflow['id'],
                version=1,
                trigger_node_id='start',
                origin_kind='human',
                origin_id=self.email,
                origin={'kind': 'human', 'user': self.email},
                idempotency_key=None,
                payload={},
                concurrency_key=None,
                activated_by=self.admin,
            )
        )
        self.url = f'{self.base}/{slug}'
        self.run_id = str(run['id'])
        self.step_url = f'{self.url}/runs/{self.run_id}/steps/ask/agent-task'
        await self._agent_step(params or pinned)

    async def _agent_step(
        self, params: dict[str, typing.Any], activated_by: str | None = None
    ) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM workflow_runtime.step_runs'
                " WHERE run_id = %s AND node_id = 'ask'",
                (self.run_id,),
            )
            await conn.execute(
                'INSERT INTO workflow_runtime.step_runs (run_id, node_id,'
                ' node_key, node_type, title, status, input) VALUES (%s,'
                " 'ask', 'ask', 'agent', 'Ask', 'running', %s)",
                (self.run_id, workflows.runs.pg_json.Jsonb(params)),
            )
            await conn.execute(
                'UPDATE workflow_runtime.runs SET activated_by = %s'
                ' WHERE id = %s',
                (activated_by or self.admin, self.run_id),
            )

    async def _cleanup_tasks(self) -> None:
        await self.graph.execute(
            """
            MATCH (n) WHERE n.id IN {ids}
            OPTIONAL MATCH (n)-[:ACTS_AS]->(s:ServiceAccount)
            DETACH DELETE s, n
            RETURN 1 AS ok
            """,
            {'ids': [self.admin, self.plain, self.agent]},
            ['ok'],
        )
        async with self.task_pool.connection() as conn:
            await conn.execute(
                'DELETE FROM agent_runtime.tasks WHERE organization_id = %s',
                (self.org,),
            )
            await conn.execute(
                'DELETE FROM agent_runtime.task_id_sequences'
                ' WHERE organization_id = %s',
                (self.org,),
            )
        await self.task_pool.close()

    async def _count(self) -> int:
        async with self.task_pool.connection() as conn:
            cur = await conn.execute(
                'SELECT COUNT(*) FROM agent_runtime.tasks'
                ' WHERE organization_id = %s',
                (self.org,),
            )
            row = await cur.fetchone()
        return row[0] if row else 0

    async def test_make_once_then_cancel(self) -> None:
        first = await self.client.post(self.step_url)
        self.assertEqual(first.status_code, 200, first.text)
        again = await self.client.post(self.step_url)
        self.assertEqual(again.json(), first.json())
        self.assertEqual(
            first.json(),
            {
                'task_id': first.json()['task_id'],
                'status': 'queued',
                'outcome': None,
                'reason': None,
                'summary': None,
            },
        )
        self.assertEqual(await self._count(), 1)
        task = await self.tasks.get(self.org, first.json()['task_id'])
        assert task is not None
        self.assertEqual(task['owner'], self.admin)
        self.assertEqual(str(task['budget']), '5.000000')
        self.assertEqual(task['idempotency_key'], f'{self.run_id}:ask')
        self.assertEqual(
            task['origin'],
            {
                'kind': 'human',
                'user': self.email,
                'workflow_run_id': self.run_id,
                'node_key': 'ask',
            },
        )
        for _ in range(2):
            response = await self.client.post(self.step_url + '/cancel')
            self.assertEqual(response.status_code, 204, response.text)
        response = await self.client.post(self.step_url)
        self.assertEqual(
            (response.json()['status'], response.json()['outcome']),
            ('closed', 'cancelled_by_human'),
        )

    async def test_malformed_input_is_422(self) -> None:
        # Not a 500: the engine would retry it, and it fails each time.
        for params in ({'agent_id': self.agent}, {'budget': 'x'}):
            await self._agent_step(params)
            response = await self.client.post(self.step_url)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(
                response.json()['detail'], {'error': 'invalid_params'}
            )
        self.assertEqual(await self._count(), 0)

    async def test_budget_above_the_agent_is_422(self) -> None:
        await self._agent_step(
            {'agent_id': self.agent, 'instruction': 'Go.', 'budget': 6}
        )
        response = await self.client.post(self.step_url)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(await self._count(), 0)

    async def test_refusals(self) -> None:
        response = await self.client.post(
            f'{self.url}/runs/{self.run_id}/steps/start/agent-task'
        )
        self.assertEqual(response.status_code, 404)
        await self._agent_run({'agent_id': 'nope', 'instruction': 'Go.'})
        response = await self.client.post(self.step_url)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()['detail'], {'error': 'agent_not_found'}
        )
        # The activator is a member with no agent_task:create.
        await self._agent_run({'agent_id': self.agent, 'instruction': 'Go.'})
        await self._agent_step(
            {'agent_id': self.agent, 'instruction': 'Go.'},
            activated_by=self.plain,
        )
        response = await self.client.post(self.step_url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()['detail'], {'error': 'owner_forbidden'}
        )
        self.assertEqual(await self._count(), 0)

    async def test_only_the_engine(self) -> None:
        overrides = self.test_app.dependency_overrides
        overrides[permissions.get_current_user] = self.user_auth
        for path in ('', '/cancel'):
            response = await self.client.post(self.step_url + path)
            self.assertEqual(response.status_code, 403)
        self.assertEqual(await self._count(), 0)

    async def test_ids_come_from_the_pinned_version(self) -> None:
        # Run input renders a template to a literal id; it is refused.
        await self._agent_run(
            {'agent_id': '{{ trigger.agent }}', 'instruction': 'Go.'},
            {'agent_id': self.agent, 'instruction': 'Go.'},
        )
        response = await self.client.post(self.step_url)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()['detail'], {'error': 'agent_params_not_literal'}
        )
        # Rendered input that names another agent does not change it.
        await self._agent_run(
            {'agent_id': self.agent, 'instruction': 'Go.'},
            {'agent_id': 'other', 'instruction': 'Go.'},
        )
        response = await self.client.post(self.step_url)
        self.assertEqual(response.status_code, 200, response.text)
        task = await self.tasks.get(self.org, response.json()['task_id'])
        assert task is not None
        self.assertEqual(task['agent_id'], self.agent)

    async def _plant(self, origin: dict[str, typing.Any], agent: str) -> str:
        """Make a task with the step's origin and key, not by the step."""
        task, _ = await self.tasks.create(
            agent_tasks.NewTask(
                organization_id=self.org,
                agent_id=agent,
                agent_version=1,
                prompt_version=None,
                service_account_id='sa',
                project_id=None,
                project_slug=None,
                title='Planted',
                description='Planted',
                origin_kind='human',
                origin_id=self.email,
                origin=origin,
                idempotency_key=f'{self.run_id}:ask',
                owner=self.email,
                budget=None,
            ),
            agent_tasks.Actor('human', self.email, 'web'),
            {},
        )
        return task['short_id']

    async def test_task_with_the_key_not_made_by_the_step(self) -> None:
        short_id = await self._plant(
            {'kind': 'human', 'user': self.email}, self.agent
        )
        response = await self.client.post(self.step_url)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()['detail'], {'error': 'task_key_conflict'}
        )
        response = await self.client.post(self.step_url + '/cancel')
        self.assertEqual(response.status_code, 204)
        task = await self.tasks.get(self.org, short_id)
        assert task is not None
        self.assertEqual(task['control'], 'run')

    async def test_task_with_another_agent(self) -> None:
        await self._plant(
            {
                'kind': 'human',
                'user': self.email,
                'workflow_run_id': self.run_id,
                'node_key': 'ask',
            },
            'other-agent',
        )
        response = await self.client.post(self.step_url)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()['detail'], {'error': 'task_key_conflict'}
        )

    async def test_run_detail_hides_task_content(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE workflow_runtime.step_runs SET status = 'failed',"
                ' port = 1, output = %s'
                " WHERE run_id = %s AND node_id = 'ask'",
                (
                    workflows.runs.pg_json.Jsonb(
                        {
                            'task_id': 'T-1',
                            'outcome': 'failed_external',
                            'reason': 'secret_reason',
                            'summary': 'Secret summary.',
                        }
                    ),
                    self.run_id,
                ),
            )
        overrides = self.test_app.dependency_overrides
        overrides[permissions.get_current_user] = self.user_auth
        url = f'{self.url}/runs/{self.run_id}'

        async def output() -> dict[str, typing.Any]:
            response = await self.client.get(url)
            self.assertEqual(response.status_code, 200, response.text)
            (ask,) = [
                s for s in response.json()['steps'] if s['node_id'] == 'ask'
            ]
            return ask['output']

        self.assertEqual(
            await output(), {'task_id': 'T-1', 'outcome': 'failed_external'}
        )
        user = await self.user_auth()

        async def reader() -> permissions.AuthContext:
            return permissions.AuthContext(
                user=user.user,
                session_id='test-session',
                auth_method='jwt',
                permissions={*user.permissions, 'agent_task:read'},
            )

        overrides[permissions.get_current_user] = reader
        self.assertEqual((await output())['summary'], 'Secret summary.')
        self.assertEqual((await output())['reason'], 'secret_reason')

    async def test_open_run_keeps_the_agent_in_use(self) -> None:
        # The run is open on version 1. Version 2 has no agent step.
        slug = self.url.rsplit('/', 1)[1]
        self.assertEqual(
            await self.store.agent_references(self.org, self.agent), 1
        )
        self.assertTrue(
            await self.store.save(
                self.org,
                slug,
                workflows.Definition(
                    name='Agent guard',
                    description='',
                    owner_team_id=self.team,
                    graph={'nodes': [_node('start', 'manual')], 'edges': []},
                    settings={},
                    validation={'issues': []},
                    author=self.email,
                ),
                self.team,
            )
        )
        await self.store.activate(self.org, slug, 2, self.admin, [])
        self.assertEqual(
            await self.store.agent_references(self.org, self.agent), 1
        )
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE workflow_runtime.runs SET status = 'succeeded'"
                ' WHERE id = %s',
                (self.run_id,),
            )
        self.assertEqual(
            await self.store.agent_references(self.org, self.agent), 0
        )
