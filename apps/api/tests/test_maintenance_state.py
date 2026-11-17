"""Tests for the maintenance run-state primitives."""

from __future__ import annotations

import typing
import unittest
import uuid
from unittest import mock

from valkey import asyncio as valkey_asyncio

from imbi.api.maintenance import log, state
from imbi.common import settings as imbi_settings


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
        'hdel',
        'hlen',
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
    async def test_leases_the_popped_id(self) -> None:
        client = mock.AsyncMock()
        client.eval = mock.AsyncMock(return_value=b'p1')
        with mock.patch.object(state.time, 'time', return_value=10_000.0):
            claim = await state.checkout(client, 'op')
        self.assertEqual(('p1', '10000.0'), claim)
        args = client.eval.await_args.args
        self.assertEqual('10000.0', args[4])
        self.assertEqual(
            (
                2,
                'imbi:maintenance:op:pending',
                'imbi:maintenance:op:processing',
            ),
            args[1:4],
        )

    async def test_returns_none_when_drained(self) -> None:
        client = mock.AsyncMock()
        client.eval = mock.AsyncMock(return_value=None)
        self.assertIsNone(await state.checkout(client, 'op'))


class RecordOutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_while_the_lease_is_held(self) -> None:
        client = mock.AsyncMock()
        client.eval = mock.AsyncMock(return_value=1)
        self.assertTrue(
            await state.record_outcome(client, 'op', 'p1', 't1', 'succeeded')
        )
        args = client.eval.await_args.args
        self.assertEqual(('p1', 'succeeded', ''), args[5:8])
        self.assertEqual('t1', args[9])

    async def test_reports_a_reclaimed_lease(self) -> None:
        client = mock.AsyncMock()
        client.eval = mock.AsyncMock(return_value=0)
        self.assertFalse(
            await state.record_outcome(client, 'op', 'p1', 't1', 'succeeded')
        )

    async def test_failure_detail_is_truncated(self) -> None:
        client = mock.AsyncMock()
        client.eval = mock.AsyncMock(return_value=1)
        await state.record_outcome(
            client, 'op', 'p1', 't1', 'failed', 'x' * 600
        )
        args = client.eval.await_args.args
        self.assertEqual(state.MAX_ERROR_LEN, len(args[7]))
        self.assertEqual(str(state.MAX_FAILURE_DETAILS), args[8])


class RequeueTests(unittest.IsolatedAsyncioTestCase):
    async def test_moves_the_id_back_to_pending(self) -> None:
        client = mock.AsyncMock()
        client.eval = mock.AsyncMock(return_value=1)
        self.assertTrue(await state.requeue(client, 'op', 'p1', 't1'))
        self.assertEqual(
            (
                2,
                'imbi:maintenance:op:pending',
                'imbi:maintenance:op:processing',
                'p1',
                't1',
            ),
            client.eval.await_args.args[1:],
        )

    async def test_skips_a_claim_it_no_longer_holds(self) -> None:
        client = mock.AsyncMock()
        client.eval = mock.AsyncMock(return_value=0)
        self.assertFalse(await state.requeue(client, 'op', 'p1', 't1'))


