"""Tests for the workflow engine (ADR 0021, Execution).

These run against the live Postgres that ``root:services`` boots. imbi-api
is a fake behind ``httpx.MockTransport`` that keeps the idempotency
contract of the deploy and email endpoints; TypeSafe is patched.
"""

import asyncio
import collections
import json
import typing
import unittest
import uuid
from unittest import mock

import httpx
import orjson
from psycopg import rows

from imbi.api import workflows
from imbi.api.endpoints import workflow_runs
from imbi.common import graph, iggy
from imbi.common.auth import encryption
from imbi.common.workflows import history
from imbi.workflows import app, engine, executors, settings, store

CLOSED = {'succeeded', 'failed', 'cancelled', 'timed_out'}


class Crash(BaseException):
    """Ends a tick the way a killed process does: nothing is recorded."""


class FakeApi:
    """imbi-api's deploy and email endpoints, keyed by ``Idempotency-Key``.

    A key in ``by_key`` with ``None`` is a call that started and did not
    finish: a repeat gets ``409 outcome_unknown``.
    """

    def __init__(self, recipient: str) -> None:
        self.recipient = recipient
        self.dispatches = 0
        self.by_key: dict[str, dict[str, typing.Any] | None] = {}
        self.bodies: list[dict[str, typing.Any]] = []
        #: The paths of the email calls that sent.
        self.emails: list[str] = []
        #: The raw path of every request.
        self.paths: list[str] = []

    def _once(
        self, request: httpx.Request, act: typing.Callable[[], dict]
    ) -> httpx.Response:
        key = request.headers['Idempotency-Key']
        if key not in self.by_key:
            self.by_key[key] = act()
        if self.by_key[key] is None:
            return httpx.Response(
                409, json={'detail': {'error': 'outcome_unknown'}}
            )
        return httpx.Response(200, json=self.by_key[key])

    def _email(self, request: httpx.Request) -> dict[str, typing.Any]:
        self.emails.append(request.url.path)
        return {'recipients': [self.recipient]}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.raw_path.decode())
        path = request.url.path
        if path.endswith(('/email', '/failure-notice')):
            return self._once(request, lambda: self._email(request))
        if path.endswith('/auth/token'):
            return httpx.Response(
                200, json={'access_token': 'token', 'expires_in': 900}
            )
        if '/commits/' in path:
            return httpx.Response(200, json={'sha': 'a' * 40})
        if request.method == 'POST' and path.endswith('/deployments'):
            key = request.headers['Idempotency-Key']
            if key not in self.by_key:
                self.dispatches += 1
                self.bodies.append(json.loads(request.content))
                self.by_key[key] = {
                    'run': {
                        'run_id': f'r{self.dispatches}',
                        'status': 'in_progress',
                    },
                    'plugin_id': 'p',
                    'plugin_slug': 'github',
                }
            return httpx.Response(202, json=self.by_key[key])
        if '/runs/' in path:
            run_id = path.rsplit('/', 1)[1]
            return httpx.Response(
                200, json={'run_id': run_id, 'status': 'success'}
            )
        return httpx.Response(404, json={'detail': 'not found'})


def _node(
    node_id: str,
    step: str,
    params: dict[str, typing.Any] | None = None,
    join: str = 'any',
) -> dict[str, typing.Any]:
    return {
        'id': node_id,
        'key': node_id,
        'type': step,
        'title': node_id.title(),
        'position': {'x': 0, 'y': 0},
        'params': params or {},
        'join': join,
    }


def _edge(source: str, target: str, port: int = 0) -> dict[str, typing.Any]:
    return {'source': source, 'port': port, 'target': target}


def _decision(response: str) -> dict[str, typing.Any]:
    return {
        'model': 'jev',
        'answers': {
            'decision': {
                'type': 'choice',
                'choice': response,
                'probabilities': {response: 0.9},
            }
        },
        'usage': {},
    }


class EngineTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        suffix = uuid.uuid4().hex[:10]
        self.org = f'wfe-{suffix}'
        self.team = f'team-{suffix}'
        self.email = f'ops-{suffix}@example.com'
        self.model = f'model-{suffix}'
        self.provider = f'prov-{suffix}'
        await graph.initialize()
        await workflows.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.pool = workflows.create_pool()
        await self.pool.open()
        self.definitions = workflows.WorkflowStore(self.pool)
        self.runs = workflows.RunStore(self.pool)
        self.addAsyncCleanup(self._cleanup)
        # What the engine and the run store publish, by stream.
        self.published: dict[str, list[dict[str, typing.Any]]] = (
            collections.defaultdict(list)
        )

        async def publish_rows(
            stream: str, topic: str, rows: list[dict[str, typing.Any]]
        ) -> None:
            self.published[stream] += rows

        patcher = mock.patch.object(
            iggy, 'publish_rows', mock.AsyncMock(side_effect=publish_rows)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        await self.graph.execute(
            """
            CREATE (o:Organization {{id: {org}, slug: {org}, name: {org}}})
            CREATE (t:Team {{id: {team}, slug: {team}, name: 'Ops'}})
            CREATE (t)-[:BELONGS_TO]->(o)
            CREATE (u:User {{id: {email}, email: {email}, display_name: 'Ops',
                             is_active: true, is_admin: true}})
            CREATE (u)-[:MEMBER_OF {{role: 'admin'}}]->(o)
            CREATE (u)-[:MEMBER_OF]->(t)
            CREATE (p:AIProvider {{id: {provider}, slug: {provider},
                                   name: 'TypeSafe', driver: 'typesafe',
                                   enabled: true,
                                   credentials_encrypted: {key}}})
            CREATE (m:AIModel {{id: {model}, slug: {model}, name: 'Jev',
                                model_id: 'jev-latest',
                                model_type: 'decision', enabled: true}})
            CREATE (m)-[:SERVED_BY]->(p)
            RETURN o.id AS id
            """,
            {
                'org': self.org,
                'team': self.team,
                'email': self.email,
                'provider': self.provider,
                'model': self.model,
                'key': encryption.encrypt_config_value('ts-key'),
            },
            ['id'],
        )
        self.api = FakeApi(self.email)
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self.api))
        self.config = settings.Workflows(
            sa_client_id='client',
            sa_client_secret='secret',
            api_url='http://api',
            deploy_poll_seconds=1,
        )
        self.engine = self._engine('worker-a')

    def _engine(self, worker_id: str) -> engine.Engine:
        return engine.Engine(
            store.Store(self.pool, worker_id),
            executors.Executors(
                executors.Api(self.http, self.config),
                self.graph,
                self.config,
            ),
            self.config,
        )

    async def _cleanup(self) -> None:
        await self.http.aclose()
        await self.graph.execute(
            """
            MATCH (n) WHERE n.id IN {ids}
            DETACH DELETE n
            RETURN 1 AS ok
            """,
            {
                'ids': [
                    self.org,
                    self.team,
                    self.email,
                    self.model,
                    self.provider,
                ]
            },
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
        nodes: list[dict[str, typing.Any]],
        edges: list[dict[str, typing.Any]],
        settings_: dict[str, typing.Any] | None = None,
        activated_by: str | None = None,
    ) -> uuid.UUID:
        slug = self.slug = f'wf-{uuid.uuid4().hex[:8]}'
        await self.definitions.create(
            self.org,
            slug,
            workflows.Definition(
                name='Deploy guard',
                description='',
                owner_team_id=self.team,
                graph={'nodes': nodes, 'edges': edges},
                settings=settings_ or {},
                validation={'issues': []},
                author=self.email,
            ),
        )
        await self.definitions.activate(
            self.org, slug, 1, activated_by or self.email
        )
        row = await self.definitions.get(self.org, slug)
        assert row is not None
        return row['id']

    async def _start(
        self,
        workflow_id: uuid.UUID,
        payload: dict[str, typing.Any] | None = None,
        activated_by: str | None = None,
    ) -> uuid.UUID:
        row, _ = await self.runs.create(
            workflows.NewRun(
                organization_id=self.org,
                workflow_id=workflow_id,
                version=1,
                trigger_node_id='start',
                origin_kind='human',
                origin_id=self.email,
                idempotency_key=None,
                payload=payload or {},
                concurrency_key=None,
                activated_by=activated_by or self.email,
            )
        )
        return row['id']

    async def _drive(
        self,
        run_id: uuid.UUID,
        until: typing.Callable[[dict[str, typing.Any]], bool] | None = None,
        runner: engine.Engine | None = None,
    ) -> dict[str, typing.Any]:
        """Tick until ``until`` holds for the run (default: closed)."""
        runner = runner or self.engine
        done = until or (lambda r: r['status'] in CLOSED)
        for _ in range(300):
            run = await self._run(run_id)
            if done(run):
                if run['status'] in CLOSED:
                    await self._check_history(run)
                return run
            if not await runner.tick():
                await asyncio.sleep(0.05)
        self.fail(f'Run {run_id} did not get there: {run}')

    async def _run(self, run_id: uuid.UUID) -> dict[str, typing.Any]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT workflow_id FROM workflow_runtime.runs WHERE id = %s',
                (run_id,),
            )
            row = await cur.fetchone()
        assert row is not None
        run = await self.runs.get(row[0], run_id)
        assert run is not None
        steps = await self.runs.steps(run_id)
        return {**run, 'steps': {s['node_id']: s for s in steps}}

    async def _events(self, run_id: uuid.UUID) -> list[str]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT seq, type FROM workflow_runtime.run_events'
                ' WHERE run_id = %s ORDER BY seq',
                (run_id,),
            )
            rows = await cur.fetchall()
        self.assertEqual([r[0] for r in rows], list(range(1, len(rows) + 1)))
        return [r[1] for r in rows]

    async def _check_history(self, run: dict[str, typing.Any]) -> None:
        """History shows the steps of a closed run as Postgres does.

        Run detail rebuilds the steps from the events once the sweep
        archives the run (ADR 0021, Run history). Check that for the
        events in Postgres, and for the rows that went to ClickHouse.
        """
        async with (
            self.pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(
                'SELECT * FROM workflow_runtime.run_events WHERE run_id = %s',
                (run['id'],),
            )
            events = await cur.fetchall()
        want = [
            workflow_runs.StepRun.model_validate(s)
            for s in await self.runs.steps(run['id'])
        ]

        def rebuilt(found: list[dict[str, typing.Any]]) -> list[typing.Any]:
            return [
                workflow_runs.StepRun.model_validate(s)
                for s in history.steps(found)
            ]

        self.assertEqual(rebuilt(events), want)
        sent = [
            {**r, 'payload': orjson.loads(r['payload'])}
            for r in self.published[history.EVENTS_STREAM]
            if r['run_id'] == str(run['id'])
        ]
        self.assertEqual(
            sorted(r['seq'] for r in sent),
            list(range(1, run['last_seq'] + 1)),
        )
        self.assertEqual(rebuilt(sent), want)
        summaries = [
            r
            for r in self.published[history.RUNS_STREAM]
            if r['run_id'] == str(run['id'])
        ]
        latest = max(summaries, key=lambda r: r['_row_version'])
        self.assertEqual(latest['status'], run['status'])
        self.assertEqual(latest['_row_version'], run['last_seq'])

    def _states(self, run: dict[str, typing.Any]) -> dict[str, str]:
        return {n: s['status'] for n, s in run['steps'].items()}


class ManualRunTestCase(EngineTestCase):
    async def test_wait_decide_deploy_email(self) -> None:
        workflow_id = await self._workflow(
            [
                _node(
                    'start',
                    'manual',
                    {'inputs': [{'name': 'version', 'type': 'string'}]},
                ),
                _node('pause', 'wait', {'duration': '1s'}),
                _node(
                    'decide',
                    'model_decision',
                    {
                        'model_id': self.model,
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
                _node(
                    'hold',
                    'email',
                    {
                        'to': [{'kind': 'team', 'id': self.team}],
                        'subject': 'Held',
                        'body': 'Held',
                    },
                ),
                _node(
                    'tell',
                    'email',
                    {
                        'to': [{'kind': 'team', 'id': self.team}],
                        'subject': 'Shipped {{ trigger.version }}',
                        'body': 'Deployment {{ ship.deployment_id }}',
                    },
                ),
            ],
            [
                _edge('start', 'pause'),
                _edge('pause', 'decide'),
                _edge('decide', 'ship', 0),
                _edge('decide', 'hold', 1),
                _edge('ship', 'tell', 0),
            ],
        )
        run_id = await self._start(workflow_id, {'version': '1.2.3'})
        with mock.patch(
            'imbi.common.llm.typesafe.decide',
            mock.AsyncMock(return_value=_decision('ship')),
        ) as decide:
            run = await self._drive(run_id)

        self.assertEqual(run['status'], 'succeeded', run)
        self.assertEqual(
            self._states(run),
            {
                'start': 'succeeded',
                'pause': 'succeeded',
                'decide': 'succeeded',
                'ship': 'succeeded',
                'hold': 'skipped',
                'tell': 'succeeded',
            },
        )
        steps = run['steps']
        self.assertEqual(steps['decide']['port'], 0)
        self.assertEqual(steps['decide']['output']['choice'], 'ship')
        self.assertEqual(
            decide.await_args.args[4]['decision']['instructions'],
            'Ship 1.2.3?',
        )
        self.assertEqual(steps['ship']['input']['version'], '1.2.3')
        self.assertEqual(
            steps['ship']['output'],
            {'deployment_id': 'r1', 'status': 'success'},
        )
        self.assertEqual(self.api.dispatches, 1)
        self.assertEqual(self.api.bodies[0]['ref_label'], '1.2.3')
        self.assertEqual(steps['tell']['output'], {'recipients': [self.email]})
        self.assertEqual(steps['tell']['input']['subject'], 'Shipped 1.2.3')
        self.assertEqual(steps['tell']['input']['body'], 'Deployment r1')
        self.assertEqual(
            self.api.emails,
            [
                f'/organizations/{self.org}/workflows/{self.slug}'
                f'/runs/{run_id}/steps/tell/email'
            ],
        )
        events = await self._events(run_id)
        self.assertEqual(events[:2], ['run.created', 'run.started'])
        self.assertEqual(events[-1], 'run.closed')
        self.assertIn('step.skipped', events)

    async def test_failed_deployment_takes_failed_port(self) -> None:
        original = FakeApi.__call__

        def failing(api: FakeApi, request: httpx.Request) -> httpx.Response:
            if '/runs/' in request.url.path:
                return httpx.Response(
                    200, json={'run_id': 'r1', 'status': 'failure'}
                )
            return original(api, request)

        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'ship',
                    'deploy',
                    {
                        'project_id': 'p1',
                        'environment': 'staging',
                        'version': '1.0.0',
                    },
                ),
                _node('ok', 'wait', {'duration': '1s'}),
                _node('undo', 'wait', {'duration': '1s'}),
            ],
            [
                _edge('start', 'ship'),
                _edge('ship', 'ok', 0),
                _edge('ship', 'undo', 1),
            ],
        )
        run_id = await self._start(workflow_id)
        with mock.patch.object(FakeApi, '__call__', failing):
            run = await self._drive(run_id)
        self.assertEqual(run['status'], 'succeeded')
        self.assertEqual(
            self._states(run),
            {
                'start': 'succeeded',
                'ship': 'failed',
                'ok': 'skipped',
                'undo': 'succeeded',
            },
        )
        self.assertEqual(run['steps']['ship']['attempt'], 1)
        self.assertEqual(self.api.dispatches, 1)

    async def test_activator_without_permission_pauses(self) -> None:
        outsider = f'gone-{uuid.uuid4().hex[:8]}@example.com'
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'ship',
                    'deploy',
                    {
                        'project_id': 'p1',
                        'environment': 'staging',
                        'version': '1.0.0',
                    },
                ),
            ],
            [_edge('start', 'ship')],
            activated_by=outsider,
        )
        run_id = await self._start(workflow_id, activated_by=outsider)
        run = await self._drive(run_id)
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['error'], 'activator_lacks_permission')
        self.assertEqual(self.api.dispatches, 0)
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT status FROM workflows.workflows WHERE id = %s',
                (workflow_id,),
            )
            self.assertEqual(await cur.fetchone(), ('paused',))


