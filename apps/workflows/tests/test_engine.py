"""Tests for the workflow engine (ADR 0021, Execution).

These run against the live Postgres that ``root:services`` boots. imbi-api
is a fake behind ``httpx.MockTransport`` that keeps the idempotency
contract of the deploy and email endpoints; TypeSafe is patched.
"""

import asyncio
import collections
import datetime
import json
import typing
import unittest
import uuid
from collections import abc
from unittest import mock

import fastapi
import httpx
import orjson
import psycopg
from psycopg import rows

from imbi.api import models, tickets, workflows
from imbi.api.auth import permissions
from imbi.api.endpoints import workflow_runs
from imbi.api.workflows import sweeper
from imbi.common import graph, iggy, sentry
from imbi.common.auth import encryption
from imbi.common.workflows import graph as wf
from imbi.common.workflows import history, script_runner
from imbi.common.workflows.registry import search_logs
from imbi.workflows import app, engine, executors, settings, store

CLOSED = {'succeeded', 'failed', 'cancelled', 'timed_out'}
#: The commit that the fake imbi-api resolves every version to.
SHA = 'a' * 40


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
        #: Addresses that the email endpoint reports as failed.
        self.failed: list[str] = []
        #: The bodies of the Slack calls that posted.
        self.slacks: list[str] = []
        #: The Slack error code that the Slack endpoint reports.
        self.slack_error: str | None = None
        #: Answer the Slack endpoint with ``502 slack_unreachable``.
        self.slack_unreachable = False
        #: Answer this many Slack calls with ``429 slack_ratelimited``.
        self.slack_ratelimited = 0
        #: The raw path of every request.
        self.paths: list[str] = []
        #: The method and raw path of every request.
        self.requests: list[tuple[str, str]] = []
        #: The person in the role of the assign_ticket endpoint.
        self.assignee: str | None = 'person@example.com'
        #: Takes the agent task calls when set.
        self.agent: (
            abc.Callable[[httpx.Request], abc.Awaitable[httpx.Response]] | None
        ) = None
        #: The bodies of the release-notes drafts.
        self.drafts: list[dict[str, typing.Any]] = []
        #: The answer of the release-notes draft endpoint.
        self.draft: dict[str, typing.Any] = {
            'bump': 'minor',
            'version': '1.6.0',
            'reasoning': 'New features.',
            'notes_markdown': '- Add things',
            'degraded': False,
            'commits_considered': 2,
        }
        #: ``'building'``: a promote takes the Release workflow path.
        self.promote_phase: str | None = None
        #: Whether imbi-api watches the build of that path.
        self.promote_watched = True
        #: The newest tag of the project, as ``release-drift`` reports it.
        self.latest_tag: str | None = None
        #: The answers of ``promote-status``, in turn; the last repeats.
        self.promote_statuses: list[dict[str, typing.Any]] = []
        #: Takes the prompt run calls when set.
        self.llm_call: (
            abc.Callable[
                [httpx.Request],
                httpx.Response | abc.Awaitable[httpx.Response],
            ]
            | None
        ) = None

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
        return {'recipients': [self.recipient], 'failed': self.failed}

    def _slack(self, request: httpx.Request) -> dict[str, typing.Any]:
        self.slacks.append(request.url.path)
        if self.slack_error:
            return {'channel': 'C0123456789', 'error': self.slack_error}
        return {
            'channel': 'C0123456789',
            'ts': '1700000000.000100',
            'permalink': 'https://example.slack.com/archives/x',
            'error': None,
        }

    def _release(self, request: httpx.Request) -> httpx.Response | None:
        path = request.url.path
        if path.endswith('/deployments/promote-status'):
            found = self.promote_statuses
            return httpx.Response(
                200, json=found.pop(0) if len(found) > 1 else found[0]
            )
        if path.endswith('/deployments/release-drift'):
            return httpx.Response(200, json={'latest_tag': self.latest_tag})
        if path.endswith('/deployments/draft-release-notes'):
            self.drafts.append(json.loads(request.content))
            return httpx.Response(200, json=self.draft)
        return None

    def __call__(
        self, request: httpx.Request
    ) -> httpx.Response | abc.Awaitable[httpx.Response]:
        self.paths.append(request.url.raw_path.decode())
        self.requests.append((request.method, self.paths[-1]))
        path = request.url.path
        if '/agent-task' in path and self.agent is not None:
            return self.agent(request)
        if path.endswith('/prompts/run') and self.llm_call is not None:
            return self.llm_call(request)
        if path.endswith(('/email', '/failure-notice')):
            return self._once(request, lambda: self._email(request))
        if path.endswith('/slack'):
            if self.slack_ratelimited:
                self.slack_ratelimited -= 1
                self.slacks.append(path)
                return httpx.Response(
                    429, json={'detail': {'error': 'slack_ratelimited'}}
                )
            if self.slack_unreachable:
                self.slacks.append(path)
                return httpx.Response(
                    502, json={'detail': {'error': 'slack_unreachable'}}
                )
            return self._once(request, lambda: self._slack(request))
        if path.endswith('/assign-ticket'):
            return self._once(
                request,
                lambda: {
                    'task_id': 'T-1',
                    'role': 'reviewer',
                    'assignee': self.assignee,
                },
            )
        if path.endswith('/auth/token'):
            return httpx.Response(
                200, json={'access_token': 'token', 'expires_in': 900}
            )
        released = self._release(request) or _logs(request)
        if released is not None:
            return released
        if '/commits/' in path:
            return httpx.Response(200, json={'sha': 'a' * 40})
        if request.method == 'POST' and path.endswith('/deployments'):
            key = request.headers['Idempotency-Key']
            if key not in self.by_key:
                self.dispatches += 1
                body = json.loads(request.content)
                self.bodies.append(body)
                self.by_key[key] = {
                    'run': {
                        'run_id': f'r{self.dispatches}',
                        'status': 'in_progress',
                    },
                    'plugin_id': 'p',
                    'plugin_slug': 'github',
                }
                if body['action'] == 'promote' and self.promote_phase:
                    self.by_key[key] |= {
                        'run': {'run_id': '', 'status': 'queued'},
                        'tag': body['tag'],
                        'phase': self.promote_phase,
                        'artifact_run_id': f'a{self.dispatches}',
                        'watched': self.promote_watched,
                    }
            return httpx.Response(202, json=self.by_key[key])
        if '/runs/' in path:
            run_id = path.rsplit('/', 1)[1]
            return httpx.Response(
                200, json={'run_id': run_id, 'status': 'success'}
            )
        return httpx.Response(404, json={'detail': 'not found'})


def _logs(request: httpx.Request) -> httpx.Response | None:
    """imbi-api's project logs search: one entry."""
    if not request.url.path.endswith('/logs/'):
        return None
    return httpx.Response(
        200, json=search_logs.STEP.sample_output | {'next_cursor': 'c2'}
    )


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
            store.Store(self.pool, worker_id, self.org),
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
            self.org, slug, 1, activated_by or self.email, []
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
                origin={},
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
        # Bound by time, not by ticks: fast ticks must not end the loop
        # before a step timeout of a few seconds elapses (#829).
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 15
        while loop.time() < deadline:
            run = await self._run(run_id)
            if done(run):
                if run['status'] in CLOSED:
                    await self._check_history(run)
                return run
            if not await runner.tick():
                await asyncio.sleep(0.05)
        self.fail(f'Run {run_id} did not get there: {await self._run(run_id)}')

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

        def failing(
            api: FakeApi, request: httpx.Request
        ) -> httpx.Response | abc.Awaitable[httpx.Response]:
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

    async def test_timeout_retry_resumes_the_deployment(self) -> None:
        # #829: the retry polls the run that attempt 1 started. It does
        # not resolve the version again or post a new deployment.
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                {
                    **_node(
                        'ship',
                        'deploy',
                        {
                            'project_id': 'p1',
                            'environment': 'staging',
                            'version': '1.0.0',
                        },
                    ),
                    # The poll is due after 1s, so the timeout comes first.
                    'timeout_seconds': 1,
                },
            ],
            [_edge('start', 'ship')],
        )
        run_id = await self._start(workflow_id)
        with mock.patch.object(engine, 'RETRY_BACKOFF', 0):
            run = await self._drive(run_id)
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(run['steps']['ship']['attempt'], 2)
        self.assertEqual(run['steps']['ship']['output']['deployment_id'], 'r1')
        self.assertEqual(
            sum('/commits/' in p for p in self.api.paths), 1, self.api.paths
        )

    async def test_error_retry_resumes_the_deployment(self) -> None:
        # #829: a failed poll of the run is retried by polling that run
        # again, not by posting a new deployment.
        original = FakeApi.__call__
        polls: list[str] = []

        def flaky(
            api: FakeApi, request: httpx.Request
        ) -> httpx.Response | abc.Awaitable[httpx.Response]:
            if '/runs/' in request.url.path:
                polls.append(request.url.path)
                if len(polls) == 1:
                    return httpx.Response(503, json={'detail': 'down'})
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
            ],
            [_edge('start', 'ship')],
        )
        run_id = await self._start(workflow_id)
        with (
            mock.patch.object(FakeApi, '__call__', flaky),
            mock.patch.object(engine, 'RETRY_BACKOFF', 0),
        ):
            run = await self._drive(run_id)
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(run['steps']['ship']['attempt'], 2)
        self.assertEqual(len(polls), 2)
        self.assertEqual(
            sum('/commits/' in p for p in self.api.paths), 1, self.api.paths
        )

    async def _deploy_without_failed_edge(self) -> uuid.UUID:
        """A deploy whose ``Failed`` port has no edge."""
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
            ],
            [_edge('start', 'ship'), _edge('ship', 'ok', 0)],
        )
        return await self._start(workflow_id)

    async def test_error_into_unconnected_failed_port_fails_run(
        self,
    ) -> None:
        original = FakeApi.__call__

        def rejecting(
            api: FakeApi, request: httpx.Request
        ) -> httpx.Response | abc.Awaitable[httpx.Response]:
            if request.url.path.endswith('/deployments'):
                return httpx.Response(422, json={'detail': 'bad'})
            return original(api, request)

        run_id = await self._deploy_without_failed_edge()
        with mock.patch.object(FakeApi, '__call__', rejecting):
            run = await self._drive(run_id)
        self.assertEqual(run['status'], 'failed')
        ship = run['steps']['ship']
        self.assertEqual((ship['status'], ship['port']), ('failed', 1))
        self.assertEqual(run['error'], ship['error'])
        self.assertEqual(run['steps']['ok']['status'], 'cancelled')
        self.assertEqual(
            [e.rsplit('/', 1)[1] for e in self.api.emails], ['failure-notice']
        )

    async def test_failure_into_unconnected_failed_port_fails_run(
        self,
    ) -> None:
        original = FakeApi.__call__

        def failing(
            api: FakeApi, request: httpx.Request
        ) -> httpx.Response | abc.Awaitable[httpx.Response]:
            if request.url.path.endswith('/runs/r1'):
                return httpx.Response(
                    200, json={'run_id': 'r1', 'status': 'failure'}
                )
            return original(api, request)

        run_id = await self._deploy_without_failed_edge()
        with mock.patch.object(FakeApi, '__call__', failing):
            run = await self._drive(run_id)
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['steps']['ship']['port'], 1)
        self.assertEqual(run['steps']['ok']['status'], 'cancelled')
        self.assertEqual(
            [e.rsplit('/', 1)[1] for e in self.api.emails], ['failure-notice']
        )

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
            # The failure policy would call imbi-api.
            {'on_failure': 'none'},
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

    async def test_webhook_payload_cannot_change_the_url(self) -> None:
        """A webhook run's payload is the sender's body (ADR 0021)."""
        workflow_id = await self._workflow(
            [
                _node('start', 'webhook', {'webhook_id': 'wh-1'}),
                _node(
                    'ship',
                    'deploy',
                    {
                        'project_id': '{{ trigger.payload.repo }}',
                        'environment': 'staging',
                        'version': '1.0.0',
                    },
                ),
            ],
            [_edge('start', 'ship')],
            # The failure policy would call imbi-api.
            {'on_failure': 'none'},
        )
        # The run as the run endpoint writes it for a gateway delivery.
        row, _ = await self.runs.create(
            workflows.NewRun(
                organization_id=self.org,
                workflow_id=workflow_id,
                version=1,
                trigger_node_id='start',
                origin_kind='webhook',
                origin_id='wh-1',
                origin={'kind': 'webhook', 'webhook_id': 'wh-1'},
                idempotency_key='d-1',
                payload={'payload': {'repo': '../../admin?x=1'}},
                concurrency_key=None,
                activated_by=self.email,
            )
        )
        run = await self._drive(row['id'])
        ship = run['steps']['ship']
        self.assertEqual(ship['status'], 'failed')
        self.assertEqual(ship['error'], 'invalid_project_id')
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


