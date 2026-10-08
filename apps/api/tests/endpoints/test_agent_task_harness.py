"""Tests for the harness-facing agent task endpoints (ADR 0020).

These run against the live Postgres that ``root:services`` boots, like
:mod:`apps.api.tests.endpoints.test_agent_tasks`. The caller is the
service account of the agent, unless a test says otherwise.
"""

import datetime
import decimal
import typing
import uuid

import httpx

from apps.api.tests.endpoints import test_agent_tasks
from imbi.api import models
from imbi.api.auth import permissions
from imbi.api.endpoints import agent_task_harness
from imbi.api.graph_sql import props_template


def new_id() -> str:
    """Return a new event id."""
    return str(uuid.uuid4())


class HarnessTestCase(test_agent_tasks.AgentTaskTestCase):
    """Fixtures: an agent, its task ``T-1``, and its service account."""

    agent_settings: typing.ClassVar[dict[str, typing.Any]] = {
        'task_budget': '1'
    }

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.agent_id = await self.make_agent(settings=self.agent_settings)
        self.task = (await self.create_task()).json()
        self.user_auth = self.test_app.dependency_overrides[
            permissions.get_current_user
        ]
        (account,) = await self.service_accounts(self.agent_id)
        self.account = models.ServiceAccount(
            id=account['id'], slug=account['slug'], display_name='Triage Bot'
        )
        self.act_as(self.account)

    def act_as(self, account: models.ServiceAccount) -> None:
        """Authenticate as ``account``, with no permissions."""

        async def service_account() -> permissions.AuthContext:
            return permissions.AuthContext(
                service_account=account, auth_method='client_credentials'
            )

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            service_account
        )

    def act_as_user(self) -> None:
        self.test_app.dependency_overrides[permissions.get_current_user] = (
            self.user_auth
        )

    async def post(
        self, path: str, body: typing.Any = None, short_id: str = 'T-1'
    ) -> httpx.Response:
        return await self.client.post(
            self.url(f'{short_id}/{path}'), json=body
        )

    async def open_session(
        self, key: str = 's-1', short_id: str = 'T-1'
    ) -> dict[str, typing.Any]:
        response = await self.post(
            'sessions',
            {'session_key': key, 'harness_instance': 'h-1'},
            short_id,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def as_user(
        self, method: str, path: str, **kwargs: typing.Any
    ) -> httpx.Response:
        """Make one request as the person who owns the task."""
        self.act_as_user()
        try:
            return await self.client.request(method, self.url(path), **kwargs)
        finally:
            self.act_as(self.account)

    async def events(
        self, short_id: str = 'T-1'
    ) -> list[dict[str, typing.Any]]:
        response = await self.as_user('GET', f'{short_id}/events')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def task_row(self, short_id: str = 'T-1') -> dict[str, typing.Any]:
        task = await self.store.get(self.org, short_id)
        assert task is not None
        return task

    async def make_model(
        self, slug: str, model_id: str, **prices: typing.Any
    ) -> None:
        props: dict[str, typing.Any] = {
            'id': slug,
            'slug': slug,
            'name': slug,
            'model_id': model_id,
            'input_cost_per_million': '3',
            'output_cost_per_million': '15',
            'cache_read_cost_per_million': '0.3',
            'cache_write_cost_per_million': '3.75',
        }
        props.update(prices)
        await self.graph.execute(
            f'CREATE (m:AIModel {props_template(props)}) RETURN m.id AS id',
            props,
            ['id'],
        )
        self.addAsyncCleanup(
            self.graph.execute,
            'MATCH (m:AIModel {{id: {id}}}) DETACH DELETE m RETURN 1 AS ok',
            {'id': slug},
            ['ok'],
        )


class AccessTests(HarnessTestCase):
    async def routes(self) -> list[tuple[str, typing.Any]]:
        session_id = str(uuid.uuid4())
        return [
            ('sessions', {'session_key': 'k'}),
            (f'sessions/{session_id}/heartbeat', None),
            (f'sessions/{session_id}/close', {'reason': 'done'}),
            ('events', {'events': [{'event_id': new_id(), 'type': 'turn'}]}),
            ('usage', {'idempotency_key': 'u', 'model_id': 'm'}),
            ('requests', {'kind': 'feedback', 'title': 'Which one?'}),
            ('outcome', {'outcome': 'done_acted'}),
        ]

    async def test_people_are_refused(self) -> None:
        self.act_as_user()
        for path, body in await self.routes():
            with self.subTest(path=path):
                response = await self.post(path, body)
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(
                    response.json()['detail']['error'], 'agent_task_forbidden'
                )

    async def test_other_agent_is_refused(self) -> None:
        other_id = await self.make_agent('other', name='Other Bot')
        self.act_as_user()
        response = await self.create_task(agent_slug='other')
        self.assertEqual(response.status_code, 201, response.text)
        (account,) = await self.service_accounts(other_id)
        self.act_as(
            models.ServiceAccount(
                id=account['id'], slug=account['slug'], display_name='Other'
            )
        )
        for path, body in await self.routes():
            with self.subTest(path=path):
                response = await self.post(path, body)
                self.assertEqual(response.status_code, 403, response.text)
        # It can work its own task.
        response = await self.post('sessions', {'session_key': 'k'}, 'T-2')
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual((await self.task_row())['last_seq'], 1)

    async def test_service_account_needs_membership(self) -> None:
        await self.graph.execute(
            'MATCH (s:ServiceAccount {{id: {id}}})-[m:MEMBER_OF]->()'
            ' DELETE m RETURN 1 AS ok',
            {'id': self.account.id},
            ['ok'],
        )
        response = await self.post('sessions', {'session_key': 'k'})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'organization_forbidden'
        )

    async def test_own_service_account_reads_its_task(self) -> None:
        response = await self.client.get(self.url('T-1'))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['id'], self.task['id'])
        response = await self.client.get(self.url('T-1/events'))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [e['type'] for e in response.json()], ['task.created']
        )
        # It still cannot list the tasks of the organization.
        response = await self.client.get(self.url())
        self.assertEqual(response.status_code, 403, response.text)

    async def test_others_need_the_read_permission(self) -> None:
        other_id = await self.make_agent('other', name='Other Bot')
        self.act_as_user()
        await self.create_task(agent_slug='other')
        (account,) = await self.service_accounts(other_id)
        self.act_as(
            models.ServiceAccount(
                id=account['id'], slug=account['slug'], display_name='Other'
            )
        )
        for path in ('T-1', 'T-1/events'):
            with self.subTest(path=path):
                response = await self.client.get(self.url(path))
                self.assertEqual(response.status_code, 403, response.text)
        self.act_as_user()
        self.permissions = set(test_agent_tasks.ALL_PERMISSIONS) - {
            'agent_task:read'
        }
        for path in ('T-1', 'T-1/events'):
            with self.subTest(path=path):
                response = await self.client.get(self.url(path))
                self.assertEqual(response.status_code, 403, response.text)
                self.assertIn('agent_task:read', response.text)

    async def test_unknown_task_is_404(self) -> None:
        response = await self.post('sessions', {'session_key': 'k'}, 'T-9')
        self.assertEqual(response.status_code, 404, response.text)