class SecurityTestCase(EngineTestCase):
    async def test_payload_cannot_change_the_url(self) -> None:
        workflow_id = await self._workflow(
            [
                _node(
                    'start',
                    'manual',
                    {'inputs': [{'name': 'version', 'type': 'string'}]},
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
            ],
            [_edge('start', 'ship')],
        )
        for bad in ('../../admin?x=1', '1.0/../../x', 'a..b', '%2e%2e'):
            with self.subTest(version=bad):
                run_id = await self._start(workflow_id, {'version': bad})
                run = await self._drive(run_id)
                ship = run['steps']['ship']
                self.assertEqual(ship['status'], 'failed')
                self.assertEqual(ship['error'], 'invalid_version')
                self.assertEqual(ship['attempt'], 1)
        self.assertEqual(self.api.paths, [])
        self.assertEqual(self.api.dispatches, 0)

    def test_path_quotes_every_segment(self) -> None:
        self.assertEqual(
            executors._path('organizations', 'a/../b', 'x?y#z'),
            '/organizations/a%2F..%2Fb/x%3Fy%23z',
        )

    async def test_activator_who_left_the_organization(self) -> None:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node('hold', 'wait', {'duration': '1s'}),
            ],
            [_edge('start', 'hold')],
        )
        await self.graph.execute(
            """
            MATCH (:User {{email: {email}}})-[m:MEMBER_OF]->(:Organization)
            DELETE m
            RETURN 1 AS ok
            """,
            {'email': self.email},
            ['ok'],
        )
        run_id = await self._start(workflow_id)
        run = await self._drive(run_id)
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['error'], 'activator_lacks_permission')
        self.assertEqual(run['steps'], {})
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT status FROM workflows.workflows WHERE id = %s',
                (workflow_id,),
            )
            self.assertEqual(await cur.fetchone(), ('paused',))

    async def test_inactive_admin_activator(self) -> None:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node('hold', 'wait', {'duration': '1s'}),
            ],
            [_edge('start', 'hold')],
        )
        await self.graph.execute(
            """
            MATCH (u:User {{email: {email}}}) SET u.is_active = false
            RETURN 1 AS ok
            """,
            {'email': self.email},
            ['ok'],
        )
        run = await self._drive(await self._start(workflow_id))
        self.assertEqual(run['error'], 'activator_lacks_permission')