class StoreTestCase(EngineTestCase):
    async def test_release_after_takeover_keeps_the_schedule(self) -> None:
        workflow_id = await self._workflow([_node('start', 'manual')], [])
        run_id = uuid.uuid4()
        # One transaction, so that no other engine sees the run unleased.
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute(
                'INSERT INTO workflow_runtime.runs (id, organization_id,'
                ' workflow_id, version, trigger_node_id, origin_kind,'
                ' origin_id, activated_by, due_at) VALUES (%s, %s, %s, 1,'
                " 'start', 'human', %s, %s, NOW() + INTERVAL '1 hour')",
                (run_id, self.org, workflow_id, self.email, self.email),
            )
            # Worker b took the run over after the lease of a expired.
            await conn.execute(
                'INSERT INTO workflow_runtime.leases'
                ' (run_id, worker_id, expires_at)'
                " VALUES (%s, 'b', NOW() + INTERVAL '1 hour')",
                (run_id,),
            )
            cur = await conn.execute(
                'SELECT due_at FROM workflow_runtime.runs WHERE id = %s',
                (run_id,),
            )
            before = await cur.fetchone()
        await store.Store(self.pool, 'a').release(
            run_id, datetime.datetime.now(datetime.UTC)
        )
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT r.due_at, l.worker_id FROM workflow_runtime.runs r'
                ' JOIN workflow_runtime.leases l ON l.run_id = r.id'
                ' WHERE r.id = %s',
                (run_id,),
            )
            self.assertEqual(await cur.fetchone(), (before[0], 'b'))

    async def test_start_waits_for_a_reopened_run_of_the_key(self) -> None:
        nodes = [_node('start', 'manual')]
        workflow_id = await self._workflow(nodes, [])
        queued = await self._start(workflow_id)
        reopened = await self._start(workflow_id)
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE workflow_runtime.runs SET concurrency_key = 'k'"
                ' WHERE id IN (%s, %s)',
                (queued, reopened),
            )
        run = await self.engine.store.claim(datetime.timedelta(seconds=60))
        assert run is not None
        self.assertEqual(run['id'], queued)
        # An operator reopens the other run between the claim and start.
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE workflow_runtime.runs SET status = 'running'"
                ' WHERE id = %s',
                (reopened,),
            )
        await self.engine._start(  # pyright: ignore[reportPrivateUsage]
            run, engine.wf.Graph.model_validate({'nodes': nodes})
        )
        state = await self._run(queued)
        self.assertEqual((state['status'], state['steps']), ('queued', {}))


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

    async def test_failed_recipient_fails_the_step(self) -> None:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'tell',
                    'email',
                    {
                        'to': [{'kind': 'team', 'id': self.team}],
                        'subject': 'Hello',
                        'body': 'Hello',
                    },
                ),
            ],
            [_edge('start', 'tell')],
            {'on_failure': 'none'},
        )
        self.api.failed = ['gone@example.com']
        run = await self._drive(await self._start(workflow_id))
        self.assertEqual(run['status'], 'failed')
        tell = run['steps']['tell']
        self.assertEqual(tell['error'], 'email_failed: gone@example.com')
        self.assertEqual(tell['attempt'], 1)
        self.assertEqual(len(self.api.emails), 1)

    async def _slack_workflow(self) -> uuid.UUID:
        return await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'tell',
                    'slack',
                    {'channel': 'C0123456789', 'text': '*Hello*'},
                ),
            ],
            [_edge('start', 'tell')],
            {'on_failure': 'none'},
        )

    async def _assign_run(self) -> tuple[uuid.UUID, dict[str, typing.Any]]:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'assign',
                    'assign_ticket',
                    {'ticket': 'T-1', 'role': 'reviewer'},
                ),
            ],
            [_edge('start', 'assign')],
            {'on_failure': 'none'},
        )
        run_id = await self._start(workflow_id)
        run = await self._drive(run_id)
        self.assertEqual(run['status'], 'succeeded', run)
        return run_id, run['steps']['assign']

    async def test_assign_ticket_takes_assigned_port(self) -> None:
        run_id, step = await self._assign_run()
        self.assertEqual(step['port'], 0)
        self.assertEqual(step['output']['assignee'], 'person@example.com')
        self.assertEqual(
            [r for r in self.api.requests if r[1].endswith('/assign-ticket')],
            [
                (
                    'POST',
                    f'/organizations/{self.org}/workflows/{self.slug}'
                    f'/runs/{run_id}/steps/assign/assign-ticket',
                )
            ],
        )

    async def test_assign_ticket_empty_role_takes_second_port(self) -> None:
        self.api.assignee = None
        _, step = await self._assign_run()
        self.assertEqual(step['port'], 1)

    async def test_slack_posts_once(self) -> None:
        run_id = await self._start(await self._slack_workflow())
        await self._crash_on(run_id, 'tell')
        run = await self._drive(run_id, runner=self._engine('worker-b'))
        self.assertEqual(run['status'], 'succeeded', run)
        self.assertEqual(
            run['steps']['tell']['output'],
            {
                'channel': 'C0123456789',
                'ts': '1700000000.000100',
                'permalink': 'https://example.slack.com/archives/x',
            },
        )
        self.assertEqual(
            self.api.slacks,
            [
                f'/organizations/{self.org}/workflows/{self.slug}'
                f'/runs/{run_id}/steps/tell/slack'
            ],
        )

    async def test_slack_error_fails_the_step(self) -> None:
        self.api.slack_error = 'not_in_channel'
        run = await self._drive(
            await self._start(await self._slack_workflow())
        )
        self.assertEqual(run['status'], 'failed')
        tell = run['steps']['tell']
        self.assertEqual(tell['error'], 'slack_failed: not_in_channel')
        self.assertEqual(tell['attempt'], 1)
        self.assertEqual(len(self.api.slacks), 1)

    async def test_slack_unreachable_is_outcome_unknown(self) -> None:
        """Slack may have posted, so an operator can recover the step."""
        self.api.slack_unreachable = True
        run = await self._drive(
            await self._start(await self._slack_workflow())
        )
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['error'], 'outcome_unknown')
        tell = run['steps']['tell']
        self.assertEqual(tell['error'], 'outcome_unknown')
        self.assertEqual(tell['attempt'], 1)
        self.assertEqual(len(self.api.slacks), 1)

    async def test_slack_rate_limit_is_retried(self) -> None:
        self.api.slack_ratelimited = 1
        with mock.patch.object(engine, 'RETRY_BACKOFF', 0):
            run = await self._drive(
                await self._start(await self._slack_workflow())
            )
        self.assertEqual(run['status'], 'succeeded', run)
        self.assertEqual(run['steps']['tell']['attempt'], 2)
        self.assertEqual(len(self.api.slacks), 2)

    async def test_slack_rate_limit_fails_after_retries(self) -> None:
        self.api.slack_ratelimited = 10
        with mock.patch.object(engine, 'RETRY_BACKOFF', 0):
            run = await self._drive(
                await self._start(await self._slack_workflow())
            )
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['steps']['tell']['error'], 'slack_ratelimited')
        self.assertEqual(len(self.api.slacks), 4)

    async def test_slack_rendered_channel_is_checked(self) -> None:
        workflow_id = await self._workflow(
            [
                _node(
                    'start',
                    'manual',
                    {'inputs': [{'name': 'channel', 'type': 'string'}]},
                ),
                _node(
                    'tell',
                    'slack',
                    {'channel': '{{ trigger.channel }}', 'text': 'Hello'},
                ),
            ],
            [_edge('start', 'tell')],
            {'on_failure': 'none'},
        )
        run = await self._drive(
            await self._start(workflow_id, {'channel': '#general'})
        )
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['steps']['tell']['error'], 'invalid_params')
        self.assertEqual(self.api.slacks, [])

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
            {'recipients': [self.email], 'failed': []},
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


