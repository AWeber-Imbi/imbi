"""Tests for the commit/tag-sync queue."""

from __future__ import annotations

import time
import unittest
from unittest import mock

from imbi.api.commit_sync import queue
from imbi.api.commit_sync.service import CommitSyncUnavailable
from imbi.common.plugins.errors import PluginRateLimited


class EnqueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_xadds_when_debounce_acquired(self) -> None:
        client = mock.AsyncMock()
        client.set = mock.AsyncMock(return_value=True)
        client.xadd = mock.AsyncMock()
        result = await queue.enqueue_commit_sync(client, 'octo', 'p1', 'alice')
        self.assertTrue(result)
        client.xadd.assert_awaited_once()
        args, _ = client.xadd.await_args
        self.assertEqual(args[0], queue.STREAM)
        self.assertEqual(args[1]['project_id'], 'p1')
        self.assertEqual(args[1]['org_slug'], 'octo')
        self.assertEqual(args[1]['requested_by'], 'alice')

    async def test_enqueue_skips_when_debounced(self) -> None:
        client = mock.AsyncMock()
        client.set = mock.AsyncMock(return_value=None)
        client.xadd = mock.AsyncMock()
        result = await queue.enqueue_commit_sync(client, 'octo', 'p1')
        self.assertFalse(result)
        client.xadd.assert_not_called()

    async def test_enqueue_none_client_returns_false(self) -> None:
        self.assertFalse(await queue.enqueue_commit_sync(None, 'octo', 'p1'))


class ProcessMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_sets_running_then_success(self) -> None:
        db = mock.AsyncMock()
        with (
            mock.patch.object(
                queue, 'run_sync', mock.AsyncMock(return_value=(3, 2))
            ),
            mock.patch.object(queue, 'set_status', mock.AsyncMock()) as ss,
        ):
            await queue._process_message(
                db,
                {'project_id': 'p1', 'org_slug': 'octo', 'requested_by': 'a'},
            )
        statuses = [c.kwargs['status'] for c in ss.await_args_list]
        self.assertEqual(['running', 'success'], statuses)
        success = ss.await_args_list[-1].kwargs
        self.assertEqual(3, success['commits'])
        self.assertEqual(2, success['tags'])

    async def test_unavailable_marks_failed_without_raising(self) -> None:
        db = mock.AsyncMock()
        with (
            mock.patch.object(
                queue,
                'run_sync',
                mock.AsyncMock(side_effect=CommitSyncUnavailable('nope')),
            ),
            mock.patch.object(queue, 'set_status', mock.AsyncMock()) as ss,
        ):
            await queue._process_message(db, {'project_id': 'p1'})
        self.assertEqual('failed', ss.await_args_list[-1].kwargs['status'])

    async def test_other_error_marks_failed_and_raises(self) -> None:
        db = mock.AsyncMock()
        with (
            mock.patch.object(
                queue,
                'run_sync',
                mock.AsyncMock(side_effect=RuntimeError('boom')),
            ),
            mock.patch.object(queue, 'set_status', mock.AsyncMock()) as ss,
        ):
            with self.assertRaises(RuntimeError):
                await queue._process_message(db, {'project_id': 'p1'})
        self.assertEqual('failed', ss.await_args_list[-1].kwargs['status'])

    async def test_missing_project_id_is_noop(self) -> None:
        db = mock.AsyncMock()
        with mock.patch.object(queue, 'set_status', mock.AsyncMock()) as ss:
            await queue._process_message(db, {})
        ss.assert_not_awaited()

    async def test_rate_limited_marks_queued_and_raises(self) -> None:
        db = mock.AsyncMock()
        with (
            mock.patch.object(
                queue,
                'run_sync',
                mock.AsyncMock(
                    side_effect=PluginRateLimited(retry_at=time.time() + 600)
                ),
            ),
            mock.patch.object(queue, 'set_status', mock.AsyncMock()) as ss,
        ):
            with self.assertRaises(PluginRateLimited):
                await queue._process_message(db, {'project_id': 'p1'})
        statuses = [c.kwargs['status'] for c in ss.await_args_list]
        # running -> queued (NOT failed); re-raised for the pause handler.
        self.assertEqual(['running', 'queued'], statuses)


class ConsumerTests(unittest.IsolatedAsyncioTestCase):
    async def test_xack_on_success(self) -> None:
        client = mock.AsyncMock()
        with mock.patch.object(queue, '_process_message', mock.AsyncMock()):
            await queue._handle_entries(
                client, [(b'1-0', {b'project_id': b'p1'})], mock.AsyncMock()
            )
        client.xack.assert_awaited_once()

    async def test_no_xack_on_exception(self) -> None:
        client = mock.AsyncMock()
        with mock.patch.object(
            queue,
            '_process_message',
            mock.AsyncMock(side_effect=RuntimeError('boom')),
        ):
            await queue._handle_entries(
                client, [(b'1-0', {b'project_id': b'p1'})], mock.AsyncMock()
            )
        client.xack.assert_not_called()

    async def test_dlq_after_max_deliveries(self) -> None:
        client = mock.AsyncMock()
        client.xpending_range = mock.AsyncMock(
            return_value=[{'times_delivered': queue.MAX_DELIVERIES}]
        )
        result = await queue._maybe_dead_letter(
            client, b'1-0', {'project_id': 'p1'}
        )
        self.assertTrue(result)
        client.xadd.assert_awaited_once()
        client.xack.assert_awaited_once()

    async def test_rate_limited_pauses_without_ack_or_dlq(self) -> None:
        client = mock.AsyncMock()
        retry_at = time.time() + 1800
        with mock.patch.object(
            queue,
            '_process_message',
            mock.AsyncMock(side_effect=PluginRateLimited(retry_at=retry_at)),
        ):
            await queue._handle_entries(
                client,
                [
                    (b'1-0', {b'project_id': b'p1'}),
                    (b'2-0', {b'project_id': b'p2'}),
                ],
                mock.AsyncMock(),
            )
        # Pause marker set; message left pending (no ack), not dead-lettered,
        # and the batch stopped before the sibling job was attempted.
        client.set.assert_awaited_once()
        self.assertEqual(queue.PAUSE_KEY, client.set.await_args.args[0])
        client.xack.assert_not_called()
        client.xadd.assert_not_called()


class PauseTests(unittest.IsolatedAsyncioTestCase):
    async def test_paused_remaining_future_and_past(self) -> None:
        client = mock.AsyncMock()
        client.get = mock.AsyncMock(
            return_value=str(time.time() + 120).encode()
        )
        self.assertGreater(await queue._paused_remaining(client), 60)
        client.get = mock.AsyncMock(return_value=str(time.time() - 5).encode())
        self.assertEqual(0.0, await queue._paused_remaining(client))

    async def test_paused_remaining_absent_is_zero(self) -> None:
        client = mock.AsyncMock()
        client.get = mock.AsyncMock(return_value=None)
        self.assertEqual(0.0, await queue._paused_remaining(client))

    async def test_consume_loop_honors_pause_and_skips_read(self) -> None:
        client = mock.AsyncMock()
        client.get = mock.AsyncMock(
            return_value=str(time.time() + 300).encode()
        )
        stop = mock.Mock()
        # Paused this tick -> sleep, then stop the loop before any read.
        stop.is_set = mock.Mock(side_effect=[False, True])
        with mock.patch.object(queue.asyncio, 'sleep', mock.AsyncMock()):
            await queue.consume_commit_sync(
                client, mock.AsyncMock(), consumer='w', stop=stop
            )
        client.xreadgroup.assert_not_called()
        client.xautoclaim.assert_not_called()
