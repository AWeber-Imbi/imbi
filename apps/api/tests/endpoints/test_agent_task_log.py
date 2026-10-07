"""Tests for the permanent agent task log in ClickHouse (ADR 0020).

These write through the real code and read the rows back from the live
ClickHouse that ``root:services`` boots.
:func:`apps.api.tests.support.sink_to_clickhouse` puts each publish
straight into its table, as the Iggy sink would.
"""

import decimal
import typing
import uuid
from unittest import mock

from apps.api.tests import support
from apps.api.tests.endpoints import test_agent_tasks
from imbi.api import agent_tasks
from imbi.api.agent_tasks import sweeper
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


class SweepTests(ClickHouseTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.make_agent()
        self.task = (await self.create_task()).json()
        # The pause events never reach ClickHouse.
        failing = mock.AsyncMock(side_effect=RuntimeError('Iggy is down'))
        with mock.patch.object(iggy, 'publish_rows', failing):
            response = await self.client.post(self.url('T-1/pause'))
        self.assertEqual(response.status_code, 200, response.text)

    async def get_log(
        self, **params: typing.Any
    ) -> list[dict[str, typing.Any]]:
        response = await self.client.get(self.url('T-1/events'), params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_sweep_republishes_missing_rows(self) -> None:
        stored = await self.stored_events(self.task['id'])
        self.assertEqual([row['seq'] for row in stored], [1])
        result = await sweeper.sweep_once(self.store)
        self.assertGreaterEqual(result.republished_events, 2)
        stored = await self.stored_events(self.task['id'])
        self.assertEqual([row['seq'] for row in stored], [1, 2, 3])
        # A complete open task is not archived.
        await sweeper.sweep_once(self.store)
        task = await self.store.get(self.org, 'T-1')
        assert task is not None
        self.assertIsNone(task['log_archived_at'])
        self.assertEqual(len(await self.postgres_events(self.task['id'])), 3)
        self.assertEqual(len(await self.stored_events(self.task['id'])), 3)

    async def test_archive_moves_the_log_to_clickhouse(self) -> None:
        response = await self.client.post(self.url('T-1/cancel'))
        self.assertEqual(response.json()['status'], 'closed')
        before = await self.get_log()
        page = await self.get_log(after_seq=1, limit=2)
        self.assertEqual([e['seq'] for e in before], [1, 2, 3, 4, 5, 6])

        # The first round only republishes; the task is not complete.
        await sweeper.sweep_once(self.store)
        task = await self.store.get(self.org, 'T-1')
        assert task is not None
        self.assertIsNone(task['log_archived_at'])

        await sweeper.sweep_once(self.store)
        task = await self.store.get(self.org, 'T-1')
        assert task is not None
        self.assertIsNotNone(task['log_archived_at'])
        self.assertEqual(await self.postgres_events(self.task['id']), [])
        self.assertEqual(await self.get_log(), before)
        self.assertEqual(await self.get_log(after_seq=1, limit=2), page)
        self.assertEqual(await self.get_log(after_seq=6), [])
        # An archived task is not swept again.
        self.assertFalse(await self.store.archive(task['id'], 6))

    async def test_sweep_republishes_usage_rows(self) -> None:
        actor = agent_tasks.Actor('agent', 'agent-1', 'harness')
        prices: dict[str, decimal.Decimal | None] = {
            'input_cost_per_million': decimal.Decimal(3),
            'output_cost_per_million': decimal.Decimal(15),
            'cache_read_cost_per_million': None,
            'cache_write_cost_per_million': None,
        }
        failing = mock.AsyncMock(side_effect=RuntimeError('Iggy is down'))
        with mock.patch.object(iggy, 'publish_rows', failing):
            _task, row, _created = await self.store.report_usage(
                self.org,
                'T-1',
                agent_tasks.Usage('u-1', 'opus', 1000, 100, None, None, None),
                prices,
                actor=actor,
                system=actor,
            )
        query = (
            'SELECT * FROM imbi.agent_usage WHERE task_id = {task_id:String}'
        )
        params = {'task_id': self.task['id']}
        self.assertEqual(await clickhouse.query(query, params), [])
        result = await sweeper.sweep_once(self.store)
        self.assertGreaterEqual(result.republished_reports, 1)
        (stored,) = await clickhouse.query(query, params)
        self.assertEqual(stored['report_id'], str(row['id']))
        self.assertEqual(stored['model_id'], 'opus')
        self.assertEqual(stored['tokens_in'], 1000)
        self.assertIsNone(stored['cache_read_tokens'])
        self.assertEqual(stored['input_cost_per_million'], 3)
        self.assertIsNone(stored['cache_read_cost_per_million'])
        self.assertEqual(stored['cost'], decimal.Decimal('0.0045'))
        self.assertEqual(stored['short_id'], 'T-1')