class ConditionTestCase(EngineTestCase):
    async def _check(
        self, conditions: list[dict[str, typing.Any]], match: str = 'all'
    ) -> dict[str, typing.Any]:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'check',
                    'condition',
                    {'conditions': conditions, 'match': match},
                ),
                _node('yes', 'wait', {'duration': '1s'}),
                _node('no', 'wait', {'duration': '1s'}),
            ],
            [
                _edge('start', 'check'),
                _edge('check', 'yes', 0),
                _edge('check', 'no', 1),
            ],
        )
        run_id = await self._start(
            workflow_id, {'count': 5, 'tags': ['a', 'b'], 'name': 'abc'}
        )
        return await self._drive(run_id)

    async def test_whole_references_keep_their_type(self) -> None:
        run = await self._check(
            [
                {
                    'a': '{{ trigger.count }}',
                    'operator': 'greater_than',
                    'b': '3',
                },
                {'a': '{{ trigger.tags }}', 'operator': 'contains', 'b': 'b'},
            ]
        )
        self.assertEqual(run['status'], 'succeeded', run)
        check = run['steps']['check']
        self.assertEqual(check['port'], 0)
        self.assertEqual(
            [(r['a'], r['result']) for r in check['output']['conditions']],
            [(5, True), (['a', 'b'], True)],
        )
        self.assertTrue(check['output']['result'])
        self.assertEqual(
            self._states(run),
            {
                'start': 'succeeded',
                'check': 'succeeded',
                'yes': 'succeeded',
                'no': 'skipped',
            },
        )

    async def test_text_templates_render_as_text(self) -> None:
        run = await self._check(
            [
                {
                    'a': '{{ trigger.count + 1 }}',
                    'operator': 'less_than',
                    'b': '{{ trigger.count }}',
                },
                {'a': '{{ trigger.name }}x', 'operator': 'equals', 'b': 'abc'},
            ],
            match='any',
        )
        self.assertEqual(run['status'], 'succeeded', run)
        check = run['steps']['check']
        self.assertEqual(check['port'], 1)
        self.assertEqual(
            [r['a'] for r in check['output']['conditions']], ['6', 'abcx']
        )
        self.assertEqual(self._states(run)['yes'], 'skipped')
        self.assertEqual(self._states(run)['no'], 'succeeded')

    async def test_an_error_fails_the_run(self) -> None:
        run = await self._check(
            [{'a': '{{ trigger.name }}', 'operator': 'greater_than', 'b': 1}]
        )
        self.assertEqual(run['status'], 'failed', run)
        check = run['steps']['check']
        self.assertEqual(
            (check['status'], check['error']), ('failed', 'not_a_number')
        )
        self.assertEqual(check['attempt'], 1)


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