class SessionTests(HarnessTestCase):
    async def test_open_is_idempotent_and_starts_the_task(self) -> None:
        first = await self.open_session()
        self.assertEqual(first['session']['session_key'], 's-1')
        self.assertEqual(first['session']['harness_instance'], 'h-1')
        self.assertEqual(first['task']['status'], 'running')
        self.assertEqual(first['task']['last_seq'], 3)
        repeat = await self.post('sessions', {'session_key': 's-1'})
        self.assertEqual(repeat.status_code, 200, repeat.text)
        self.assertEqual(repeat.json()['session'], first['session'])
        second = await self.open_session('s-2')
        self.assertNotEqual(second['session']['id'], first['session']['id'])
        events = await self.events()
        self.assertEqual(
            [e['type'] for e in events],
            [
                'task.created',
                'session.opened',
                'state.changed',
                'session.opened',
            ],
        )
        opened = events[1]
        self.assertEqual(opened['actor_kind'], 'agent')
        self.assertEqual(opened['actor_id'], self.agent_id)
        self.assertEqual(opened['channel'], 'harness')
        self.assertEqual(opened['session_id'], first['session']['id'])
        self.assertEqual(
            events[2]['payload'],
            {'from': 'queued', 'to': 'running', 'reason': 'session_opened'},
        )

    async def test_open_refuses_closed_and_cancelled_tasks(self) -> None:
        await self.open_session()
        response = await self.as_user('POST', 'T-1/cancel')
        self.assertEqual(response.json()['control'], 'cancel')
        response = await self.post('sessions', {'session_key': 's-2'})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'task_cancelled')
        await self.post('outcome', {'outcome': 'done_acted'})
        response = await self.post('sessions', {'session_key': 's-1'})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'task_closed')

    async def test_heartbeat_returns_control_seq_and_budget(self) -> None:
        session = (await self.open_session())['session']
        path = f'sessions/{session["id"]}/heartbeat'
        response = await self.post(path)
        self.assertEqual(response.status_code, 200, response.text)
        state = response.json()
        self.assertEqual(state['control'], 'run')
        self.assertEqual(state['status'], 'running')
        self.assertEqual(state['last_seq'], 3)
        self.assertEqual(float(state['budget_remaining']), 1)
        await self.as_user('POST', 'T-1/pause')
        state = (await self.post(path)).json()
        self.assertEqual(state['control'], 'pause')
        self.assertEqual(state['last_seq'], 4)
        sessions = await self.sessions()
        self.assertIsNotNone(sessions[0]['heartbeat_at'])

    async def test_resume_runs_a_paused_task_with_a_session(self) -> None:
        await self.as_user('POST', 'T-1/pause')
        self.assertEqual((await self.task_row())['status'], 'paused')
        await self.open_session()
        self.assertEqual((await self.task_row())['status'], 'paused')
        response = await self.as_user('POST', 'T-1/resume')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'running')
        changed = [
            e for e in await self.events() if e['type'] == 'state.changed'
        ]
        self.assertEqual(
            changed[-1]['payload'],
            {'from': 'paused', 'to': 'running', 'reason': 'control_changed'},
        )

    async def test_heartbeat_needs_an_open_session(self) -> None:
        session = (await self.open_session())['session']
        response = await self.post(f'sessions/{uuid.uuid4()}/heartbeat')
        self.assertEqual(response.status_code, 404, response.text)
        await self.post(f'sessions/{session["id"]}/close', {'reason': 'x'})
        response = await self.post(f'sessions/{session["id"]}/heartbeat')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'session_closed')

    async def test_close_follows_the_control_value(self) -> None:
        cases = [
            (None, 'queued', None),
            ('pause', 'paused', None),
            ('cancel', 'closed', 'cancelled_by_human'),
        ]
        for index, (action, status, outcome) in enumerate(cases, start=1):
            with self.subTest(action=action):
                short_id = f'T-{index}'
                if index > 1:
                    self.act_as_user()
                    await self.create_task()
                    self.act_as(self.account)
                session = (await self.open_session(short_id=short_id))[
                    'session'
                ]
                if action:
                    await self.as_user('POST', f'{short_id}/{action}')
                path = f'sessions/{session["id"]}/close'
                response = await self.post(path, {'reason': 'done'}, short_id)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['status'], status)
                self.assertEqual(response.json()['outcome'], outcome)
                closed = [
                    e
                    for e in await self.events(short_id)
                    if e['type'] == 'session.closed'
                ]
                self.assertEqual(len(closed), 1)
                self.assertEqual(closed[0]['payload']['reason'], 'done')
        # Closing a closed session changes nothing.
        last_seq = (await self.task_row())['last_seq']
        sessions = await self.sessions()
        response = await self.post(
            f'sessions/{sessions[0]["id"]}/close', {'reason': 'again'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['last_seq'], last_seq)

    async def sessions(
        self, short_id: str = 'T-1'
    ) -> list[dict[str, typing.Any]]:
        task = await self.task_row(short_id)
        async with self.pool.connection() as conn:
            cursor = await conn.execute(
                'SELECT id, heartbeat_at FROM agent_runtime.sessions'
                ' WHERE task_id = %s ORDER BY opened_at',
                (task['id'],),
            )
            return [
                {'id': str(row[0]), 'heartbeat_at': row[1]}
                for row in await cursor.fetchall()
            ]


class TimeoutTests(HarnessTestCase):
    agent_settings: typing.ClassVar[dict[str, typing.Any]] = {
        'task_timeout_seconds': 60
    }

    async def test_heartbeat_closes_a_task_past_its_timeout(self) -> None:
        session = (await self.open_session())['session']
        path = f'sessions/{session["id"]}/heartbeat'
        self.assertEqual((await self.post(path)).json()['status'], 'running')
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE agent_runtime.sessions'
                " SET opened_at = NOW() - INTERVAL '2 minutes'"
                ' WHERE id = %s',
                (uuid.UUID(session['id']),),
            )
        response = await self.post(path)
        self.assertEqual(response.status_code, 200, response.text)
        state = response.json()
        self.assertEqual(state['status'], 'closed')
        self.assertEqual(state['outcome'], 'exceeded_ceiling')
        self.assertEqual(state['outcome_reason'], 'task_timeout')
        events = await self.events()
        self.assertEqual(
            [e['type'] for e in events[-3:]],
            ['session.closed', 'state.changed', 'outcome.set'],
        )
        self.assertEqual(events[-1]['actor_kind'], 'system')
        response = await self.post(path)
        self.assertEqual(response.status_code, 409, response.text)


