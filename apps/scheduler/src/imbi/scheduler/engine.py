"""The trigger loop.

Each tick claims every task that has come due, fires them concurrently under a
ceiling, and records what happened. Claiming is what makes this safe to run on
several replicas at once — see ``Tasks.claim_due`` and ADR 0001. Ticks overlap:
the loop spawns each one and keeps polling, so a slow target delays its own
task rather than every other task's.

Waking is a bounded sleep plus a ``LISTEN`` on the task channel. A missed
notification costs latency, not a missed run, because the bounded sleep
re-polls regardless.
"""

import asyncio
import contextlib
import datetime
import logging
import uuid
from collections import abc

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
        self._wake = asyncio.Event()
        # Runs this replica is executing, by run_id. A cancel request arrives
        # on every replica; only the one holding the run has something to
        # cancel, and this is how it knows.
        self._in_flight: dict[str, asyncio.Task[runs.Run]] = {}
        # Runs this replica cancelled on purpose. Without it, `_execute` could
        # not tell a requested cancellation from the loop being torn down or
        # the caller going away, and would report either as "cancelled".
        self._cancelling: set[str] = set()

    async def tick(
        self, now: datetime.datetime | None = None
    ) -> list[runs.Run]:
        """Claim and fire everything due, returning the recorded runs."""
        moment = now or datetime.datetime.now(datetime.UTC)
        claimed = await self._tasks.claim_due(moment)
        if not claimed:
            return []
        LOGGER.debug('Claimed %d due task(s)', len(claimed))
        # `return_exceptions` is not optional here. `_execute` catches its own
        # failures, but the lease calls and the ClickHouse write in `_record`
        # do not, and a bare `gather` propagating one of those would cancel
        # every sibling firing in the same tick — including ones whose request
        # is already on the wire, whose effect would then land with no run row
        # ever written for it.
        results = await asyncio.gather(
            *(self._fire(task, moment) for task in claimed),
            return_exceptions=True,
        )
        fired: list[runs.Run] = []
        for task, result in zip(claimed, results, strict=True):
            if isinstance(result, BaseException):
                LOGGER.error(
                    'Unhandled error firing %s', task.slug, exc_info=result
                )
            elif result is not None:
                fired.append(result)
        return fired

    async def _fire(
        self, task: models.Task, moment: datetime.datetime
    ) -> runs.Run | None:
        """Fire one claimed task, recording whatever happens."""
        misfire = self._misfire_reason(task, moment)
        if misfire is not None:
            return await self._decline(task, moment, misfire)
        return await self._fire_under_lease(task, moment)

    async def run_now(self, task: models.Task) -> runs.Run:
        """Fire `task` immediately, as ``POST /tasks/{slug}/run`` asks.

        The misfire check is skipped and only that: an on-demand run is by
        definition on time, but it is still a real firing, so it takes an
        execution slot, counts against this process's concurrency ceiling,
        resolves identity, and lands in history like any other.
        """
        run = await self._fire_under_lease(
            task, datetime.datetime.now(datetime.UTC)
        )
        if run is None:  # pragma: no cover - the lease path always records
            raise RuntimeError('on-demand run produced no record')
        return run

    async def dry_run(self, task: models.Task) -> executor_module.DryRun:
        """Report what firing `task` would do, without firing it.

        No lease and no semaphore: nothing is executed, so nothing needs a
        slot, and a dry run must stay available while every slot is busy --
        that is exactly when an operator wants it.
        """
        return await self._executor.dry_run(
            task, datetime.datetime.now(datetime.UTC)
        )

    async def _fire_under_lease(
        self, task: models.Task, moment: datetime.datetime
    ) -> runs.Run | None:
        """Take a slot, execute, and record, whatever the outcome.

        The run_id is minted here rather than inside the executor because the
        lease row carries it: a cancel request has to be able to name a
        firing before that firing has written anything.
        """
        run_id = uuid.uuid4()
        lease = await self._tasks.acquire_lease(
            task.id,
            run_id=run_id,
            limit=task.execution.max_running_instances,
            ttl=self._lease_ttl(task),
        )
        if lease is None:
            # Two causes since the existence check landed, and they send an
            # operator to different places: a saturated ceiling is a live
            # concurrency question, while a vanished task means the firing
            # raced a delete and there is nothing to investigate.
            reason = (
                'max_running_instances already reached'
                if await self._tasks.get_by_id(task.id) is not None
                else 'the task was deleted before the firing could start'
            )
            return await self._decline(task, moment, reason)
        try:
            run = await self._execute(task, moment, run_id)
        finally:
            await self._tasks.release_lease(lease)
        return await self._record(task, run)

    async def _execute(
        self,
        task: models.Task,
        moment: datetime.datetime,
        run_id: uuid.UUID,
    ) -> runs.Run:
        """Run the firing as a cancellable task, and classify how it ended."""
        if await self._tasks.cancel_requested(run_id):
            # Cancelled between taking the lease and starting: the NOTIFY had
            # nothing to find in `_in_flight` yet, so catch it here.
            return self._cancelled_run(task, moment, run_id, started=False)
        key = str(run_id)
        async with self._semaphore:
            # Checked again after the slot is granted, not only before. A run
            # can sit queued here for as long as the concurrency ceiling is
            # saturated, and a cancel arriving in that window finds nothing in
            # `_in_flight` to interrupt, so the gate above has already passed.
            if await self._tasks.cancel_requested(run_id):
                return self._cancelled_run(task, moment, run_id, started=False)
            pending = asyncio.create_task(
                self._executor.execute(task, moment, run_id=run_id)
            )
            self._in_flight[key] = pending
            try:
                return await pending
            except asyncio.CancelledError:
                if key not in self._cancelling:
                    # Not a cancel request: the loop is being torn down, or
                    # whoever awaited this went away. Swallowing it would
                    # report a phantom cancellation and break the caller's
                    # cancellation, so it propagates.
                    raise
                LOGGER.info('Run %s cancelled while firing %s', key, task.slug)
                return self._cancelled_run(task, moment, run_id, started=True)
            except Exception:
                # A crash here would silently drop the firing, so record it as
                # a failure rather than letting the gather propagate.
                LOGGER.exception('Unhandled error firing %s', task.slug)
                return runs.finish(
                    runs.start(task, moment, run_id=run_id),
                    'failed',
                    runs.Outcome(
                        error_type='internal',
                        error_message='unhandled scheduler error',
                    ),
                )
            finally:
                self._in_flight.pop(key, None)
                self._cancelling.discard(key)

    def _cancelled_run(
        self,
        task: models.Task,
        moment: datetime.datetime,
        run_id: uuid.UUID,
        *,
        started: bool,
    ) -> runs.Run:
        """Return the terminal record for a cancelled firing.

        The message distinguishes the two cases because they differ in what
        the operator still has to check. Cancelling before the call means
        nothing happened. Cancelling during it means the request was already
        on the wire: the target may have acted and the response was simply
        never read, so claiming nothing happened would be a lie.
        """
        message = (
            'cancelled after the request was sent; the target may have '
            'already acted on it'
            if started
            else 'cancelled before the request was sent'
        )
        return runs.finish(
            runs.start(task, moment, run_id=run_id),
            'cancelled',
            runs.Outcome(error_type='cancelled', error_message=message),
        )

    async def cancel(self, run_id: str) -> bool:
        """Ask for `run_id` to stop, wherever it is running.

        Reports whether a lease existed to cancel. The local task is not
        cancelled here: ``request_cancel`` notifies every replica including
        this one, so the listener does it, and cancellation takes one path
        whether the caller happened to reach the replica running the job.
        """
        return await self._tasks.request_cancel(run_id)

    def _cancel_local(self, run_id: str) -> None:
        """Cancel `run_id` if this replica is the one running it.

        Marked as ours before it is cancelled, so ``_execute`` can tell this
        apart from a cancellation it did not ask for.
        """
        pending = self._in_flight.get(run_id)
        if pending is None:
            return
        LOGGER.info('Cancelling in-flight run %s', run_id)
        self._cancelling.add(run_id)
        pending.cancel()

    def _lease_ttl(self, task: models.Task) -> datetime.timedelta:
        """Return how long a slot stays reserved without being released.

        An upper bound on one firing rather than a guess: every attempt can
        spend the full timeout, and the backoff between them is bounded by the
        same. Only a replica that dies mid-run ever reaches it.
        """
        attempts = task.execution.retries + 1
        return datetime.timedelta(
            seconds=task.execution.timeout * (2 * attempts) + 60
        )

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

        Neither write is allowed to propagate. The firing has already happened
        against the real target by the time this runs, so raising here would
        turn a delivered action into a 500 from ``POST /tasks/{slug}/run`` and
        lose the `Run` the caller needs. A failed `runs.record` also leaves the
        executor's `running` row unsuperseded, which is exactly the case an
        operator has to be told about rather than have hidden by a traceback.
        """
        results = await asyncio.gather(
            runs.record(run),
            self._tasks.record_outcome(
                task.id,
                skipped=run.state == 'skipped',
                no_effect=run.state == 'no_effect',
            ),
            return_exceptions=True,
        )
        for label, result in zip(
            ('run history', 'outcome counters'), results, strict=True
        ):
            if isinstance(result, BaseException):
                LOGGER.error(
                    'Failed to persist %s for run %s of %s',
                    label,
                    run.run_id,
                    task.slug,
                    exc_info=result,
                )
        await self._apply_limits(task, run)
        return run

    async def _apply_limits(self, task: models.Task, run: runs.Run) -> None:
        """Disable or flag a task whose streak has hit a limit.

        A run of skips means the task can no longer establish its principal,
        so it is disabled. A run of `no_effect` is
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
        ticks: set[asyncio.Task[list[runs.Run]]] = set()
        while not stop.is_set():
            # Cleared before the tick, not before the sleep: a notification
            # that lands *during* a tick must survive into the next sleep, or
            # a task mutation would wait out a full poll interval.
            self._wake.clear()
            # Spawned rather than awaited. A tick awaits every firing it
            # claimed, so one target sitting on its full timeout and retry
            # budget would otherwise hold up every other task's firing for
            # minutes. Overlapping ticks are safe: claiming advances
            # `next_run_at` inside its own transaction, and the instance limit
            # is a lease in Postgres rather than a property of one tick.
            tick = asyncio.create_task(self._guarded_tick())
            ticks.add(tick)
            tick.add_done_callback(ticks.discard)
            await self._sleep(stop)
        if ticks:
            LOGGER.info('Waiting on %d tick(s) in flight', len(ticks))
            await asyncio.gather(*ticks, return_exceptions=True)
        LOGGER.info('Scheduler engine stopped')

    async def _guarded_tick(self) -> list[runs.Run]:
        """Tick, keeping a failure from taking the loop down with it."""
        try:
            return await self.tick()
        except Exception:
            LOGGER.exception('Tick failed; continuing')
            return []

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
            # Awaited, not just cancelled: a cancelled task that is never
            # retrieved leaves the loop to report "Task was destroyed but it
            # is pending" at shutdown, which reads as a scheduler bug in the
            # logs of an otherwise clean stop.
            await asyncio.gather(*waiters, return_exceptions=True)

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
    async def listening(self, pool: store.Pool) -> 'abc.AsyncGenerator[None]':
        """Listen for task changes and cancel requests within the block.

        A connection each rather than two ``LISTEN``s on one: cancels carry a
        payload and mean "stop this run", so they must not queue behind the
        task channel's backlog. It costs two of the pool's connections for the
        process's life.
        """
        watchers = [
            asyncio.create_task(
                self._subscribe(
                    pool,
                    tasks_repo.NOTIFY_CHANNEL,
                    lambda _: self.notify(),
                    # Losing this one degrades latency, not correctness: the
                    # bounded sleep keeps polling.
                    'Task change listener stopped',
                )
            ),
            asyncio.create_task(
                self._subscribe(
                    pool,
                    tasks_repo.CANCEL_CHANNEL,
                    self._cancel_local,
                    # Losing this one costs correctness: a cancel would be
                    # recorded and never enforced.
                    'Cancel listener stopped; cancel requests reaching this '
                    'replica will be recorded but not enforced',
                )
            ),
        ]
        try:
            yield
        finally:
            for watcher in watchers:
                watcher.cancel()
            for watcher in watchers:
                with contextlib.suppress(asyncio.CancelledError):
                    await watcher

    async def _subscribe(
        self,
        pool: store.Pool,
        channel: str,
        handler: 'abc.Callable[[str], None]',
        failure_message: str,
    ) -> None:
        """Call `handler` with each payload delivered on `channel`.

        Failures are logged and swallowed rather than raised: losing a
        listener degrades the scheduler, but taking the whole process down
        over it would stop far more work than it saves.
        """
        try:
            async with pool.connection() as conn:
                await conn.set_autocommit(True)
                await conn.execute(
                    sql.SQL('LISTEN {channel}').format(
                        channel=sql.Identifier(channel)
                    )
                )
                async for notice in conn.notifies():
                    handler(notice.payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception('%s', failure_message)