class ReleaseStepTestCase(EngineTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.project = f'proj-{uuid.uuid4().hex[:8]}'
        self.env = f'env-{uuid.uuid4().hex[:8]}'
        self.addAsyncCleanup(self._delete_nodes)
        await self.graph.execute(
            """
            CREATE (p:Project {{id: {project}, slug: {project}}})
            CREATE (e:Environment {{id: {env}, slug: {env}}})
            WITH e
            MATCH (o:Organization {{id: {org}}})
            CREATE (e)-[:BELONGS_TO]->(o)
            RETURN e.id AS id
            """,
            {'project': self.project, 'env': self.env, 'org': self.org},
            ['id'],
        )

    async def _delete_nodes(self) -> None:
        await self.graph.execute(
            """
            MATCH (n) WHERE n.id IN {ids} OR n.id STARTS WITH {project}
            DETACH DELETE n
            RETURN 1 AS ok
            """,
            {'ids': [self.project, self.env], 'project': self.project},
            ['ok'],
        )

    async def _deployed(self, *rows: tuple[str, str, str, str]) -> None:
        """Record deployments to the destination: tag, commit, status, at."""
        await self.graph.execute(
            """
            MATCH (p:Project {{id: {project}}}), (e:Environment {{id: {env}}})
            UNWIND {rows} AS row
            CREATE (r:Release {{id: {project} + row[0], tag: row[0],
                                committish: row[1]}})
            CREATE (d:Deployment {{id: {project} + '-' + row[0],
                                   status: row[2], created_at: row[3]}})
            CREATE (p)-[:HAS_RELEASE]->(r)
            CREATE (d)-[:BELONGS_TO]->(p)
            CREATE (d)-[:TARGETS]->(e)
            CREATE (r)-[:HAS_DEPLOYMENT]->(d)
            RETURN count(d) AS n
            """,
            {
                'project': self.project,
                'env': self.env,
                'rows': [list(row) for row in rows],
            },
            ['n'],
        )

    async def _released(self, tag: str, committish: str) -> None:
        """Record a release that the destination has not run."""
        await self.graph.execute(
            """
            MATCH (p:Project {{id: {project}}})
            CREATE (r:Release {{id: {project} + {tag}, tag: {tag},
                                committish: {committish}}})
            CREATE (p)-[:HAS_RELEASE]->(r)
            RETURN r.id AS id
            """,
            {'project': self.project, 'tag': tag, 'committish': committish},
            ['id'],
        )

    async def _failed_build(self, tag: str, committish: str) -> None:
        await self._released(tag, committish)
        await self.graph.execute(
            """
            MATCH (r:Release {{id: {release}}})
            CREATE (b:Blocker {{id: {release} + '-b', status: 'open',
                                type: 'build-failure'}})
            CREATE (r)-[:BLOCKED_BY]->(b)
            RETURN b.id AS id
            """,
            {'release': self.project + tag},
            ['id'],
        )

    async def _promote(self, **params: typing.Any) -> uuid.UUID:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'ship',
                    'release',
                    {
                        'project_id': self.project,
                        'from_environment': 'testing',
                        'environment': self.env,
                        'commit': '0123abc',
                        **params,
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
        return await self._start(workflow_id)

    def _promotion(self, tag: str, notes: str) -> dict[str, typing.Any]:
        return {
            'action': 'promote',
            'from_environment': 'testing',
            'to_environment': self.env,
            'from_committish': SHA,
            'tag': tag,
            'release_notes_markdown': notes,
        }

    async def test_promotes_once_and_never_acknowledges_ci(self) -> None:
        run_id = await self._promote(tag='1.4.0', release_notes='Notes.')
        run = await self._drive(run_id)
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(self.api.bodies, [self._promotion('1.4.0', 'Notes.')])
        self.assertIn(f'{run_id}:ship', self.api.by_key)
        self.assertEqual(self.api.drafts, [])
        ship = run['steps']['ship']
        self.assertEqual((ship['status'], ship['port']), ('succeeded', 0))
        self.assertEqual(
            ship['output'],
            {
                'deployment_id': 'r1',
                'status': 'success',
                'tag': '1.4.0',
                'release_notes': 'Notes.',
                'degraded': False,
                'error': None,
            },
        )

    async def test_untagged_source_drafts_the_release(self) -> None:
        await self._deployed(
            ('1.3.0', 'c130', 'success', '2026-01-01'),
            ('1.4.0', 'c140', 'success', '2026-02-01'),
            ('1.5.0', 'c150', 'failed', '2026-03-01'),
        )
        run = await self._drive(await self._promote())
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(
            self.api.drafts,
            [{'base_sha': '1.4.0', 'head_sha': SHA, 'last_tag': '1.4.0'}],
        )
        self.assertEqual(
            self.api.bodies, [self._promotion('1.6.0', '- Add things')]
        )
        output = run['steps']['ship']['output']
        self.assertEqual((output['tag'], output['degraded']), ('1.6.0', False))

    async def test_draft_bumps_from_the_newest_tag(self) -> None:
        await self._deployed(('1.4.0', 'c140', 'success', '2026-02-01'))
        self.api.latest_tag = '1.5.0'
        run = await self._drive(await self._promote())
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(
            self.api.drafts,
            [{'base_sha': '1.5.0', 'head_sha': SHA, 'last_tag': '1.5.0'}],
        )

    async def test_drafted_tag_that_exists_is_refused(self) -> None:
        await self._deployed(
            ('1.4.0', 'c140', 'success', '2026-02-01'),
            ('1.3.0', 'c130', 'success', '2026-03-01'),
        )
        self.api.draft = {**self.api.draft, 'version': '1.4.0'}
        run = await self._drive(await self._promote())
        ship = run['steps']['ship']
        self.assertEqual((ship['status'], ship['port']), ('failed', 1))
        self.assertEqual(
            (ship['output']['status'], ship['output']['error']),
            ('refused', 'tag_exists: 1.4.0'),
        )
        self.assertEqual(self.api.bodies, [])

    async def test_tagged_commit_is_refused(self) -> None:
        await self._released('2.0.0', SHA[:7])
        run = await self._drive(await self._promote())
        ship = run['steps']['ship']
        self.assertEqual((ship['status'], ship['port']), ('failed', 1))
        self.assertEqual(
            ship['output']['error'], 'commit_already_tagged: 2.0.0'
        )
        self.assertEqual(self.api.bodies, [])

    async def test_given_tag_gets_drafted_notes(self) -> None:
        await self._deployed(('1.4.0', 'c140', 'success', '2026-02-01'))
        run = await self._drive(await self._promote(tag='1.9.0'))
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(
            self.api.bodies, [self._promotion('1.9.0', '- Add things')]
        )

    async def test_failed_build_does_not_hold_the_next_tag(self) -> None:
        await self._deployed(('1.4.0', 'c140', 'success', '2026-02-01'))
        await self._failed_build('1.5.0', SHA[:7])
        self.api.latest_tag = '1.4.0'
        run = await self._drive(await self._promote())
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual([d['last_tag'] for d in self.api.drafts], ['1.5.0'])
        self.assertEqual(
            self.api.bodies, [self._promotion('1.6.0', '- Add things')]
        )

    async def test_given_notes_are_kept(self) -> None:
        await self._deployed(('1.4.0', 'c140', 'success', '2026-02-01'))
        run = await self._drive(await self._promote(release_notes='Mine.'))
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(self.api.bodies, [self._promotion('1.6.0', 'Mine.')])

    async def test_given_tag_and_notes_are_not_drafted(self) -> None:
        await self._deployed(('1.4.0', 'c140', 'success', '2026-02-01'))
        run = await self._drive(
            await self._promote(tag='1.9.0', release_notes='Mine.')
        )
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(self.api.drafts, [])
        self.assertEqual(self.api.bodies, [self._promotion('1.9.0', 'Mine.')])

    async def test_commit_with_several_tags_is_refused(self) -> None:
        await self._released('2.0.0', SHA[:7])
        await self._released('2.0.1', SHA[:7])
        run = await self._drive(await self._promote())
        ship = run['steps']['ship']
        self.assertEqual((ship['status'], ship['port']), ('failed', 1))
        self.assertEqual(
            ship['output']['error'], 'commit_has_several_tags: 2.0.0, 2.0.1'
        )
        self.assertEqual(self.api.bodies, [])

    async def test_refused_draft_is_refused(self) -> None:
        await self._deployed(('1.4.0', 'c140', 'success', '2026-02-01'))
        original = FakeApi.__call__

        def disabled(
            api: FakeApi, request: httpx.Request
        ) -> httpx.Response | abc.Awaitable[httpx.Response]:
            if request.url.path.endswith('/draft-release-notes'):
                return httpx.Response(
                    409, json={'detail': 'Delivery is disabled.'}
                )
            return original(api, request)

        run_id = await self._promote()
        with mock.patch.object(FakeApi, '__call__', disabled):
            run = await self._drive(run_id)
        ship = run['steps']['ship']
        self.assertEqual((ship['status'], ship['port']), ('failed', 1))
        self.assertEqual(ship['output']['error'], 'Delivery is disabled.')
        self.assertEqual(self.api.bodies, [])

    async def test_degraded_draft_is_reported(self) -> None:
        await self._deployed(('1.4.0', 'c140', 'success', '2026-02-01'))
        self.api.draft = {**self.api.draft, 'degraded': True}
        run = await self._drive(await self._promote())
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertTrue(run['steps']['ship']['output']['degraded'])

    async def test_retry_does_not_draft_again(self) -> None:
        await self._deployed(('1.4.0', 'c140', 'success', '2026-02-01'))
        original = FakeApi.__call__
        posts: list[str] = []

        def flaky(
            api: FakeApi, request: httpx.Request
        ) -> httpx.Response | abc.Awaitable[httpx.Response]:
            if request.method == 'POST' and request.url.path.endswith(
                '/deployments'
            ):
                posts.append(request.url.path)
                if len(posts) == 1:
                    return httpx.Response(503, json={'detail': 'down'})
            return original(api, request)

        run_id = await self._promote()
        with (
            mock.patch.object(FakeApi, '__call__', flaky),
            mock.patch.object(engine, 'RETRY_BACKOFF', 0),
        ):
            run = await self._drive(run_id)
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(run['steps']['ship']['attempt'], 2)
        self.assertEqual(len(posts), 2)
        self.assertEqual(len(self.api.drafts), 1)
        self.assertEqual(
            self.api.bodies, [self._promotion('1.6.0', '- Add things')]
        )

    async def test_first_release_drafts_from_history(self) -> None:
        # A failed deployment is not a release the environment runs.
        await self._deployed(('1.5.0', 'c150', 'failed', '2026-03-01'))
        run = await self._drive(await self._promote())
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(
            self.api.drafts,
            [{'base_sha': '', 'head_sha': SHA, 'last_tag': None}],
        )
        self.assertEqual(
            self.api.bodies, [self._promotion('1.6.0', '- Add things')]
        )

    def _status(
        self,
        status: str,
        tag: str = '1.4.0',
        error: str | None = None,
        artifact: str = 'a1',
    ) -> dict[str, typing.Any]:
        return {
            'status': status,
            'tag': tag,
            'committish': '0123abc',
            'environment': self.env,
            'from_environment': 'testing',
            'artifact_run_id': artifact,
            'error': error,
        }

    def _status_polls(self) -> int:
        return sum(p.endswith('/promote-status') for p in self.api.paths)

    async def test_release_workflow_is_followed_to_success(self) -> None:
        self.api.promote_phase = 'building'
        self.api.promote_statuses = [
            self._status('building'),
            self._status('deploying'),
            self._status('success'),
        ]
        run = await self._drive(
            await self._promote(tag='1.4.0', release_notes='Notes.')
        )
        self.assertEqual(run['status'], 'succeeded', run['error'])
        ship = run['steps']['ship']
        self.assertEqual((ship['status'], ship['port']), ('succeeded', 0))
        self.assertEqual(
            ship['output'],
            {
                'deployment_id': 'a1',
                'status': 'success',
                'tag': '1.4.0',
                'release_notes': 'Notes.',
                'degraded': False,
                'error': None,
            },
        )
        self.assertEqual(self._status_polls(), 3)
        self.assertEqual(self.api.dispatches, 1)

    async def test_release_workflow_failures_take_failed(self) -> None:
        self.api.promote_phase = 'building'
        for status in ('build_failed', 'deploy_failed', 'failed'):
            with self.subTest(status):
                self.api.dispatches = 0
                self.api.promote_statuses = [
                    self._status(status, error='Boom.')
                ]
                run = await self._drive(
                    await self._promote(tag='1.4.0', release_notes='Notes.')
                )
                ship = run['steps']['ship']
                self.assertEqual((ship['status'], ship['port']), ('failed', 1))
                self.assertEqual(ship['output']['status'], status)
                self.assertEqual(ship['output']['error'], f'{status}: Boom.')

    async def test_the_status_of_another_build_is_skipped(self) -> None:
        self.api.promote_phase = 'building'
        self.api.promote_statuses = [
            self._status('deploying', tag='1.5.0', artifact='a9'),
            self._status('success', tag='1.5.0', artifact='a9'),
            self._status('success'),
        ]
        run = await self._drive(
            await self._promote(tag='1.4.0', release_notes='Notes.')
        )
        ship = run['steps']['ship']
        self.assertEqual((ship['status'], ship['port']), ('succeeded', 0))
        self.assertEqual(self._status_polls(), 3)

    async def test_deployment_tells_the_end_under_another_build(
        self,
    ) -> None:
        self.api.promote_phase = 'building'
        self.api.promote_statuses = [
            self._status('deploying', tag='1.5.0', artifact='a9')
        ]
        run_id = await self._promote(tag='1.4.0', release_notes='Notes.')
        await self._drive(run_id, until=lambda _: self._status_polls() >= 1)
        # Only now: a Release with the tag before the cut is refused.
        await self._deployed(('1.4.0', SHA[:7], 'success', '2026-04-01'))
        run = await self._drive(run_id)
        ship = run['steps']['ship']
        self.assertEqual((ship['status'], ship['port']), ('succeeded', 0))
        self.assertEqual(
            (ship['output']['deployment_id'], ship['output']['tag']),
            ('a1', '1.4.0'),
        )

    async def test_failed_rollout_under_another_build(self) -> None:
        self.api.promote_phase = 'building'
        self.api.promote_statuses = [
            self._status('deploying', tag='1.5.0', artifact='a9')
        ]
        run_id = await self._promote(tag='1.4.0', release_notes='Notes.')
        await self._drive(run_id, until=lambda _: self._status_polls() >= 1)
        await self._deployed(('1.4.0', SHA[:7], 'failed', '2026-04-01'))
        run = await self._drive(run_id)
        ship = run['steps']['ship']
        self.assertEqual((ship['status'], ship['port']), ('failed', 1))
        self.assertEqual(ship['output']['error'], 'deployment_failed')

    async def test_failed_build_under_another_build(self) -> None:
        self.api.promote_phase = 'building'
        self.api.promote_statuses = [
            self._status('deploying', tag='1.5.0', artifact='a9')
        ]
        run_id = await self._promote(tag='1.4.0', release_notes='Notes.')
        await self._drive(run_id, until=lambda _: self._status_polls() >= 1)
        await self._failed_build('1.4.0', SHA[:7])
        run = await self._drive(run_id)
        ship = run['steps']['ship']
        self.assertEqual((ship['status'], ship['port']), ('failed', 1))
        self.assertEqual(ship['output']['error'], 'build_failed')

    async def test_unwatched_build_fails_at_once(self) -> None:
        self.api.promote_phase = 'building'
        self.api.promote_watched = False
        run = await self._drive(
            await self._promote(tag='1.4.0', release_notes='Notes.')
        )
        ship = run['steps']['ship']
        self.assertEqual((ship['status'], ship['port']), ('failed', 1))
        self.assertEqual(ship['output']['error'], 'promote_not_watched')
        self.assertEqual(ship['output']['deployment_id'], 'a1')
        self.assertEqual(self._status_polls(), 0)

    async def test_legacy_path_follows_the_run(self) -> None:
        original = FakeApi.__call__

        def failing(
            api: FakeApi, request: httpx.Request
        ) -> httpx.Response | abc.Awaitable[httpx.Response]:
            if '/runs/' in request.url.path:
                return httpx.Response(
                    200, json={'run_id': 'r1', 'status': 'failure'}
                )
            return original(api, request)

        run_id = await self._promote(tag='1.4.0', release_notes='Notes.')
        with mock.patch.object(FakeApi, '__call__', failing):
            run = await self._drive(run_id)
        ship = run['steps']['ship']
        self.assertEqual((ship['status'], ship['port']), ('failed', 1))
        self.assertEqual(
            ship['output'],
            {
                'deployment_id': 'r1',
                'status': 'failure',
                'tag': '1.4.0',
                'release_notes': 'Notes.',
                'degraded': False,
                'error': 'deployment_failure',
            },
        )
        self.assertEqual(self._status_polls(), 0)

    async def _drive_answered(
        self, response: httpx.Response
    ) -> dict[str, typing.Any]:
        """Drive a tagged promote whose POST gets ``response``."""
        original = FakeApi.__call__

        def answer(
            api: FakeApi, request: httpx.Request
        ) -> httpx.Response | abc.Awaitable[httpx.Response]:
            if request.method == 'POST' and request.url.path.endswith(
                '/deployments'
            ):
                api.dispatches += 1
                return response
            return original(api, request)

        run_id = await self._promote(tag='1.4.0', release_notes='Notes.')
        with mock.patch.object(FakeApi, '__call__', answer):
            run = await self._drive(run_id)
        self.assertEqual(run['status'], 'succeeded', run['error'])
        return run['steps']['ship']

    async def test_conflict_is_refused(self) -> None:
        for status, detail in (
            (409, "Release '1.4.0' is blocked and cannot be deployed"),
            (
                409,
                'Release 1.4.0 is already building; wait for it to finish '
                'before you promote it again.',
            ),
            (
                409,
                'CI failed for commit 0123abc. Review the failing checks '
                'before you promote it.',
            ),
            (400, "Environment 'staging' cannot be promoted to."),
            (404, 'Environment not found'),
        ):
            with self.subTest(detail):
                self.api.dispatches = 0
                ship = await self._drive_answered(
                    httpx.Response(status, json={'detail': detail})
                )
                self.assertEqual((ship['status'], ship['port']), ('failed', 1))
                self.assertEqual(ship['attempt'], 1)
                self.assertEqual(
                    ship['output'],
                    {
                        'deployment_id': '',
                        'status': 'refused',
                        'tag': '1.4.0',
                        'release_notes': 'Notes.',
                        'degraded': False,
                        'error': detail,
                    },
                )
                self.assertEqual(self.api.dispatches, 1)

    async def test_autonomy_refusal_is_refused(self) -> None:
        ship = await self._drive_answered(
            httpx.Response(
                403,
                json={
                    'detail': {
                        'error': 'environment_not_autonomous',
                        'message': 'Staging does not allow it.',
                    }
                },
            )
        )
        self.assertEqual((ship['status'], ship['port']), ('failed', 1))
        self.assertEqual(
            ship['output']['error'],
            'environment_not_autonomous: Staging does not allow it.',
        )

    async def test_unrecorded_promote_fails(self) -> None:
        ship = await self._drive_answered(
            httpx.Response(
                202,
                json={
                    'run': {'run_id': '', 'status': 'queued'},
                    'plugin_id': 'p',
                    'plugin_slug': 'github',
                    'recorded': False,
                    'tag': '1.4.0',
                    'warning': 'trigger_deployment failed: boom',
                },
            )
        )
        self.assertEqual((ship['status'], ship['port']), ('failed', 1))
        self.assertEqual(
            ship['output']['error'], 'trigger_deployment failed: boom'
        )
        self.assertEqual(ship['attempt'], 1)

    async def test_errors_without_a_reason_stay_errors(self) -> None:
        for response, code in (
            (httpx.Response(403, json={'detail': 'Forbidden'}), 'forbidden'),
            (httpx.Response(422, json={'detail': 'bad'}), 'http_422'),
            (
                httpx.Response(
                    409, json={'detail': {'error': 'outcome_unknown'}}
                ),
                'outcome_unknown',
            ),
        ):
            with self.subTest(code):
                ship = await self._drive_answered(response)
                self.assertEqual(
                    (ship['status'], ship['port'], ship['error']),
                    ('failed', 1, code),
                )
                self.assertIsNone(ship['output'])
                self.assertEqual(ship['attempt'], 1)


class WaitTestCase(EngineTestCase):
    async def _hold(self, hold: str) -> dict[str, typing.Any]:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node('hold', 'wait', {'duration': '{{ trigger.hold }}'}),
            ],
            [_edge('start', 'hold')],
        )
        return await self._drive(
            await self._start(workflow_id, payload={'hold': hold})
        )

    async def test_duration_from_the_trigger(self) -> None:
        run = await self._hold('1s')
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(run['steps']['hold']['output'], {'waited_seconds': 1})

    async def test_rendered_value_that_is_not_a_duration(self) -> None:
        for hold in (
            'soon',
            '{{ trigger.other }}',
            '999999999999d',
            '9' * 4301 + 'd',
        ):
            with self.subTest(hold):
                hold_step = (await self._hold(hold))['steps']['hold']
                self.assertEqual(
                    (hold_step['status'], hold_step['error']),
                    ('failed', 'invalid_params'),
                )
                self.assertEqual(hold_step['attempt'], 1)


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


