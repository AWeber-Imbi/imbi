"""Tests for the ``agent_activity`` of a ticket."""

import typing

from apps.api.tests.endpoints import test_agent_tasks
from imbi.api import tickets


class AgentActivityTests(test_agent_tasks.AgentTaskTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.make_agent()

    async def activity(self) -> tuple[str | None, str | None]:
        """Return the activity of T-1 from the detail and the list."""
        detail = await self.client.get(self.url('T-1'))
        self.assertEqual(detail.status_code, 200, detail.text)
        listed = await self.client.get(self.url())
        self.assertEqual(listed.status_code, 200, listed.text)
        row = next(t for t in listed.json() if t['short_id'] == 'T-1')
        return detail.json()['agent_activity'], row['agent_activity']

    async def sql(self, statement: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(statement, {'org': self.org})

    async def request(
        self, kind: typing.Literal['feedback', 'approval']
    ) -> None:
        await self.store.open_request(
            self.org,
            'T-1',
            tickets.NewRequest(
                kind=kind,
                title=f'A {kind} request',
                why=None,
                options=None,
                artifacts=None,
                artifact_digests=None,
                expires_at=None,
                session_id=None,
            ),
            tickets.Actor('agent', 'triage', 'harness'),
        )

    async def test_activity(self) -> None:
        parent = (await self.create_task()).json()  # T-1
        self.assertEqual(await self.activity(), (None, None))

        await self.open_session(parent['id'])
        self.assertEqual(await self.activity(), ('working', 'working'))

        await self.create_task()  # T-2, made a child of T-1
        await self.sql(
            'UPDATE tickets.tickets AS c SET parent_id = p.id'
            ' FROM tickets.tickets AS p'
            ' WHERE c.organization_id = %(org)s'
            " AND p.organization_id = %(org)s AND c.short_id = 'T-2'"
            " AND p.short_id = 'T-1'"
        )
        self.assertEqual(await self.activity(), ('subagent', 'subagent'))

        await self.sql(
            "UPDATE tickets.tickets SET status = 'closed'"
            " WHERE organization_id = %(org)s AND short_id = 'T-2'"
        )
        await self.sql(
            'UPDATE tickets.sessions'
            " SET heartbeat_at = NOW() - interval '5 minutes'"
            ' WHERE ticket_id IN (SELECT id FROM tickets.tickets'
            " WHERE organization_id = %(org)s AND short_id = 'T-1')"
        )
        self.assertEqual(await self.activity(), ('stalled', 'stalled'))

        await self.request('feedback')
        self.assertEqual(await self.activity(), ('person', 'person'))
        await self.request('approval')
        self.assertEqual(await self.activity(), ('approval', 'approval'))

    async def test_run_started_at(self) -> None:
        task = (await self.create_task()).json()  # T-1
        await self.create_task()  # T-2, not running
        await self.open_session(task['id'])
        await self.sql(
            'UPDATE tickets.sessions'
            " SET opened_at = '2026-11-24T12:00:00+00:00'"
            ' WHERE ticket_id IN (SELECT id FROM tickets.tickets'
            " WHERE organization_id = %(org)s AND short_id = 'T-1')"
        )
        listed = await self.client.get(self.url(), params={'group': 'running'})
        self.assertEqual(listed.status_code, 200, listed.text)
        rows = {t['short_id']: t for t in listed.json()}
        self.assertEqual(list(rows), ['T-1'])
        self.assertEqual(rows['T-1']['run_started_at'], '2026-11-24T12:00:00Z')
        listed = await self.client.get(self.url())
        rows = {t['short_id']: t for t in listed.json()}
        self.assertIsNone(rows['T-2']['run_started_at'])
