"""The lease sweep of the runner pool (ADR 0022, "Leases and fencing").

A runner that loses only its connection to imbi-api can still reach
GitHub, so lease expiry alone must not make its chain claimable. Each
round:

1. Marks each runner with an expired lease as lost, and moves its
   running chain to ``fencing`` with the next attempt. The agent tokens
   of the old attempt stop working at once.
2. Calls every fencer for the lost runner. A fencer revokes what the
   runner holds outside imbi-api, for example its secret resolutions.
   When a fencer fails, the chain is ``stuck`` and shows on the Runners
   page; the next round calls the fencers again.
3. When the fencers succeed and :data:`store.GRACE_SECONDS` have passed,
   writes an ``attempt_marker`` event to each open task of the chain
   and puts the chain back in the queue.

Every instance runs the loop. The row locks make a second sweep safe; a
fencer must be idempotent, because two instances can call it at once.
"""

import asyncio
import logging
import uuid
from collections import abc

from imbi.api.harness import store as harness_store

LOGGER = logging.getLogger(__name__)

#: How often the sweep runs.
SWEEP_INTERVAL_SECONDS = 10
#: The longest wait for one fencer. A timeout is a failure, so the
#: chain is ``stuck`` and the next round tries again.
FENCER_TIMEOUT_SECONDS = 30

#: A fencer gets the id of a lost runner and returns ``True`` when
#: everything that the runner holds outside imbi-api is revoked.
type Fencer = abc.Callable[[uuid.UUID], abc.Awaitable[bool]]

_fencers: list[Fencer] = []


def register_fencer(fencer: Fencer) -> None:
    """Add a fencer. The secrets broker registers its release here."""
    if fencer not in _fencers:
        _fencers.append(fencer)


def unregister_fencer(fencer: Fencer) -> None:
    """Remove a fencer."""
    if fencer in _fencers:
        _fencers.remove(fencer)


async def run_fencers(runner_id: uuid.UUID) -> str | None:
    """Call every fencer; return ``None`` when all succeed, else why."""
    failed: list[str] = []
    for fencer in list(_fencers):
        name = getattr(fencer, '__qualname__', repr(fencer))
        try:
            async with asyncio.timeout(FENCER_TIMEOUT_SECONDS):
                ok = await fencer(runner_id)
            if not ok:
                failed.append(name)
        except Exception:  # noqa: BLE001 - a fencer error keeps it fenced
            LOGGER.warning(
                'Fencer %s failed for runner %s',
                name,
                runner_id,
                exc_info=True,
            )
            failed.append(name)
    return f'fencers failed: {", ".join(failed)}' if failed else None


async def sweep_once(store: harness_store.HarnessStore) -> None:
    """Run one round of the lease sweep.

    An error on one chain is logged, and the round goes on with the
    next chain.
    """
    await store.expire_leases()
    for chain in await store.fencing_chains():
        try:
            await _sweep_chain(store, chain)
        except Exception:  # noqa: BLE001 - the next chain still sweeps
            LOGGER.warning(
                'Lease sweep failed for chain %s',
                chain['root_task_id'],
                exc_info=True,
            )


async def _sweep_chain(
    store: harness_store.HarnessStore, chain: harness_store.Row
) -> None:
    """Run the fencers of one fenced chain, then requeue it when ready."""
    if chain['fencers_ok_at'] is None:
        error = (
            'runner unknown'
            if chain['runner_id'] is None
            else await run_fencers(chain['runner_id'])
        )
        updated = await store.set_fence_result(chain, error)
        if error is not None:
            LOGGER.warning(
                'Chain %s is stuck: %s', chain['root_task_id'], error
            )
        if updated is None or error is not None:
            return
    if await store.requeue(chain['root_task_id']):
        LOGGER.info(
            'Chain %s is back in the queue (attempt %s)',
            chain['root_task_id'],
            chain['attempt'],
        )


async def run_sweeper(
    store: harness_store.HarnessStore, *, stop: asyncio.Event
) -> None:
    """Sweep every :data:`SWEEP_INTERVAL_SECONDS` until ``stop`` is set."""
    rounds = 0
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=SWEEP_INTERVAL_SECONDS)
        except TimeoutError:
            pass
        else:
            return
        try:
            await sweep_once(store)
            rounds += 1
            if rounds % 360 == 0:  # about once an hour
                await store.prune()
        except Exception:  # noqa: BLE001
            LOGGER.warning('Harness lease sweep failed', exc_info=True)