class CrashTestCase(EngineTestCase):
    async def _crash_on(self, run_id: uuid.UUID, node_id: str) -> None:
        """Run until ``node_id`` acts, then die before the result is
        recorded, and let the lease expire."""
        real = self.engine.steps.run

        async def crashing(call: executors.Call) -> executors.Outcome:
            outcome = await real(call)
            if call.node.id == node_id:
                raise Crash
            return outcome

        self.engine.steps.run = crashing  # type: ignore[method-assign]
        with self.assertRaises(Crash):
            await self._drive(run_id)
        run = await self._run(run_id)
        self.assertEqual(run['steps'][node_id]['status'], 'running')
        self.assertIsNotNone(run['steps'][node_id]['call_started_at'])
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE workflow_runtime.leases'
                " SET expires_at = NOW() - INTERVAL '1 second'"
                ' WHERE run_id = %s',
                (run_id,),
            )

    async def test_resume_without_second_deployment(self) -> None:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'ship',
                    'deploy',
                    {
                        'project_id': 'p1',
                        'environment': 'staging',
                        'version': '1.0.0',
                    },
                ),
                _node(
                    'tell',
                    'email',
                    {
                        'to': [{'kind': 'user', 'id': self.email}],
                        'subject': 'Shipped',
                        'body': '{{ ship.deployment_id }}',
                    },
                ),
            ],
            [_edge('start', 'ship'), _edge('ship', 'tell', 0)],
        )
        run_id = await self._start(workflow_id)
        await self._crash_on(run_id, 'ship')
        self.assertEqual(self.api.dispatches, 1)

        run = await self._drive(run_id, runner=self._engine('worker-b'))
        self.assertEqual(run['status'], 'succeeded', run)
        self.assertEqual(self.api.dispatches, 1)
        self.assertEqual(run['steps']['ship']['attempt'], 1)
        self.assertEqual(run['steps']['ship']['output']['deployment_id'], 'r1')
        self.assertEqual(run['steps']['tell']['input']['body'], 'r1')
        self.assertEqual(len(self.api.emails), 1)

    async def test_interrupted_email_is_not_sent_twice(self) -> None:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'tell',
                    'email',
                    {
                        'to': [{'kind': 'user', 'id': self.email}],
                        'subject': 'Hello',
                        'body': 'Hello',
                    },
                ),
            ],
            [_edge('start', 'tell')],
            {'on_failure': 'none'},
        )
        run_id = await self._start(workflow_id)
        await self._crash_on(run_id, 'tell')
        run = await self._drive(run_id, runner=self._engine('worker-b'))
        self.assertEqual(run['status'], 'succeeded', run)
        self.assertEqual(run['steps']['tell']['attempt'], 1)
        self.assertEqual(len(self.api.emails), 1)

    async def test_unknown_outcome_fails_without_retry(self) -> None:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'tell',
                    'email',
                    {
                        'to': [{'kind': 'user', 'id': self.email}],
                        'subject': 'Hello',
                        'body': 'Hello',
                    },
                ),
            ],
            [_edge('start', 'tell')],
        )
        run_id = await self._start(workflow_id)
        # imbi-api began this call before a crash and has no result.
        self.api.by_key[f'{run_id}:tell'] = None
        run = await self._drive(run_id)
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['error'], 'outcome_unknown')
        self.assertEqual(run['steps']['tell']['attempt'], 1)
        # No step email; the default failure policy tells the owner team.
        self.assertEqual(
            [e.rsplit('/', 1)[1] for e in self.api.emails], ['failure-notice']
        )
        self.assertEqual(
            self.api.by_key[f'{run_id}/failure-notice'],
            {'recipients': [self.email]},
        )

    async def test_node_keyed_on_failure_keeps_the_notice(self) -> None:
        """A step key cannot take the failure notice's key."""
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'on_failure',
                    'email',
                    {
                        'to': [{'kind': 'user', 'id': self.email}],
                        'subject': 'Hello',
                        'body': 'Hello',
                    },
                ),
            ],
            [_edge('start', 'on_failure')],
        )
        run_id = await self._start(workflow_id)
        self.api.by_key[f'{run_id}:on_failure'] = None
        run = await self._drive(run_id)
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['error'], 'outcome_unknown')
        self.assertEqual(
            [e.rsplit('/', 1)[1] for e in self.api.emails], ['failure-notice']
        )


