"""Background reaper for abandoned document read sessions.

A reading session normally closes itself with a final ``sendBeacon``
flush, but that is best-effort -- a killed tab, a dropped network, a
crashed browser. Anything still open past the idle timeout is finalized
here instead; without it, an abandoned session never contributes to a
document's numbers.

Lives beside the other background workers rather than in ``endpoints``:
the lifespan module should not have to import the router package (and
with it every endpoint) to start a worker.
"""

import asyncio
import logging

from valkey import asyncio as valkey_asyncio

from imbi.api.endpoints import _document_reads

LOGGER = logging.getLogger(__name__)

#: How often the reaper looks for abandoned sessions.
SWEEP_INTERVAL_SECONDS = 60
_SWEEP_LOCK_KEY = 'imbi:document:read-sweeper'


async def _try_sweep_lock(client: valkey_asyncio.Valkey) -> bool:
    """Claim this sweep round for one instance.

    Every API instance runs a sweeper; without a lock they would all
    aggregate and re-insert the same sessions each round. Duplicate
    finalization is *harmless* -- the sessions table dedups on
    ``session_id`` -- so this is purely to avoid N-way wasted work, and
    a Valkey outage degrades to every instance sweeping rather than to
    sessions never being finalized.
    """
    try:
        return bool(
            await client.set(
                _SWEEP_LOCK_KEY, '1', nx=True, ex=SWEEP_INTERVAL_SECONDS
            )
        )
    except Exception:  # noqa: BLE001
        LOGGER.debug('read-session sweep lock acquire failed', exc_info=True)
        return True


async def sweep_once(client: valkey_asyncio.Valkey) -> int:
    """Finalize every abandoned session found this round.

    Returns how many sessions were finalized.
    """
    if not await _try_sweep_lock(client):
        return 0
    session_ids = await _document_reads.stale_session_ids()
    if not session_ids:
        return 0
    finalized = await _document_reads.finalize_sessions(session_ids)
    if finalized:
        LOGGER.info('Finalized %d abandoned read session(s)', finalized)
    return finalized


async def run_sweeper(
    client: valkey_asyncio.Valkey,
    *,
    stop: asyncio.Event,
) -> None:
    """Poll for abandoned read sessions until ``stop`` is set.

    A session ends when the reader closes the tab, which normally
    arrives as a ``sendBeacon`` flush marked final. That beacon is
    best-effort -- a killed tab, a lost network, a crashed browser --
    so anything still open past the idle timeout is finalized here
    instead. Without this, an abandoned session would never contribute
    to a document's numbers.

    The loop waits before its first sweep rather than after: nothing can
    have gone stale in the instant the process booted, and starting with
    I/O would put a ClickHouse round-trip -- and any ClickHouse outage --
    directly in the startup path.
    """
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=SWEEP_INTERVAL_SECONDS)
        except TimeoutError:
            pass
        else:
            return
        try:
            await sweep_once(client)
        except Exception:  # noqa: BLE001
            LOGGER.warning('Read-session sweep failed', exc_info=True)
