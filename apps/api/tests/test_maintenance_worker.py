"""Tests for the maintenance worker loop."""

from __future__ import annotations

import asyncio
import time
import typing
import unittest
from unittest import mock

from imbi.api.maintenance import log, registry, worker
from imbi.api.maintenance.operations import MaintenanceItemFailed
from imbi.common.plugins.errors import PluginRateLimited


def _operation(
    execute: mock.AsyncMock | typing.Any,
    pause_key: str | None = None,
    items_are_projects: bool = True,
) -> registry.OperationDefinition:
    return registry.OperationDefinition(
        slug=typing.cast('registry.MaintenanceSlug', 'op'),
        label='Op',
        description='Test operation',
        pause_key=pause_key,
        enumerate=mock.AsyncMock(return_value=[]),
        execute=execute,
        items_are_projects=items_are_projects,
    )


class TickOperationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = mock.AsyncMock()
        self.db = mock.AsyncMock()
        self.state: dict[str, mock.AsyncMock] = {}
        for name in (
            'has_active_run',
            'checkout',
            'record_outcome',
            'requeue',
            'maybe_finalize',
        ):
            patcher = mock.patch.object(worker.state, name, mock.AsyncMock())
            self.state[name] = patcher.start()
            self.addCleanup(patcher.stop)
        self.state['has_active_run'].return_value = True
        self.state['checkout'].return_value = 'p1'
        self.state['maybe_finalize'].return_value = False
        run_meta = mock.patch.object(
            worker.state,
            'read_run_meta',
            mock.AsyncMock(return_value=('run1', 'admin')),
        )
        self.state['read_run_meta'] = run_meta.start()
        self.addCleanup(run_meta.stop)
        slugs = mock.patch(
            'imbi.api.endpoints._helpers.lookup_project_slugs',
            mock.AsyncMock(return_value=('proj', 'team')),
        )
        self.lookup_slugs = slugs.start()
        self.addCleanup(slugs.stop)
        writes = mock.patch.object(log, '_write', mock.AsyncMock())
        self.write = writes.start()
        self.addCleanup(writes.stop)

    def written_rows(self) -> list[object]:
        return [
            row for call in self.write.await_args_list for row in call.args[0]
        ]

    async def test_no_active_run_is_noop(self) -> None:
        self.state['has_active_run'].return_value = False
        operation = _operation(mock.AsyncMock())
        result = await worker._tick_operation(self.client, self.db, operation)
        self.assertFalse(result)
        self.state['checkout'].assert_not_awaited()

    async def test_success_records_outcome(self) -> None:
        operation = _operation(mock.AsyncMock(return_value='succeeded'))
        result = await worker._tick_operation(self.client, self.db, operation)
        self.assertTrue(result)
        self.state['record_outcome'].assert_awaited_once_with(
            self.client, 'op', 'p1', 'succeeded', ''
        )
        self.state['maybe_finalize'].assert_awaited()

    async def test_record_outcome_failure_requeues(self) -> None:
        self.state['record_outcome'].side_effect = RuntimeError('valkey down')
        operation = _operation(mock.AsyncMock(return_value='succeeded'))
        result = await worker._tick_operation(self.client, self.db, operation)
        self.assertTrue(result)
        self.state['requeue'].assert_awaited_once_with(self.client, 'op', 'p1')

    async def test_log_context_failure_does_not_strand_the_claim(
        self,
    ) -> None:
        """Valkey failing after checkout must not lose the item."""
        self.state['read_run_meta'].side_effect = RuntimeError('valkey down')
        operation = _operation(mock.AsyncMock(return_value='succeeded'))
        result = await worker._tick_operation(self.client, self.db, operation)
        self.assertTrue(result)
        self.state['record_outcome'].assert_awaited_once_with(
            self.client, 'op', 'p1', 'succeeded', ''
        )
        row = self.written_rows()[0]
        self.assertEqual('', row.run_id)
        self.assertEqual('p1', row.item_id)

    async def test_a_slug_lookup_failure_keeps_the_run_metadata(self) -> None:
        self.lookup_slugs.side_effect = RuntimeError('graph down')
        operation = _operation(mock.AsyncMock(return_value='succeeded'))
        result = await worker._tick_operation(self.client, self.db, operation)
        self.assertTrue(result)
        row = self.written_rows()[0]
        self.assertEqual('run1', row.run_id)
        self.assertEqual('', row.project_slug)

    async def test_drained_finalizes(self) -> None:
        self.state['checkout'].return_value = None
        operation = _operation(mock.AsyncMock())
        result = await worker._tick_operation(self.client, self.db, operation)
        self.assertFalse(result)
        self.state['maybe_finalize'].assert_awaited_once()

    async def test_item_failed_records_message(self) -> None:
        operation = _operation(
            mock.AsyncMock(side_effect=MaintenanceItemFailed('boom'))
        )
        result = await worker._tick_operation(self.client, self.db, operation)
        self.assertTrue(result)
        self.state['record_outcome'].assert_awaited_once_with(
            self.client, 'op', 'p1', 'failed', 'boom'
        )

    async def test_unexpected_error_records_generic_message(self) -> None:
        operation = _operation(
            mock.AsyncMock(side_effect=RuntimeError('secret detail'))
        )
        result = await worker._tick_operation(self.client, self.db, operation)
        self.assertTrue(result)
        error = self.state['record_outcome'].await_args.args[4]
        self.assertNotIn('secret detail', error)

    async def test_rate_limited_requeues_and_pauses(self) -> None:
        retry_at = time.time() + 120
        operation = _operation(
            mock.AsyncMock(side_effect=PluginRateLimited(retry_at)),
            pause_key='imbi:test:paused-until',
        )
        with mock.patch.object(
            worker, 'pause_until', mock.AsyncMock()
        ) as pause:
            result = await worker._tick_operation(
                self.client, self.db, operation
            )
        self.assertFalse(result)
        self.state['requeue'].assert_awaited_once_with(self.client, 'op', 'p1')
        self.state['record_outcome'].assert_not_awaited()
        pause.assert_awaited_once_with(
            self.client, 'imbi:test:paused-until', retry_at
        )

    async def test_pause_key_honored_before_checkout(self) -> None:
        operation = _operation(
            mock.AsyncMock(), pause_key='imbi:test:paused-until'
        )
        with mock.patch.object(
            worker,
            'paused_remaining',
            mock.AsyncMock(return_value=30.0),
        ):
            result = await worker._tick_operation(
                self.client, self.db, operation
            )
        self.assertFalse(result)
        self.state['checkout'].assert_not_awaited()
        self.state['maybe_finalize'].assert_awaited_once()

    async def test_cancelled_requeues_and_reraises(self) -> None:
        operation = _operation(
            mock.AsyncMock(side_effect=asyncio.CancelledError())
        )
        with self.assertRaises(asyncio.CancelledError):
            await worker._tick_operation(self.client, self.db, operation)
        self.state['requeue'].assert_awaited_once_with(self.client, 'op', 'p1')

    async def test_success_writes_an_attempt_row(self) -> None:
        operation = _operation(mock.AsyncMock(return_value='succeeded'))
        await worker._tick_operation(self.client, self.db, operation)
        rows = self.written_rows()
        self.assertEqual(1, len(rows))
        self.assertEqual('attempt', rows[0].event_type)
        self.assertEqual('succeeded', rows[0].disposition)
        self.assertEqual('run1', rows[0].run_id)
        self.assertEqual('p1', rows[0].project_id)
        self.assertEqual('proj', rows[0].project_slug)
        self.assertTrue(rows[0].attempt_id)

    async def test_failure_message_reaches_the_attempt_row(self) -> None:
        operation = _operation(
            mock.AsyncMock(side_effect=MaintenanceItemFailed('boom'))
        )
        await worker._tick_operation(self.client, self.db, operation)
        rows = self.written_rows()
        self.assertEqual('failed', rows[0].disposition)
        self.assertEqual('boom', rows[0].message)

    async def test_what_the_operation_recorded_flushes_with_it(self) -> None:
        async def execute(
            _db: object,
            _client: object,
            _project_id: str,
            *,
            ctx: log.MaintenanceContext,
        ) -> str:
            ctx.log.record('succeeded', 'normalize', 'Normalized 2')
            return 'succeeded'

        operation = _operation(execute)
        await worker._tick_operation(self.client, self.db, operation)
        rows = self.written_rows()
        self.assertEqual(['activity', 'attempt'], [r.event_type for r in rows])
        self.assertEqual(rows[0].attempt_id, rows[1].attempt_id)

    async def test_rate_limited_is_recorded_as_deferred(self) -> None:
        operation = _operation(
            mock.AsyncMock(side_effect=PluginRateLimited(time.time() + 120)),
        )
        await worker._tick_operation(self.client, self.db, operation)
        rows = self.written_rows()
        self.assertEqual(1, len(rows))
        self.assertEqual('attempt', rows[0].event_type)
        self.assertEqual('deferred', rows[0].disposition)

    async def test_unrecordable_outcome_is_deferred_not_claimed(self) -> None:
        self.state['record_outcome'].side_effect = RuntimeError('valkey down')
        operation = _operation(mock.AsyncMock(return_value='succeeded'))
        await worker._tick_operation(self.client, self.db, operation)
        rows = self.written_rows()
        self.assertEqual('deferred', rows[0].disposition)

    async def test_cancellation_writes_nothing(self) -> None:
        operation = _operation(
            mock.AsyncMock(side_effect=asyncio.CancelledError())
        )
        with self.assertRaises(asyncio.CancelledError):
            await worker._tick_operation(self.client, self.db, operation)
        self.assertEqual([], self.written_rows())

    async def test_a_non_project_item_has_no_project_id(self) -> None:
        self.state['checkout'].return_value = 'Project:n1'
        operation = _operation(
            mock.AsyncMock(return_value='succeeded'), items_are_projects=False
        )
        await worker._tick_operation(self.client, self.db, operation)
        rows = self.written_rows()
        self.assertEqual('Project:n1', rows[0].item_id)
        self.assertEqual('', rows[0].project_id)


class RunWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_event_exits_promptly(self) -> None:
        stop = asyncio.Event()
        stop.set()
        await asyncio.wait_for(
            worker.run_worker(mock.AsyncMock(), mock.AsyncMock(), stop),
            timeout=1.0,
        )

    async def test_processes_until_stopped(self) -> None:
        stop = asyncio.Event()
        calls = 0

        async def tick(*_args: object) -> bool:
            nonlocal calls
            calls += 1
            if calls >= len(registry.OPERATIONS) * 2:
                stop.set()
            return True

        with mock.patch.object(worker, '_tick_operation', tick):
            await asyncio.wait_for(
                worker.run_worker(mock.AsyncMock(), mock.AsyncMock(), stop),
                timeout=2.0,
            )
        self.assertGreaterEqual(calls, len(registry.OPERATIONS))


class PauseHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_paused_remaining_reads_future_epoch(self) -> None:
        client = mock.AsyncMock()
        client.get = mock.AsyncMock(
            return_value=str(time.time() + 60).encode()
        )
        remaining = await worker.paused_remaining(client, 'k')
        self.assertGreater(remaining, 55.0)

    async def test_paused_remaining_clear_when_absent(self) -> None:
        client = mock.AsyncMock()
        client.get = mock.AsyncMock(return_value=None)
        self.assertEqual(0.0, await worker.paused_remaining(client, 'k'))

    async def test_pause_until_sets_key_with_ttl(self) -> None:
        client = mock.AsyncMock()
        retry_at = time.time() + 60
        await worker.pause_until(client, 'k', retry_at)
        args, kwargs = client.set.await_args
        self.assertEqual('k', args[0])
        self.assertGreaterEqual(kwargs['ex'], 60)