class BranchTestCase(EngineTestCase):
    async def test_branch_not_taken_and_all_join(self) -> None:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'decide',
                    'model_decision',
                    {
                        'model_id': self.model,
                        'prompt': 'Which?',
                        'branches': ['a', 'b'],
                    },
                ),
                _node('wa', 'wait', {'duration': '1s'}),
                _node('wb', 'wait', {'duration': '1s'}),
                _node('after_b', 'wait', {'duration': '1s'}),
                _node('wc', 'wait', {'duration': '1s'}),
                _node('join', 'wait', {'duration': '1s'}, join='all'),
            ],
            [
                _edge('start', 'decide'),
                _edge('decide', 'wa', 0),
                _edge('decide', 'wb', 1),
                _edge('wb', 'after_b'),
                _edge('start', 'wc'),
                _edge('wa', 'join'),
                _edge('after_b', 'join'),
                _edge('wc', 'join'),
            ],
        )
        run_id = await self._start(workflow_id)
        with mock.patch(
            'imbi.common.llm.typesafe.decide',
            mock.AsyncMock(return_value=_decision('a')),
        ):
            run = await self._drive(run_id)
        self.assertEqual(run['status'], 'succeeded', run)
        states = self._states(run)
        self.assertEqual(states['wb'], 'skipped')
        self.assertEqual(states['after_b'], 'skipped')
        self.assertEqual(states['join'], 'succeeded')
        steps = run['steps']
        self.assertGreaterEqual(
            steps['join']['started_at'],
            max(steps['wa']['finished_at'], steps['wc']['finished_at']),
        )


