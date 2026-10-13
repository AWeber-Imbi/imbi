"""The archive sweep of the workflow run log (ADR 0021, Run history).

imbi-api and the engine publish run events and summary rows after the
commit, and a failed publish is only logged. This sweep is what makes
ClickHouse complete: for each run whose log is not archived, it compares
Postgres with ClickHouse and publishes again every event that ClickHouse
does not have, and the summary row when ClickHouse shows another status.

For a closed run that ClickHouse holds completely, with its terminal
summary row, the sweep deletes the run's events and step rows from
Postgres and sets ``log_archived_at``. The ``runs`` row stays. After
that, run detail reads the steps from ClickHouse.

Postgres events have no gaps, so ClickHouse is complete for a run when
it has ``last_seq`` distinct seqs, the lowest is 1, and the highest is
``last_seq``.

It runs like the agent task sweep (:mod:`imbi.api.agent_tasks.sweeper`):
every instance runs the loop, and a Valkey lock gives each round to one
of them.

The same round cancels the agent tasks whose agent step has ended
(:func:`cancel_orphan_agent_tasks`). The engine cancels a task when
its step or its run ends, but only as best effort; this is what makes
the cancel certain.
"""

import asyncio
import dataclasses
import itertools
import logging
import uuid

from imbi.api import agent_tasks
from imbi.api.workflows import runs as run_store
from imbi.common import valkey
from imbi.common.workflows import history, runtime

LOGGER = logging.getLogger(__name__)

#: How often the sweep runs.
SWEEP_INTERVAL_SECONDS = 60
_SWEEP_LOCK_KEY = 'imbi:workflows:log-sweeper'
#: Runs read per page, so memory and each ClickHouse ``IN`` list stay
#: bounded when the backlog grows.
PAGE_SIZE = 500


@dataclasses.dataclass
class SweepResult:
    """What one round did."""

    republished_events: int = 0
    republished_summaries: int = 0
    archived: int = 0


async def _try_sweep_lock() -> bool:
    """Claim this round for one instance.

    A second sweep does no harm: a republished row collapses in
    ClickHouse and an archive is idempotent. When Valkey is not
    available, every instance sweeps.
    """
    try:
        client = valkey.get_client()
        return bool(
            await client.set(
                _SWEEP_LOCK_KEY, '1', nx=True, ex=SWEEP_INTERVAL_SECONDS
            )
        )
    except Exception:  # noqa: BLE001
        LOGGER.debug('workflow run sweep lock acquire failed', exc_info=True)
        return True


async def _sweep_run(
    store: run_store.RunStore,
    run: history.Row,
    events: dict[str, tuple[int, int, int]],
    summaries: dict[str, str],
    result: SweepResult,
) -> None:
    run_id = str(run['id'])
    last_seq = run['last_seq']
    complete = True
    if last_seq and events.get(run_id) != (last_seq, 1, last_seq):
        complete = False
        stored = await history.stored_seqs(run)
        missing = [seq for seq in range(1, last_seq + 1) if seq not in stored]
        rows = await store.events_with_seqs(run['id'], missing)
        await history.publish(run, rows, summary=False)
        result.republished_events += len(rows)
    if summaries.get(run_id) != run['status']:
        complete = False
        await history.publish(run, [], summary=True)
        result.republished_summaries += 1
    if (
        complete
        and run['status'] in runtime.CLOSED
        and await store.archive(run['id'], last_seq)
    ):
        result.archived += 1


async def _sweep_batch(
    store: run_store.RunStore,
    organization_id: str,
    batch: list[history.Row],
    result: SweepResult,
) -> None:
    """Sweep the runs of one organization in one page.

    A ClickHouse failure skips this batch only, so the other
    organizations are still swept.
    """
    ids = [str(run['id']) for run in batch]
    try:
        events = await history.event_counts(organization_id, ids)
        summaries = await history.summaries(organization_id, ids)
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Workflow run sweep failed for organization %s',
            organization_id,
            exc_info=True,
        )
        return
    for run in batch:
        try:
            await _sweep_run(store, run, events, summaries, result)
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                'Workflow run sweep failed for run %s',
                run['id'],
                exc_info=True,
            )


async def cancel_orphan_agent_tasks(
    store: run_store.RunStore, tasks: agent_tasks.TaskStore
) -> int:
    """Cancel the open tasks of agent steps that ended. Return how many.

    See :meth:`run_store.RunStore.orphan_agent_tasks`. A task that
    closed or got a cancel since the query is not an error.
    """
    actor = agent_tasks.Actor('system', 'imbi-workflows-reconciler', 'api')
    cancelled = 0
    for task in await store.orphan_agent_tasks():
        try:
            await tasks.set_control(
                task['organization_id'], task['short_id'], 'cancel', actor
            )
        except (
            agent_tasks.TaskNotFound,
            agent_tasks.TaskClosed,
            agent_tasks.CancelPending,
        ):
            continue
        cancelled += 1
    if cancelled:
        LOGGER.info('Cancelled %d agent tasks of ended steps', cancelled)
    return cancelled


async def sweep_once(
    store: run_store.RunStore, tasks: agent_tasks.TaskStore | None = None
) -> SweepResult:
    """Republish what ClickHouse does not have and archive complete runs.

    With ``tasks``, also cancel the tasks of agent steps that ended.
    """
    result = SweepResult()
    if not await _try_sweep_lock():
        return result
    if tasks is not None:
        try:
            await cancel_orphan_agent_tasks(store, tasks)
        except Exception:  # noqa: BLE001 -- the next round tries again
            LOGGER.warning('Agent task reconcile failed', exc_info=True)
    after: tuple[str, uuid.UUID] | None = None
    while page := await store.unarchived(after, PAGE_SIZE):
        after = (page[-1]['organization_id'], page[-1]['id'])
        for organization_id, group in itertools.groupby(
            page, key=lambda run: run['organization_id']
        ):
            await _sweep_batch(store, organization_id, list(group), result)
    if result != SweepResult():
        LOGGER.info('Workflow run sweep: %s', result)
    return result


async def run_sweeper(
    store: run_store.RunStore,
    tasks: agent_tasks.TaskStore,
    *,
    stop: asyncio.Event,
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
            await sweep_once(store, tasks)
        except Exception:  # noqa: BLE001
            LOGGER.warning('Workflow run sweep failed', exc_info=True)
