"""Tests for the scoring recompute queue."""

from __future__ import annotations

import asyncio
import typing
import unittest
from unittest import mock

from imbi_api.scoring import queue as score_queue

if typing.TYPE_CHECKING:
    from imbi_common.scoring import models as sm


class EnqueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_xadds_when_debounce_acquired(self) -> None:
        client = mock.AsyncMock()
        client.set = mock.AsyncMock(return_value=True)
        client.xadd = mock.AsyncMock()
        result = await score_queue.enqueue_recompute(
            client, 'p1', 'attribute_change'
        )
        self.assertTrue(result)
        client.set.assert_awaited_once()
        client.xadd.assert_awaited_once()
        args, _kwargs = client.xadd.await_args
        self.assertEqual(args[0], score_queue.STREAM)
        self.assertEqual(args[1]['project_id'], 'p1')
        self.assertEqual(args[1]['reason'], 'attribute_change')

    async def test_enqueue_skips_when_debounced(self) -> None:
        client = mock.AsyncMock()
        client.set = mock.AsyncMock(return_value=None)
        client.xadd = mock.AsyncMock()
        result = await score_queue.enqueue_recompute(
            client, 'p1', 'attribute_change'
        )
        self.assertFalse(result)
        client.xadd.assert_not_called()


class ConsumerTests(unittest.IsolatedAsyncioTestCase):
    async def test_xack_on_success(self) -> None:
        client = mock.AsyncMock()
        client.xack = mock.AsyncMock()
        with mock.patch.object(
            score_queue, '_process_message', mock.AsyncMock()
        ):
            await score_queue._handle_entries(
                client,
                [(b'1-0', {b'project_id': b'p1'})],
                mock.AsyncMock(),
                mock.AsyncMock(),
            )
        client.xack.assert_awaited_once()

    async def test_no_xack_on_exception(self) -> None:
        client = mock.AsyncMock()
        client.xack = mock.AsyncMock()
        with mock.patch.object(
            score_queue,
            '_process_message',
            mock.AsyncMock(side_effect=RuntimeError('boom')),
        ):
            await score_queue._handle_entries(
                client,
                [(b'1-0', {b'project_id': b'p1'})],
                mock.AsyncMock(),
                mock.AsyncMock(),
            )
        client.xack.assert_not_called()

    async def test_dlq_after_max_deliveries(self) -> None:
        client = mock.AsyncMock()
        client.xpending_range = mock.AsyncMock(
            return_value=[{'times_delivered': 6}]
        )
        client.xadd = mock.AsyncMock()
        client.xack = mock.AsyncMock()
        result = await score_queue._maybe_dead_letter(
            client, b'1-0', {'project_id': 'p1'}
        )
        self.assertTrue(result)
        client.xadd.assert_awaited_once()
        client.xack.assert_awaited_once()

    async def test_dlq_skipped_below_threshold(self) -> None:
        client = mock.AsyncMock()
        client.xpending_range = mock.AsyncMock(
            return_value=[{'times_delivered': 1}]
        )
        client.xadd = mock.AsyncMock()
        client.xack = mock.AsyncMock()
        result = await score_queue._maybe_dead_letter(
            client, b'1-0', {'project_id': 'p1'}
        )
        self.assertFalse(result)

    async def test_dlq_skipped_when_empty_pending(self) -> None:
        client = mock.AsyncMock()
        client.xpending_range = mock.AsyncMock(return_value=[])
        result = await score_queue._maybe_dead_letter(
            client, b'1-0', {'project_id': 'p1'}
        )
        self.assertFalse(result)

    async def test_dlq_xpending_exception_returns_false(self) -> None:
        client = mock.AsyncMock()
        client.xpending_range = mock.AsyncMock(
            side_effect=RuntimeError('nope')
        )
        result = await score_queue._maybe_dead_letter(
            client, b'1-0', {'project_id': 'p1'}
        )
        self.assertFalse(result)

    async def test_dlq_tuple_entry_path(self) -> None:
        """Cover the tuple-based entry format from xpending_range."""
        client = mock.AsyncMock()
        # Simulate a tuple-based response: [msg_id, consumer, idle, deliveries]
        client.xpending_range = mock.AsyncMock(
            return_value=[(b'1-0', b'worker-0', 70000, 6)]
        )
        client.xadd = mock.AsyncMock()
        client.xack = mock.AsyncMock()
        result = await score_queue._maybe_dead_letter(
            client, b'1-0', {'project_id': 'p1'}
        )
        self.assertTrue(result)


class EnqueueNoneClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_none_client_returns_false(self) -> None:
        result = await score_queue.enqueue_recompute(
            None, 'p1', 'bulk_rescore'
        )
        self.assertFalse(result)

    async def test_enqueue_exception_returns_false(self) -> None:
        client = mock.AsyncMock()
        client.set = mock.AsyncMock(side_effect=RuntimeError('conn error'))
        result = await score_queue.enqueue_recompute(
            client, 'p1', 'attribute_change'
        )
        self.assertFalse(result)


class EnsureGroupTests(unittest.IsolatedAsyncioTestCase):
    async def test_busygroup_is_ignored(self) -> None:
        client = mock.AsyncMock()
        client.xgroup_create = mock.AsyncMock(
            side_effect=Exception('BUSYGROUP Consumer Group already exists')
        )
        await score_queue.ensure_group(client)  # should not raise

    async def test_other_error_is_logged(self) -> None:
        client = mock.AsyncMock()
        client.xgroup_create = mock.AsyncMock(
            side_effect=Exception('some other error')
        )
        with self.assertLogs('imbi_api.scoring.queue', level='WARNING'):
            await score_queue.ensure_group(client)


class ClaimStaleTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_entries_from_xautoclaim(self) -> None:
        client = mock.AsyncMock()
        entries = [(b'1-0', {b'project_id': b'p1'})]
        client.xautoclaim = mock.AsyncMock(return_value=['0-0', entries, []])
        result = await score_queue._claim_stale(client, 'worker-0')
        self.assertEqual(result, entries)

    async def test_returns_empty_on_exception(self) -> None:
        client = mock.AsyncMock()
        client.xautoclaim = mock.AsyncMock(side_effect=Exception('fail'))
        result = await score_queue._claim_stale(client, 'worker-0')
        self.assertEqual(result, [])

    async def test_returns_empty_when_result_malformed(self) -> None:
        client = mock.AsyncMock()
        client.xautoclaim = mock.AsyncMock(return_value=None)
        result = await score_queue._claim_stale(client, 'worker-0')
        self.assertEqual(result, [])

    async def test_returns_empty_when_msgs_not_list(self) -> None:
        client = mock.AsyncMock()
        # result[1] is not a list
        client.xautoclaim = mock.AsyncMock(return_value=['0-0', None, []])
        result = await score_queue._claim_stale(client, 'worker-0')
        self.assertEqual(result, [])


class HandleEntriesWithDlqTest(unittest.IsolatedAsyncioTestCase):
    async def test_dead_letter_prevents_processing(self) -> None:
        client = mock.AsyncMock()
        process = mock.AsyncMock()
        with mock.patch.object(
            score_queue,
            '_maybe_dead_letter',
            mock.AsyncMock(return_value=True),
        ):
            with mock.patch.object(score_queue, '_process_message', process):
                await score_queue._handle_entries(
                    client,
                    [(b'1-0', {b'project_id': b'p1'})],
                    mock.AsyncMock(),
                    mock.AsyncMock(),
                    check_dlq=True,
                )
        process.assert_not_called()


class ProcessMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_missing_project_id(self) -> None:
        db = mock.AsyncMock()
        ch = mock.AsyncMock()
        await score_queue._process_message(db, ch, {})
        db.match.assert_not_called()

    async def test_skips_when_project_not_found(self) -> None:
        db = mock.AsyncMock()
        db.match = mock.AsyncMock(return_value=[])
        ch = mock.AsyncMock()
        with self.assertLogs('imbi_api.scoring.queue', level='INFO'):
            await score_queue._process_message(
                db, ch, {'project_id': 'p1', 'reason': 'policy_change'}
            )

    async def test_computes_and_records_score(self) -> None:
        from imbi_common import models

        db = mock.AsyncMock()
        project = mock.MagicMock(spec=models.Project)
        project.score = 0.5
        db.match = mock.AsyncMock(return_value=[project])
        ch = mock.AsyncMock()
        with (
            mock.patch(
                'imbi_api.scoring.queue.compute_score',
                mock.AsyncMock(return_value=(0.8, None)),
            ),
            mock.patch(
                'imbi_api.scoring.queue.record_score_change',
                mock.AsyncMock(),
            ) as mock_record,
        ):
            await score_queue._process_message(
                db, ch, {'project_id': 'p1', 'reason': 'attribute_change'}
            )
            mock_record.assert_awaited_once()

    async def test_uses_zero_when_project_score_is_none(self) -> None:
        from imbi_common import models

        db = mock.AsyncMock()
        project = mock.MagicMock(spec=models.Project)
        project.score = None
        db.match = mock.AsyncMock(return_value=[project])
        ch = mock.AsyncMock()
        with (
            mock.patch(
                'imbi_api.scoring.queue.compute_score',
                mock.AsyncMock(return_value=(0.5, None)),
            ),
            mock.patch(
                'imbi_api.scoring.queue.record_score_change',
                mock.AsyncMock(),
            ) as mock_record,
        ):
            await score_queue._process_message(
                db, ch, {'project_id': 'p1', 'reason': 'attribute_change'}
            )
            _args, kwargs = mock_record.call_args
            # previous should have been 0.0 (default when score is None)
            self.assertEqual(
                kwargs.get('previous', _args[4] if len(_args) > 4 else None),
                0.0,
            )