class CancelTestCase(EngineTestCase):
    async def test_cancel_stops_the_run(self) -> None:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node('hold', 'wait', {'duration': '1h'}),
                _node(
                    'tell',
                    'email',
                    {
                        'to': [{'kind': 'user', 'id': self.email}],
                        'subject': 'Done',
                        'body': 'Done',
                    },
                ),
            ],
            [_edge('start', 'hold'), _edge('hold', 'tell')],
        )
        run_id = await self._start(workflow_id)
        await self._drive(
            run_id,
            until=lambda r: bool(r['steps'].get('hold', {}).get('state')),
        )
        self.assertTrue(await self.runs.cancel(run_id))
        run = await self._drive(run_id)
        self.assertEqual(run['status'], 'cancelled')
        self.assertEqual(
            self._states(run),
            {'start': 'succeeded', 'hold': 'cancelled', 'tell': 'cancelled'},
        )
        # The history that ClickHouse gets shows the cancelled steps.
        sent = [
            {**r, 'payload': orjson.loads(r['payload'])}
            for r in self.published[history.EVENTS_STREAM]
            if r['run_id'] == str(run_id)
        ]
        self.assertEqual(
            {s['node_id']: s['status'] for s in history.steps(sent)},
            {'start': 'succeeded', 'hold': 'cancelled', 'tell': 'cancelled'},
        )
        self.assertEqual(self.api.emails, [])
        self.assertFalse(await self.runs.cancel(run_id))


