"""Tests for the maintenance run-state primitives."""

from __future__ import annotations

import typing
import unittest
from unittest import mock

from imbi_api.maintenance import state


def _client_with_pipeline(
    results: list[object] | None = None,
) -> tuple[mock.AsyncMock, mock.Mock]:
    """A mock client whose pipeline queues commands synchronously."""
    client = mock.AsyncMock()
    pipe = mock.MagicMock()
    for name in (
        'delete',
        'sadd',
        'hset',
        'expire',
        'hincrby',
        'scard',
        'hget',
        'hgetall',
        'exists',
    ):
        setattr(pipe, name, mock.Mock())
    pipe.execute = mock.AsyncMock(return_value=results or [])
    pipe.__aenter__ = mock.AsyncMock(return_value=pipe)
    pipe.__aexit__ = mock.AsyncMock(return_value=False)
    client.pipeline = mock.Mock(return_value=pipe)
    return client, pipe


class StartRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_acquires_lock_and_seeds_pending(self) -> None:
        client, pipe = _client_with_pipeline()
        client.set = mock.AsyncMock(return_value=True)
        status = await state.start_run(client, 'op', ['p1', 'p2'], 'alice')
        assert status is not None
        self.assertEqual('running', status.state)
        self.assertEqual(2, status.total)
        self.assertEqual('alice', status.started_by)
        args, kwargs = client.set.await_args
        self.assertEqual('imbi:maintenance:op:lock', args[0])
        self.assertTrue(kwargs['nx'])
        self.assertEqual(state.LOCK_TTL_SECONDS, kwargs['ex'])
        sadd_args = pipe.sadd.call_args
        self.assertEqual(
            ('imbi:maintenance:op:pending', 'p1', 'p2'), sadd_args.args
        )
        mapping = pipe.hset.call_args.kwargs['mapping']
        self.assertEqual(2, mapping['total'])
        self.assertEqual('running', mapping['state'])

    async def test_returns_none_when_lock_held(self) -> None:
        client, pipe = _client_with_pipeline()
        client.set = mock.AsyncMock(return_value=None)
        result = await state.start_run(client, 'op', ['p1'], 'alice')
        self.assertIsNone(result)
        pipe.execute.assert_not_awaited()

    async def test_empty_project_set_finalizes_immediately(self) -> None:
        client, _ = _client_with_pipeline()
        client.set = mock.AsyncMock(return_value=True)
        completed = state.RunStatus(state='completed', total=0)
        with (
            mock.patch.object(
                state, 'maybe_finalize', mock.AsyncMock()
            ) as finalize,
            mock.patch.object(
                state,
                'read_status',
                mock.AsyncMock(return_value=completed),
            ),
        ):
            status = await state.start_run(client, 'op', [], 'alice')
        assert status is not None
        self.assertEqual('completed', status.state)
        self.assertEqual(0, status.total)
        finalize.assert_awaited_once_with(client, 'op')


class CheckoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_pops_and_marks_in_flight(self) -> None:
        client = mock.AsyncMock()
        client.spop = mock.AsyncMock(return_value=b'p1')
        client.hincrby = mock.AsyncMock()
        result = await state.checkout(client, 'op')
        self.assertEqual('p1', result)
        client.hincrby.assert_awaited_once_with(
            'imbi:maintenance:op:run', 'in_flight', 1
        )

    async def test_returns_none_when_drained(self) -> None:
        client = mock.AsyncMock()
        client.spop = mock.AsyncMock(return_value=None)
        client.hincrby = mock.AsyncMock()
        self.assertIsNone(await state.checkout(client, 'op'))
        client.hincrby.assert_not_awaited()


class RecordOutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_moves_counters(self) -> None:
        client, pipe = _client_with_pipeline()
        await state.record_outcome(client, 'op', 'p1', 'succeeded')
        calls = pipe.hincrby.call_args_list
        self.assertEqual(
            ('imbi:maintenance:op:run', 'in_flight', -1), calls[0].args
        )
        self.assertEqual(
            ('imbi:maintenance:op:run', 'succeeded', 1), calls[1].args
        )
        pipe.hset.assert_not_called()

    async def test_failure_records_truncated_detail(self) -> None:
        client, pipe = _client_with_pipeline()
        client.hlen = mock.AsyncMock(return_value=0)
        await state.record_outcome(client, 'op', 'p1', 'failed', 'x' * 600)
        args = pipe.hset.call_args.args
        self.assertEqual('imbi:maintenance:op:failures', args[0])
        self.assertEqual('p1', args[1])
        self.assertEqual(state.MAX_ERROR_LEN, len(args[2]))

    async def test_failure_detail_capped(self) -> None:
        client, pipe = _client_with_pipeline()
        client.hlen = mock.AsyncMock(return_value=state.MAX_FAILURE_DETAILS)
        await state.record_outcome(client, 'op', 'p1', 'failed', 'boom')
        pipe.hset.assert_not_called()
        # The counter still moves even without the detail.
        self.assertEqual(
            ('imbi:maintenance:op:run', 'failed', 1),
            pipe.hincrby.call_args_list[1].args,
        )


class RequeueTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_id_and_decrements(self) -> None:
        client, pipe = _client_with_pipeline()
        await state.requeue(client, 'op', 'p1')
        self.assertEqual(
            ('imbi:maintenance:op:pending', 'p1'), pipe.sadd.call_args.args
        )
        self.assertEqual(
            ('imbi:maintenance:op:run', 'in_flight', -1),
            pipe.hincrby.call_args.args,
        )


class MaybeFinalizeTests(unittest.IsolatedAsyncioTestCase):
    async def test_finalizes_when_drained(self) -> None:
        client, _ = _client_with_pipeline([0, b'0', b'running'])
        with mock.patch.object(state, '_finish', mock.AsyncMock()) as finish:
            result = await state.maybe_finalize(client, 'op')
        self.assertTrue(result)
        finish.assert_awaited_once_with(client, 'op', 'completed')

    async def test_skips_when_pending_remain(self) -> None:
        client, _ = _client_with_pipeline([3, b'0', b'running'])
        with mock.patch.object(state, '_finish', mock.AsyncMock()) as finish:
            self.assertFalse(await state.maybe_finalize(client, 'op'))
        finish.assert_not_awaited()

    async def test_skips_when_in_flight(self) -> None:
        client, _ = _client_with_pipeline([0, b'2', b'running'])
        with mock.patch.object(state, '_finish', mock.AsyncMock()) as finish:
            self.assertFalse(await state.maybe_finalize(client, 'op'))
        finish.assert_not_awaited()

    async def test_skips_when_not_running(self) -> None:
        client, _ = _client_with_pipeline([0, b'0', b'completed'])
        with mock.patch.object(state, '_finish', mock.AsyncMock()) as finish:
            self.assertFalse(await state.maybe_finalize(client, 'op'))
        finish.assert_not_awaited()


class CancelRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancels_running(self) -> None:
        client, _ = _client_with_pipeline()
        client.exists = mock.AsyncMock(return_value=1)
        client.hget = mock.AsyncMock(return_value=b'running')
        client.delete = mock.AsyncMock()
        with mock.patch.object(state, '_finish', mock.AsyncMock()) as finish:
            self.assertTrue(await state.cancel_run(client, 'op'))
        client.delete.assert_awaited_once_with('imbi:maintenance:op:pending')
        finish.assert_awaited_once_with(client, 'op', 'cancelled')

    async def test_returns_false_when_idle(self) -> None:
        client, _ = _client_with_pipeline()
        client.exists = mock.AsyncMock(return_value=0)
        self.assertFalse(await state.cancel_run(client, 'op'))


class ReadStatusTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _run_hash(run_state: bytes) -> dict[bytes, bytes]:
        return {
            b'run_id': b'r1',
            b'total': b'10',
            b'started_at': b'2026-07-13T00:00:00+00:00',
            b'started_by': b'alice',
            b'state': run_state,
            b'in_flight': b'1',
            b'succeeded': b'4',
            b'failed': b'1',
            b'skipped': b'2',
        }

    async def test_running(self) -> None:
        client, _ = _client_with_pipeline([1, self._run_hash(b'running'), 2])
        status = await state.read_status(client, 'op')
        self.assertEqual('running', status.state)
        self.assertEqual(10, status.total)
        self.assertEqual(2, status.remaining)
        self.assertEqual(4, status.succeeded)
        self.assertEqual('alice', status.started_by)

    async def test_abandoned_when_running_without_lock(self) -> None:
        client, _ = _client_with_pipeline([0, self._run_hash(b'running'), 2])
        status = await state.read_status(client, 'op')
        self.assertEqual('abandoned', status.state)

    async def test_idle_when_no_run_hash(self) -> None:
        client, _ = _client_with_pipeline(
            [0, typing.cast('dict[bytes, bytes]', {}), 0]
        )
        status = await state.read_status(client, 'op')
        self.assertEqual('idle', status.state)


class ReadFailuresTests(unittest.IsolatedAsyncioTestCase):
    async def test_decodes_entries(self) -> None:
        client = mock.AsyncMock()
        client.hgetall = mock.AsyncMock(return_value={b'p1': b'boom'})
        self.assertEqual(
            {'p1': 'boom'}, await state.read_failures(client, 'op')
        )
