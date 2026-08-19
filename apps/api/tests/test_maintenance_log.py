"""Tests for the maintenance activity log writer."""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from imbi.api.maintenance import log


def _item_log() -> log.ItemLog:
    return log.ItemLog('op', 'run1', 'attempt1', 'p1', 'p1', 'proj', 'admin')


class SanitizeDetailTests(unittest.TestCase):
    def test_empty_detail_stays_empty(self) -> None:
        self.assertEqual({}, log._sanitize_detail({}))

    def test_unserializable_values_become_strings(self) -> None:
        detail = log._sanitize_detail({'when': object()})
        self.assertIsInstance(detail['when'], str)

    def test_oversized_detail_is_dropped_for_a_marker(self) -> None:
        detail = log._sanitize_detail({'blob': 'x' * (log.MAX_DETAIL_BYTES)})
        self.assertEqual({'_truncated': True}, detail)


class ItemLogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(log, '_write', mock.AsyncMock())
        self.write = patcher.start()
        self.addCleanup(patcher.stop)

    async def test_record_buffers_without_writing(self) -> None:
        item = _item_log()
        item.record('succeeded', 'normalize', 'Normalized 3 committishes')
        self.assertEqual(1, item.buffered)
        self.write.assert_not_awaited()

    async def test_flush_writes_every_buffered_row_at_once(self) -> None:
        item = _item_log()
        item.record('succeeded', 'normalize')
        item.record('failed', 'merge', 'Tag resolution failed')
        item.attempt('failed', 'Operation failed.', 12)
        await item.flush()
        self.write.assert_awaited_once()
        rows = self.write.await_args.args[0]
        self.assertEqual(3, len(rows))
        self.assertEqual(
            ['activity', 'activity', 'attempt'], [r.event_type for r in rows]
        )
        self.assertEqual(12, rows[2].duration_ms)

    async def test_flush_clears_the_buffer(self) -> None:
        item = _item_log()
        item.record('succeeded', 'normalize')
        await item.flush()
        await item.flush()
        self.assertEqual(0, item.buffered)
        self.write.assert_awaited_once()

    async def test_rows_carry_the_item_identity(self) -> None:
        item = _item_log()
        item.record('skipped', 'resync', 'No deployment integration')
        await item.flush()
        row = self.write.await_args.args[0][0]
        self.assertEqual('run1', row.run_id)
        self.assertEqual('attempt1', row.attempt_id)
        self.assertEqual('p1', row.item_id)
        self.assertEqual('p1', row.project_id)
        self.assertEqual('proj', row.project_slug)
        self.assertEqual('admin', row.started_by)
        self.assertEqual('op', row.slug)

    async def test_a_long_message_is_truncated(self) -> None:
        item = _item_log()
        item.record('failed', 'merge', 'x' * (log.MAX_MESSAGE_LEN + 100))
        await item.flush()
        row = self.write.await_args.args[0][0]
        self.assertEqual(log.MAX_MESSAGE_LEN, len(row.message))

    async def test_detail_lands_on_the_row(self) -> None:
        item = _item_log()
        item.record('succeeded', 'merge', survivor='r1', folded=2)
        await item.flush()
        row = self.write.await_args.args[0][0]
        self.assertEqual({'survivor': 'r1', 'folded': 2}, row.detail)

    async def test_a_non_project_item_leaves_project_id_empty(self) -> None:
        item = log.ItemLog('search-reindex', 'run1', 'a1', 'Project:n1')
        item.attempt('succeeded')
        await item.flush()
        row = self.write.await_args.args[0][0]
        self.assertEqual('Project:n1', row.item_id)
        self.assertEqual('', row.project_id)


class RecordRunTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(log, '_write', mock.AsyncMock())
        self.write = patcher.start()
        self.addCleanup(patcher.stop)

    async def test_run_row_carries_the_counters(self) -> None:
        await log.record_run(
            'op', 'run1', 'completed', 'admin', total=5, failed=1
        )
        row = self.write.await_args.args[0][0]
        self.assertEqual('run', row.event_type)
        self.assertEqual('completed', row.disposition)
        self.assertEqual('admin', row.started_by)
        self.assertEqual({'total': 5, 'failed': 1}, row.detail)
        self.assertEqual('', row.attempt_id)


class BestEffortConstructionTests(unittest.IsolatedAsyncioTestCase):
    """Building a row must not fail the work that logged it."""

    def setUp(self) -> None:
        patcher = mock.patch.object(log, '_write', mock.AsyncMock())
        self.write = patcher.start()
        self.addCleanup(patcher.stop)
        sanitize = mock.patch.object(
            log, '_sanitize_detail', side_effect=RuntimeError('nope')
        )
        sanitize.start()
        self.addCleanup(sanitize.stop)

    async def test_record_drops_the_row_instead_of_raising(self) -> None:
        item = _item_log()
        item.record('succeeded', 'normalize', 'ok', count=1)
        self.assertEqual(0, item.buffered)

    async def test_attempt_drops_the_row_instead_of_raising(self) -> None:
        item = _item_log()
        item.attempt('succeeded', 'ok', 12, count=1)
        self.assertEqual(0, item.buffered)
        await item.flush()
        self.write.assert_not_awaited()

    async def test_record_run_drops_the_row_instead_of_raising(self) -> None:
        await log.record_run('op', 'run1', 'completed', 'admin', total=5)
        self.write.assert_not_awaited()


class WriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_rows_is_not_an_insert(self) -> None:
        with mock.patch.object(log.clickhouse, 'insert') as insert:
            await log._write([])
        insert.assert_not_called()

    async def test_a_clickhouse_failure_is_swallowed(self) -> None:
        item = _item_log()
        item.attempt('succeeded')
        with mock.patch.object(
            log.clickhouse,
            'insert',
            mock.AsyncMock(side_effect=RuntimeError('clickhouse down')),
        ):
            await item.flush()

    async def test_a_stalled_insert_times_out(self) -> None:
        async def _stall(*_args: object, **_kwargs: object) -> None:
            await asyncio.sleep(60)

        item = _item_log()
        item.attempt('succeeded')
        with (
            mock.patch.object(log, 'WRITE_TIMEOUT_SECONDS', 0.01),
            mock.patch.object(log.clickhouse, 'insert', _stall),
        ):
            await item.flush()
        self.assertEqual(0, item.buffered)

    async def test_the_insert_asks_the_server_to_batch(self) -> None:
        item = _item_log()
        item.attempt('succeeded')
        with mock.patch.object(
            log.clickhouse, 'insert', mock.AsyncMock()
        ) as insert:
            await item.flush()
        self.assertEqual(log.TABLE, insert.await_args.args[0])
        self.assertEqual(
            log.INSERT_SETTINGS, insert.await_args.kwargs['settings']
        )
