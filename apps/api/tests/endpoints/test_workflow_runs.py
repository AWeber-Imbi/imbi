"""Tests for the workflow run endpoints (ADR 0021).

These run against the live Postgres that ``root:services`` boots. The
engine is not running: a started run stays ``queued``.
"""

import datetime
import typing
import uuid
from unittest import mock

import fastapi
import httpx

from apps.api.tests import support
from imbi.api import email, models, workflows
from imbi.api.auth import organizations, permissions
from imbi.api.endpoints import project_deployments, workflow_runs
from imbi.common import graph
from imbi.common.plugins import base as plugin_base

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


def _graph(team: str) -> dict[str, typing.Any]:
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
                    'project_id': 'p1',
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


class WorkflowRunTestCase(support.SharedAppAsyncTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        suffix = uuid.uuid4().hex[:10]
        self.org = f'wfr-{suffix}'
        self.team = f'team-{suffix}'
        self.email = f'dev-{suffix}@example.com'
        self.base = f'/organizations/{self.org}/workflows'
        await graph.initialize()
        await workflows.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.pool = workflows.create_pool()
        await self.pool.open()
        self.store = workflows.WorkflowStore(self.pool)
        self.runs = workflows.RunStore(self.pool)
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
            RETURN o.id AS id
            """,
            {'org': self.org, 'team': self.team, 'email': self.email},
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
            {'ids': [self.org, self.team, self.email]},
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

    async def _workflow(self, *, activate: bool = True) -> str:
        response = await self.client.post(
            self.base + '/',
            json={
                'name': 'Deploy guard',
                'owner_team_slug': self.team,
                'graph': _graph(self.team),
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        if activate:
            response = await self.client.post(
                f'{self.base}/deploy-guard/activate'
            )
            self.assertEqual(response.status_code, 200, response.text)
        return f'{self.base}/deploy-guard'

    async def _forget(self, key: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM workflow_runtime.side_effects WHERE key = %s',
                (key,),
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
        self.addAsyncCleanup(self._forget, f'unknown:{key}')
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

    async def test_refusal_forgets_and_unknown_is_409(self) -> None:
        key = f'run-{uuid.uuid4()}:ship'
        self.addAsyncCleanup(self._forget, f'unknown:{key}')
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

        async def send_email(message: typing.Any) -> typing.Any:
            self.sent.append(message)
            return mock.Mock(status='sent')

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
        self.addAsyncCleanup(self._forget, f'imbi-workflows:{self.run_id}:k')

    async def test_step_email_once(self) -> None:
        url = f'{self.url}/runs/{self.run_id}/steps/tell/email'
        headers = {'Idempotency-Key': f'{self.run_id}:k'}
        for _ in range(2):
            response = await self.client.post(url, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {'recipients': [self.email]})
        self.assertEqual(
            [(m.to_email, m.subject, m.text_body) for m in self.sent],
            [(self.email, 'Shipped 1', 'Deployment r1')],
        )

        response = await self.client.post(
            f'{self.url}/runs/{self.run_id}/steps/start/email',
            headers=headers,
        )
        self.assertEqual(response.status_code, 404)

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
        self.assertEqual(response.json(), {'recipients': [self.email]})
        self.assertEqual(self.sent[0].subject, 'Workflow Deploy guard failed')