class SearchLogsStepTestCase(EngineTestCase):
    async def test_output_feeds_the_next_step(self) -> None:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'logs',
                    'search_logs',
                    {
                        'project_id': 'proj-1',
                        'environments': ['production', 'staging'],
                        'start_time': '2026-01-01T00:00:00Z',
                        'limit': 50,
                        'filters': ['service:eq:api'],
                        'levels': ['ERROR', 'WARN'],
                        'source': '',
                    },
                ),
                _node(
                    'check',
                    'condition',
                    {
                        'conditions': [
                            {
                                'a': '{{ logs.total }}',
                                'operator': 'greater_than',
                                'b': '0',
                            }
                        ]
                    },
                ),
            ],
            [_edge('start', 'logs'), _edge('logs', 'check')],
        )
        run = await self._drive(await self._start(workflow_id))
        self.assertEqual(run['status'], 'succeeded', run)
        self.assertIn(
            (
                'GET',
                f'/organizations/{self.org}/projects/proj-1/logs/'
                '?environment=production&environment=staging'
                '&start_time=2026-01-01T00%3A00%3A00Z&limit=50'
                '&filter=service%3Aeq%3Aapi&level=ERROR&level=WARN',
            ),
            self.api.requests,
        )
        output = run['steps']['logs']['output']
        self.assertEqual(output['entries'][0]['message'], 'sample')
        self.assertEqual(output['next_cursor'], 'c2')
        self.assertEqual(run['steps']['check']['port'], 0)