class ConsumeRecomputeTests(unittest.IsolatedAsyncioTestCase):
    async def test_processes_messages_then_stops(self) -> None:
        client = mock.AsyncMock()
        client.xgroup_create = mock.AsyncMock(
            side_effect=Exception('BUSYGROUP Consumer Group already exists')
        )
        client.xautoclaim = mock.AsyncMock(return_value=['0-0', [], []])
        stop = asyncio.Event()

        # First xreadgroup call returns a message; second stops the loop
        call_count = 0

        async def xreadgroup_side_effect(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [[b'stream', [(b'1-0', {b'project_id': b'p1'})]]]
            stop.set()
            return []

        client.xreadgroup = mock.AsyncMock(side_effect=xreadgroup_side_effect)
        client.xack = mock.AsyncMock()

        with mock.patch.object(
            score_queue, '_process_message', mock.AsyncMock()
        ):
            await score_queue.consume_recompute(
                client,
                mock.AsyncMock(),
                mock.AsyncMock(),
                stop=stop,
            )

        client.xack.assert_awaited()

    async def test_handles_xreadgroup_exception(self) -> None:
        import asyncio

        client = mock.AsyncMock()
        client.xgroup_create = mock.AsyncMock(
            side_effect=Exception('BUSYGROUP Consumer Group already exists')
        )
        client.xautoclaim = mock.AsyncMock(return_value=['0-0', [], []])
        stop = asyncio.Event()
        call_count = 0

        async def xreadgroup_fail(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            stop.set()
            raise RuntimeError('xreadgroup failed')

        client.xreadgroup = mock.AsyncMock(side_effect=xreadgroup_fail)

        with self.assertLogs('imbi_api.scoring.queue', level='ERROR'):
            await score_queue.consume_recompute(
                client,
                mock.AsyncMock(),
                mock.AsyncMock(),
                stop=stop,
            )

    async def test_processes_stale_messages(self) -> None:
        import asyncio

        client = mock.AsyncMock()
        client.xgroup_create = mock.AsyncMock(
            side_effect=Exception('BUSYGROUP Consumer Group already exists')
        )
        stop = asyncio.Event()
        stale_entries = [(b'0-1', {b'project_id': b'stale'})]
        client.xautoclaim = mock.AsyncMock(
            return_value=['0-0', stale_entries, []]
        )
        client.xack = mock.AsyncMock()

        call_count = 0

        async def xreadgroup_side_effect(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            stop.set()
            return []

        client.xreadgroup = mock.AsyncMock(side_effect=xreadgroup_side_effect)

        with (
            mock.patch.object(
                score_queue,
                '_maybe_dead_letter',
                mock.AsyncMock(return_value=False),
            ),
            mock.patch.object(
                score_queue, '_process_message', mock.AsyncMock()
            ) as mock_proc,
        ):
            await score_queue.consume_recompute(
                client,
                mock.AsyncMock(),
                mock.AsyncMock(),
                stop=stop,
            )

        mock_proc.assert_awaited_once()


class AllProjectIdsTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_project_ids_no_filter(self) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'id': 'a1'}, {'id': 'b2'}])
        result = await score_queue.all_project_ids(db)
        self.assertEqual(result, ['a1', 'b2'])

    async def test_all_project_ids_with_type_filter(self) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'id': 'c3'}])
        result = await score_queue.all_project_ids(db, 'service')
        self.assertEqual(result, ['c3'])


class ProjectsOfTypeTest(unittest.IsolatedAsyncioTestCase):
    async def test_projects_of_type(self) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'id': 'p1'}, {'id': 'p2'}])
        result = await score_queue.projects_of_type(db, 'service')
        self.assertEqual(result, ['p1', 'p2'])


