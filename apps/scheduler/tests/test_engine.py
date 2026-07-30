"""Engine tests.

The executor is replaced with a stub so these exercise scheduling decisions —
claiming, misfire, instance limits, counter streaks — rather than HTTP.
"""

import asyncio
import datetime
import unittest.mock
import uuid

from apps.scheduler.tests import helpers, test_store
from imbi.common import clickhouse
from imbi.scheduler import (
    engine,
    lifespans,
    models,
    runs,
    settings,
    store,
)
from imbi.scheduler import (
    executor as executor_module,
)
from imbi.scheduler.store import tasks as tasks_repo


def utc(*args: int) -> datetime.datetime:
    return datetime.datetime(*args, tzinfo=datetime.UTC)


class StubExecutor:
    """Records what it was asked to fire and returns a canned outcome."""

    def __init__(
        self,
        state: models.RunState = 'succeeded',
        *,
        delay: float = 0.0,
        raises: bool = False,
        delays: dict[str, float] | None = None,
    ) -> None:
        self.state = state
        self.delay = delay
        self.raises = raises
        #: Per-slug override of `delay`, for tests that need one firing in a
        #: tick to still be running while another has already finished.
        self.delays = delays or {}
        self.fired: list[str] = []

    async def execute(
        self,
        task: models.Task,
        fired_at: datetime.datetime,
        *,
        run_id: uuid.UUID | None = None,
        trace_id: str = '',
    ) -> runs.Run:
        self.fired.append(task.slug)
        delay = self.delays.get(task.slug, self.delay)
        if delay:
            await asyncio.sleep(delay)
        if self.raises:
            raise RuntimeError('boom')
        run = runs.start(task, fired_at, run_id=run_id, trace_id=trace_id)
        return runs.finish(run, self.state, runs.Outcome(http_status=202))

    async def dry_run(
        self, task: models.Task, fired_at: datetime.datetime
    ) -> executor_module.DryRun:
        del fired_at
        self.dry_ran = getattr(self, 'dry_ran', [])
        self.dry_ran.append(task.slug)
        return executor_module.DryRun(
            would_run=True, method='POST', url='https://api.test/x'
        )