class AgentStepTestCase(EngineTestCase):
    """The agent step, with the real agent task routes and store.

    The fake imbi-api passes the agent task calls to the route
    functions of imbi-api, so the step makes real ADR 0020 tasks. The
    test closes a task with the store, as the harness routes do.
    """

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.config.agent_poll_seconds = 1
        await tickets.initialize()
        self.task_pool = tickets.create_pool()
        await self.task_pool.open()
        self.tasks = tickets.TicketStore(self.task_pool)
        self.addAsyncCleanup(self._cleanup_tasks)
        self.agent_id = f'agent-{uuid.uuid4().hex[:8]}'
        await self.graph.execute(
            """
            MATCH (o:Organization {{id: {org}}})
            CREATE (a:Agent {{id: {id}, slug: {id}, name: 'Fixer',
                              enabled: true, settings: '{{}}',
                              version: 2, org_id: {org}}})
            CREATE (a)-[:BELONGS_TO]->(o)
            RETURN a.id AS id
            """,
            {'org': self.org, 'id': self.agent_id},
            ['id'],
        )
        self.engine_auth = permissions.AuthContext(
            service_account=models.ServiceAccount(
                slug='imbi-workflows', display_name='Imbi Workflows'
            ),
            auth_method='client_credentials',
        )
        #: Status codes to answer instead of the next agent task calls,
        #: after the route ran.
        self.fail_with: list[int] = []
        #: A status code that every cancel call gets, when set.
        self.fail_cancel: int | None = None
        self.api.agent = self._agent_route

    async def _cleanup_tasks(self) -> None:
        await self.graph.execute(
            """
            MATCH (a:Agent {{id: {id}}})
            OPTIONAL MATCH (a)-[:ACTS_AS]->(s:ServiceAccount)
            DETACH DELETE s, a
            RETURN 1 AS ok
            """,
            {'id': self.agent_id},
            ['ok'],
        )
        async with self.task_pool.connection() as conn:
            await conn.execute(
                'DELETE FROM tickets.tickets WHERE organization_id = %s',
                (self.org,),
            )
            await conn.execute(
                'DELETE FROM tickets.ticket_id_sequences'
                ' WHERE organization_id = %s',
                (self.org,),
            )
        await self.task_pool.close()

    async def _agent_route(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path.split('/')
        # /organizations/{org}/workflows/{slug}/runs/{run}/steps/{node}/...
        org, slug, run_id, node_id = parts[2], parts[4], parts[6], parts[8]
        args: dict[str, typing.Any] = {
            'org_id': self.org,
            'slug': slug,
            'run_id': uuid.UUID(run_id),
            'node_id': node_id,
            'store': self.definitions,
            'runs': self.runs,
            'tasks': self.tasks,
            'auth': self.engine_auth,
        }
        try:
            if parts[-1] == 'cancel' and self.fail_cancel:
                return httpx.Response(self.fail_cancel, json={})
            if parts[-1] == 'cancel':
                await workflow_runs.cancel_step_agent_task(**args)
                response = httpx.Response(204)
            else:
                body = await workflow_runs.step_agent_task(
                    org_slug=org, db=self.graph, **args
                )
                response = httpx.Response(200, json=body)
        except fastapi.HTTPException as e:
            response = httpx.Response(e.status_code, json={'detail': e.detail})
        if self.fail_with:
            return httpx.Response(self.fail_with.pop(0), json={})
        return response

    async def _agent_workflow(self, **ask: typing.Any) -> uuid.UUID:
        """``ask`` sets node fields of the agent step, such as retries."""
        return await self._workflow(
            [
                _node(
                    'start',
                    'manual',
                    {'inputs': [{'name': 'version', 'type': 'string'}]},
                ),
                _node(
                    'ask',
                    'agent',
                    {
                        'agent_id': self.agent_id,
                        'instruction': 'Check {{ trigger.version }}.',
                    },
                )
                | ask,
                _node('ok', 'wait', {'duration': '1s'}),
                _node('bad', 'wait', {'duration': '1s'}),
            ],
            [
                _edge('start', 'ask'),
                _edge('ask', 'ok', 0),
                _edge('ask', 'bad', 1),
            ],
        )

    async def _task(self, run_id: uuid.UUID) -> dict[str, typing.Any]:
        """Tick until the agent step has its task; return the task."""
        run = await self._drive(
            run_id,
            until=lambda r: bool(r['steps'].get('ask', {}).get('state')),
        )
        task = await self.tasks.get(
            self.org, run['steps']['ask']['state']['task_id']
        )
        assert task is not None
        return task

    async def _org_tasks(self) -> list[dict[str, typing.Any]]:
        async with (
            self.task_pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(
                'SELECT * FROM tickets.tickets WHERE organization_id = %s',
                (self.org,),
            )
            return await cur.fetchall()

    def _agent(self) -> tickets.Actor:
        return tickets.Actor('agent', self.agent_id, 'harness')

    async def test_task_done_takes_succeeded(self) -> None:
        run_id = await self._start(
            await self._agent_workflow(), {'version': '1.2'}
        )
        task = await self._task(run_id)
        self.assertEqual(task['status'], 'queued')
        self.assertEqual(task['description'], 'Check 1.2.')
        self.assertEqual(task['title'], 'Deploy guard: Ask')
        self.assertEqual(task['owner'], self.email)
        self.assertEqual(task['agent_version'], 2)
        self.assertEqual(task['idempotency_key'], f'{run_id}:ask')
        self.assertEqual(
            (task['origin_kind'], task['origin_id']), ('human', self.email)
        )
        self.assertEqual(
            task['origin'],
            {
                'kind': 'human',
                'workflow_run_id': str(run_id),
                'node_key': 'ask',
            },
        )
        await self.tasks.reply(
            self.org, task['short_id'], 'Version 1.2 is fine.', self._agent()
        )
        await self.tasks.set_outcome(
            self.org, task['short_id'], 'done_acted', None, self._agent()
        )
        run = await self._drive(run_id)
        self.assertEqual(run['status'], 'succeeded', run)
        ask = run['steps']['ask']
        self.assertEqual(
            (ask['status'], ask['port'], ask['attempt']), ('succeeded', 0, 1)
        )
        self.assertEqual(
            ask['output'],
            {
                'task_id': task['short_id'],
                'outcome': 'done_acted',
                'reason': None,
                'summary': 'Version 1.2 is fine.',
                'result': None,
                'title': 'Deploy guard: Ask',
                'url': None,
                'project': None,
                'agent': self.agent_id,
                'cost_usd': 0.0,
                'type': 'task',
                'priority': 'normal',
                'due_date': None,
                'labels': [],
                'roles': {},
                'team': None,
                'custom_fields': {},
            },
        )
        self.assertEqual(
            self._states(run),
            {
                'start': 'succeeded',
                'ask': 'succeeded',
                'ok': 'succeeded',
                'bad': 'skipped',
            },
        )
        self.assertEqual(len(await self._org_tasks()), 1)

    async def _structured_step(
        self, outcome: tickets.Outcome, reason: str | None
    ) -> dict[str, typing.Any]:
        """Return the agent step of a task that closes with ``outcome``
        and structured output."""
        fields = [
            {'name': 'subjects', 'type': 'array', 'items': 'string'},
            {'name': 'note', 'type': 'string', 'required': False},
        ]
        run_id = await self._start(
            await self._agent_workflow(
                params={
                    'agent_id': self.agent_id,
                    'instruction': 'Triage.',
                    'output_fields': fields,
                }
            ),
            {'version': '1'},
        )
        task = await self._task(run_id)
        self.assertEqual(task['output_schema']['required'], ['subjects'])
        await self.tasks.set_outcome(
            self.org,
            task['short_id'],
            outcome,
            reason,
            self._agent(),
            {'subjects': ['Hi']},
        )
        run = await self._drive(run_id)
        return run['steps']['ask']

    async def test_structured_output_is_the_result(self) -> None:
        ask = await self._structured_step('done_acted', None)
        self.assertEqual((ask['status'], ask['port']), ('succeeded', 0))
        self.assertEqual(
            ask['output']['result'], {'subjects': ['Hi'], 'note': None}
        )

    async def test_failed_outcome_has_no_result(self) -> None:
        ask = await self._structured_step('failed_external', 'ci_down')
        self.assertEqual((ask['status'], ask['port']), ('failed', 1))
        self.assertIsNone(ask['output']['result'])

    async def test_failed_outcome_takes_failed(self) -> None:
        run_id = await self._start(
            await self._agent_workflow(), {'version': '1'}
        )
        task = await self._task(run_id)
        await self.tasks.set_outcome(
            self.org,
            task['short_id'],
            'failed_external',
            'ci_down',
            self._agent(),
        )
        run = await self._drive(run_id)
        self.assertEqual(run['status'], 'succeeded', run)
        ask = run['steps']['ask']
        self.assertEqual((ask['status'], ask['port']), ('failed', 1))
        self.assertEqual(ask['output']['reason'], 'ci_down')
        self.assertIsNone(ask['output']['summary'])
        self.assertEqual(run['steps']['ok']['status'], 'skipped')
        self.assertEqual(run['steps']['bad']['status'], 'succeeded')

    async def test_cancel_run_cancels_task(self) -> None:
        run_id = await self._start(
            await self._agent_workflow(), {'version': '1'}
        )
        task = await self._task(run_id)
        self.assertTrue(await self.runs.cancel(run_id))
        run = await self._drive(run_id)
        self.assertEqual(run['status'], 'cancelled')
        self.assertEqual(run['steps']['ask']['status'], 'cancelled')
        closed = await self.tasks.get(self.org, task['short_id'])
        assert closed is not None
        self.assertEqual(closed['control'], 'cancel')
        # No harness session is open, so the cancel closes it at once.
        self.assertEqual(
            (closed['status'], closed['outcome']),
            ('closed', 'cancelled_by_human'),
        )

    async def test_retry_does_not_make_a_second_task(self) -> None:
        run_id = await self._start(
            await self._agent_workflow(), {'version': '1'}
        )
        # The first call makes the task, and its answer is lost.
        self.fail_with = [503]
        with mock.patch.object(engine, 'RETRY_BACKOFF', 0):
            task = await self._task(run_id)
        run = await self._run(run_id)
        self.assertEqual(run['steps']['ask']['attempt'], 2)
        self.assertEqual(len(await self._org_tasks()), 1)
        # A retry keeps the task open.
        self.assertEqual(task['control'], 'run')
        await self.tasks.set_outcome(
            self.org, task['short_id'], 'done_acted', None, self._agent()
        )
        run = await self._drive(run_id)
        self.assertEqual(
            run['steps']['ask']['output']['task_id'], task['short_id']
        )
        self.assertEqual(len(await self._org_tasks()), 1)

    async def test_step_timeout_cancels_the_task(self) -> None:
        run_id = await self._start(
            await self._agent_workflow(timeout_seconds=1, retries=0),
            {'version': '1'},
        )
        task = await self._task(run_id)
        await asyncio.sleep(1.1)
        run = await self._drive(run_id)
        ask = run['steps']['ask']
        self.assertEqual(
            (ask['status'], ask['error'], ask['port']),
            ('failed', 'timeout', 1),
        )
        closed = await self.tasks.get(self.org, task['short_id'])
        assert closed is not None
        self.assertEqual(
            (closed['control'], closed['status'], closed['outcome']),
            ('cancel', 'closed', 'cancelled_by_human'),
        )
        self.assertEqual(len(await self._org_tasks()), 1)

    async def _control(self, short_id: str) -> tuple[str, str]:
        task = await self.tasks.get(self.org, short_id)
        assert task is not None
        return task['control'], task['status']

    async def test_failed_cancel_at_close_is_reconciled(self) -> None:
        run_id = await self._start(
            await self._agent_workflow(), {'version': '1'}
        )
        task = await self._task(run_id)
        self.fail_cancel = 503
        self.assertTrue(await self.runs.cancel(run_id))
        run = await self._drive(run_id)
        # The run closes although the cancel call failed.
        self.assertEqual(run['status'], 'cancelled')
        self.assertEqual(
            await self._control(task['short_id']), ('run', 'queued')
        )
        await sweeper.cancel_orphan_agent_tasks(self.runs, self.tasks)
        self.assertEqual(
            await self._control(task['short_id']), ('cancel', 'closed')
        )

    async def test_failed_cancel_at_step_failure_is_reconciled(self) -> None:
        run_id = await self._start(
            await self._agent_workflow(timeout_seconds=1, retries=0),
            {'version': '1'},
        )
        task = await self._task(run_id)
        self.fail_cancel = 403
        await asyncio.sleep(1.1)
        run = await self._drive(run_id)
        self.assertEqual(run['steps']['ask']['status'], 'failed')
        self.assertEqual(
            await self._control(task['short_id']), ('run', 'queued')
        )
        await sweeper.cancel_orphan_agent_tasks(self.runs, self.tasks)
        self.assertEqual(
            await self._control(task['short_id']), ('cancel', 'closed')
        )

    async def test_reconcile_keeps_a_running_step_task(self) -> None:
        run_id = await self._start(
            await self._agent_workflow(), {'version': '1'}
        )
        task = await self._task(run_id)
        await sweeper.cancel_orphan_agent_tasks(self.runs, self.tasks)
        self.assertEqual(
            await self._control(task['short_id']), ('run', 'queued')
        )


COUNT = [{'name': 'count', 'type': 'integer'}]


class ScriptStepTestCase(EngineTestCase):
    async def asyncSetUp(self) -> None:
        self.scripts = await self.enterAsyncContext(
            script_runner.open_runner(
                processes=1, max_memory=16 * 1024 * 1024, max_seconds=2.0
            )
        )
        await super().asyncSetUp()

    def _engine(self, worker_id: str) -> engine.Engine:
        runner = super()._engine(worker_id)
        runner.steps.scripts = self.scripts
        return runner

    async def test_result_branch_and_reference(self) -> None:
        # The code holds Jinja syntax: it must reach the sandbox as
        # written, while the inputs are rendered.
        echo = "f'{{{{n}}}}'\n{'count': n * 2}"
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'calc',
                    'script',
                    {
                        'inputs': {'runs': '{{ trigger.runs }}'},
                        'code': "n = len([r for r in runs if r == 'x'])\n"
                        "{'count': n, 'branch': 'many' if n > 1 else 'few'}",
                        'output_fields': COUNT,
                        'branches': ['few', 'many'],
                    },
                ),
                _node(
                    'echo',
                    'script',
                    {
                        'inputs': {'n': '{{ calc.result.count }}'},
                        'code': echo,
                        'output_fields': COUNT,
                    },
                ),
                _node(
                    'other',
                    'script',
                    {'code': "{'count': 0}", 'output_fields': COUNT},
                ),
            ],
            [
                _edge('start', 'calc'),
                _edge('calc', 'other', 0),
                _edge('calc', 'echo', 1),
            ],
        )
        run = await self._drive(
            await self._start(workflow_id, {'runs': ['x', 'y', 'x']})
        )
        self.assertEqual(run['status'], 'succeeded', run['error'])
        steps = run['steps']
        self.assertEqual(
            self._states(run),
            {
                'start': 'succeeded',
                'calc': 'succeeded',
                'echo': 'succeeded',
                'other': 'skipped',
            },
        )
        self.assertEqual(
            steps['calc']['output'],
            {'result': {'count': 2}, 'branch': 'many', 'stdout': None},
        )
        self.assertEqual(steps['calc']['port'], 1)
        self.assertEqual(steps['echo']['input']['inputs'], {'n': 2})
        self.assertEqual(steps['echo']['input']['code'], echo)
        self.assertEqual(steps['echo']['output']['result'], {'count': 4})

    async def test_script_error_fails_the_run(self) -> None:
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                _node(
                    'calc',
                    'script',
                    {
                        'code': "raise ValueError('nope')",
                        'output_fields': COUNT,
                    },
                ),
            ],
            [_edge('start', 'calc')],
            {'on_failure': 'none'},
        )
        run = await self._drive(await self._start(workflow_id))
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['error'], 'script_error: ValueError: nope')
        self.assertEqual(run['steps']['calc']['attempt'], 1)


