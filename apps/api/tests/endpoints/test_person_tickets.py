"""Tests for person tickets (ADR 0028, plan P1)."""

import typing
import uuid
from unittest import mock

import httpx
import psycopg.errors

from apps.api.tests.endpoints import test_agent_tasks
from imbi.api import tickets

#: The agent columns of a valid agent row.
_AGENT: dict[str, typing.Any] = {
    'assignee_kind': 'agent',
    'assignee': None,
    'agent_id': 'agent-1',
    'agent_version': 1,
    'service_account_id': 'sa-1',
    'status': 'queued',
}

#: The columns of a valid person row.
_PERSON: dict[str, typing.Any] = {
    'assignee_kind': 'person',
    'assignee': 'p@example.com',
    'agent_id': None,
    'agent_version': None,
    'service_account_id': None,
    'status': 'open',
}

#: Each invalid combination, and the check that refuses it.
_INVALID: list[tuple[str, dict[str, typing.Any], str]] = [
    (
        'unknown kind',
        {**_AGENT, 'assignee_kind': 'team'},
        'tickets_assignee_kind_check',
    ),
    ('agent without agent_id', {**_AGENT, 'agent_id': None}, 'agent'),
    (
        'agent without agent_version',
        {**_AGENT, 'agent_version': None},
        'agent',
    ),
    (
        'agent without service account',
        {**_AGENT, 'service_account_id': None},
        'agent',
    ),
    ('agent with assignee', {**_AGENT, 'assignee': 'p@x.com'}, 'agent'),
    ('agent open', {**_AGENT, 'status': 'open'}, 'agent'),
    ('agent in_progress', {**_AGENT, 'status': 'in_progress'}, 'agent'),
    ('person without assignee', {**_PERSON, 'assignee': None}, 'person'),
    ('person with empty assignee', {**_PERSON, 'assignee': ''}, 'person'),
    ('person with agent_id', {**_PERSON, 'agent_id': 'agent-1'}, 'person'),
    ('person with agent_version', {**_PERSON, 'agent_version': 1}, 'person'),
    (
        'person with service account',
        {**_PERSON, 'service_account_id': 'sa-1'},
        'person',
    ),
    ('person queued', {**_PERSON, 'status': 'queued'}, 'person'),
    ('person running', {**_PERSON, 'status': 'running'}, 'person'),
    ('person paused', {**_PERSON, 'status': 'paused'}, 'person'),
]


class PersonTicketTestCase(test_agent_tasks.AgentTaskTestCase):
    async def create_person(self, **body: typing.Any) -> httpx.Response:
        payload: dict[str, typing.Any] = {
            'assignee_kind': 'person',
            'assignee': self.member,
            'title': 'Rotate the key',
            'description': 'Rotate the deploy key.',
        }
        payload.update(body)
        return await self.client.post(self.url(), json=payload)

    async def set_status(
        self, short_id: str, status: str, **body: typing.Any
    ) -> httpx.Response:
        return await self.client.post(
            self.url(f'{short_id}/status'), json={'status': status, **body}
        )

    async def status_of(self, short_id: str) -> str:
        task = await self.store.get(self.org, short_id)
        assert task is not None
        return str(task['status'])


class CheckTests(PersonTicketTestCase):
    """The checks on ``tickets.tickets``."""

    async def insert(self, columns: dict[str, typing.Any]) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO tickets.tickets (id, organization_id, short_id,'
                ' title, description, origin_kind, origin_id, origin, owner,'
                ' assignee_kind, assignee, agent_id, agent_version,'
                ' service_account_id, status) VALUES (%s, %s, %s,'
                " 't', 'd', 'human', 'u', '{}', 'o@example.com',"
                ' %s, %s, %s, %s, %s, %s)',
                (
                    uuid.uuid4(),
                    self.org,
                    f'T-{uuid.uuid4().hex[:8]}',
                    columns['assignee_kind'],
                    columns['assignee'],
                    columns['agent_id'],
                    columns['agent_version'],
                    columns['service_account_id'],
                    columns['status'],
                ),
            )

    async def test_valid_rows(self) -> None:
        await self.insert(_AGENT)
        await self.insert(_PERSON)
        for status in ('held', 'in_progress', 'blocked', 'closed'):
            await self.insert({**_PERSON, 'status': status})

    async def test_each_invalid_combination_is_refused(self) -> None:
        for name, columns, check in _INVALID:
            with self.subTest(name):
                with self.assertRaises(psycopg.errors.CheckViolation) as ctx:
                    await self.insert(columns)
                if check in ('agent', 'person'):
                    check = f'tickets_{check}_assignee_check'
                self.assertEqual(ctx.exception.diag.constraint_name, check)