class ConcurrencyTests(HarnessTestCase):
    agent_settings: typing.ClassVar[dict[str, typing.Any]] = {
        'max_concurrent_tasks': 1
    }

    async def test_open_sessions_are_capped_per_agent(self) -> None:
        self.act_as_user()
        await self.create_task()
        self.act_as(self.account)
        session = (await self.open_session())['session']
        response = await self.post('sessions', {'session_key': 'b'}, 'T-2')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'concurrency_limit'
        )
        # A repeat of an open session is not a new session.
        response = await self.post('sessions', {'session_key': 's-1'})
        self.assertEqual(response.status_code, 200, response.text)
        # A new session on a running task is not a new concurrent task.
        response = await self.post('sessions', {'session_key': 's-2'})
        self.assertEqual(response.status_code, 201, response.text)
        await self.post(
            f'sessions/{response.json()["session"]["id"]}/close',
            {'reason': 'x'},
        )
        await self.post(f'sessions/{session["id"]}/close', {'reason': 'x'})
        response = await self.post('sessions', {'session_key': 'b'}, 'T-2')
        self.assertEqual(response.status_code, 201, response.text)


class EventTests(HarnessTestCase):
    async def test_harness_events_are_written_in_order(self) -> None:
        session = (await self.open_session())['session']
        at = '2026-10-07T12:00:00.123456+00:00'
        response = await self.post(
            'events',
            {
                'session_id': session['id'],
                'events': [
                    {
                        'event_id': new_id(),
                        'type': 'turn',
                        'payload': {'body': 'Looking.'},
                    },
                    {
                        'event_id': new_id(),
                        'type': 'tool.called',
                        'actor_kind': 'subagent',
                        'actor_id': 'helper',
                        'at': at,
                        'payload': {
                            'tool': 'github.search',
                            'mutating': False,
                        },
                    },
                    {
                        'event_id': new_id(),
                        'type': 'phase.changed',
                        'payload': {'phase': 'triage'},
                    },
                    {
                        'event_id': new_id(),
                        'type': 'todos.updated',
                        'payload': {'todos': []},
                    },
                    {
                        'event_id': new_id(),
                        'type': 'check.reported',
                        'schema_version': 2,
                        'payload': {'name': 'tests', 'verdict': 'pass'},
                    },
                ],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        written = response.json()['written']
        self.assertEqual(response.json()['duplicates'], [])
        self.assertEqual([e['seq'] for e in written], [4, 5, 6, 7, 8])
        self.assertEqual(written, (await self.events())[3:])
        self.assertTrue(all(e['session_id'] == session['id'] for e in written))
        self.assertEqual(written[0]['actor_id'], self.agent_id)
        self.assertEqual(written[1]['actor_kind'], 'subagent')
        self.assertEqual(written[1]['actor_id'], 'helper')
        self.assertEqual(
            datetime.datetime.fromisoformat(written[1]['at']),
            datetime.datetime.fromisoformat(at),
        )
        self.assertEqual(written[4]['schema_version'], 2)
        self.assertEqual((await self.task_row())['phase'], 'triage')

    async def test_a_batch_sent_again_writes_nothing(self) -> None:
        batch = {
            'events': [
                {'event_id': new_id(), 'type': 'turn'},
                {
                    'event_id': new_id(),
                    'type': 'phase.changed',
                    'payload': {'phase': 'one'},
                },
            ]
        }
        response = await self.post('events', batch)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(
            [e['seq'] for e in response.json()['written']], [2, 3]
        )
        response = await self.post('events', batch)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['written'], [])
        self.assertEqual(
            response.json()['duplicates'],
            [e['event_id'] for e in batch['events']],
        )
        self.assertEqual((await self.task_row())['last_seq'], 3)

        # New and duplicate ids mixed: only the new ones, in order, with
        # no gap in seq. A repeat inside one batch is a duplicate too.
        first, second = new_id(), new_id()
        response = await self.post(
            'events',
            {
                'events': [
                    {'event_id': first, 'type': 'turn', 'payload': {'n': 1}},
                    batch['events'][0],
                    {
                        'event_id': second,
                        'type': 'phase.changed',
                        'payload': {'phase': 'two'},
                    },
                    {'event_id': first, 'type': 'turn', 'payload': {'n': 2}},
                ]
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(
            [(e['seq'], e['event_id']) for e in body['written']],
            [(4, first), (5, second)],
        )
        self.assertEqual(body['written'][0]['payload'], {'n': 1})
        self.assertEqual(
            body['duplicates'], [batch['events'][0]['event_id'], first]
        )
        task = await self.task_row()
        self.assertEqual(task['last_seq'], 5)
        self.assertEqual(task['phase'], 'two')
        self.assertEqual(
            [e['seq'] for e in await self.events()], [1, 2, 3, 4, 5]
        )

    async def test_event_id_of_another_task_is_a_conflict(self) -> None:
        self.act_as_user()
        await self.create_task()
        self.act_as(self.account)
        event_id = new_id()
        body = {'events': [{'event_id': event_id, 'type': 'turn'}]}
        response = await self.post('events', body, 'T-2')
        self.assertEqual(response.status_code, 201, response.text)
        response = await self.post('events', body)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'event_id_conflict'
        )
        self.assertEqual((await self.task_row())['last_seq'], 1)

    async def test_imbi_event_types_are_refused(self) -> None:
        for event_type in (
            'task.created',
            'state.changed',
            'control.changed',
            'owner.changed',
            'session.opened',
            'session.closed',
            'usage.reported',
            'request.opened',
            'request.resolved',
            'request.expired',
            'outcome.set',
            'something.else',
        ):
            with self.subTest(event_type=event_type):
                response = await self.post(
                    'events',
                    {'events': [{'event_id': new_id(), 'type': event_type}]},
                )
                self.assertEqual(response.status_code, 422, response.text)
        for body in (
            {'events': []},
            {'events': [{'type': 'turn'}]},
            {
                'events': [
                    {
                        'event_id': new_id(),
                        'type': 'phase.changed',
                        'payload': {},
                    }
                ]
            },
            {
                'events': [
                    {
                        'event_id': new_id(),
                        'type': 'turn',
                        'actor_kind': 'human',
                    }
                ]
            },
            {
                'events': [
                    {
                        'event_id': new_id(),
                        'type': 'turn',
                        'at': '2026-10-07T12:00:00',
                    }
                ]
            },
        ):
            with self.subTest(body=body):
                response = await self.post('events', body)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual((await self.task_row())['last_seq'], 1)

    async def test_payload_size_is_capped(self) -> None:
        big = 'x' * agent_task_harness.MAX_PAYLOAD_BYTES
        response = await self.post(
            'events',
            {
                'events': [
                    {
                        'event_id': new_id(),
                        'type': 'turn',
                        'payload': {'body': 'fits'},
                    },
                    {
                        'event_id': new_id(),
                        'type': 'turn',
                        'payload': {'body': big},
                    },
                ]
            },
        )
        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'payload_too_large'
        )
        self.assertEqual((await self.task_row())['last_seq'], 1)

    async def test_session_must_be_open(self) -> None:
        session = (await self.open_session())['session']
        await self.post(f'sessions/{session["id"]}/close', {'reason': 'x'})
        response = await self.post(
            'events',
            {
                'session_id': session['id'],
                'events': [{'event_id': new_id(), 'type': 'turn'}],
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        response = await self.post(
            'events',
            {
                'session_id': str(uuid.uuid4()),
                'events': [{'event_id': new_id(), 'type': 'turn'}],
            },
        )
        self.assertEqual(response.status_code, 404, response.text)


class RequestTests(HarnessTestCase):
    async def test_request_blocks_the_task(self) -> None:
        session = (await self.open_session())['session']
        expires = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            hours=1
        )
        response = await self.post(
            'requests',
            {
                'kind': 'approval',
                'title': 'Merge the fix?',
                'why': 'The build is red.',
                'options': ['merge', 'wait'],
                'artifacts': [{'name': 'diff', 'digest': 'sha256:ab'}],
                'artifact_digests': ['sha256:ab'],
                'expires_at': expires.isoformat(),
                'session_id': session['id'],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body['task']['status'], 'blocked')
        self.assertEqual(body['request']['status'], 'open')
        self.assertEqual(body['request']['artifact_digests'], ['sha256:ab'])
        events = await self.events()
        self.assertEqual(
            [e['type'] for e in events[-2:]],
            ['request.opened', 'state.changed'],
        )
        opened = events[-2]['payload']
        self.assertEqual(opened['request_id'], body['request']['id'])
        self.assertEqual(opened['kind'], 'approval')
        self.assertEqual(opened['options'], ['merge', 'wait'])
        # A new session does not unblock a task with an open request.
        response = await self.post('sessions', {'session_key': 's-2'})
        self.assertEqual(response.json()['task']['status'], 'blocked')

    async def test_resume_keeps_a_task_with_an_open_request_blocked(
        self,
    ) -> None:
        session = (await self.open_session())['session']
        response = await self.post(
            'requests',
            {
                'kind': 'feedback',
                'title': 'Which repo?',
                'session_id': session['id'],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        await self.post(f'sessions/{session["id"]}/close', {'reason': 'x'})
        response = await self.as_user('POST', 'T-1/pause')
        self.assertEqual(response.json()['status'], 'paused')
        response = await self.as_user('POST', 'T-1/resume')
        self.assertEqual(response.json()['status'], 'blocked')
        response = await self.post('sessions', {'session_key': 's-2'})
        self.assertEqual(response.json()['task']['status'], 'blocked')

    async def test_request_is_validated(self) -> None:
        past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            hours=1
        )
        for body in (
            {'kind': 'approval', 'title': 'No digests'},
            {
                'kind': 'feedback',
                'title': 'Late',
                'expires_at': past.isoformat(),
            },
            {'kind': 'other', 'title': 'Kind'},
            {'kind': 'feedback', 'title': ''},
        ):
            with self.subTest(body=body):
                response = await self.post('requests', body)
                self.assertEqual(response.status_code, 422, response.text)
        response = await self.post(
            'requests',
            {
                'kind': 'feedback',
                'title': 'Big',
                'options': ['x' * agent_task_harness.MAX_PAYLOAD_BYTES],
            },
        )
        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual((await self.task_row())['status'], 'queued')


class OutcomeTests(HarnessTestCase):
    async def test_outcome_closes_the_task_and_sessions(self) -> None:
        await self.open_session()
        await self.open_session('s-2')
        response = await self.post(
            'outcome', {'outcome': 'failed_external', 'reason': 'github_down'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        state = response.json()
        self.assertEqual(state['status'], 'closed')
        self.assertEqual(state['outcome'], 'failed_external')
        self.assertEqual(state['outcome_reason'], 'github_down')
        events = await self.events()
        self.assertEqual(
            [e['type'] for e in events[-4:]],
            [
                'session.closed',
                'session.closed',
                'state.changed',
                'outcome.set',
            ],
        )
        self.assertEqual(
            events[-1]['payload'],
            {'outcome': 'failed_external', 'reason': 'github_down'},
        )
        task = await self.task_row()
        self.assertIsNotNone(task['closed_at'])
        async with self.pool.connection() as conn:
            cursor = await conn.execute(
                'SELECT count(*) FROM agent_runtime.sessions'
                ' WHERE task_id = %s AND closed_at IS NULL',
                (task['id'],),
            )
            self.assertEqual(await cursor.fetchone(), (0,))

    async def test_outcome_is_validated(self) -> None:
        for body in (
            {'outcome': 'failed_external'},
            {'outcome': 'failed_external', 'reason': ''},
            {'outcome': 'failed_external', 'reason': 'Not A Slug'},
            {'outcome': 'done'},
        ):
            with self.subTest(body=body):
                response = await self.post('outcome', body)
                self.assertEqual(response.status_code, 422, response.text)
        response = await self.post('outcome', {'outcome': 'done_acted'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()['outcome_reason'])

    async def test_closed_task_refuses_everything(self) -> None:
        session = (await self.open_session())['session']
        await self.post('outcome', {'outcome': 'done_acted'})
        last_seq = (await self.task_row())['last_seq']
        for path, body in (
            ('sessions', {'session_key': 's-2'}),
            (f'sessions/{session["id"]}/heartbeat', None),
            (f'sessions/{session["id"]}/close', {'reason': 'x'}),
            ('events', {'events': [{'event_id': new_id(), 'type': 'turn'}]}),
            ('usage', {'idempotency_key': 'u', 'model_id': 'm'}),
            ('requests', {'kind': 'feedback', 'title': 'Hello?'}),
            ('outcome', {'outcome': 'done_acted'}),
        ):
            with self.subTest(path=path):
                response = await self.post(path, body)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(
                    response.json()['detail']['error'], 'task_closed'
                )
        self.assertEqual((await self.task_row())['last_seq'], last_seq)


class UsageTests(HarnessTestCase):
    agent_settings: typing.ClassVar[dict[str, typing.Any]] = {
        'task_budget': '0.03'
    }

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.slug = f'opus-{uuid.uuid4().hex[:8]}'
        self.model_id = f'claude-test-{uuid.uuid4().hex[:8]}'
        await self.make_model(self.slug, self.model_id)

    async def report(self, key: str, **body: typing.Any) -> httpx.Response:
        payload: dict[str, typing.Any] = {
            'idempotency_key': key,
            'model_id': self.slug,
            'tokens_in': 1000,
            'tokens_out': 500,
            'cache_read_tokens': 10000,
            'cache_write_tokens': 2000,
        }
        payload.update(body)
        return await self.post('usage', payload)

    async def ledger(self) -> list[dict[str, typing.Any]]:
        return await self.store.ledger((await self.task_row())['id'])

    async def test_usage_is_priced_from_the_catalog(self) -> None:
        session = (await self.open_session())['session']
        response = await self.report('u-1', session_id=session['id'])
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        # 1000 * 3 + 500 * 15 + 10000 * 0.3 + 2000 * 3.75, per million.
        self.assertEqual(
            decimal.Decimal(body['cost']), decimal.Decimal('0.021')
        )
        self.assertEqual(
            decimal.Decimal(body['cache_read_cost_per_million']),
            decimal.Decimal('0.3'),
        )
        self.assertEqual(
            decimal.Decimal(body['cache_write_cost_per_million']),
            decimal.Decimal('3.75'),
        )
        self.assertEqual(body['task']['status'], 'running')
        self.assertEqual(
            decimal.Decimal(body['task']['budget_remaining']),
            decimal.Decimal('0.009'),
        )
        task = await self.task_row()
        self.assertEqual(task['tokens_in'], 1000)
        self.assertEqual(task['tokens_out'], 500)
        self.assertEqual(task['cache_read_tokens'], 10000)
        self.assertEqual(task['cache_write_tokens'], 2000)
        self.assertEqual(task['cost_total'], decimal.Decimal('0.021'))
        (row,) = await self.ledger()
        self.assertEqual(row['input_cost_per_million'], 3)
        self.assertEqual(str(row['session_id']), session['id'])
        event = (await self.events())[-1]
        self.assertEqual(event['type'], 'usage.reported')
        self.assertEqual(event['payload']['report_id'], body['id'])
        self.assertEqual(event['payload']['cost'], '0.021000')
        self.assertEqual(event['payload']['budget_remaining'], '0.009000')
        # The provider model id finds the same catalog entry.
        response = await self.report(
            'u-2',
            model_id=self.model_id,
            tokens_in=1,
            tokens_out=None,
            cache_read_tokens=None,
            cache_write_tokens=None,
        )
        self.assertEqual(response.json()['input_cost_per_million'], '3.000000')

    async def test_repeat_key_returns_the_first_report(self) -> None:
        first = await self.report('u-1')
        last_seq = (await self.task_row())['last_seq']
        repeat = await self.report('u-1', tokens_in=999999)
        self.assertEqual(repeat.status_code, 200, repeat.text)
        self.assertEqual(repeat.json(), first.json())
        self.assertEqual(len(await self.ledger()), 1)
        task = await self.task_row()
        self.assertEqual(task['last_seq'], last_seq)
        self.assertEqual(task['tokens_in'], 1000)

    async def test_unmeasured_and_unknown_are_recorded(self) -> None:
        response = await self.post(
            'usage', {'idempotency_key': 'u-1', 'model_id': self.slug}
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertIsNone(body['tokens_in'])
        self.assertIsNone(body['cost'])
        self.assertEqual(body['input_cost_per_million'], '3.000000')
        response = await self.report('u-2', model_id='no-such-model')
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body['tokens_in'], 1000)
        self.assertIsNone(body['cost'])
        self.assertIsNone(body['input_cost_per_million'])
        self.assertIsNone(body['cache_write_cost_per_million'])
        rows = await self.ledger()
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0]['tokens_in'])
        task = await self.task_row()
        self.assertEqual(task['tokens_in'], 1000)
        self.assertEqual(task['cost_total'], 0)

    async def test_missing_cache_price_makes_the_cost_unknown(self) -> None:
        slug = f'nocache-{uuid.uuid4().hex[:8]}'
        await self.make_model(slug, slug, cache_read_cost_per_million=None)
        response = await self.report('u-1', model_id=slug)
        self.assertIsNone(response.json()['cost'])
        response = await self.report('u-2', model_id=slug, cache_read_tokens=0)
        self.assertEqual(
            decimal.Decimal(response.json()['cost']), decimal.Decimal('0.018')
        )

    async def test_budget_closes_the_task(self) -> None:
        await self.open_session()
        first = await self.report('u-1')
        self.assertEqual(first.json()['task']['status'], 'running')
        second = await self.report('u-2')
        self.assertEqual(second.status_code, 201, second.text)
        state = second.json()['task']
        self.assertEqual(state['status'], 'closed')
        self.assertEqual(state['outcome'], 'exceeded_ceiling')
        self.assertEqual(state['outcome_reason'], 'budget')
        self.assertEqual(
            decimal.Decimal(state['budget_remaining']),
            decimal.Decimal('-0.012'),
        )
        events = await self.events()
        self.assertEqual(
            [e['type'] for e in events[-4:]],
            [
                'usage.reported',
                'session.closed',
                'state.changed',
                'outcome.set',
            ],
        )
        # The repeat of the report that closed the task still answers.
        repeat = await self.report('u-2')
        self.assertEqual(repeat.status_code, 200, repeat.text)
        self.assertEqual(repeat.json()['id'], second.json()['id'])
        response = await self.report('u-3')
        self.assertEqual(response.status_code, 409, response.text)