class RetryTestCase(EngineTestCase):
    async def test_error_is_retried(self) -> None:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'decide',
                    'model_decision',
                    {
                        'model_id': self.model,
                        'prompt': 'Which?',
                        'branches': ['a', 'b'],
                    },
                ),
            ],
            [_edge('start', 'decide')],
        )
        run_id = await self._start(workflow_id)
        decide = mock.AsyncMock(
            side_effect=[
                executors.typesafe.DecisionError('TypeSafe returned HTTP 503'),
                _decision('b'),
            ]
        )
        with (
            mock.patch('imbi.common.llm.typesafe.decide', decide),
            mock.patch.object(engine, 'RETRY_BACKOFF', 0),
        ):
            run = await self._drive(run_id)
        self.assertEqual(run['status'], 'succeeded', run)
        self.assertEqual(run['steps']['decide']['attempt'], 2)
        self.assertEqual(run['steps']['decide']['port'], 1)
        self.assertEqual(decide.await_count, 2)


class RollbackTestCase(EngineTestCase):
    async def test_last_healthy(self) -> None:
        project = f'proj-{uuid.uuid4().hex[:8]}'
        env = f'env-{uuid.uuid4().hex[:8]}'
        self.addAsyncCleanup(self._delete_nodes, project, env)
        await self.graph.execute(
            """
            CREATE (p:Project {{id: {project}, slug: {project}}})
            CREATE (e:Environment {{id: {env}, slug: {env}}})
            WITH p, e
            MATCH (o:Organization {{id: {org}}})
            CREATE (e)-[:BELONGS_TO]->(o)
            WITH p, e
            UNWIND [['1.0.0', 'success', '2026-01-01'],
                    ['1.1.0', 'success', '2026-02-01'],
                    ['1.2.0', 'failure', '2026-03-01']] AS row
            CREATE (r:Release {{id: {project} + row[0], tag: row[0]}})
            CREATE (d:Deployment {{id: {project} + '-' + row[0],
                                   status: row[1], created_at: row[2]}})
            CREATE (d)-[:BELONGS_TO]->(p)
            CREATE (d)-[:TARGETS]->(e)
            CREATE (r)-[:HAS_DEPLOYMENT]->(d)
            RETURN count(d) AS n
            """,
            {'project': project, 'env': env, 'org': self.org},
            ['n'],
        )
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'undo',
                    'rollback',
                    {
                        'project_id': project,
                        'environment': env,
                        'target': 'last_healthy',
                    },
                ),
            ],
            [_edge('start', 'undo')],
        )
        run_id = await self._start(workflow_id)
        run = await self._drive(run_id)
        self.assertEqual(run['status'], 'succeeded', run)
        self.assertEqual(
            self.api.bodies,
            [
                {
                    'action': 'redeploy',
                    'environment': env,
                    'committish': 'a' * 40,
                    'ref_label': '1.1.0',
                }
            ],
        )

    async def _delete_nodes(self, project: str, env: str) -> None:
        await self.graph.execute(
            """
            MATCH (n) WHERE n.id IN {ids} OR n.id STARTS WITH {project}
            DETACH DELETE n
            RETURN 1 AS ok
            """,
            {'ids': [project, env], 'project': project},
            ['ok'],
        )


