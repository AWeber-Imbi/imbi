"""The archive sweep of the agent task log (ADR 0020).

Task writes publish their events and ledger rows after the commit, and a
failed publish is only logged. This sweep is what makes ClickHouse
complete: for each task whose log is not archived, it compares Postgres
with ClickHouse and publishes again every event and ledger row that
ClickHouse does not have. It replaces a transactional outbox.

For a closed task that ClickHouse holds completely, the sweep deletes the
Postgres events and sets ``log_archived_at``. After that, the events
endpoint reads the log from ClickHouse.

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
from imbi.api.agent_tasks.store import TaskStore
from imbi.common import valkey

LOGGER = logging.getLogger(__name__)

#: How often the sweep runs.
SWEEP_INTERVAL_SECONDS = 60
_SWEEP_LOCK_KEY = 'imbi:agent-tasks:log-sweeper'


@dataclasses.dataclass
class SweepResult:
    """What one round did."""

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


async def sweep_once(store: TaskStore) -> SweepResult:
    """Republish what ClickHouse does not have; archive complete tasks."""
    result = SweepResult()
    if not await _try_sweep_lock():
        return result
    tasks = await store.unarchived()
    for organization_id, group in itertools.groupby(
        tasks, key=lambda task: task['organization_id']
    ):
        batch = list(group)
        ids = [str(task['id']) for task in batch]
        events = await log.event_counts(organization_id, ids)
        reports = await log.usage_counts(organization_id, ids)
        for task in batch:
            complete = True
            last_seq = task['last_seq']
            if events.get(str(task['id'])) != (last_seq, last_seq):
                complete = False
                stored = await log.stored_seqs(task)
                missing = [
                    seq for seq in range(1, last_seq + 1) if seq not in stored
                ]
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
    if result != SweepResult():
        LOGGER.info('Agent task sweep: %s', result)
    return result


async def run_sweeper(store: TaskStore, *, stop: asyncio.Event) -> None:
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