RISK = [{'name': 'risk', 'type': 'string'}]


class LLMCallStepTestCase(EngineTestCase):
    """The LLM Call step, with a fake ``POST .../prompts/run``."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        #: The requests to the run endpoint.
        self.calls: list[httpx.Request] = []
        #: The answers, in order; the last one repeats. An exception
        #: is raised, as a transport failure.
        self.answers: list[httpx.Response | Exception] = []

        def run(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            answer = self.answers[min(len(self.calls), len(self.answers)) - 1]
            if isinstance(answer, Exception):
                raise answer
            return answer

        self.api.llm_call = run

    def _answer(self, n: int = 1) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                'ref': f'workflows/{self.org}.wf.sum@{n}',
                'n': n,
                'model': 'chat',
                'model_id': 'chat-1',
                'usage': {'input_tokens': 10, 'output_tokens': 5},
                'content_sha256': 'abc',
                'text': '{"risk": "low"}',
                'result': {'risk': 'low'},
                'cost_usd': 0.001,
                'call_id': '00000000-0000-0000-0000-000000000001',
            },
        )

    @staticmethod
    def _error(status: int, code: str, retry: bool) -> httpx.Response:
        return httpx.Response(
            status, json={'detail': {'error': code, 'retry': retry}}
        )

    async def _drive_llm_call(
        self, timeout_seconds: int | None = None
    ) -> dict[str, typing.Any]:
        params = {
            'prompt_ref': f'workflows/{self.org}.wf.sum',
            'prompt_version': 1,
            'output_fields': RISK,
        }
        workflow_id = await self._workflow(
            [
                _node('start', 'manual'),
                {
                    **_node(
                        'sum',
                        'llm_call',
                        {**params, 'inputs': {'diff': '{{ trigger.diff }}'}},
                    ),
                    'timeout_seconds': timeout_seconds,
                },
                _node(
                    'then',
                    'llm_call',
                    {**params, 'inputs': {'risk': '{{ sum.result.risk }}'}},
                ),
            ],
            [_edge('start', 'sum'), _edge('sum', 'then')],
            {'on_failure': 'none'},
        )
        run_id = await self._start(workflow_id, {'diff': 'd'})
        with (
            mock.patch.object(engine, 'RETRY_BACKOFF', 0),
            mock.patch.object(executors, 'LLM_CALL_POLL_SECONDS', 0),
        ):
            return await self._drive(run_id)

    def _keys(self) -> list[str]:
        return [
            r.headers['Idempotency-Key'].split(':', 1)[1] for r in self.calls
        ]

    async def test_result_and_reference(self) -> None:
        self.answers = [self._answer()]
        run = await self._drive_llm_call()
        self.assertEqual(run['status'], 'succeeded', run['error'])
        first = self.calls[0]
        self.assertEqual(
            first.url.path, f'/organizations/{self.org}/prompts/run'
        )
        self.assertEqual(
            json.loads(first.content),
            {
                'ref': f'workflows/{self.org}.wf.sum@1',
                'variables': {'diff': 'd'},
                'output_fields': [
                    {
                        'name': 'risk',
                        'type': 'string',
                        'description': '',
                        'required': True,
                        'enum': None,
                        'format': None,
                        'items': None,
                        'fields': None,
                    }
                ],
            },
        )
        self.assertEqual(
            first.headers['Idempotency-Key'], f'{run["id"]}:sum:1'
        )
        self.assertEqual(
            first.extensions['timeout']['read'], executors.LLM_CALL_TIMEOUT
        )
        output = run['steps']['sum']['output']
        self.assertEqual(output['result'], {'risk': 'low'})
        self.assertEqual(output['prompt_version'], 1)
        self.assertEqual(output['usage']['input_tokens'], 10)
        self.assertEqual(
            run['steps']['then']['input']['inputs'], {'risk': 'low'}
        )

    async def test_retry_is_a_new_attempt(self) -> None:
        self.answers = [
            self._error(503, 'rate_limited', True),
            self._answer(),
        ]
        run = await self._drive_llm_call()
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(self._keys()[:2], ['sum:1', 'sum:2'])
        self.assertEqual(run['steps']['sum']['attempt'], 2)

    async def test_call_in_progress_asks_again_with_the_same_key(
        self,
    ) -> None:
        self.answers = [
            self._error(409, 'call_in_progress', True),
            self._answer(),
        ]
        run = await self._drive_llm_call()
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(self._keys()[:2], ['sum:1', 'sum:1'])
        self.assertEqual(run['steps']['sum']['attempt'], 1)

    async def test_transport_failure_asks_again_with_the_same_key(
        self,
    ) -> None:
        # imbi-api may have made the call: a new key could pay twice.
        self.answers = [httpx.ReadTimeout('lost'), self._answer()]
        run = await self._drive_llm_call()
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(self._keys()[:2], ['sum:1', 'sum:1'])
        self.assertEqual(run['steps']['sum']['attempt'], 1)

    async def test_error_without_a_code_asks_again_with_the_same_key(
        self,
    ) -> None:
        # A 5xx with no error code, such as a failed record of the
        # answer or a proxy page, does not tell whether the call ran.
        self.answers = [
            httpx.Response(500, text='Internal Server Error'),
            httpx.Response(502, text='<html>Bad Gateway</html>'),
            self._answer(),
        ]
        run = await self._drive_llm_call()
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(self._keys()[:3], ['sum:1', 'sum:1', 'sum:1'])
        self.assertEqual(run['steps']['sum']['attempt'], 1)

    async def test_step_error_log_has_no_request_input(self) -> None:
        # A validation error echoes the request input; the log keeps
        # only where and what, not the value.
        detail = [
            {'input': 'secret-ticket-text', 'loc': ['body', 'x'], 'msg': 'bad'}
        ]
        self.answers = [httpx.Response(422, json={'detail': detail})]
        with self.assertLogs('imbi.workflows.engine', 'WARNING') as logs:
            await self._drive_llm_call()
        text = '\n'.join(logs.output)
        self.assertIn("'msg': 'bad'", text)
        self.assertNotIn('secret-ticket-text', text)

    async def test_token_failure_asks_again_with_the_same_key(
        self,
    ) -> None:
        # The first call can still run in imbi-api when a token refresh
        # fails during the poll. A new key could pay twice.
        self.answers = [
            self._error(409, 'call_in_progress', True),
            self._answer(),
        ]
        bearer = executors.Api.bearer
        tokens: list[int] = []

        async def failing(self_: executors.Api) -> str:
            tokens.append(1)
            if len(self.calls) == 1 and len(tokens) == 2:
                raise executors.StepError('token_http_503', retry=True)
            return await bearer(self_)

        with mock.patch.object(executors.Api, 'bearer', failing):
            run = await self._drive_llm_call()
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(self._keys()[:2], ['sum:1', 'sum:1'])
        self.assertEqual(run['steps']['sum']['attempt'], 1)

    async def test_wait_ends_before_the_engine_cancels_the_call(
        self,
    ) -> None:
        # A cancelled call is retried with a new key while imbi-api can
        # still run the first call. The wait must end first, so that
        # the step asks again with the same key.
        self.config.lease_seconds = 60
        self.answers = [self._answer()]
        run = await self._drive_llm_call()
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertLess(self.calls[0].extensions['timeout']['read'], 30)

    async def test_wait_counts_the_time_to_get_the_org_slug(self) -> None:
        # The engine limit includes the org_slug lookup. Limit 1s,
        # budget 0.9s, lookup 0.5s: the wait must be below 0.5s.
        self.config.lease_seconds = 31
        self.answers = [self._answer()]
        org_slug = executors.Executors.org_slug

        async def slow(self_: executors.Executors, org_id: str) -> str:
            await asyncio.sleep(0.5)
            return await org_slug(self_, org_id)

        with mock.patch.object(executors.Executors, 'org_slug', slow):
            run = await self._drive_llm_call()
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertLess(self.calls[0].extensions['timeout']['read'], 0.5)
        self.assertEqual(set(self._keys()), {'sum:1', 'then:1'})

    async def test_slow_org_slug_lookup_keeps_the_attempt(self) -> None:
        # After an unknown outcome the step resumes. A lookup slower
        # than the budget must not let the engine cancel the step and
        # retry it with a new key. Limit 1s, budget 0.9s.
        self.config.lease_seconds = 31
        self.answers = [
            self._error(409, 'call_in_progress', True),
            self._answer(),
        ]
        org_slug = executors.Executors.org_slug
        lookups: list[str] = []

        async def slow(self_: executors.Executors, org_id: str) -> str:
            lookups.append(org_id)
            if len(lookups) == 2:
                await asyncio.sleep(5)
            return await org_slug(self_, org_id)

        with mock.patch.object(executors.Executors, 'org_slug', slow):
            run = await self._drive_llm_call()
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(self._keys()[:2], ['sum:1', 'sum:1'])
        self.assertEqual(run['steps']['sum']['attempt'], 1)

    async def test_failed_org_slug_lookup_keeps_the_attempt(self) -> None:
        # After an unknown outcome the step resumes. A lost graph
        # connection in the lookup must not retry with a new key.
        self.answers = [
            self._error(409, 'call_in_progress', True),
            self._answer(),
        ]
        org_slug = executors.Executors.org_slug
        lookups: list[str] = []

        async def flaky(self_: executors.Executors, org_id: str) -> str:
            lookups.append(org_id)
            if len(lookups) == 2:
                raise psycopg.OperationalError('connection lost')
            return await org_slug(self_, org_id)

        with mock.patch.object(executors.Executors, 'org_slug', flaky):
            run = await self._drive_llm_call()
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(self._keys()[:2], ['sum:1', 'sum:1'])
        self.assertEqual(run['steps']['sum']['attempt'], 1)

    async def test_slow_response_asks_again_with_the_same_key(self) -> None:
        # The httpx timeout limits each phase, not the total. A response
        # that is slower than the budget must not let the engine cancel
        # the step and retry it with a new key. Limit 1s, budget 0.9s.
        self.config.lease_seconds = 31
        answer = self._answer()

        async def slow(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            if len(self.calls) == 1:
                await asyncio.sleep(5)
            return answer

        self.api.llm_call = slow
        run = await self._drive_llm_call()
        self.assertEqual(run['status'], 'succeeded', run['error'])
        self.assertEqual(self._keys()[:2], ['sum:1', 'sum:1'])
        self.assertEqual(run['steps']['sum']['attempt'], 1)

    async def test_timeout_retry_keeps_the_key(self) -> None:
        # The call of attempt 1 can still run in imbi-api when the step
        # times out. A new key could pay twice; with the same key,
        # imbi-api returns the outcome of the first call. Only a known
        # failure gets a new key. Timeout 1s: the call of attempt 1 runs
        # until attempt 2 starts, then fails with a known error.
        attempts: list[int] = []
        llm_call = executors.Executors._llm_call

        async def tracked(
            self_: executors.Executors, call: executors.Call
        ) -> executors.Outcome:
            attempts.append(call.attempt)
            return await llm_call(self_, call)

        def run(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            key = self._keys()[-1]
            if key.startswith('then:') or key == 'sum:3':
                return self._answer()
            if 2 not in attempts:
                return self._error(409, 'call_in_progress', True)
            return self._error(503, 'rate_limited', True)

        self.api.llm_call = run
        with mock.patch.object(executors.Executors, '_llm_call', tracked):
            run_ = await self._drive_llm_call(timeout_seconds=1)
        self.assertEqual(run_['status'], 'succeeded', run_['error'])
        self.assertEqual(run_['steps']['sum']['attempt'], 3)
        sum_keys = [k for k in self._keys() if k.startswith('sum:')]
        self.assertEqual(sorted(set(sum_keys)), ['sum:1', 'sum:3'])

    async def test_provider_outcome_unknown_fails(self) -> None:
        self.answers = [self._error(502, 'provider_outcome_unknown', False)]
        run = await self._drive_llm_call()
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['error'], 'provider_outcome_unknown')
        self.assertEqual(len(self.calls), 1)

    async def test_error_without_retry_fails(self) -> None:
        self.answers = [self._error(422, 'model_no_structured_output', False)]
        run = await self._drive_llm_call()
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['error'], 'model_no_structured_output')
        self.assertEqual(len(self.calls), 1)

    async def test_version_mismatch_fails(self) -> None:
        self.answers = [self._answer(n=2)]
        run = await self._drive_llm_call()
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['error'], 'prompt_version_mismatch')
        self.assertEqual(len(self.calls), 1)


class AppTestCase(unittest.IsolatedAsyncioTestCase):
    def test_sentry_is_initialised_first(self) -> None:
        with mock.patch.object(app.lifespan, 'Lifespan') as composed:
            app.create_app()
        self.assertIs(sentry.sentry_lifespan, composed.call_args.args[0])

    async def test_status(self) -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app.create_app()),
            base_url='http://test',
        ) as client:
            response = await client.get('/status')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['service'], 'imbi-workflows')

    async def test_engine_lifespan_starts_and_stops(self) -> None:
        real_store = store.Store
        with (
            mock.patch.dict(
                'os.environ', {'IMBI_WORKFLOWS_POLL_INTERVAL': '0.1'}
            ),
            # An organization with no runs: this engine must not take
            # runs from other tests that share the database.
            mock.patch.object(
                store,
                'Store',
                lambda pool, worker_id: real_store(
                    pool, worker_id, f'none-{uuid.uuid4().hex}'
                ),
            ),
        ):
            async with app.engine_lifespan() as runner:
                await asyncio.sleep(0.3)
                self.assertIsInstance(runner, engine.Engine)


class ApiErrorTestCase(unittest.IsolatedAsyncioTestCase):
    async def _error(self, response: httpx.Response) -> executors.StepError:
        def answer(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith('/auth/token'):
                return httpx.Response(
                    200, json={'access_token': 'token', 'expires_in': 900}
                )
            return response

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(answer)
        ) as client:
            api = executors.Api(
                client,
                settings.Workflows(
                    sa_client_id='client',
                    sa_client_secret='secret',
                    api_url='http://api',
                ),
            )
            with self.assertRaises(executors.StepError) as raised:
                await api.request('POST', '/deployments')
        return raised.exception

    async def test_text_detail(self) -> None:
        error = await self._error(
            httpx.Response(409, json={'detail': 'Release 1.4.0 is blocked'})
        )
        self.assertEqual(error.code, 'http_409')
        self.assertFalse(error.retry)
        self.assertEqual(error.detail, 'Release 1.4.0 is blocked')

    async def test_forbidden_keeps_its_detail(self) -> None:
        detail = {'error': 'autonomous_not_allowed', 'message': 'No.'}
        error = await self._error(httpx.Response(403, json={'detail': detail}))
        self.assertEqual(error.code, 'forbidden')
        self.assertFalse(error.retry)
        self.assertEqual(error.detail, detail)

    async def test_error_code_keeps_its_detail(self) -> None:
        detail = {'error': 'slack_unreachable', 'retry': True}
        error = await self._error(httpx.Response(502, json={'detail': detail}))
        self.assertEqual(error.code, 'slack_unreachable')
        self.assertTrue(error.retry)
        self.assertEqual(error.detail, detail)

    async def test_no_body(self) -> None:
        error = await self._error(httpx.Response(502, text='<html>'))
        self.assertEqual(error.code, 'http_502')
        self.assertTrue(error.retry)
        self.assertIsNone(error.detail)


class RenderTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_agent_results(self) -> None:
        fields = [
            {'name': 'subjects', 'type': 'array', 'items': 'string'},
            {
                'name': 'sender',
                'type': 'object',
                'fields': [{'name': 'email', 'type': 'string'}],
            },
        ]
        nodes = {
            node_id: wf.Node.model_validate(
                _node(
                    node_id,
                    'agent',
                    {
                        'agent_id': 'a1',
                        'instruction': 'Triage.',
                        'output_fields': fields,
                    },
                )
            )
            for node_id in ('a', 'b')
        }
        steps = {
            'a': {
                'node_key': 'a',
                'node_type': 'agent',
                'status': 'succeeded',
                'output': {
                    'result': {
                        'subjects': ['Hi', 'Bye'],
                        'sender': {'email': 'a@example.com'},
                    }
                },
            },
            'b': {
                'node_key': 'b',
                'node_type': 'agent',
                'status': 'skipped',
                'output': None,
            },
        }
        with mock.patch.dict(
            'os.environ', {'IMBI_PROMPT_RENDER_INPROCESS': 'true'}
        ):
            rendered = await engine._render(
                {
                    'whole': '{{ a.result.subjects }}',
                    'loop': '{% for s in a.result.subjects %}{{ s }};'
                    '{% endfor %}',
                    'nested': '{{ a.result.sender.email }}',
                    'skipped': '[{{ b.result.sender.email }}]',
                },
                steps,
                {},
                nodes,
            )
        self.assertEqual(
            rendered,
            {
                'whole': ['Hi', 'Bye'],
                'loop': 'Hi;Bye;',
                'nested': 'a@example.com',
                'skipped': '[]',
            },
        )

    async def test_escape_applies_to_values_only(self) -> None:
        """A value cannot add Slack markup; the template's own can."""
        with mock.patch.dict(
            'os.environ', {'IMBI_PROMPT_RENDER_INPROCESS': 'true'}
        ):
            steps, payload = engine._escaped_inputs(
                {
                    'a': {
                        'node_key': 'a',
                        'node_type': 'agent',
                        'status': 'succeeded',
                        'output': {'summary': '<https://x|ok>'},
                    }
                },
                {
                    'title': '<!channel> a & b',
                    'pr': {'labels': ['<x>']},
                    'tags': {'<!channel>': 'v'},
                },
                engine.slack_step.escape,
            )
            rendered = await engine._render(
                {
                    'text': '<!here> {{ trigger.title }}',
                    'whole': '{{ trigger.title }}',
                    'nested': '{{ trigger.pr.labels[0] }}',
                    'step': '{{ a.summary }}',
                    'keys': '{% for k in trigger.tags %}{{ k }}{% endfor %}',
                },
                steps,
                payload,
                {},
            )
        self.assertEqual(
            rendered,
            {
                'text': '<!here> &lt;!channel&gt; a &amp; b',
                'whole': '&lt;!channel&gt; a &amp; b',
                'nested': '&lt;x&gt;',
                'step': '&lt;https://x|ok&gt;',
                'keys': '&lt;!channel&gt;',
            },
        )

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
                {},
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
