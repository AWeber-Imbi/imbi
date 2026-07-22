"""Deployment-resync queue (Valkey Streams).

Mirrors :mod:`imbi.api.commit_sync.queue`: a single consumer group
drains an ``imbi:deployment-sync`` stream, with a per-project debounce,
stale-entry reclaim, and a dead-letter queue after repeated failures.
Each job backfills recent remote deployments via
:func:`deployment_sync.service.run_resync` and records the outcome on
the ``Project`` node.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import time
import typing
from collections import abc

from valkey import asyncio as valkey

from imbi.api.deployment_sync.service import (
    DeploymentSyncUnavailable,
    run_resync,
    set_status,
)
from imbi.common import graph
from imbi.common.plugins.errors import PluginRateLimited

STREAM = 'imbi:deployment-sync'
GROUP = 'deployment-sync-workers'
CONSUMER_PREFIX = 'worker'
DLQ = 'imbi:deployment-sync:dlq'
DEBOUNCE_PREFIX = 'imbi:deployment-sync:debounce'
DEBOUNCE_SECONDS = 10
MAX_DELIVERIES = 3
CLAIM_IDLE_MS = 120_000
#: How often an in-flight job renews its claim; keeps a deep backfill
#: (minutes of remote calls) from looking stale to other workers while
#: leaving crashed-worker recovery at ``CLAIM_IDLE_MS``.
CLAIM_RENEW_SECONDS = 30
PAUSE_KEY = 'imbi:deployment-sync:paused-until'
PAUSE_POLL_CAP_SECONDS = 30
PAUSE_KEY_BUFFER_SECONDS = 5
#: ``limit`` bounds mirror the endpoint's (GitHub's per-page ceiling).
MAX_LIMIT = 100

LOGGER = logging.getLogger(__name__)


async def enqueue_deployment_sync(
    client: valkey.Valkey | None,
    org_slug: str,
    project_id: str,
    requested_by: str | None = None,
    limit: int = 1,
) -> bool:
    """Debounce-then-XADD a deployment-resync job.

    Returns True if enqueued.  Tolerates *client* being ``None``
    (returns False) so the endpoint can surface "queueing unavailable"
    rather than 500 when Valkey is down.
    """
    if client is None:
        return False
    key = f'{DEBOUNCE_PREFIX}:{project_id}'
    try:
        acquired = await client.set(key, b'1', ex=DEBOUNCE_SECONDS, nx=True)
        if not acquired:
            return False
        await client.xadd(
            STREAM,
            {
                'org_slug': org_slug,
                'project_id': project_id,
                'requested_by': requested_by or 'system',
                'limit': str(limit),
            },
        )
    except Exception:
        # Release the debounce key so a transient Valkey write failure
        # doesn't block the user's immediate retry for DEBOUNCE_SECONDS.
        try:
            await client.delete(key)
        except Exception:
            LOGGER.exception('failed to clear debounce key for %s', project_id)
        LOGGER.exception('enqueue_deployment_sync failed for %s', project_id)
        return False
    return True


async def ensure_group(client: valkey.Valkey) -> None:
    try:
        await client.xgroup_create(STREAM, GROUP, id='$', mkstream=True)
    except Exception as err:
        if 'BUSYGROUP' not in str(err):
            LOGGER.exception('xgroup_create failed')
            raise


def _parse_limit(raw: str | None) -> int:
    try:
        limit = int(raw) if raw else 1
    except ValueError:
        return 1
    return max(1, min(limit, MAX_LIMIT))


async def _process_message(db: graph.Graph, fields: dict[str, str]) -> None:
    project_id = fields.get('project_id')
    org_slug = fields.get('org_slug') or ''
    requested_by = fields.get('requested_by') or 'system'
    limit = _parse_limit(fields.get('limit'))
    if not project_id:
        return
    await set_status(
        db, project_id, status='running', requested_by=requested_by
    )
    try:
        summary = await run_resync(db, org_slug, project_id, limit)
    except DeploymentSyncUnavailable as exc:
        # Misconfiguration, not transient: record and don't retry.
        LOGGER.warning(
            'deployment-sync unavailable for %s: %s', project_id, exc
        )
        await set_status(
            db,
            project_id,
            status='failed',
            requested_by=requested_by,
            error=str(exc),
        )
        return
    except PluginRateLimited:
        # Transient: GitHub's rate limit is exhausted.  Keep the job
        # queued (the consumer pauses until the reset and retries)
        # instead of marking it failed -- the failure path would
        # dead-letter it before the limit clears.
        LOGGER.warning(
            'deployment-sync rate-limited for %s; left queued until '
            'GitHub resets',
            project_id,
        )
        await set_status(
            db, project_id, status='queued', requested_by=requested_by
        )
        raise
    except Exception:
        # Persist a generic, user-safe message; the polling endpoint
        # exposes this status, so keep raw exception detail in logs only.
        LOGGER.exception('deployment-sync run failed for %s', project_id)
        await set_status(
            db,
            project_id,
            status='failed',
            requested_by=requested_by,
            error='Deployment resync failed. See server logs for details.',
        )
        raise
    LOGGER.info(
        'deployment-sync for %s observed %d deployments, recorded %d events',
        project_id,
        summary.observed,
        summary.events_recorded,
    )
    await set_status(
        db,
        project_id,
        status='success',
        requested_by=requested_by,
        summary=summary,
    )


def _decode_fields(
    raw: abc.Mapping[bytes | str, bytes | str],
) -> dict[str, str]:
    return {
        (k.decode() if isinstance(k, bytes) else k): (
            v.decode() if isinstance(v, bytes) else v
        )
        for k, v in raw.items()
    }


async def _paused_remaining(client: valkey.Valkey) -> float:
    """Seconds left on the global rate-limit pause, ``0.0`` when clear."""
    try:
        raw = await client.get(PAUSE_KEY)
    except Exception:  # noqa: BLE001
        return 0.0
    if raw is None:
        return 0.0
    try:
        until = float(raw.decode() if isinstance(raw, bytes) else raw)
    except ValueError:
        return 0.0
    return max(0.0, until - time.time())


async def _pause_until(client: valkey.Valkey, retry_at: float) -> None:
    """Record the resume time so every worker backs off until *retry_at*."""
    ttl = max(1, int(retry_at - time.time()) + PAUSE_KEY_BUFFER_SECONDS)
    try:
        await client.set(PAUSE_KEY, str(retry_at), ex=ttl)
    except Exception:
        LOGGER.exception('failed to set deployment-sync pause marker')


async def _claim_stale(
    client: valkey.Valkey,
    consumer: str,
) -> list[tuple[bytes, abc.Mapping[bytes | str, bytes | str]]]:
    try:
        result = await client.xautoclaim(
            STREAM,
            GROUP,
            consumer,
            min_idle_time=CLAIM_IDLE_MS,
            start_id='0-0',
            count=16,
        )
    except Exception as err:  # noqa: BLE001
        LOGGER.debug('xautoclaim failed: %s', err)
        return []
    if isinstance(result, (list, tuple)) and len(result) >= 2:  # type: ignore[arg-type]
        msgs: object = result[1]  # type: ignore[index]
        if isinstance(msgs, list):
            return msgs  # type: ignore[return-value]
    return []


async def _renew_claim(
    client: valkey.Valkey,
    consumer: str,
    msg_id: bytes,
) -> None:
    """Reset *msg_id*'s idle clock while its job is still running.

    ``xautoclaim``'s ``min_idle_time`` measures "no ack yet", not
    consumer liveness, so a deep backfill that legitimately runs past
    ``CLAIM_IDLE_MS`` would otherwise be reclaimed and duplicate-
    processed by another worker mid-flight.  ``JUSTID`` renews without
    re-reading the entry or bumping the delivery counter, so renewal
    never pushes a healthy job toward the dead-letter threshold.

    Runs until cancelled by :func:`_handle_entries`.
    """
    while True:
        await asyncio.sleep(CLAIM_RENEW_SECONDS)
        try:
            await client.xclaim(
                STREAM,
                GROUP,
                consumer,
                min_idle_time=0,
                message_ids=[msg_id],
                justid=True,
            )
        except Exception as err:  # noqa: BLE001
            LOGGER.debug('claim renewal failed for %s: %s', msg_id, err)


async def _maybe_dead_letter(
    client: valkey.Valkey,
    msg_id: bytes,
    fields: dict[str, str],
) -> bool:
    try:
        info = await client.xpending_range(
            STREAM, GROUP, min=msg_id, max=msg_id, count=1
        )
    except Exception:  # noqa: BLE001
        return False
    if not info:
        return False
    entry: object = info[0]  # type: ignore[index]
    delivered: int | None = None
    if isinstance(entry, dict):
        raw_delivered = entry.get('times_delivered')  # type: ignore[union-attr]
        if raw_delivered is not None:
            delivered = int(raw_delivered)  # type: ignore[arg-type]
    elif isinstance(entry, (list, tuple)) and len(entry) >= 4:  # type: ignore[arg-type]
        raw_delivered = entry[3]  # type: ignore[index]
        if raw_delivered is not None:
            delivered = int(raw_delivered)  # type: ignore[arg-type]
    if delivered is not None and delivered >= MAX_DELIVERIES:
        await client.xadd(DLQ, fields)
        await client.xack(STREAM, GROUP, msg_id)
        LOGGER.warning(
            'dead-lettered deployment-sync msg %s after %s deliveries',
            msg_id,
            delivered,
        )
        return True
    return False


async def _handle_entries(
    client: valkey.Valkey,
    entries: list[tuple[bytes, abc.Mapping[bytes | str, bytes | str]]],
    db: graph.Graph,
    consumer: str,
    check_dlq: bool = False,
) -> None:
    for msg_id, raw_fields in entries:
        fields = _decode_fields(raw_fields)
        if check_dlq and await _maybe_dead_letter(client, msg_id, fields):
            continue
        renewer = asyncio.ensure_future(_renew_claim(client, consumer, msg_id))
        try:
            await _process_message(db, fields)
        except PluginRateLimited as exc:
            # Don't ack, don't dead-letter: leave the job pending and
            # pause every worker until GitHub resets.  Stop the batch --
            # its siblings hit the same token -- and let the next
            # reclaim drain it once the pause clears.
            await _pause_until(client, exc.retry_at)
            LOGGER.warning(
                'deployment-sync paused ~%.0fs (GitHub rate limit); %d '
                'job(s) left queued',
                max(0.0, exc.retry_at - time.time()),
                len(entries),
            )
            return
        except Exception:
            LOGGER.exception('deployment-sync failed for %s', fields)
            continue
        finally:
            renewer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renewer
        await client.xack(STREAM, GROUP, msg_id)


async def consume_deployment_sync(
    client: valkey.Valkey,
    db: graph.Graph,
    consumer: str | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Run the deployment-sync consumer loop until *stop* is set."""
    # Derive a per-process consumer name so concurrent workers don't
    # share a Pending Entries List and stale-claim each other's
    # in-flight jobs.
    consumer = (
        consumer or f'{CONSUMER_PREFIX}-{socket.gethostname()}-{os.getpid()}'
    )
    await ensure_group(client)
    LOGGER.info(
        'Deployment-sync consumer loop running (consumer=%s)', consumer
    )
    while stop is None or not stop.is_set():
        paused = await _paused_remaining(client)
        if paused > 0:
            await asyncio.sleep(min(paused, PAUSE_POLL_CAP_SECONDS))
            continue
        stale = await _claim_stale(client, consumer)
        if stale:
            try:
                await _handle_entries(
                    client, stale, db, consumer, check_dlq=True
                )
            except Exception:
                LOGGER.exception('deployment-sync stale-entry handling failed')
                await asyncio.sleep(1)
                continue
        # Stale handling may have just paused us; don't read new work
        # into a guaranteed re-throttle -- loop back and honor the pause.
        if await _paused_remaining(client) > 0:
            continue
        try:
            response = await client.xreadgroup(
                GROUP,
                consumer,
                {STREAM: '>'},
                count=16,
                block=2000,
            )
        except Exception:
            LOGGER.exception('xreadgroup failed')
            await asyncio.sleep(1)
            continue
        if not response:
            continue
        for _stream, entries in typing.cast(
            'list[tuple[object, list[typing.Any]]]', response
        ):
            try:
                await _handle_entries(client, entries, db, consumer)
            except Exception:
                LOGGER.exception('deployment-sync entry handling failed')
                await asyncio.sleep(1)
                break
