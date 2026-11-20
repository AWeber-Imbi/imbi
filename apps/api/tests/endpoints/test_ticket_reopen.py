"""Tests for the reopen of a closed ticket (ADR 0028, plan P3b)."""

import typing
import uuid

import httpx

from apps.api.tests.endpoints import (
    test_agent_task_log,
    test_harness,
    test_person_tickets,
)
from imbi.api import secret_broker, tickets
from imbi.api.tickets import store as task_store
from imbi.api.tickets import sweeper


class ReopenTestCase(test_person_tickets.PersonTicketTestCase):
    """The owner can make tickets (a role with ``ticket:create``), so an
    agent can work for them."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        role = f'reopen-{self.org}'
        await self.graph.execute(
            'MERGE (p:Permission {{name: "ticket:create"}})'
            ' CREATE (r:Role {{slug: {role}, name: {role}}})'
            ' CREATE (r)-[:GRANTS]->(p)'
            ' WITH r MATCH (:User {{email: {email}}})-[m:MEMBER_OF]->()'
            ' SET m.role = {role} RETURN 1 AS ok',
            {'role': role, 'email': self.email},
            ['ok'],
        )
        self.addAsyncCleanup(
            self.graph.execute,
            'MATCH (r:Role {{slug: {role}}}) DETACH DELETE r RETURN 1 AS ok',
            {'role': role},
            ['ok'],
        )

    async def reopen(
        self, short_id: str, **body: typing.Any
    ) -> httpx.Response:
        return await self.client.post(
            self.url(f'{short_id}/reopen'),
            json={'reason': 'Not fixed', **body},
        )

    async def clear_outbox(self, short_id: str) -> None:
        """Do what the ``ticket_closed`` trigger does after its runs."""
        for row in await self.store.pending_triggers():
            if (row['organization_id'], row['short_id']) == (
                self.org,
                short_id,
            ):
                await self.store.triggers_started(row['id'], row['close_id'])

    async def get_events(self, short_id: str) -> list[dict[str, typing.Any]]:
        response = await self.client.get(self.url(f'{short_id}/events'))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def closed_person_ticket(self) -> str:
        short_id = (await self.create_person()).json()['short_id']
        response = await self.set_status(
            short_id, 'closed', outcome='done_acted'
        )
        self.assertEqual(response.status_code, 200, response.text)
        await self.clear_outbox(short_id)
        return str(short_id)

    async def closed_agent_ticket(self) -> dict[str, typing.Any]:
        await self.make_agent()
        task = (await self.create_task()).json()
        response = await self.client.post(
            self.url(f'{task["short_id"]}/cancel')
        )
        self.assertEqual(response.json()['status'], 'closed')
        return typing.cast('dict[str, typing.Any]', task)


class PersonReopenTests(ReopenTestCase):
    async def test_reopen_clears_the_outcome(self) -> None:
        short_id = await self.closed_person_ticket()
        response = await self.reopen(short_id)
        self.assertEqual(response.status_code, 200, response.text)
        task = response.json()
        self.assertEqual(task['status'], 'open')
        self.assertIsNone(task['outcome'])
        self.assertIsNone(task['closed_at'])
        self.assertEqual(task['assignee'], self.member)
        events = await self.get_events(short_id)
        self.assertEqual(
            [(e['type'], e['payload']) for e in events[-2:]],
            [
                (
                    'reopened',
                    {
                        'outcome': 'done_acted',
                        'outcome_reason': None,
                        'reason': 'Not fixed',
                    },
                ),
                (
                    'state.changed',
                    {'from': 'closed', 'to': 'open', 'reason': 'reopened'},
                ),
            ],
        )
        # It can close again.
        response = await self.set_status(
            short_id, 'closed', outcome='superseded'
        )
        self.assertEqual(response.json()['outcome'], 'superseded')

    async def test_an_open_ticket_is_refused(self) -> None:
        short_id = (await self.create_person()).json()['short_id']
        response = await self.reopen(short_id)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'not_closed')
        response = await self.reopen('T-99')
        self.assertEqual(response.status_code, 404, response.text)

    async def test_owner_and_assignee_need_no_permission(self) -> None:
        short_id = await self.closed_person_ticket()
        self.permissions = set()
        # The caller owns the ticket.
        response = await self.reopen(short_id)
        self.assertEqual(response.status_code, 200, response.text)
        # Another person owns it; the assignee is a third person.
        actor = tickets.Actor('human', 'x', 'web')
        await self.store.set_owner(self.org, short_id, self.member, actor)
        await self.store.set_person_status(
            self.org, short_id, 'closed', actor, outcome='done_acted'
        )
        await self.clear_outbox(short_id)
        self.permissions = {'ticket:read'}
        response = await self.reopen(short_id)
        self.assertEqual(response.status_code, 403, response.text)
        self.permissions.add('ticket:manage')
        response = await self.reopen(short_id)
        self.assertEqual(response.status_code, 200, response.text)

    async def test_reopen_to_an_agent(self) -> None:
        agent_id = await self.make_agent(settings={'task_budget': '2'})
        short_id = await self.closed_person_ticket()
        response = await self.reopen(
            short_id, assignee_kind='agent', agent_slug='triage'
        )
        self.assertEqual(response.status_code, 200, response.text)
        task = response.json()
        self.assertEqual(task['status'], 'queued')
        self.assertEqual(task['assignee_kind'], 'agent')
        self.assertIsNone(task['assignee'])
        self.assertEqual(task['agent_id'], agent_id)
        self.assertEqual(task['agent_version'], 3)
        self.assertEqual(task['budget'], '2.000000')
        self.assertIsNotNone(task['service_account_id'])
        (event,) = [
            e
            for e in await self.get_events(short_id)
            if e['type'] == 'reopened'
        ]
        self.assertEqual(
            event['payload']['assignee'],
            {
                'from': {'kind': 'person', 'assignee': self.member},
                'to': {
                    'kind': 'agent',
                    'agent_id': agent_id,
                    'agent_version': 3,
                },
            },
        )

    async def test_new_assignee_is_checked(self) -> None:
        short_id = await self.closed_person_ticket()
        response = await self.reopen(short_id, assignee_kind='agent')
        self.assertEqual(response.status_code, 422, response.text)
        response = await self.reopen(
            short_id, assignee_kind='person', assignee='nobody@example.com'
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.permissions.discard('ticket:create')
        response = await self.reopen(
            short_id, assignee_kind='agent', agent_slug='triage'
        )
        self.assertEqual(response.status_code, 403, response.text)


class AgentReopenTests(ReopenTestCase):
    async def test_reopen_to_a_person(self) -> None:
        task = await self.closed_agent_ticket()
        await self.clear_outbox(task['short_id'])
        response = await self.reopen(
            task['short_id'], assignee_kind='person', assignee=self.member
        )
        self.assertEqual(response.status_code, 200, response.text)
        reopened = response.json()
        self.assertEqual(reopened['status'], 'open')
        self.assertEqual(reopened['assignee'], self.member)
        self.assertIsNone(reopened['agent_id'])
        # The budget stays, as in a handoff.
        self.assertEqual(reopened['budget'], task['budget'])

    async def test_agent_reopen_needs_create_and_an_enabled_agent(
        self,
    ) -> None:
        task = await self.closed_agent_ticket()
        await self.clear_outbox(task['short_id'])
        # The caller owns the ticket, but cannot make agent tickets.
        self.permissions = {'ticket:read'}
        response = await self.reopen(task['short_id'])
        self.assertEqual(response.status_code, 403, response.text)
        self.permissions.add('ticket:create')
        await self.graph.execute(
            'MATCH (a:Agent {{id: {id}}}) SET a.enabled = false'
            ' RETURN a.id AS id',
            {'id': task['agent_id']},
            ['id'],
        )
        response = await self.reopen(task['short_id'])
        self.assertEqual(response.status_code, 409, response.text)
        await self.graph.execute(
            'MATCH (a:Agent {{id: {id}}}) SET a.enabled = true'
            ' RETURN a.id AS id',
            {'id': task['agent_id']},
            ['id'],
        )
        response = await self.reopen(task['short_id'])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['budget'], task['budget'])

    async def test_root_chain_row_returns_to_the_queue(self) -> None:
        task = await self.closed_agent_ticket()
        task_id = uuid.UUID(task['id'])
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO harness.chains (root_ticket_id,'
                " organization_id, state) VALUES (%s, %s, 'done')",
                (task_id, self.org),
            )
        # The runs of the close have not started yet.
        response = await self.reopen(task['short_id'])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'triggers_pending'
        )
        await self.clear_outbox(task['short_id'])
        response = await self.reopen(task['short_id'])
        self.assertEqual(response.status_code, 200, response.text)
        reopened = response.json()
        self.assertEqual(reopened['status'], 'queued')
        self.assertEqual(reopened['control'], 'run')
        self.assertEqual(reopened['chain_id'], task['id'])
        chain = await self.harness.chain(task_id)
        assert chain is not None
        self.assertEqual((chain['state'], chain['attempt']), ('queued', 2))

    async def test_pinned_chain_is_refused(self) -> None:
        task = await self.closed_agent_ticket()
        await self.clear_outbox(task['short_id'])
        for state in ('running', 'fencing', 'stuck'):
            async with self.pool.connection() as conn:
                await conn.execute(
                    'INSERT INTO harness.chains (root_ticket_id,'
                    ' organization_id, state) VALUES (%s, %s, %s)'
                    ' ON CONFLICT (root_ticket_id)'
                    ' DO UPDATE SET state = EXCLUDED.state',
                    (uuid.UUID(task['id']), self.org, state),
                )
            response = await self.reopen(task['short_id'])
            with self.subTest(state):
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(
                    response.json()['detail']['error'], 'chain_pinned'
                )

    async def test_two_close_cycles_write_two_outbox_rows(self) -> None:
        closes: list[dict[str, typing.Any]] = []

        async def hook(task: dict[str, typing.Any]) -> None:
            closes.append(task)

        task_store.register_close_hook(hook)
        self.addCleanup(task_store.unregister_close_hook, hook)
        task = await self.closed_agent_ticket()
        await self.clear_outbox(task['short_id'])
        response = await self.reopen(task['short_id'])
        self.assertEqual(response.status_code, 200, response.text)
        await self.client.post(self.url(f'{task["short_id"]}/cancel'))
        (pending,) = [
            row
            for row in await self.store.pending_triggers()
            if row['organization_id'] == self.org
        ]
        first, second = (close['close_id'] for close in closes)
        self.assertEqual(first, task_store.FIRST_CLOSE_ID)
        self.assertNotEqual(second, first)
        self.assertEqual(pending['close_id'], second)
        self.assertEqual(pending['status'], 'closed')


class ReopenedChildClaimTests(test_harness.RunnerTestCase):
    """A reopened child is a chain root, so a runner claims it."""

    async def test_reopened_child_is_claimed(self) -> None:
        await secret_broker.initialize()
        helper_id = await self.make_agent('helper', name='Helper')
        await self.make_version({'subagents': [{'agent_id': helper_id}]})
        runner = await self.register()
        claim = await self.claim(runner)
        assert claim is not None
        token = claim['agent_token']
        response = await self.client.post(
            '/harness/tickets/T-1/children',
            json={
                'agent_slug': 'helper',
                'title': 'Help',
                'description': 'Help out.',
            },
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(response.status_code, 201, response.text)
        child = response.json()
        actor = tickets.Actor('agent', 'triage', 'harness')
        for short_id in (child['short_id'], 'T-1'):
            await self.store.set_outcome(
                self.org, short_id, 'done_acted', None, actor
            )
        response = await self.runner_post(runner, 'finish')
        self.assertEqual(response.json()['chain_state'], 'done')
        for row in await self.store.pending_triggers():
            if row['organization_id'] == self.org:
                await self.store.triggers_started(row['id'], row['close_id'])

        self.act_as_user()
        response = await self.client.post(
            self.url(f'{child["short_id"]}/reopen'), json={'reason': 'Again'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['chain_id'], child['id'])
        self.act_as(self.account)

        claim = await self.claim(await self.register())
        assert claim is not None
        self.assertEqual(claim['task']['short_id'], child['short_id'])
        self.assertEqual(claim['chain_id'], child['id'])
        # The root stays closed; nothing else waits.
        self.assertIsNone(await self.claim(await self.register()))


class ArchivedReopenTests(
    ReopenTestCase, test_agent_task_log.ClickHouseTestCase
):
    async def archive(self, short_id: str) -> None:
        for _ in range(3):
            await sweeper.sweep_once(self.store)
            task = await self.store.get(self.org, short_id)
            assert task is not None
            if task['log_archived_at'] is not None:
                return
        self.fail(f'{short_id} was not archived')

    async def test_reopened_archived_ticket_reads_one_log(self) -> None:
        await self.make_agent()
        short_id = (await self.create_task()).json()['short_id']
        response = await self.client.post(
            self.url(f'{short_id}/reply'), json={'body': 'Look at the logs'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        await self.client.post(self.url(f'{short_id}/cancel'))
        await self.clear_outbox(short_id)
        await self.archive(short_id)
        archived = await self.get_events(short_id)
        last_seq = archived[-1]['seq']

        response = await self.reopen(short_id)
        self.assertEqual(response.status_code, 200, response.text)
        row = await self.store.get(self.org, short_id)
        assert row is not None
        self.assertIsNone(row['log_archived_at'])
        self.assertEqual(row['archived_seq'], last_seq)
        response = await self.client.post(
            self.url(f'{short_id}/reply'), json={'body': 'Try again'}
        )
        self.assertEqual(response.status_code, 200, response.text)

        events = await self.get_events(short_id)
        self.assertEqual(
            [e['seq'] for e in events], list(range(1, last_seq + 4))
        )
        self.assertEqual(events[:last_seq], archived)
        # A page that spans the two stores.
        response = await self.client.get(
            self.url(f'{short_id}/events'),
            params={'after_seq': last_seq - 1, 'limit': 2},
        )
        self.assertEqual(
            [e['seq'] for e in response.json()], [last_seq, last_seq + 1]
        )
        # The history of a new session has the reopen and the comment.
        turns, _requests = await self.store.history(row)
        self.assertEqual(
            [
                (t['type'], t['payload'].get('body') or t['payload']['reason'])
                for t in turns
            ],
            [
                ('turn', 'Look at the logs'),
                ('reopened', 'Not fixed'),
                ('turn', 'Try again'),
            ],
        )

        # It closes and archives again; the log stays one log.
        await self.client.post(self.url(f'{short_id}/cancel'))
        await self.clear_outbox(short_id)
        await self.archive(short_id)
        again = await self.get_events(short_id)
        self.assertEqual(again[: len(events)], events)
        self.assertEqual(
            [e['seq'] for e in again], list(range(1, len(again) + 1))
        )
