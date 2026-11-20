"""Tests for ticket handoff (ADR 0028, plan P4)."""

import decimal
import typing
import uuid

import httpx

from apps.api.tests.endpoints import test_agent_task_harness, test_harness
from imbi.api import tickets
from imbi.api.endpoints import harness as harness_api


class HandOffTestCase(test_agent_task_harness.HarnessTestCase):
    """``T-1`` is a queued agent ticket of ``triage``, owned by ``email``.

    The owner can make tickets (a role with ``ticket:create``), so an
    agent can work for them.
    """

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.role = f'handoff-{self.org}'
        await self.graph.execute(
            'MERGE (p:Permission {{name: "ticket:create"}})'
            ' CREATE (r:Role {{slug: {role}, name: {role}}})'
            ' CREATE (r)-[:GRANTS]->(p)'
            ' WITH r MATCH (:User {{email: {email}}})-[m:MEMBER_OF]->()'
            ' SET m.role = {role} RETURN 1 AS ok',
            {'role': self.role, 'email': self.email},
            ['ok'],
        )
        self.addAsyncCleanup(
            self.graph.execute,
            'MATCH (r:Role {{slug: {role}}}) DETACH DELETE r RETURN 1 AS ok',
            {'role': self.role},
            ['ok'],
        )

    async def hand_off(
        self, short_id: str = 'T-1', **body: typing.Any
    ) -> httpx.Response:
        return await self.as_user('POST', f'{short_id}/hand-off', json=body)

    async def to_person(
        self, short_id: str = 'T-1', **body: typing.Any
    ) -> httpx.Response:
        return await self.hand_off(
            short_id,
            assignee_kind='person',
            assignee=body.pop('assignee', self.member),
            **body,
        )

    async def to_agent(self, short_id: str = 'T-1') -> httpx.Response:
        return await self.hand_off(
            short_id, assignee_kind='agent', agent_slug='triage'
        )

    async def types(self, short_id: str = 'T-1') -> list[str]:
        return [e['type'] for e in await self.events(short_id)]

    async def close_sessions(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE tickets.sessions SET closed_at = NOW()'
                ' WHERE closed_at IS NULL'
            )