class CreateTests(PersonTicketTestCase):
    async def test_create_person_ticket(self) -> None:
        response = await self.create_person(project_ids=[self.project_id])
        self.assertEqual(response.status_code, 201, response.text)
        task = response.json()
        self.assertEqual(task['assignee_kind'], 'person')
        self.assertEqual(task['assignee'], self.member)
        self.assertEqual(task['status'], 'open')
        self.assertIsNone(task['agent_id'])
        self.assertIsNone(task['agent_version'])
        self.assertIsNone(task['service_account_id'])
        self.assertEqual(task['owner'], self.email)
        events = (await self.client.get(self.url('T-1/events'))).json()
        self.assertEqual(events[0]['payload']['assignee'], self.member)
        listed = (await self.client.get(self.url())).json()
        self.assertEqual([t['short_id'] for t in listed], ['T-1'])

    async def test_invalid_bodies(self) -> None:
        await self.make_agent()
        bodies: list[dict[str, typing.Any]] = [
            {'agent_slug': 'triage'},
            {'assignee': None},
            {'budget': '1.00'},
            {'assignee': f'nobody-{self.org}@example.com'},
            {'requires': [{'short_id': 'T-99'}]},
            {'requires': [{'short_id': 'T-9'}, {'short_id': 't-9'}]},
        ]
        for body in bodies:
            with self.subTest(body):
                response = await self.create_person(**body)
                self.assertEqual(response.status_code, 422, response.text)
        response = await self.create_task(agent_slug=None)
        self.assertEqual(response.status_code, 422, response.text)
        response = await self.create_task(assignee=self.member)
        self.assertEqual(response.status_code, 422, response.text)

    async def test_requires_gates_a_new_ticket(self) -> None:
        await self.make_agent()
        prerequisite = (await self.create_task()).json()
        response = await self.create_person(
            requires=[{'short_id': 't-1', 'gates': True}]
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['status'], 'held')
        # A plain link does not hold, for either kind.
        response = await self.create_person(requires=[{'short_id': 'T-1'}])
        self.assertEqual(response.json()['status'], 'open')
        response = await self.create_task(
            requires=[{'short_id': 'T-1', 'gates': True}]
        )
        self.assertEqual(response.json()['status'], 'held')
        relations = (await self.client.get(self.url('T-2/relations'))).json()
        self.assertEqual(relations['requires'][0]['short_id'], 'T-1')
        self.assertTrue(relations['requires'][0]['gates'])
        self.assertEqual(
            await self.event_types('T-1'),
            ['ticket.created', *['dependency.added'] * 3],
        )
        # A done close releases both kinds.
        await self.store.set_outcome(
            self.org,
            prerequisite['short_id'],
            'done_acted',
            None,
            tickets.Actor('agent', 'triage', 'harness'),
        )
        self.assertEqual(await self.status_of('T-2'), 'open')
        self.assertEqual(await self.status_of('T-4'), 'queued')

    async def test_closed_done_prerequisite_does_not_hold(self) -> None:
        await self.create_person()
        await self.set_status('T-1', 'closed', outcome='done_acted')
        response = await self.create_person(
            requires=[{'short_id': 'T-1', 'gates': True}]
        )
        self.assertEqual(response.json()['status'], 'open')


