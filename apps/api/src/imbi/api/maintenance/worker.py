"""Per-instance consumer for global maintenance runs.

Every API instance runs one of these; work is distributed through the
Valkey pending SET (:mod:`imbi_api.maintenance.state`), so N instances
give N-way parallelism with one in-flight project per instance -- the
gentlest shape for plugin APIs that share a rate-limited token.
"""

from __future__ import annotations

import asyncio
import logging
import time

from imbi_common import graph
from imbi_common.plugins.errors import PluginRateLimited
from valkey import asyncio as valkey

from imbi_api.maintenance import registry, state
from imbi_api.maintenance.operations import MaintenanceItemFailed

LOGGER = logging.getLogger(__name__)

POLL_IDLE_SECONDS = 2.0
#: Cushion on the pause key's TTL so it outlives the resume time.
PAUSE_KEY_BUFFER_SECONDS = 5


async def paused_remaining(client: valkey.Valkey, key: str) -> float:
    """Seconds left on a rate-limit pause key, ``0.0`` when clear."""
    try:
        raw = await client.get(key)
    except Exception:  # noqa: BLE001
        return 0.0
    if raw is None:
        return 0.0
    try:
        until = float(raw.decode() if isinstance(raw, bytes) else raw)
    except ValueError:
        return 0.0
    return max(0.0, until - time.time())


async def pause_until(
    client: valkey.Valkey, key: str, retry_at: float
) -> None:
    """Record the resume time so every consumer of *key* backs off."""
    ttl = max(1, int(retry_at - time.time()) + PAUSE_KEY_BUFFER_SECONDS)
    try:
        await client.set(key, str(retry_at), ex=ttl)
    except Exception:
        LOGGER.exception('failed to set pause marker %s', key)


async def _tick_operation(
    client: valkey.Valkey,
    db: graph.Graph,
    operation: registry.OperationDefinition,
) -> bool:
    """Execute at most one pending project for *operation*.

    Returns ``True`` when a project was processed (successfully or
    not), so the caller loops immediately instead of idling.
    """
    if not await state.has_active_run(client, operation.slug):
        return False
    if (
        operation.pause_key
        and await paused_remaining(client, operation.pause_key) > 0
    ):
        # Another instance may drain to zero while we're paused.
        await state.maybe_finalize(client, operation.slug)
        return False
    project_id = await state.checkout(client, operation.slug)
    if project_id is None:
        await state.maybe_finalize(client, operation.slug)
        return False
    outcome: state.Outcome
    error = ''
    try:
        outcome = await operation.execute(db, client, project_id)
    except asyncio.CancelledError:
        # Graceful shutdown: hand the project back so nothing is lost.
        await state.requeue(client, operation.slug, project_id)
        raise
    except PluginRateLimited as exc:
        await state.requeue(client, operation.slug, project_id)
        if operation.pause_key:
            await pause_until(client, operation.pause_key, exc.retry_at)
        LOGGER.warning(
            'maintenance %s paused ~%.0fs (rate limit); %s requeued',
            operation.slug,
            max(0.0, exc.retry_at - time.time()),
            project_id,
        )
        return False
    except MaintenanceItemFailed as exc:
        outcome, error = 'failed', str(exc)
    except Exception:
        LOGGER.exception(
            'maintenance %s failed for %s', operation.slug, project_id
        )
        outcome = 'failed'
        error = 'Operation failed. See server logs for details.'
    try:
        await state.record_outcome(
            client, operation.slug, project_id, outcome, error
        )
    except Exception:
        # Compensate so in_flight cannot stay stuck until the lock TTL:
        # hand the project back; its outcome is recorded on the retry.
        LOGGER.exception(
            'maintenance %s failed to record outcome for %s; requeueing',
            operation.slug,
            project_id,
        )
        await state.requeue(client, operation.slug, project_id)
    if await state.maybe_finalize(client, operation.slug):
        LOGGER.info('maintenance %s run completed', operation.slug)
    return True


async def run_worker(
    client: valkey.Valkey,
    db: graph.Graph,
    stop: asyncio.Event,
) -> None:
    """Run the maintenance consumer loop until *stop* is set."""
    LOGGER.info('Maintenance worker loop running')
    while not stop.is_set():
        worked = False
        for operation in registry.OPERATIONS.values():
            if stop.is_set():
                break
            try:
                worked = await _tick_operation(client, db, operation) or worked
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    'maintenance tick failed for %s', operation.slug
                )
        if not worked:
            try:
                await asyncio.wait_for(stop.wait(), POLL_IDLE_SECONDS)
            except TimeoutError:
                pass
