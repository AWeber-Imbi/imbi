"""Tests for the permanent agent task log in ClickHouse (ADR 0020).

These write through the real code and read the rows back from the live
ClickHouse that ``root:services`` boots.
:func:`apps.api.tests.support.sink_to_clickhouse` puts each publish
straight into its table, as the Iggy sink would.
"""

import typing
import uuid
from unittest import mock

from apps.api.tests import support
from apps.api.tests.endpoints import test_agent_tasks
from imbi.common import clickhouse, iggy
from imbi.common.clickhouse import client


class ClickHouseTestCase(test_agent_tasks.AgentTaskTestCase):
    """Agent task fixtures with a private ClickHouse client."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # The ClickHouse client binds to the loop that opened it, and each
        # test has its own loop, so each test takes its own client.
        previous = client.Clickhouse._instance
        client.Clickhouse._instance = None

        async def restore() -> None:
            await clickhouse.aclose()
            client.Clickhouse._instance = previous

        self.addAsyncCleanup(restore)
        await clickhouse.initialize()
        await clickhouse.setup_schema()
        sink = support.sink_to_clickhouse()
        sink.__enter__()
        self.addCleanup(sink.__exit__, None, None, None)

    async def stored_events(self, task_id: str) -> list[dict[str, typing.Any]]:
        """Return the ClickHouse rows of a task, with duplicates."""
        return await clickhouse.query(
            'SELECT * FROM imbi.agent_task_events'
            ' WHERE task_id = {task_id:String} ORDER BY seq',
            {'task_id': task_id},
        )

    async def postgres_events(
        self, task_id: str
    ) -> list[dict[str, typing.Any]]:
        return await self.store.events(uuid.UUID(task_id), 0, 1000)


class PublishTests(ClickHouseTestCase):
    async def test_every_event_reaches_clickhouse_once(self) -> None:
        await self.make_agent()
        task = (await self.create_task(project_id=self.project_id)).json()
        for action in ('pause', 'resume', 'cancel'):
            response = await self.client.post(self.url(f'T-1/{action}'))
            self.assertEqual(response.status_code, 200, response.text)

        expected = await self.postgres_events(task['id'])
        stored = await self.stored_events(task['id'])
        self.assertEqual(len(expected), 8)
        self.assertEqual(
            [row['seq'] for row in stored], [e['seq'] for e in expected]
        )
        for event, row in zip(expected, stored, strict=True):
            self.assertEqual(row['event_id'], str(event['event_id']))
            self.assertEqual(row['type'], event['type'])
            self.assertEqual(row['organization_id'], self.org)
            self.assertEqual(row['short_id'], 'T-1')
            self.assertEqual(row['agent_id'], task['agent_id'])
            self.assertEqual(row['agent_version'], 3)
            self.assertEqual(row['project_id'], self.project_id)
            self.assertEqual(row['actor_id'], self.email)
            self.assertEqual(row['channel'], 'web')
            self.assertEqual(clickhouse.as_utc(row['at']), event['at'])

    async def test_publish_failure_does_not_fail_the_write(self) -> None:
        await self.make_agent()
        failing = mock.AsyncMock(side_effect=RuntimeError('Iggy is down'))
        with mock.patch.object(iggy, 'publish_rows', failing):
            response = await self.create_task()
        self.assertEqual(response.status_code, 201, response.text)
        failing.assert_awaited_once()
        self.assertEqual(await self.stored_events(response.json()['id']), [])
        self.assertEqual(
            len(await self.postgres_events(response.json()['id'])), 1
        )
