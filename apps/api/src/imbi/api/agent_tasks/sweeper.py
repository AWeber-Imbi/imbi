"""The archive sweep of the agent task log (ADR 0020).

Task writes publish their events and ledger rows after the commit, and a
failed publish is only logged. This sweep is what makes ClickHouse
complete: for each task whose log is not archived, it compares Postgres
with ClickHouse and publishes again every event and ledger row that
ClickHouse does not have. It replaces a transactional outbox.

For a closed task that ClickHouse holds completely, the sweep deletes the
Postgres events and sets ``log_archived_at``. After that, the events
endpoint reads the log from ClickHouse.

Before that, the sweep closes each open session with no heartbeat in
:data:`STALE_SESSION_SECONDS`, with the reason ``heartbeat_lost``, as a
harness would. A harness that dies would otherwise hold its place under
the agent's ``max_concurrent_tasks`` for ever.

Postgres events have no gaps, so a task's ``last_seq`` is both the number
of its events and the highest ``seq``. ClickHouse is complete for a task
when it has ``last_seq`` distinct seqs and the highest is ``last_seq``.

It runs like the other API sweepers (see
:mod:`imbi.api.documents.read_sweeper`): every instance runs the loop,
and a Valkey lock gives each round to one of them.
"""

import asyncio
import dataclasses
import itertools
import logging

from imbi.api.agent_tasks import log
from imbi.api.agent_tasks import store as task_store
from imbi.common import valkey

LOGGER = logging.getLogger(__name__)

#: How often the sweep runs.
SWEEP_INTERVAL_SECONDS = 60
_SWEEP_LOCK_KEY = 'imbi:agent-tasks:log-sweeper'
#: A session with no heartbeat for this long has lost its harness.
STALE_SESSION_SECONDS = 5 * 60
_SYSTEM = task_store.Actor('system', 'imbi', 'harness')


@dataclasses.dataclass
class SweepResult:
    """What one round did."""

    closed_sessions: int = 0
    republished_events: int = 0
    republished_reports: int = 0
    archived: int = 0


async def _try_sweep_lock() -> bool:
    """Claim this round for one instance.

    A second sweep does no harm: a republished row collapses in
    ClickHouse and an archive is idempotent. The lock only prevents
    wasted work, so when Valkey is not available, every instance sweeps.
    """
    try:
        client = valkey.get_client()
        return bool(
            await client.set(
                _SWEEP_LOCK_KEY, '1', nx=True, ex=SWEEP_INTERVAL_SECONDS
            )
        )
    except Exception:  # noqa: BLE001
        LOGGER.debug('agent task sweep lock acquire failed', exc_info=True)
        return True


async def _sweep_task(
    store: task_store.TaskStore,
    task: task_store.Row,
    events: dict[str, tuple[int, int]],
    reports: dict[str, int],
    result: SweepResult,
) -> None:
    """Republish what ClickHouse does not have of one task, and archive
    the task when it is closed and ClickHouse holds all of it."""
    complete = True
    last_seq = task['last_seq']
    if events.get(str(task['id'])) != (last_seq, last_seq):
        complete = False
        stored = await log.stored_seqs(task)
        missing = [seq for seq in range(1, last_seq + 1) if seq not in stored]
        rows = await store.events_with_seqs(task['id'], missing)
        await log.publish(task, rows)
        result.republished_events += len(rows)
    if reports.get(str(task['id']), 0) != task['ledger_count']:
        complete = False
        stored_reports = await log.stored_reports(task)
        rows = [
            row
            for row in await store.ledger(task['id'])
            if str(row['id']) not in stored_reports
        ]
        await log.publish(task, [], rows)
        result.republished_reports += len(rows)
    if (
        complete
        and task['status'] == 'closed'
        and await store.archive(task['id'], last_seq)
    ):
        result.archived += 1


async def sweep_once(store: task_store.TaskStore) -> SweepResult:
    """Close stale sessions, republish what ClickHouse does not have,
    and archive complete tasks."""
    result = SweepResult()
    if not await _try_sweep_lock():
        return result
    for session in await store.stale_sessions(STALE_SESSION_SECONDS):
        try:
            await store.close_session(
                session['organization_id'],
                session['short_id'],
                session['id'],
                'heartbeat_lost',
                _SYSTEM,
                stale_seconds=STALE_SESSION_SECONDS,
            )
        except (
            task_store.TaskNotFound,
            task_store.TaskClosed,
            task_store.SessionNotFound,
        ):
            continue
        result.closed_sessions += 1
    tasks = await store.unarchived()
    for organization_id, group in itertools.groupby(
        tasks, key=lambda task: task['organization_id']
    ):
        batch = list(group)
        ids = [str(task['id']) for task in batch]
        events = await log.event_counts(organization_id, ids)
        reports = await log.usage_counts(organization_id, ids)
        for task in batch:
            try:
                await _sweep_task(store, task, events, reports, result)
            except Exception:  # noqa: BLE001
                LOGGER.warning(
                    'Agent task sweep failed for task %s',
                    task['id'],
                    exc_info=True,
                )
    if result != SweepResult():
        LOGGER.info('Agent task sweep: %s', result)
    return result


async def run_sweeper(
    store: task_store.TaskStore, *, stop: asyncio.Event
) -> None:
    """Sweep every :data:`SWEEP_INTERVAL_SECONDS` until ``stop`` is set.

    The loop waits before its first sweep, so a ClickHouse outage is
    not in the startup path.
    """
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=SWEEP_INTERVAL_SECONDS)
        except TimeoutError:
            pass
        else:
            return
        try:
            await sweep_once(store)
        except Exception:  # noqa: BLE001
            LOGGER.warning('Agent task sweep failed', exc_info=True)