class ClaimFencingValkeyTests(unittest.IsolatedAsyncioTestCase):
    """Run the claim-token Lua scripts against the real test Valkey."""

    async def asyncSetUp(self) -> None:
        self.client = valkey_asyncio.Valkey.from_url(
            str(imbi_settings.Valkey().url)
        )
        self.slug = f'test-{uuid.uuid4().hex}'
        await state.start_run(self.client, self.slug, ['p1'], 'alice')

    async def asyncTearDown(self) -> None:
        await self.client.delete(
            *(
                state._key(self.slug, part)
                for part in (
                    'lock',
                    'pending',
                    'processing',
                    'run',
                    'failures',
                )
            )
        )
        await self.client.aclose()

    async def _replaced_claim(self) -> tuple[str, str]:
        """Check p1 out with an expired lease, reclaim, and check out again."""
        with mock.patch.object(state.time, 'time', return_value=1_000.0):
            old = await state.checkout(self.client, self.slug)
        self.assertEqual(('p1', '1000.0'), old)
        self.assertEqual(1, await state.reclaim(self.client, self.slug))
        new = await state.checkout(self.client, self.slug)
        assert new is not None
        return '1000.0', new[1]

    async def _holder(self) -> object:
        return await self.client.hget(
            state._key(self.slug, 'processing'), 'p1'
        )

    async def test_former_holder_cannot_record_an_outcome(self) -> None:
        old, new = await self._replaced_claim()
        self.assertFalse(
            await state.record_outcome(
                self.client, self.slug, 'p1', old, 'succeeded'
            )
        )
        self.assertEqual(new.encode(), await self._holder())
        self.assertTrue(
            await state.record_outcome(
                self.client, self.slug, 'p1', new, 'succeeded'
            )
        )
        status = await state.read_status(self.client, self.slug)
        self.assertEqual(1, status.succeeded)
        self.assertEqual(0, status.in_flight)

    async def test_former_holder_cannot_requeue(self) -> None:
        old, new = await self._replaced_claim()
        self.assertFalse(
            await state.requeue(self.client, self.slug, 'p1', old)
        )
        self.assertEqual(new.encode(), await self._holder())
        status = await state.read_status(self.client, self.slug)
        self.assertEqual(0, status.remaining)

    async def test_requeue_after_a_committed_outcome_is_a_no_op(
        self,
    ) -> None:
        # The outcome committed but its reply was lost, so the worker
        # falls back to requeueing with the same token.
        claim = await state.checkout(self.client, self.slug)
        assert claim is not None
        self.assertTrue(
            await state.record_outcome(
                self.client, self.slug, 'p1', claim[1], 'succeeded'
            )
        )
        self.assertFalse(
            await state.requeue(self.client, self.slug, 'p1', claim[1])
        )
        status = await state.read_status(self.client, self.slug)
        self.assertEqual(1, status.succeeded)
        self.assertEqual(0, status.remaining)
        self.assertEqual(0, status.in_flight)


class ReclaimTests(unittest.IsolatedAsyncioTestCase):
    async def test_reclaims_leases_older_than_the_ttl(self) -> None:
        client = mock.AsyncMock()
        client.eval = mock.AsyncMock(return_value=2)
        with mock.patch.object(state.time, 'time', return_value=10_000.0):
            self.assertEqual(2, await state.reclaim(client, 'op'))
        args = client.eval.await_args.args
        self.assertEqual(str(10_000.0 - state.LEASE_SECONDS), args[4])


class MaybeFinalizeTests(unittest.IsolatedAsyncioTestCase):
    async def test_finalizes_when_drained(self) -> None:
        client, _ = _client_with_pipeline([0, b'0', b'running'])
        with mock.patch.object(state, '_finish', mock.AsyncMock()) as finish:
            result = await state.maybe_finalize(client, 'op')
        self.assertTrue(result)
        client.pipeline.assert_called_once_with(transaction=True)
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