class TransitionTests(PersonTicketTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        response = await self.create_person(assignee=self.email)
        self.assertEqual(response.status_code, 201, response.text)

    async def test_person_lifecycle(self) -> None:
        steps = [
            ('in_progress', {}, 'started'),
            ('blocked', {'reason': 'Waiting on ops'}, 'blocked'),
            ('in_progress', {}, 'unblocked'),
            ('blocked', {'reason': 'Again'}, 'blocked'),
            ('open', {}, 'unblocked'),
        ]
        for status, body, reason in steps:
            response = await self.set_status('T-1', status, **body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['status'], status)
            event = (await self.client.get(self.url('T-1/events'))).json()[-1]
            self.assertEqual(event['payload']['reason'], reason)
            self.assertEqual(event['payload']['note'], body.get('reason'))
        response = await self.set_status(
            'T-1', 'closed', outcome='superseded', reason='Done elsewhere'
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['outcome'], 'superseded')
        self.assertEqual(response.json()['outcome_reason'], 'Done elsewhere')
        response = await self.set_status('T-1', 'open')
        self.assertEqual(response.status_code, 409, response.text)

    async def test_invalid_moves(self) -> None:
        await self.set_status('T-1', 'in_progress')
        response = await self.set_status('T-1', 'open')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'transition_invalid'
        )
        # The same status changes nothing.
        response = await self.set_status('T-1', 'in_progress')
        self.assertEqual(response.status_code, 200, response.text)
        bodies: list[dict[str, typing.Any]] = [
            {'status': 'blocked'},
            {'status': 'closed'},
            {'status': 'closed', 'outcome': 'failed'},
            {'status': 'open', 'outcome': 'done_acted'},
            {'status': 'queued'},
        ]
        for body in bodies:
            with self.subTest(body):
                response = await self.client.post(
                    self.url('T-1/status'), json=body
                )
                self.assertEqual(response.status_code, 422, response.text)

    async def test_held_opens_only_by_its_gates(self) -> None:
        await self.create_person()
        response = await self.client.put(
            self.url('T-1/requires/T-2'), json={'gates': True}
        )
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(await self.status_of('T-1'), 'held')
        response = await self.set_status('T-1', 'open')
        self.assertEqual(response.status_code, 409, response.text)
        # A held ticket can be cancelled.
        response = await self.set_status(
            'T-1', 'closed', outcome='cancelled_by_human'
        )
        self.assertEqual(response.status_code, 200, response.text)

    async def test_started_person_ticket_refuses_a_gate(self) -> None:
        await self.create_person()
        await self.set_status('T-1', 'in_progress')
        response = await self.client.put(
            self.url('T-1/requires/T-2'), json={'gates': True}
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'ticket_started')

    async def test_assignee_needs_no_manage(self) -> None:
        await self.create_person()
        self.permissions = {'ticket:read'}
        response = await self.set_status('T-1', 'in_progress')
        self.assertEqual(response.status_code, 200, response.text)
        # Another person needs ticket:manage.
        response = await self.set_status('T-2', 'in_progress')
        self.assertEqual(response.status_code, 403, response.text)
        self.permissions = {'ticket:manage'}
        response = await self.set_status('T-2', 'in_progress')
        self.assertEqual(response.status_code, 200, response.text)

    async def test_agent_controls_refuse_a_person_ticket(self) -> None:
        for action in ('pause', 'resume', 'cancel'):
            with self.subTest(action):
                response = await self.client.post(self.url(f'T-1/{action}'))
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(
                    response.json()['detail']['error'], 'person_ticket'
                )
        response = await self.client.post(
            self.url('T-1/reply'), json={'body': 'hi', 'hold': True}
        )
        self.assertEqual(response.status_code, 409, response.text)
        await self.set_status('T-1', 'closed', outcome='done_acted')
        response = await self.client.post(self.url('T-1/retry'), json={})
        self.assertEqual(response.status_code, 409, response.text)

    async def test_agent_ticket_refuses_person_status(self) -> None:
        await self.make_agent()
        await self.create_task()
        response = await self.set_status('T-2', 'in_progress')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'agent_ticket')

    async def test_sessions_and_usage_skip_person_tickets(self) -> None:
        actor = tickets.Actor('agent', 'triage', 'harness')
        with self.assertRaises(tickets.WrongAssigneeKind):
            await self.store.open_session(
                self.org,
                'T-1',
                key='k',
                harness_instance=None,
                max_concurrent=None,
                actor=actor,
            )
        with self.assertRaises(tickets.WrongAssigneeKind):
            await self.store.report_usage(
                self.org,
                'T-1',
                tickets.Usage('u', 'm', 1, 1, None, None, None),
                None,
                actor=actor,
                system=actor,
            )

    async def test_deadlock_runs_the_change_again(self) -> None:
        # A done close locks the held dependents after the ticket, so it
        # can deadlock with a dependency change.
        original = tickets.store._lock_task
        calls = 0

        async def deadlock_once(*args: typing.Any) -> typing.Any:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise psycopg.errors.DeadlockDetected('deadlock detected')
            return await original(*args)

        with mock.patch.object(tickets.store, '_lock_task', deadlock_once):
            response = await self.set_status('T-1', 'in_progress')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(calls, 2)
        self.assertEqual(await self.status_of('T-1'), 'in_progress')

    async def test_log_rows_have_empty_agent_columns(self) -> None:
        task = await self.store.get(self.org, 'T-1')
        assert task is not None
        (event,) = await self.store.events(task['id'], 0, 1)
        row = tickets.log.event_row(task, event)
        self.assertEqual((row['agent_id'], row['agent_version']), ('', 0))
