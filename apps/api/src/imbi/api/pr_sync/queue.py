"""PR-sync queue (Valkey Streams).

Mirrors :mod:`imbi_api.commit_sync.queue`: a single consumer group
drains an ``imbi:pr-sync`` stream, with a per-project debounce,
stale-entry reclaim, and a dead-letter queue after repeated failures.
Each job runs a full PR backfill via
:func:`pr_sync.service.run_sync` and records the outcome on the
``Project`` node.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import typing
from collections import abc

from imbi_common import graph
from imbi_common.plugins.errors import PluginRateLimited
from valkey import asyncio as valkey

from imbi_api.pr_sync.service import (
    PRSyncUnavailable,
    run_sync,
    set_status,
)

STREAM = 'imbi:pr-sync'
GROUP = 'pr-sync-workers'
CONSUMER_PREFIX = 'worker'
DLQ = 'imbi:pr-sync:dlq'
DEBOUNCE_PREFIX = 'imbi:pr-sync:debounce'
DEBOUNCE_SECONDS = 10
MAX_DELIVERIES = 3
CLAIM_IDLE_MS = 120_000
PAUSE_KEY = 'imbi:pr-sync:paused-until'
PAUSE_POLL_CAP_SECONDS = 30
PAUSE_KEY_BUFFER_SECONDS = 5

LOGGER = logging.getLogger(__name__)


async def enqueue_pr_sync(
    client: valkey.Valkey | None,
    org_slug: str,
    project_id: str,
    requested_by: str | None = None,
) -> bool:
    """Debounce-then-XADD a PR-sync job. Returns True if enqueued."""
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
            },
        )
    except Exception:
        try:
            await client.delete(key)
        except Exception:
            LOGGER.exception('failed to clear debounce key for %s', project_id)
        LOGGER.exception('enqueue_pr_sync failed for %s', project_id)
        return False
    return True


async def ensure_group(client: valkey.Valkey) -> None:
    try:
        await client.xgroup_create(STREAM, GROUP, id='$', mkstream=True)
    except Exception as err:
        if 'BUSYGROUP' not in str(err):
            LOGGER.exception('xgroup_create failed')
            raise


async def _process_message(db: graph.Graph, fields: dict[str, str]) -> None:
    project_id = fields.get('project_id')
    org_slug = fields.get('org_slug') or ''
    requested_by = fields.get('requested_by') or 'system'
    if not project_id:
        return
    await set_status(
        db, project_id, status='running', requested_by=requested_by
    )
    try:
        prs = await run_sync(db, org_slug, project_id)
    except PRSyncUnavailable as exc:
        LOGGER.warning('pr-sync unavailable for %s: %s', project_id, exc)
        await set_status(
            db,
            project_id,
            status='failed',
            requested_by=requested_by,
            error=str(exc),
        )
        return
    except PluginRateLimited:
        LOGGER.warning(
            'pr-sync rate-limited for %s; left queued until GitHub resets',
            project_id,
        )
        await set_status(
            db, project_id, status='queued', requested_by=requested_by
        )
        raise
    except Exception:
        LOGGER.exception('pr-sync run failed for %s', project_id)
        await set_status(
            db,
            project_id,
            status='failed',
            requested_by=requested_by,
            error='PR sync failed. See server logs for details.',
        )
        raise
    LOGGER.info(
        'pr-sync for %s recorded %d pull requests',
        project_id,
        prs,
    )
    await set_status(
        db,
        project_id,
        status='success',
        requested_by=requested_by,
        prs=prs,
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
    ttl = max(1, int(retry_at - time.time()) + PAUSE_KEY_BUFFER_SECONDS)
    try:
        await client.set(PAUSE_KEY, str(retry_at), ex=ttl)
    except Exception:
        LOGGER.exception('failed to set pr-sync pause marker')


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
            'dead-lettered pr-sync msg %s after %s deliveries',
            msg_id,
            delivered,
        )
        return True
    return False


async def _handle_entries(
    client: valkey.Valkey,
    entries: list[tuple[bytes, abc.Mapping[bytes | str, bytes | str]]],
    db: graph.Graph,
    check_dlq: bool = False,
) -> None:
    for msg_id, raw_fields in entries:
        fields = _decode_fields(raw_fields)
        if check_dlq and await _maybe_dead_letter(client, msg_id, fields):
            continue
        try:
            await _process_message(db, fields)
        except PluginRateLimited as exc:
            await _pause_until(client, exc.retry_at)
            LOGGER.warning(
                'pr-sync paused ~%.0fs (GitHub rate limit); %d job(s) '
                'left queued',
                max(0.0, exc.retry_at - time.time()),
                len(entries),
            )
            return
        except Exception:
            LOGGER.exception('pr-sync failed for %s', fields)
            continue
        await client.xack(STREAM, GROUP, msg_id)


async def consume_pr_sync(
    client: valkey.Valkey,
    db: graph.Graph,
    consumer: str | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Run the PR-sync consumer loop until *stop* is set."""
    consumer = (
        consumer or f'{CONSUMER_PREFIX}-{socket.gethostname()}-{os.getpid()}'
    )
    await ensure_group(client)
    LOGGER.info('PR-sync consumer loop running (consumer=%s)', consumer)
    while stop is None or not stop.is_set():
        paused = await _paused_remaining(client)
        if paused > 0:
            await asyncio.sleep(min(paused, PAUSE_POLL_CAP_SECONDS))
            continue
        stale = await _claim_stale(client, consumer)
        if stale:
            try:
                await _handle_entries(client, stale, db, check_dlq=True)
            except Exception:
                LOGGER.exception('pr-sync stale-entry handling failed')
                await asyncio.sleep(1)
                continue
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
                await _handle_entries(client, entries, db)
            except Exception:
                LOGGER.exception('pr-sync entry handling failed')
                await asyncio.sleep(1)
                break