class HandOffTests(HandOffTestCase):
    async def test_agent_to_person_and_back(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE tickets.tickets SET cost_total = 0.4, control = %s'
                " , status = 'paused' WHERE id = %s",
                ('pause', uuid.UUID(self.task['id'])),
            )
        response = await self.to_person(note='Please finish it.')
        self.assertEqual(response.status_code, 200, response.text)
        task = response.json()
        self.assertEqual(task['assignee_kind'], 'person')
        self.assertEqual(task['assignee'], self.member)
        self.assertEqual(task['status'], 'open')
        self.assertEqual(task['control'], 'run')
        for column in ('agent_id', 'agent_version', 'service_account_id'):
            self.assertIsNone(task[column])
        events = await self.events()
        handed = next(e for e in events if e['type'] == 'handed_off')
        self.assertEqual(
            handed['payload'],
            {
                'from': {
                    'kind': 'agent',
                    'agent_id': self.agent_id,
                    'agent_version': 3,
                },
                'to': {'kind': 'person', 'assignee': self.member},
                'note': 'Please finish it.',
            },
        )
        self.assertEqual(
            events[-1]['payload'],
            {'from': 'paused', 'to': 'open', 'reason': 'handed_off'},
        )

        response = await self.to_agent()
        self.assertEqual(response.status_code, 200, response.text)
        task = response.json()
        self.assertEqual(task['assignee_kind'], 'agent')
        self.assertIsNone(task['assignee'])
        self.assertEqual(task['status'], 'queued')
        self.assertEqual(task['agent_id'], self.agent_id)
        self.assertEqual(task['agent_version'], 3)
        self.assertEqual(task['prompt_version'], 7)
        self.assertIsNotNone(task['service_account_id'])
        # The budget counts the cost of every agent period.
        self.assertEqual(decimal.Decimal(task['budget']), 1)
        self.assertEqual(
            decimal.Decimal(task['cost_total']), decimal.Decimal('0.4')
        )

    async def test_person_ticket_gets_the_agent_budget(self) -> None:
        self.act_as_user()
        response = await self.client.post(
            self.url(),
            json={
                'assignee_kind': 'person',
                'assignee': self.member,
                'title': 'Rotate',
                'description': 'Rotate the key.',
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertIsNone(response.json()['budget'])
        response = await self.to_agent('T-2')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(decimal.Decimal(response.json()['budget']), 1)
        self.assertEqual(
            (await self.types('T-2'))[-2:], ['handed_off', 'state.changed']
        )

    async def test_agent_budget_caps_the_ticket(self) -> None:
        # The agent has task_budget 1 (HarnessTestCase).
        await self.to_person()
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE tickets.tickets SET budget = 50 WHERE id = %s',
                (uuid.UUID(self.task['id']),),
            )
        response = await self.to_agent()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(decimal.Decimal(response.json()['budget']), 1)
        # A lower budget stays.
        await self.to_person()
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE tickets.tickets SET budget = 0.5 WHERE id = %s',
                (uuid.UUID(self.task['id']),),
            )
        response = await self.to_agent()
        self.assertEqual(
            decimal.Decimal(response.json()['budget']), decimal.Decimal('0.5')
        )

    async def test_open_requests_are_withdrawn(self) -> None:
        await self.open_session()
        response = await self.post(
            'requests', {'kind': 'feedback', 'title': 'Which one?'}
        )
        self.assertEqual(response.status_code, 201, response.text)
        request_id = response.json()['request']['id']
        await self.close_sessions()
        self.assertEqual((await self.task_row())['status'], 'blocked')
        response = await self.to_person()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'open')
        events = await self.events()
        withdrawn = [e for e in events if e['type'] == 'request.withdrawn']
        self.assertEqual(
            [e['payload'] for e in withdrawn], [{'request_id': request_id}]
        )
        async with self.pool.connection() as conn:
            cursor = await conn.execute(
                'SELECT status, resolved_by FROM tickets.requests'
                ' WHERE id = %s',
                (uuid.UUID(request_id),),
            )
            self.assertEqual(
                await cursor.fetchone(), ('withdrawn', self.email)
            )
        # A withdrawn request cannot be resolved.
        response = await self.as_user(
            'POST',
            f'T-1/requests/{request_id}/resolve',
            json={'status': 'answered', 'answer': 'A'},
        )
        self.assertEqual(response.status_code, 409, response.text)

    async def test_held_stays_held(self) -> None:
        self.act_as_user()
        await self.create_task()
        response = await self.client.put(
            self.url('T-1/requires/T-2'), json={'gates': True}
        )
        self.assertEqual(response.status_code, 204, response.text)
        response = await self.to_person()
        self.assertEqual(response.json()['status'], 'held')
        self.assertNotIn('state.changed', (await self.types())[-1:])
        response = await self.to_agent()
        self.assertEqual(response.json()['status'], 'held')
        # The release reads the new kind.
        await self.to_person()
        await self.store.set_outcome(
            self.org,
            'T-2',
            'done_acted',
            None,
            tickets.Actor('human', self.email, 'web'),
        )
        self.assertEqual((await self.task_row())['status'], 'open')

    async def test_person_to_person(self) -> None:
        await self.to_person()
        response = await self.to_person(assignee=self.email, note='Yours')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['assignee'], self.email)
        self.assertEqual(response.json()['status'], 'open')
        event = (await self.events())[-1]
        self.assertEqual(event['type'], 'assignee.changed')
        self.assertEqual(
            event['payload'],
            {'from': self.member, 'to': self.email, 'note': 'Yours'},
        )
        # The same person changes nothing.
        before = (await self.task_row())['last_seq']
        await self.to_person(assignee=self.email)
        self.assertEqual((await self.task_row())['last_seq'], before)

    async def test_refusals(self) -> None:
        response = await self.to_agent()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'agent_ticket')
        response = await self.to_person(assignee='nobody@example.com')
        self.assertEqual(response.status_code, 422, response.text)
        for body in (
            {'assignee_kind': 'person'},
            {'assignee_kind': 'agent', 'assignee': self.member},
            {
                'assignee_kind': 'person',
                'assignee': self.member,
                'agent_slug': 'triage',
            },
        ):
            with self.subTest(body):
                response = await self.hand_off(**body)
                self.assertEqual(response.status_code, 422, response.text)

        await self.open_session()
        response = await self.to_person()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'session_open')
        await self.close_sessions()

        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO harness.chains'
                ' (root_ticket_id, organization_id, state)'
                " VALUES (%s, %s, 'fencing')",
                (uuid.UUID(self.task['id']), self.org),
            )
        response = await self.to_person()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'chain_pinned')

        await self.store.set_outcome(
            self.org,
            'T-1',
            'done_acted',
            None,
            tickets.Actor('human', self.email, 'web'),
        )
        response = await self.to_person()
        self.assertEqual(response.status_code, 409, response.text)

    async def test_who_may_hand_off(self) -> None:
        self.act_as_user()
        await self.client.post(
            self.url(),
            json={
                'assignee_kind': 'person',
                'assignee': self.member,
                'title': 'Theirs',
                'description': 'Owned by someone else.',
            },
        )
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE tickets.tickets SET owner = %s'
                ' WHERE organization_id = %s',
                ('other@example.com', self.org),
            )
        self.permissions = {'ticket:read'}
        response = await self.to_person()
        self.assertEqual(response.status_code, 403, response.text)
        # The assignee needs no ticket:manage.
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE tickets.tickets SET assignee = %s WHERE short_id = %s'
                ' AND organization_id = %s',
                (self.email.upper(), 'T-2', self.org),
            )
        response = await self.to_person('T-2')
        self.assertEqual(response.status_code, 200, response.text)
        self.permissions = {'ticket:manage'}
        response = await self.to_person()
        self.assertEqual(response.status_code, 200, response.text)

    async def test_agent_target_needs_create(self) -> None:
        await self.to_person()
        # The caller is the assignee, not the owner, with no
        # ticket:create: a person target is allowed, an agent is not.
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE tickets.tickets SET owner = %s, assignee = %s'
                ' WHERE organization_id = %s',
                (self.member, self.email, self.org),
            )
        self.permissions = {'ticket:read'}
        response = await self.to_agent()
        self.assertEqual(response.status_code, 403, response.text)
        response = await self.to_person(assignee=self.email)
        self.assertEqual(response.status_code, 200, response.text)
        # With ticket:create, the owner must still be able to make
        # tickets: the agent works for them.
        self.permissions = {'ticket:read', 'ticket:create'}
        response = await self.to_agent()
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()['detail']['error'], 'owner_forbidden')
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE tickets.tickets SET owner = %s'
                ' WHERE organization_id = %s',
                (self.email, self.org),
            )
        response = await self.to_agent()
        self.assertEqual(response.status_code, 200, response.text)

    async def test_person_to_person_while_the_chain_is_held(self) -> None:
        # The agent handed the ticket to a person, and its runner still
        # holds the chain (fencing) or a fencer failed (stuck).
        await self.to_person()
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO harness.chains'
                ' (root_ticket_id, organization_id, state)'
                " VALUES (%s, %s, 'stuck')",
                (uuid.UUID(self.task['id']), self.org),
            )
        response = await self.to_person(assignee=self.email)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['assignee'], self.email)
        # Back to an agent waits for the runner.
        response = await self.to_agent()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'chain_pinned')

    async def test_agent_gets_the_current_platform_config(self) -> None:
        await self.to_person()
        self.assertIsNone((await self.task_row())['platform_config_version'])
        config = await self.harness.add_platform_config(
            self.org, {'denied_tools': ['Bash']}, self.email
        )
        self.addAsyncCleanup(self.drop_platform_configs)
        response = await self.to_agent()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            (await self.task_row())['platform_config_version'],
            config['version'],
        )

    async def drop_platform_configs(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM harness.platform_configs'
                ' WHERE organization_id = %s',
                (self.org,),
            )

    async def test_done_chain_is_queued_again(self) -> None:
        await self.to_person()
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO harness.chains'
                ' (root_ticket_id, organization_id, state, attempt)'
                " VALUES (%s, %s, 'done', 2)",
                (uuid.UUID(self.task['id']), self.org),
            )
        response = await self.to_agent()
        self.assertEqual(response.status_code, 200, response.text)
        chain = await self.harness.chain(uuid.UUID(self.task['id']))
        assert chain is not None
        self.assertEqual((chain['state'], chain['attempt']), ('queued', 3))

    async def test_timeout_counts_from_the_handoff(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO tickets.sessions'
                ' (id, ticket_id, opened_at, closed_at) VALUES'
                " (%s, %s, NOW() - interval '1 day',"
                " NOW() - interval '1 day')",
                (uuid.uuid4(), uuid.UUID(self.task['id'])),
            )
        await self.to_person()
        await self.to_agent()
        session = await self.open_session()
        task = await self.store.heartbeat(
            self.org,
            'T-1',
            uuid.UUID(session['session']['id']),
            timeout_seconds=3600,
            system=tickets.Actor('system', None, 'harness'),
        )
        self.assertEqual(task['status'], 'running')


