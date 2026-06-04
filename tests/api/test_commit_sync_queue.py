"""Tests for the commit/tag-sync queue."""

from __future__ import annotations

import unittest
from unittest import mock

from imbi_api.commit_sync import queue
from imbi_api.commit_sync.service import CommitSyncUnavailable


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