class AffectedProjectsTests(unittest.IsolatedAsyncioTestCase):
    def _policy(
        self,
        attribute_name: str,
        targets: list[str] | None = None,
    ) -> sm.AttributePolicy:
        from imbi_common.scoring import models as sm

        return sm.AttributePolicy(
            name='p',
            slug='p',
            attribute_name=attribute_name,
            weight=10,
            value_score_map={'py': 100},
            targets=targets or [],
        )

    async def test_unknown_attribute_returns_empty(self) -> None:
        from imbi_common import models

        class _Extended(models.Project):
            lang: str | None = None

        db = mock.AsyncMock()
        with mock.patch(
            'imbi_api.scoring.queue.blueprints.get_model',
            mock.AsyncMock(return_value=_Extended),
        ):
            result = await score_queue.affected_projects(
                db, self._policy('unknown_attr')
            )
        self.assertEqual([], result)
        db.execute.assert_not_called()

    async def test_no_targets_returns_all_projects(self) -> None:
        from imbi_common import models

        class _Extended(models.Project):
            lang: str | None = None

        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'id': 'p1'}, {'id': 'p2'}])
        with mock.patch(
            'imbi_api.scoring.queue.blueprints.get_model',
            mock.AsyncMock(return_value=_Extended),
        ):
            result = await score_queue.affected_projects(
                db, self._policy('lang')
            )
        self.assertEqual(['p1', 'p2'], result)

    async def test_targets_restricts_to_matching_types(self) -> None:
        from imbi_common import models

        class _Extended(models.Project):
            lang: str | None = None

        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'id': 'p3'}])
        with mock.patch(
            'imbi_api.scoring.queue.blueprints.get_model',
            mock.AsyncMock(return_value=_Extended),
        ):
            result = await score_queue.affected_projects(
                db, self._policy('lang', targets=['api'])
            )
        self.assertEqual(['p3'], result)
        args = db.execute.call_args.args
        self.assertIn('{slug}', args[0])

    async def test_targets_deduplicates_across_types(self) -> None:
        from imbi_common import models

        class _Extended(models.Project):
            lang: str | None = None

        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'id': 'p1'}])
        with mock.patch(
            'imbi_api.scoring.queue.blueprints.get_model',
            mock.AsyncMock(return_value=_Extended),
        ):
            result = await score_queue.affected_projects(
                db, self._policy('lang', targets=['api', 'service'])
            )
        self.assertEqual(['p1'], result)

    async def test_link_presence_skips_attribute_check(self) -> None:
        from imbi_common.scoring import models as sm

        policy = sm.LinkPresencePolicy(
            name='has-source',
            slug='has-source',
            link_slug='source-code',
            weight=10,
        )
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'id': 'p1'}])
        # blueprints.get_model is not consulted for link_presence policies.
        with mock.patch(
            'imbi_api.scoring.queue.blueprints.get_model',
            mock.AsyncMock(side_effect=AssertionError('should not be called')),
        ):
            result = await score_queue.affected_projects(db, policy)
        self.assertEqual(['p1'], result)

    async def test_condition_skips_attribute_check(self) -> None:
        from imbi_common.scoring import models as sm

        policy = sm.ConditionPolicy.model_validate(
            {
                'name': 'no-deprecated-deps',
                'slug': 'no-deprecated-deps',
                'weight': 10,
                'condition': {
                    'relationship': {
                        'quantifier': 'none',
                        'where': {
                            'attribute': 'deprecated',
                            'op': 'eq',
                            'value': True,
                        },
                    }
                },
            }
        )
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'id': 'p1'}])
        with mock.patch(
            'imbi_api.scoring.queue.blueprints.get_model',
            mock.AsyncMock(side_effect=AssertionError('should not be called')),
        ):
            result = await score_queue.affected_projects(db, policy)
        self.assertEqual(['p1'], result)