class EngineTestCase(test_store.StoreTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.assertTrue(await clickhouse.initialize())
        await clickhouse.setup_schema()
        self.executor = StubExecutor()
        self.settings = settings.Scheduler(
            consecutive_skips_limit=3, consecutive_no_effect_limit=3
        )
        self.engine = engine.Engine(
            self.tasks,
            self.executor,  # type: ignore[arg-type]
            self.settings,
        )

    async def asyncTearDown(self) -> None:
        await clickhouse.aclose()
        await super().asyncTearDown()


class TickTests(EngineTestCase):
    async def test_fires_a_due_task(self) -> None:
        await self.tasks.create(
            helpers.build_task(next_run_at=utc(2026, 7, 28, 6))
        )
        fired = await self.engine.tick(utc(2026, 7, 28, 6, 0, 5))
        self.assertEqual(['nightly-recompute'], self.executor.fired)
        self.assertEqual(['succeeded'], [run.state for run in fired])

    async def test_nothing_due(self) -> None:
        await self.tasks.create(
            helpers.build_task(next_run_at=utc(2026, 7, 30, 6))
        )
        self.assertEqual([], await self.engine.tick(utc(2026, 7, 28, 6)))
        self.assertEqual([], self.executor.fired)

    async def test_fires_several_tasks_concurrently(self) -> None:
        for index in range(4):
            await self.tasks.create(
                helpers.build_task(
                    slug=f'task-{index}', next_run_at=utc(2026, 7, 28, 6)
                )
            )
        fired = await self.engine.tick(utc(2026, 7, 28, 6, 0, 5))
        self.assertEqual(4, len(fired))
        self.assertEqual(4, len(set(self.executor.fired)))

    async def test_records_the_run(self) -> None:
        task = await self.tasks.create(
            helpers.build_task(next_run_at=utc(2026, 7, 28, 6))
        )
        await self.engine.tick(utc(2026, 7, 28, 6, 0, 5))
        history = await runs.for_task(task.id)
        self.assertEqual(1, len(history))
        self.assertEqual('succeeded', history[0].state)

    async def test_a_recording_failure_does_not_cancel_siblings(self) -> None:
        # `_execute` catches its own failures, but `_record` — the ClickHouse
        # write — does not. Propagating that out of the tick's `gather` would
        # cancel every sibling firing, including ones whose request is already
        # on the wire, so the effect would land with no run row for it.
        for index in range(4):
            await self.tasks.create(
                helpers.build_task(
                    slug=f'task-{index}', next_run_at=utc(2026, 7, 28, 6)
                )
            )
        self.executor.delays = {f'task-{index}': 0.25 for index in range(1, 4)}
        original = self.engine._record

        async def record(task: models.Task, run: runs.Run) -> runs.Run:
            if task.slug == 'task-0':
                raise RuntimeError('clickhouse is down')
            return await original(task, run)

        with unittest.mock.patch.object(self.engine, '_record', record):
            fired = await self.engine.tick(utc(2026, 7, 28, 6, 0, 5))
        self.assertEqual(
            {'task-1', 'task-2', 'task-3'}, {run.task_slug for run in fired}
        )
        # And every sibling ran to completion rather than being cancelled
        # part-way through its outbound call.
        self.assertEqual(
            {'task-0', 'task-1', 'task-2', 'task-3'}, set(self.executor.fired)
        )
        self.assertEqual({'succeeded'}, {run.state for run in fired})

    async def test_an_executor_crash_is_recorded_as_failure(self) -> None:
        self.executor.raises = True
        await self.tasks.create(
            helpers.build_task(next_run_at=utc(2026, 7, 28, 6))
        )
        fired = await self.engine.tick(utc(2026, 7, 28, 6, 0, 5))
        self.assertEqual(['failed'], [run.state for run in fired])
        self.assertEqual('internal', fired[0].error_type)


class MisfireTests(EngineTestCase):
    async def test_late_firing_within_grace_still_runs(self) -> None:
        await self.tasks.create(
            helpers.build_task(next_run_at=utc(2026, 7, 28, 6))
        )
        fired = await self.engine.tick(utc(2026, 7, 28, 6, 4))
        self.assertEqual(['succeeded'], [run.state for run in fired])

    async def test_beyond_grace_is_skipped(self) -> None:
        await self.tasks.create(
            helpers.build_task(next_run_at=utc(2026, 7, 28, 6))
        )
        fired = await self.engine.tick(utc(2026, 7, 28, 7))
        self.assertEqual(['skipped'], [run.state for run in fired])
        self.assertIn('misfired', fired[0].error_message)
        self.assertEqual([], self.executor.fired)

    async def test_disabled_grace_never_misfires(self) -> None:
        await self.tasks.create(
            helpers.build_task(
                next_run_at=utc(2026, 7, 28, 6),
                execution=models.ExecutionPolicy(misfire_grace_time=None),
            )
        )
        fired = await self.engine.tick(utc(2026, 7, 29, 6))
        self.assertEqual(['succeeded'], [run.state for run in fired])

    async def test_a_long_gap_fires_once_not_once_per_interval(self) -> None:
        # Coalescing falls out of claiming: one claim per due timestamp.
        await self.tasks.create(
            helpers.build_task(
                trigger={'kind': 'interval', 'minutes': 1},
                next_run_at=utc(2026, 7, 28, 6),
                execution=models.ExecutionPolicy(misfire_grace_time=None),
            )
        )
        await self.engine.tick(utc(2026, 7, 28, 8))
        self.assertEqual(1, len(self.executor.fired))


class InstanceLimitTests(EngineTestCase):
    async def test_the_limit_holds_across_replicas(self) -> None:
        # The reason the limit is a lease in Postgres rather than a counter in
        # the process: a second replica claims the next firing while the first
        # is still executing the previous one.
        self.executor.delay = 0.3
        task = await self.tasks.create(
            helpers.build_task(
                trigger={'kind': 'interval', 'seconds': 1},
                next_run_at=utc(2026, 7, 28, 6),
                execution=models.ExecutionPolicy(
                    max_running_instances=1, misfire_grace_time=None
                ),
            )
        )
        other = engine.Engine(
            tasks_repo.Tasks(self.pool, schema=test_store.TEST_SCHEMA),
            StubExecutor(),  # type: ignore[arg-type]
            self.settings,
        )
        first = asyncio.create_task(self.engine.tick(utc(2026, 7, 28, 6)))
        await asyncio.sleep(0.05)
        stored = await self.tasks.get(task.slug)
        assert stored is not None
        await self.tasks.reschedule(stored)
        second = await other.tick(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
        )
        await first
        self.assertEqual(['skipped'], [run.state for run in second])
        self.assertEqual([], other._executor.fired)  # type: ignore[attr-defined]

    async def test_second_overlapping_run_is_skipped(self) -> None:
        self.executor.delay = 0.2
        await self.tasks.create(
            helpers.build_task(
                trigger={'kind': 'interval', 'seconds': 1},
                next_run_at=utc(2026, 7, 28, 6),
                execution=models.ExecutionPolicy(
                    max_running_instances=1, misfire_grace_time=None
                ),
            )
        )
        first = asyncio.create_task(self.engine.tick(utc(2026, 7, 28, 6)))
        await asyncio.sleep(0.05)
        stored = await self.tasks.get('nightly-recompute')
        assert stored is not None
        await self.tasks.reschedule(stored)
        second = await self.engine.tick(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
        )
        await first
        self.assertEqual(['skipped'], [run.state for run in second])

    async def test_the_limit_skip_does_not_count_toward_disabling(
        self,
    ) -> None:
        # A target slower than its interval would otherwise disable itself
        # after `consecutive_skips_limit` firings.
        self.executor.delay = 0.2
        task = await self.tasks.create(
            helpers.build_task(
                trigger={'kind': 'interval', 'seconds': 1},
                next_run_at=utc(2026, 7, 28, 6),
                consecutive_skips=2,
                execution=models.ExecutionPolicy(
                    max_running_instances=1, misfire_grace_time=None
                ),
            )
        )
        first = asyncio.create_task(self.engine.tick(utc(2026, 7, 28, 6)))
        await asyncio.sleep(0.05)
        stored = await self.tasks.get(task.slug)
        assert stored is not None
        await self.tasks.reschedule(stored)
        await self.engine.tick(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
        )
        await first
        stored = await self.tasks.get(task.slug)
        assert stored is not None
        self.assertTrue(stored.enabled)


class StreakTests(EngineTestCase):
    async def test_repeated_skips_disable_the_task(self) -> None:
        # A skip from the executor is an identity failure — the only kind the
        # limit is meant to catch.
        self.executor.state = 'skipped'
        task = helpers.build_task(
            next_run_at=utc(2026, 7, 28, 6), consecutive_skips=2
        )
        await self.tasks.create(task)
        await self.engine.tick(utc(2026, 7, 28, 6, 0, 5))
        stored = await self.tasks.get(task.slug)
        assert stored is not None
        self.assertFalse(stored.enabled)

    async def test_skips_below_the_limit_leave_it_enabled(self) -> None:
        self.executor.state = 'skipped'
        task = helpers.build_task(
            next_run_at=utc(2026, 7, 28, 6), consecutive_skips=0
        )
        await self.tasks.create(task)
        await self.engine.tick(utc(2026, 7, 28, 6, 0, 5))
        stored = await self.tasks.get(task.slug)
        assert stored is not None
        self.assertTrue(stored.enabled)
        self.assertEqual(1, stored.consecutive_skips)

    async def test_a_misfire_does_not_count_toward_disabling(self) -> None:
        # A task whose window was missed — a scheduler restart, a slow
        # target — must not be disabled: its identity is not in question.
        task = helpers.build_task(
            next_run_at=utc(2026, 7, 28, 6), consecutive_skips=2
        )
        await self.tasks.create(task)
        fired = await self.engine.tick(utc(2026, 7, 28, 8))
        self.assertEqual(['skipped'], [run.state for run in fired])
        stored = await self.tasks.get(task.slug)
        assert stored is not None
        self.assertTrue(stored.enabled)
        self.assertEqual(2, stored.consecutive_skips)

    async def test_success_resets_the_skip_counter(self) -> None:
        task = helpers.build_task(
            next_run_at=utc(2026, 7, 28, 6), consecutive_skips=2
        )
        await self.tasks.create(task)
        await self.engine.tick(utc(2026, 7, 28, 6, 0, 5))
        stored = await self.tasks.get(task.slug)
        assert stored is not None
        self.assertEqual(0, stored.consecutive_skips)
        self.assertTrue(stored.enabled)

    async def test_no_effect_streak_does_not_disable(self) -> None:
        self.executor.state = 'no_effect'
        task = helpers.build_task(
            slug='synthetic-delivery',
            identity=None,
            target=models.GatewayTarget(webhook_id='w-1', payload={}),
            next_run_at=utc(2026, 7, 28, 6),
            consecutive_no_effect=2,
        )
        await self.tasks.create(task)
        await self.engine.tick(utc(2026, 7, 28, 6, 0, 5))
        stored = await self.tasks.get(task.slug)
        assert stored is not None
        self.assertTrue(stored.enabled)
        self.assertEqual(3, stored.consecutive_no_effect)


class SleepTests(EngineTestCase):
    async def test_delay_is_capped_by_the_poll_interval(self) -> None:
        await self.tasks.create(
            helpers.build_task(next_run_at=utc(2099, 1, 1))
        )
        self.assertEqual(
            float(self.settings.poll_interval), await self.engine._delay()
        )

    async def test_delay_with_no_tasks(self) -> None:
        self.assertEqual(
            float(self.settings.poll_interval), await self.engine._delay()
        )

    async def test_overdue_task_means_no_delay(self) -> None:
        await self.tasks.create(
            helpers.build_task(next_run_at=utc(2020, 1, 1))
        )
        self.assertEqual(0.0, await self.engine._delay())

    async def test_notify_wakes_the_sleep_early(self) -> None:
        stop = asyncio.Event()
        self.engine.notify()
        await asyncio.wait_for(self.engine._sleep(stop), timeout=1)

    async def test_stop_ends_run_forever(self) -> None:
        stop = asyncio.Event()
        loop = asyncio.create_task(self.engine.run_forever(stop))
        await asyncio.sleep(0.05)
        stop.set()
        self.engine.notify()
        await asyncio.wait_for(loop, timeout=2)

    async def test_a_slow_firing_does_not_hold_up_the_loop(self) -> None:
        # A target sitting on its timeout used to block every other task's
        # firing, because the loop awaited the whole tick before re-polling.
        stop = asyncio.Event()
        ticks = 0
        released = asyncio.Event()

        async def slow_tick(
            now: datetime.datetime | None = None,
        ) -> list[runs.Run]:
            nonlocal ticks
            ticks += 1
            self.engine.notify()
            if ticks >= 3:
                stop.set()
            await released.wait()
            return []

        self.engine.tick = slow_tick  # type: ignore[method-assign]
        self.engine.notify()
        loop = asyncio.create_task(self.engine.run_forever(stop))
        for _ in range(100):
            if ticks >= 3:
                break
            await asyncio.sleep(0.01)
        self.assertGreaterEqual(ticks, 3)
        released.set()
        await asyncio.wait_for(loop, timeout=2)

    async def test_the_loop_waits_for_ticks_in_flight_before_exiting(
        self,
    ) -> None:
        # Shutdown must not orphan a firing whose outcome is unrecorded.
        stop = asyncio.Event()
        finished = False

        async def slow_tick(
            now: datetime.datetime | None = None,
        ) -> list[runs.Run]:
            nonlocal finished
            stop.set()
            await asyncio.sleep(0.1)
            finished = True
            return []

        self.engine.tick = slow_tick  # type: ignore[method-assign]
        self.engine.notify()
        await asyncio.wait_for(self.engine.run_forever(stop), timeout=2)
        self.assertTrue(finished)

    async def test_a_failing_tick_does_not_stop_the_loop(self) -> None:
        stop = asyncio.Event()
        calls: list[int] = []

        async def failing_tick(
            now: datetime.datetime | None = None,
        ) -> list[runs.Run]:
            calls.append(1)
            # Wake immediately so the test does not wait out a poll interval.
            self.engine.notify()
            if len(calls) < 2:
                raise RuntimeError('transient')
            stop.set()
            return []

        self.engine.tick = failing_tick  # type: ignore[method-assign]
        self.engine.notify()
        await asyncio.wait_for(self.engine.run_forever(stop), timeout=2)
        self.assertGreaterEqual(len(calls), 2)


class WiringTests(EngineTestCase):
    """The hook is what turns the process into a scheduler."""

    async def test_the_hook_fires_a_due_task(self) -> None:
        await self.tasks.create(
            helpers.build_task(
                slug='synthetic-delivery',
                identity=None,
                target=models.GatewayTarget(webhook_id='w-1', payload={}),
                next_run_at=datetime.datetime.now(datetime.UTC),
                execution=models.ExecutionPolicy(
                    retries=0, misfire_grace_time=None
                ),
            )
        )
        stored = None
        async with store.store_lifespan(), lifespans.engine_hook() as instance:
            self.assertIsInstance(instance, engine.Engine)
            for _ in range(100):
                stored = await self.tasks.get('synthetic-delivery')
                assert stored is not None
                if stored.last_run_at is not None:
                    break
                await asyncio.sleep(0.05)
        assert stored is not None
        # The delivery itself fails — nothing is listening on the gateway
        # port — but the firing is what this proves.
        self.assertIsNotNone(stored.last_run_at)

    async def test_shutdown_drains_the_ticks_in_flight(self) -> None:
        # `stop.set()` and `notify()` only schedule the loop's waiters to
        # resume, so cancelling straight afterwards would always tear
        # `run_forever` out of its sleep before it reached the post-loop
        # drain — abandoning a firing whose outcome is unrecorded, and
        # closing the shared httpx client out from under it.
        drained = asyncio.Event()

        async def slow_tick(
            _self: engine.Engine, now: datetime.datetime | None = None
        ) -> list[runs.Run]:
            del now
            await asyncio.sleep(0.1)
            drained.set()
            return []

        with unittest.mock.patch.object(engine.Engine, 'tick', slow_tick):
            async with store.store_lifespan(), lifespans.engine_hook():
                await asyncio.sleep(0.02)
        self.assertTrue(drained.is_set())

    async def test_shutdown_cancels_a_loop_that_will_not_drain(self) -> None:
        # The graceful wait is bounded: a tick that never returns must not
        # hold the process open past its termination grace period.
        async def stuck_tick(
            _self: engine.Engine, now: datetime.datetime | None = None
        ) -> list[runs.Run]:
            del now
            await asyncio.Event().wait()
            return []

        with (
            unittest.mock.patch.object(engine.Engine, 'tick', stuck_tick),
            unittest.mock.patch.object(
                lifespans, 'SHUTDOWN_DRAIN_TIMEOUT', 0.05
            ),
        ):
            async with store.store_lifespan(), lifespans.engine_hook():
                await asyncio.sleep(0.02)


class ListenTests(EngineTestCase):
    async def test_a_task_mutation_wakes_the_engine(self) -> None:
        async with self.engine.listening(self.pool):
            await asyncio.sleep(0.1)
            await self.tasks.create(helpers.build_task())
            for _ in range(50):
                if self.engine._wake.is_set():
                    break
                await asyncio.sleep(0.05)
        self.assertTrue(self.engine._wake.is_set())
