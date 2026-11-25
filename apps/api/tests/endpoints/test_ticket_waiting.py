"""Tests for the Waiting on me lists (ADR 0028, plan P5)."""

import datetime
import typing

from apps.api.tests.endpoints import test_agent_tasks
from imbi.api import tickets


class WaitingTests(test_agent_tasks.AgentTaskTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.agent_id = await self.make_agent()
        self.agent = tickets.Actor('agent', 'triage', 'harness')

    async def waiting(self) -> dict[str, typing.Any]:
        response = await self.client.get(
            self.url('waiting'), params={'lists': 'true'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def request(
        self,
        short_id: str,
        title: str,
        actor: tickets.Actor | None = None,
        **kwargs: typing.Any,
    ) -> None:
        values: dict[str, typing.Any] = {
            'kind': 'feedback',
            'title': title,
            'why': None,
            'options': None,
            'artifacts': None,
            'artifact_digests': None,
            'expires_at': None,
            'session_id': None,
        }
        await self.store.open_request(
            self.org,
            short_id,
            tickets.NewRequest(**{**values, **kwargs}),
            actor or self.agent,
        )

    async def test_three_lists(self) -> None:
        await self.create_task()  # T-1, owned by the caller
        await self.create_task()  # T-2, owned by someone else
        await self.request('T-1', 'Which branch?')
        await self.request('T-2', 'Not mine')
        await self.request(
            'T-1',
            'Expired',
            expires_at=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(seconds=1),
        )
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE tickets.tickets SET owner = 'x@example.com'"
                " WHERE organization_id = %s AND short_id = 'T-2'",
                (self.org,),
            )
            await conn.execute(
                'UPDATE tickets.requests'
                " SET expires_at = NOW() - interval '1 second'"
                " WHERE title = 'Expired'"
            )
        # T-3 for the caller (by email in another case); T-4 for another.
        for assignee in (self.email, self.member):
            response = await self.client.post(
                self.url(),
                json={
                    'assignee_kind': 'person',
                    'assignee': assignee,
                    'title': 'Rotate',
                    'description': 'Rotate the key.',
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE tickets.tickets SET assignee = upper(assignee)'
                " WHERE organization_id = %s AND short_id = 'T-3'",
                (self.org,),
            )
        # T-5 fails; T-6 is held by it; T-7 is held by open T-1.
        await self.create_task()
        await self.store.set_outcome(
            self.org, 'T-5', 'failed_external', 'down', self.agent
        )
        await self.create_task(requires=[{'short_id': 'T-5', 'gates': True}])
        await self.create_task(requires=[{'short_id': 'T-1', 'gates': True}])
        self.assertEqual(
            [
                t['status']
                for t in (await self.client.get(self.url())).json()
                if t['short_id'] in ('T-6', 'T-7')
            ],
            ['held', 'held'],
        )

        body = await self.waiting()
        self.assertEqual(
            [(r['short_id'], r['title']) for r in body['requests']],
            [('T-1', 'Which branch?')],
        )
        self.assertEqual(
            body['requests'][0]['ticket_title'], 'Look at the build'
        )
        self.assertEqual([t['short_id'] for t in body['assigned']], ['T-3'])
        self.assertEqual(
            [(t['short_id'], t['failed']) for t in body['held']],
            [('T-6', ['T-5'])],
        )
        self.assertEqual(body['count'], 3)
        # The badge reads the count only.
        response = await self.client.get(self.url('waiting'))
        self.assertEqual(
            response.json(),
            {'count': 3, 'requests': [], 'assigned': [], 'held': []},
        )

        # A closed ticket waits on nobody.
        await self.store.set_outcome(
            self.org, 'T-1', 'cancelled_by_human', 'x', self.agent
        )
        body = await self.waiting()
        self.assertEqual(body['requests'], [])

    async def test_service_account_has_none(self) -> None:
        await self.act_as_service_account(member=True)
        self.assertEqual(
            await self.waiting(),
            {'count': 0, 'requests': [], 'assigned': [], 'held': []},
        )

    async def test_assigned_carries_due_date_and_rank(self) -> None:
        response = await self.client.post(
            self.url(),
            json={
                'assignee_kind': 'person',
                'assignee': self.email,
                'title': 'Rotate',
                'description': 'Rotate the key.',
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        short_id = response.json()['short_id']
        body = await self.waiting()
        self.assertEqual(body['assigned'][0]['due_date'], None)
        self.assertEqual(body['assigned'][0]['backlog_rank'], None)
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE tickets.tickets SET due_date = '2026-12-01',"
                ' backlog_rank = 2.5'
                ' WHERE organization_id = %s AND short_id = %s',
                (self.org, short_id),
            )
        body = await self.waiting()
        self.assertEqual(body['assigned'][0]['due_date'], '2026-12-01')
        self.assertEqual(body['assigned'][0]['backlog_rank'], 2.5)

    async def test_request_carries_the_agent_that_opened_it(self) -> None:
        await self.create_task()
        await self.request(
            'T-1',
            'From the agent',
            tickets.Actor('agent', self.agent_id, 'harness'),
        )
        await self.request(
            'T-1', 'From the system', tickets.Actor('system', 'imbi', 'api')
        )
        body = await self.waiting()
        self.assertEqual(
            [
                (r['title'], r['agent_slug'], r['agent_name'])
                for r in body['requests']
            ],
            [
                ('From the agent', 'triage', 'Triage Bot'),
                ('From the system', None, None),
            ],
        )