class HarnessHandOffTests(test_harness.RunnerTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        claim = await self.claim(await self.register())
        assert claim is not None
        self.token: str = claim['agent_token']
        response = await self.as_agent(
            self.token, 'POST', 'T-1/sessions', {'session_key': 'k'}
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.session_id = response.json()['session']['id']

    async def agent_hand_off(self, **body: typing.Any) -> httpx.Response:
        return await self.as_agent(
            self.token,
            'POST',
            f'T-1/sessions/{self.session_id}/hand-off',
            {'note': 'Merge the PR; I cannot.', **body},
        )

    async def test_agent_hands_off_to_the_owner(self) -> None:
        response = await self.agent_hand_off()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'open')
        task = await self.task_row()
        self.assertEqual(task['assignee'], self.email)
        session = await self.store.events(task['id'], 0, 100)
        closed = [e for e in session if e['type'] == 'session.closed']
        self.assertEqual(closed[0]['payload']['reason'], 'handed_off')
        handed = next(e for e in session if e['type'] == 'handed_off')
        self.assertEqual(handed['actor_kind'], 'agent')
        self.assertEqual(handed['payload']['note'], 'Merge the PR; I cannot.')
        # The ticket left the agent: its token no longer works on it.
        response = await self.agent_hand_off()
        self.assertEqual(response.status_code, 403, response.text)

    async def test_history_has_the_handoff(self) -> None:
        response = await self.agent_hand_off(assignee=self.member)
        self.assertEqual(response.status_code, 200, response.text)
        (event,), _requests = await self.store.history(await self.task_row())
        entry = harness_api._event_entry(event, webhook=False)
        self.assertEqual(entry.kind, 'handoff')
        self.assertEqual(entry.actor, self.agent_id)
        self.assertEqual(
            entry.text,
            f'from agent {self.agent_id} to {self.member}\n'
            'Note: Merge the PR; I cannot.',
        )

    async def test_runner_keeps_the_chain(self) -> None:
        await self.agent_hand_off()
        # Until the runner finishes, the chain is pinned.
        response = await self.as_user(
            'POST',
            'T-1/hand-off',
            json={'assignee_kind': 'agent', 'agent_slug': 'triage'},
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'chain_pinned')

    async def test_refusals(self) -> None:
        response = await self.agent_hand_off(assignee='nobody@example.com')
        self.assertEqual(response.status_code, 422, response.text)
        response = await self.as_agent(
            self.token,
            'POST',
            f'T-1/sessions/{uuid.uuid4()}/hand-off',
            {'note': 'x'},
        )
        self.assertEqual(response.status_code, 404, response.text)
        response = await self.agent_hand_off(note='')
        self.assertEqual(response.status_code, 422, response.text)
