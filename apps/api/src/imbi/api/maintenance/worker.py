"""Per-instance consumer for global maintenance runs.

Every API instance runs one of these; work is distributed through the
Valkey pending SET (:mod:`imbi.api.maintenance.state`), so N instances
give N-way parallelism with one in-flight project per instance -- the
gentlest shape for plugin APIs that share a rate-limited token.
"""

from __future__ import annotations

import asyncio
import logging
import time

import nanoid
from valkey import asyncio as valkey

from imbi.api.maintenance import log, registry, state
from imbi.api.maintenance.operations import MaintenanceItemFailed
from imbi.common import graph
from imbi.common.plugins.errors import PluginRateLimited

LOGGER = logging.getLogger(__name__)

POLL_IDLE_SECONDS = 2.0
#: Cushion on the pause key's TTL so it outlives the resume time.
PAUSE_KEY_BUFFER_SECONDS = 5


def _elapsed_ms(started: float) -> int:
    """Milliseconds since a ``time.monotonic()`` reading."""
    return int((time.monotonic() - started) * 1000)


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


async def _item_context(
    client: valkey.Valkey,
    db: graph.Graph,
    operation: registry.OperationDefinition,
    item_id: str,
) -> log.MaintenanceContext:
    """Build the activity-log context for one claimed item.

    ``project_id`` is left empty for an operation whose work items are
    not projects (``search-reindex``), so a reader can trust the column
    rather than having to know which operations are project-scoped.

    The caller has already claimed *item_id* and incremented
    ``in_flight``, so this cannot raise: the lookups below are log
    metadata, and letting one fail would strand the claim until the
    run lock expires. A failure costs the row its context, nothing
    more.
    """
    # Imported here, not at module scope: ``imbi.api.endpoints`` pulls in
    # the maintenance router, which imports this module back.
    from imbi.api.endpoints._helpers import lookup_project_slugs

    project_id = item_id if operation.items_are_projects else ''
    run_id, started_by, project_slug = '', '', ''
    try:
        run_id, started_by = await state.read_run_meta(client, operation.slug)
        if project_id:
            project_slug, _ = await lookup_project_slugs(db, project_id)
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'maintenance %s could not read log context for %s; '
            'logging this attempt without it',
            operation.slug,
            item_id,
            exc_info=True,
        )
    attempt_id = nanoid.generate()
    return log.MaintenanceContext(
        run_id=run_id,
        attempt_id=attempt_id,
        item_id=item_id,
        project_id=project_id,
        project_slug=project_slug,
        log=log.ItemLog(
            operation.slug,
            run_id,
            attempt_id,
            item_id,
            project_id,
            project_slug,
            started_by,
        ),
    )


async def _tick_operation(
    client: valkey.Valkey,
    db: graph.Graph,
    operation: registry.OperationDefinition,
) -> bool:
    """Execute at most one pending project for *operation*.

    Returns ``True`` when a project was processed (successfully or
    not), so the caller loops immediately instead of idling.

    Every path but cancellation writes one ``attempt`` row to the
    activity log, alongside whatever the operation recorded while it
    ran. Cancellation writes nothing on purpose: the project goes back
    on the pending set, so the attempt that matters is the next one.
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
    ctx = await _item_context(client, db, operation, project_id)
    started = time.monotonic()
    outcome: state.Outcome
    error = ''
    try:
        outcome = await operation.execute(db, client, project_id, ctx=ctx)
    except asyncio.CancelledError:
        # Graceful shutdown: hand the project back so nothing is lost.
        await state.requeue(client, operation.slug, project_id)
        raise
    except PluginRateLimited as exc:
        await state.requeue(client, operation.slug, project_id)
        if operation.pause_key:
            await pause_until(client, operation.pause_key, exc.retry_at)
        retry_in = max(0.0, exc.retry_at - time.time())
        LOGGER.warning(
            'maintenance %s paused ~%.0fs (rate limit); %s requeued',
            operation.slug,
            retry_in,
            project_id,
        )
        # Recorded rather than dropped: an operation spending hours
        # thrashing against a plugin's rate limit is invisible if the
        # only rows are the ones that ran to completion.
        ctx.log.attempt(
            'deferred',
            'Rate limited; requeued for a later attempt.',
            _elapsed_ms(started),
            retry_in_seconds=round(retry_in),
        )
        await ctx.log.flush()
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
        # The run counters never saw this outcome, so the log must not
        # claim it did either; the retry writes the real one.
        ctx.log.attempt(
            'deferred',
            'Outcome could not be recorded; requeued.',
            _elapsed_ms(started),
        )
    else:
        ctx.log.attempt(outcome, error, _elapsed_ms(started))
    await ctx.log.flush()
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