class TimeoutTestCase(EngineTestCase):
    async def test_max_run_time(self) -> None:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node('hold', 'wait', {'duration': '1h'}),
            ],
            [_edge('start', 'hold')],
            {'max_run_time_seconds': 1},
        )
        run_id = await self._start(workflow_id)
        run = await self._drive(run_id)
        self.assertEqual(run['status'], 'timed_out')
        self.assertEqual(run['steps']['hold']['status'], 'cancelled')


class AppTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_status(self) -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app.create_app()),
            base_url='http://test',
        ) as client:
            response = await client.get('/status')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['service'], 'imbi-workflows')

    async def test_engine_lifespan_starts_and_stops(self) -> None:
        with mock.patch.dict(
            'os.environ', {'IMBI_WORKFLOWS_POLL_INTERVAL': '0.1'}
        ):
            async with app.engine_lifespan() as runner:
                await asyncio.sleep(0.3)
                self.assertIsInstance(runner, engine.Engine)


class RenderTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_references(self) -> None:
        steps = {
            'a': {
                'node_key': 'a',
                'node_type': 'deploy',
                'status': 'succeeded',
                'output': {'deployment_id': 'r1', 'status': 'success'},
            },
            'b': {
                'node_key': 'b',
                'node_type': 'deploy',
                'status': 'skipped',
                'output': None,
            },
        }
        with mock.patch.dict(
            'os.environ', {'IMBI_PROMPT_RENDER_INPROCESS': 'true'}
        ):
            rendered = await engine._render(
                {
                    'whole': '{{ trigger.count }}',
                    'text': 'n={{ trigger.count }} {{ a.deployment_id }}',
                    'skipped': '{{ b.deployment_id }}',
                    'skipped_text': '[{{ b.deployment_id }}]',
                    'nested': [{'x': '{{ a.status }}'}],
                    'plain': 'no references',
                },
                steps,
                {'count': 3},
            )
        self.assertEqual(
            rendered,
            {
                'whole': 3,
                'text': 'n=3 r1',
                'skipped': None,
                'skipped_text': '[]',
                'nested': [{'x': 'success'}],
                'plain': 'no references',
            },
        )