class FinishTests(unittest.IsolatedAsyncioTestCase):
    #: hset, delete (1 = this instance removed the lock), expire x3
    WON: typing.ClassVar[list[int]] = [1, 1, 1, 1, 1]
    LOST: typing.ClassVar[list[int]] = [1, 0, 1, 1, 1]

    async def test_run_row_carries_the_final_counters(self) -> None:
        client, _ = _client_with_pipeline(self.WON)
        status = state.RunStatus(
            state='completed',
            run_id='r1',
            total=5,
            succeeded=3,
            failed=1,
            skipped=1,
            started_by='alice',
        )
        with (
            mock.patch.object(
                state, 'read_status', mock.AsyncMock(return_value=status)
            ),
            mock.patch.object(log, 'record_run', mock.AsyncMock()) as record,
        ):
            await state._finish(client, 'op', 'completed')
        record.assert_awaited_once_with(
            'op',
            'r1',
            'completed',
            'alice',
            total=5,
            succeeded=3,
            failed=1,
            skipped=1,
            remaining=0,
            in_flight=0,
        )

    async def test_cancellation_records_what_it_left_unfinished(
        self,
    ) -> None:
        # A cancelled run finishes with items still in flight, so its
        # counters fall short of its attempt rows by design. Recording
        # the shortfall is what separates that from a logging gap.
        client, _ = _client_with_pipeline(self.WON)
        status = state.RunStatus(
            state='cancelled',
            total=10,
            succeeded=4,
            in_flight=2,
            remaining=4,
        )
        with (
            mock.patch.object(
                state, 'read_status', mock.AsyncMock(return_value=status)
            ),
            mock.patch.object(log, 'record_run', mock.AsyncMock()) as record,
        ):
            await state._finish(client, 'op', 'cancelled')
        self.assertEqual('cancelled', record.await_args.args[2])
        self.assertEqual(2, record.await_args.kwargs['in_flight'])
        self.assertEqual(4, record.await_args.kwargs['remaining'])

    async def test_only_the_lock_holder_writes_the_run_row(self) -> None:
        # Two instances can both pass maybe_finalize's drained check; the
        # one whose DEL removed nothing must not write a second run row.
        client, _ = _client_with_pipeline(self.LOST)
        with (
            mock.patch.object(
                state,
                'read_status',
                mock.AsyncMock(return_value=state.RunStatus()),
            ),
            mock.patch.object(log, 'record_run', mock.AsyncMock()) as record,
        ):
            await state._finish(client, 'op', 'completed')
        record.assert_not_awaited()

    async def test_a_status_read_failure_does_not_reach_the_caller(
        self,
    ) -> None:
        # The terminal state is already written and the lock is gone by
        # here; cancel_run must not report a failure for a cancellation
        # that applied.
        client, _ = _client_with_pipeline(self.WON)
        with (
            mock.patch.object(
                state,
                'read_status',
                mock.AsyncMock(side_effect=RuntimeError('valkey down')),
            ),
            mock.patch.object(log, 'record_run', mock.AsyncMock()) as record,
        ):
            await state._finish(client, 'op', 'cancelled')
        record.assert_not_awaited()


class ReadRunMetaTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_run_id_and_started_by(self) -> None:
        client = mock.AsyncMock()
        client.hmget = mock.AsyncMock(return_value=[b'r1', b'alice'])
        self.assertEqual(
            ('r1', 'alice'), await state.read_run_meta(client, 'op')
        )

    async def test_missing_values_are_empty(self) -> None:
        client = mock.AsyncMock()
        client.hmget = mock.AsyncMock(return_value=[None, None])
        self.assertEqual(('', ''), await state.read_run_meta(client, 'op'))


class ReadStatusTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _run_hash(run_state: bytes) -> dict[bytes, bytes]:
        return {
            b'run_id': b'r1',
            b'total': b'10',
            b'started_at': b'2026-07-13T00:00:00+00:00',
            b'started_by': b'alice',
            b'state': run_state,
            b'succeeded': b'4',
            b'failed': b'1',
            b'skipped': b'2',
        }

    async def test_running(self) -> None:
        client, _ = _client_with_pipeline(
            [1, self._run_hash(b'running'), 2, 1]
        )
        status = await state.read_status(client, 'op')
        self.assertEqual('running', status.state)
        self.assertEqual(10, status.total)
        self.assertEqual(2, status.remaining)
        self.assertEqual(1, status.in_flight)
        self.assertEqual(4, status.succeeded)
        self.assertEqual('alice', status.started_by)

    async def test_abandoned_when_running_without_lock(self) -> None:
        client, _ = _client_with_pipeline(
            [0, self._run_hash(b'running'), 2, 1]
        )
        status = await state.read_status(client, 'op')
        self.assertEqual('abandoned', status.state)

    async def test_idle_when_no_run_hash(self) -> None:
        client, _ = _client_with_pipeline(
            [0, typing.cast('dict[bytes, bytes]', {}), 0, 0]
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
