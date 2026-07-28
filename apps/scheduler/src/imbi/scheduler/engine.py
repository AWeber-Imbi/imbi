"""The trigger loop.

Each tick claims every task that has come due, fires them concurrently under a
ceiling, and records what happened. Claiming is what makes this safe to run on
several replicas at once — see ``Tasks.claim_due`` and ADR 0001.

Waking is a bounded sleep plus a ``LISTEN`` on the task channel. A missed
notification costs latency, not a missed run, because the bounded sleep
re-polls regardless.
"""

import asyncio
import collections
import contextlib
import datetime
import logging
import typing
import uuid

from psycopg import sql

from imbi.scheduler import executor as executor_module
from imbi.scheduler import models, runs, settings, store
from imbi.scheduler.store import tasks as tasks_repo

LOGGER = logging.getLogger(__name__)


class Engine:
    """Claims due tasks and fires them."""

    def __init__(
        self,
        tasks: tasks_repo.Tasks,
        executor: executor_module.Executor,
        config: settings.Scheduler | None = None,
    ) -> None:
        self._tasks = tasks
        self._executor = executor
        self._settings = config or settings.Scheduler()
        self._semaphore = asyncio.Semaphore(self._settings.max_concurrent_runs)
        self._in_flight: collections.Counter[uuid.UUID] = collections.Counter()
        self._wake = asyncio.Event()

    async def tick(
        self, now: datetime.datetime | None = None
    ) -> list[runs.Run]:
        """Claim and fire everything due, returning the recorded runs."""
        moment = now or datetime.datetime.now(datetime.UTC)
        claimed = await self._tasks.claim_due(moment)
        if not claimed:
            return []
        LOGGER.debug('Claimed %d due task(s)', len(claimed))
        results = await asyncio.gather(
            *(self._fire(task, moment) for task in claimed)
        )
        return [run for run in results if run is not None]

    async def _fire(
        self, task: models.Task, moment: datetime.datetime
    ) -> runs.Run | None:
        """Fire one claimed task, recording whatever happens."""
        if self._at_instance_limit(task):
            return await self._decline(
                task,
                moment,
                f'{self._in_flight[task.id]} instance(s) already running, '
                'max_running_instances already reached',
            )
        misfire = self._misfire_reason(task, moment)
        if misfire is not None:
            return await self._decline(task, moment, misfire)
        self._in_flight[task.id] += 1
        try:
            async with self._semaphore:
                run = await self._executor.execute(task, moment)
        except Exception:
            # A crash here would silently drop the firing, so record it as a
            # failure rather than letting the gather propagate.
            LOGGER.exception('Unhandled error firing %s', task.slug)
            run = runs.finish(
                runs.start(task, moment),
                'failed',
                runs.Outcome(
                    error_type='internal',
                    error_message='unhandled scheduler error',
                ),
            )
        finally:
            self._in_flight[task.id] -= 1
            if not self._in_flight[task.id]:
                del self._in_flight[task.id]
        return await self._record(task, run)

    async def _decline(
        self, task: models.Task, moment: datetime.datetime, reason: str
    ) -> runs.Run:
        """Record a firing the engine itself declined to make.

        The outcome counters are deliberately left untouched. The
        consecutive-skip streak exists to disable a task whose principal can
        no longer be established (PRD 9.1.4); an instance-limit or misfire
        skip says nothing about the task's identity, so counting it would
        permanently disable a task whose only fault is a slow target or a
        scheduler that was down. Resetting the streak would be just as wrong —
        it would let an unresolvable task escape the limit by misfiring — so
        neither counter moves.
        """
        LOGGER.info('Skipping %s: %s', task.slug, reason)
        run = runs.skipped(task, moment, reason)
        await runs.record(run)
        return run

    def _at_instance_limit(self, task: models.Task) -> bool:
        return self._in_flight[task.id] >= task.execution.max_running_instances

    def _misfire_reason(
        self, task: models.Task, moment: datetime.datetime
    ) -> str | None:
        """Return why a firing is too late to run, if it is.

        Coalescing needs no separate handling: one claim per due timestamp
        means a task that fell far behind fires once on catch-up rather than
        once per interval it missed.
        """
        grace = task.execution.misfire_grace_time
        if grace is None or task.next_run_at is None:
            return None
        lateness = (moment - task.next_run_at).total_seconds()
        if lateness > grace:
            return f'misfired: {int(lateness)}s late, grace is {grace}s'
        return None

    async def _record(self, task: models.Task, run: runs.Run) -> runs.Run:
        """Persist a run and update the task's outcome counters.

        The two writes hit different databases and do not depend on each
        other, so they go out together — the run stays counted against the
        concurrency ceiling until both land.
        """
        await asyncio.gather(
            runs.record(run),
            self._tasks.record_outcome(
                task.id,
                skipped=run.state == 'skipped',
                no_effect=run.state == 'no_effect',
            ),
        )
        await self._apply_limits(task, run)
        return run

    async def _apply_limits(self, task: models.Task, run: runs.Run) -> None:
        """Disable or flag a task whose streak has hit a limit.

        A run of skips means the task can no longer establish its principal,
        so it is disabled and its owner notified. A run of `no_effect` is
        flagged but not disabled: intermittent no-ops are legitimate when the
        gateway's rules are conditional.
        """
        if run.state == 'skipped':
            streak = task.consecutive_skips + 1
            if streak >= self._settings.consecutive_skips_limit:
                LOGGER.warning(
                    'Disabling %s after %d consecutive skipped runs',
                    task.slug,
                    streak,
                )
                await self._tasks.set_enabled(task.slug, enabled=False)
        elif run.state == 'no_effect':
            streak = task.consecutive_no_effect + 1
            if streak >= self._settings.consecutive_no_effect_limit:
                LOGGER.warning(
                    '%s has had %d consecutive runs with no effect; the '
                    'target webhook may not match anything',
                    task.slug,
                    streak,
                )

    async def run_forever(self, stop: asyncio.Event) -> None:
        """Tick until `stop` is set."""
        LOGGER.info('Scheduler engine started')
        while not stop.is_set():
            # Cleared before the tick, not before the sleep: a notification
            # that lands *during* a tick must survive into the next sleep, or
            # a task mutation would wait out a full poll interval.
            self._wake.clear()
            try:
                await self.tick()
            except Exception:
                LOGGER.exception('Tick failed; continuing')
            await self._sleep(stop)
        LOGGER.info('Scheduler engine stopped')

    async def _sleep(self, stop: asyncio.Event) -> None:
        """Wait until the next firing is due, a change lands, or stop."""
        delay = await self._delay()
        if self._wake.is_set():
            return
        waiters = [
            asyncio.create_task(stop.wait()),
            asyncio.create_task(self._wake.wait()),
        ]
        try:
            await asyncio.wait(
                waiters, timeout=delay, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for waiter in waiters:
                waiter.cancel()

    async def _delay(self) -> float:
        """Return how long to sleep, bounded by the poll interval."""
        ceiling = float(self._settings.poll_interval)
        due = await self._tasks.next_due_at()
        if due is None:
            return ceiling
        remaining = (due - datetime.datetime.now(datetime.UTC)).total_seconds()
        return max(0.0, min(ceiling, remaining))

    def notify(self) -> None:
        """Wake the loop early, e.g. after a task mutation."""
        self._wake.set()

    @contextlib.asynccontextmanager
    async def listening(
        self, pool: store.Pool
    ) -> 'typing.AsyncGenerator[None]':
        """Wake the loop on ``NOTIFY`` for the duration of the block."""
        listener = asyncio.create_task(self._listen(pool))
        try:
            yield
        finally:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener

    async def _listen(self, pool: store.Pool) -> None:
        """Set the wake event whenever a task changes."""
        try:
            async with pool.connection() as conn:
                await conn.set_autocommit(True)
                await conn.execute(
                    sql.SQL('LISTEN {channel}').format(
                        channel=sql.Identifier(tasks_repo.NOTIFY_CHANNEL)
                    )
                )
                async for _ in conn.notifies():
                    self.notify()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Losing the listener degrades latency, not correctness: the
            # bounded sleep keeps polling.
            LOGGER.exception('Task change listener stopped')