class DependentCascadeTests(unittest.IsolatedAsyncioTestCase):
    async def test_condition_policies_exist_true(self) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'id': 'sp1'}])
        self.assertTrue(await score_queue.condition_policies_exist(db))

    async def test_condition_policies_exist_false(self) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[])
        self.assertFalse(await score_queue.condition_policies_exist(db))

    async def test_dependent_project_ids(self) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'id': 'b1'}, {'id': 'c2'}])
        result = await score_queue.dependent_project_ids(db, 'a0')
        self.assertEqual(['b1', 'c2'], result)

    async def test_enqueue_dependents_none_client(self) -> None:
        db = mock.AsyncMock()
        result = await score_queue.enqueue_dependents(None, db, 'a0')
        self.assertEqual(0, result)
        db.execute.assert_not_called()

    async def test_enqueue_dependents_skips_when_no_condition_policy(
        self,
    ) -> None:
        client = mock.AsyncMock()
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[])  # no condition policies
        result = await score_queue.enqueue_dependents(client, db, 'a0')
        self.assertEqual(0, result)
        # Only the existence check ran; no dependents query.
        self.assertEqual(1, db.execute.call_count)

    async def test_enqueue_dependents_enqueues_dependents(self) -> None:
        client = mock.AsyncMock()
        db = mock.AsyncMock()
        # 1st execute: condition policy exists; 2nd: dependents.
        db.execute = mock.AsyncMock(
            side_effect=[[{'id': 'sp1'}], [{'id': 'b1'}, {'id': 'c2'}]]
        )
        with mock.patch.object(
            score_queue,
            'enqueue_recompute_bulk',
            mock.AsyncMock(return_value=2),
        ) as bulk:
            result = await score_queue.enqueue_dependents(client, db, 'a0')
        self.assertEqual(2, result)
        bulk.assert_awaited_once_with(
            client, ['b1', 'c2'], 'dependency_change'
        )


class DailyTickTests(unittest.IsolatedAsyncioTestCase):
    async def test_acquires_lock_and_enqueues_all(self) -> None:
        import datetime

        client = mock.AsyncMock()
        client.set = mock.AsyncMock(return_value=True)
        client.xadd = mock.AsyncMock()
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'id': 'p1'}, {'id': 'p2'}])
        await score_queue._try_daily_tick(
            client, db, datetime.date(2026, 5, 12)
        )
        # Daily-tick SET + per-project debounce SETs.
        self.assertEqual(3, client.set.await_count)
        self.assertEqual(2, client.xadd.await_count)

    async def test_skips_when_lock_held(self) -> None:
        import datetime

        client = mock.AsyncMock()
        client.set = mock.AsyncMock(return_value=None)
        client.xadd = mock.AsyncMock()
        db = mock.AsyncMock()
        await score_queue._try_daily_tick(
            client, db, datetime.date(2026, 5, 12)
        )
        client.xadd.assert_not_called()
        db.execute.assert_not_called()

    async def test_lock_failure_swallowed(self) -> None:
        import datetime

        client = mock.AsyncMock()
        client.set = mock.AsyncMock(side_effect=RuntimeError('valkey down'))
        client.xadd = mock.AsyncMock()
        db = mock.AsyncMock()
        await score_queue._try_daily_tick(
            client, db, datetime.date(2026, 5, 12)
        )
        client.xadd.assert_not_called()

    async def test_run_daily_tick_honors_hour_threshold(self) -> None:
        import datetime

        client = mock.AsyncMock()
        client.set = mock.AsyncMock(return_value=True)
        client.xadd = mock.AsyncMock()
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[])
        stop = asyncio.Event()
        early = datetime.datetime(2026, 5, 12, 3, 0, tzinfo=datetime.UTC)

        async def _fire_then_stop() -> None:
            await asyncio.sleep(0.05)
            stop.set()

        # Before the threshold (3:00 < hour_utc=6) we should not call set.
        await asyncio.gather(
            score_queue.run_daily_tick(
                client,
                db,
                hour_utc=6,
                poll_seconds=0.01,
                stop=stop,
                clock=lambda: early,
            ),
            _fire_then_stop(),
        )
        client.set.assert_not_called()

    async def test_run_daily_tick_fires_after_threshold(self) -> None:
        import datetime

        # Daily-tick lock returns True the first time, then None — the
        # second iteration must observe the held lock.
        set_calls: list[bool | None] = []

        async def _fake_set(
            key: str, *_args: object, **_kwargs: object
        ) -> bool | None:
            if key.startswith(score_queue.DAILY_TICK_KEY_PREFIX):
                acquired = not set_calls
                set_calls.append(acquired)
                return acquired
            return True  # debounce SET acquires

        client = mock.AsyncMock()
        client.set = mock.AsyncMock(side_effect=_fake_set)
        client.xadd = mock.AsyncMock()
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'id': 'p1'}])
        stop = asyncio.Event()
        late = datetime.datetime(2026, 5, 12, 7, 0, tzinfo=datetime.UTC)

        async def _fire_then_stop() -> None:
            await asyncio.sleep(0.05)
            stop.set()

        await asyncio.gather(
            score_queue.run_daily_tick(
                client,
                db,
                hour_utc=6,
                poll_seconds=0.01,
                stop=stop,
                clock=lambda: late,
            ),
            _fire_then_stop(),
        )
        # Project enumerated exactly once.
        self.assertEqual(1, db.execute.await_count)
        # xadd fired for the single project.
        self.assertEqual(1, client.xadd.await_count)
