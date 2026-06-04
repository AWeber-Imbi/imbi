"""Commit/tag-sync queue (Valkey Streams).

Mirrors :mod:`imbi_api.scoring.queue`: a single consumer group drains an
``imbi:commit-sync`` stream, with a per-project debounce, stale-entry
reclaim, and a dead-letter queue after repeated failures.  Each job runs
a full commit/tag backfill via :func:`commit_sync.service.run_sync` and
records the outcome on the ``Project`` node.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import typing
from collections import abc

from imbi_common import graph
from valkey import asyncio as valkey

from imbi_api.commit_sync.service import (
    CommitSyncUnavailable,
    run_sync,
    set_status,
)

STREAM = 'imbi:commit-sync'
GROUP = 'commit-sync-workers'
CONSUMER_PREFIX = 'worker'
DLQ = 'imbi:commit-sync:dlq'
DEBOUNCE_PREFIX = 'imbi:commit-sync:debounce'
DEBOUNCE_SECONDS = 10
MAX_DELIVERIES = 3
CLAIM_IDLE_MS = 120_000

LOGGER = logging.getLogger(__name__)


async def enqueue_commit_sync(
    client: valkey.Valkey | None,
    org_slug: str,
    project_id: str,
    requested_by: str | None = None,
) -> bool:
    """Debounce-then-XADD a commit-sync job. Returns True if enqueued.

    Tolerates *client* being ``None`` (returns False) so the endpoint can
    surface "queueing unavailable" rather than 500 when Valkey is down.
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
            },
        )
    except Exception:
        # Release the debounce key so a transient Valkey write failure
        # doesn't block the user's immediate retry for DEBOUNCE_SECONDS.
        try:
            await client.delete(key)
        except Exception:
            LOGGER.exception('failed to clear debounce key for %s', project_id)
        LOGGER.exception('enqueue_commit_sync failed for %s', project_id)
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
        commits, tags = await run_sync(db, org_slug, project_id)
    except CommitSyncUnavailable as exc:
        # Misconfiguration, not transient: record and don't retry.
        LOGGER.warning('commit-sync unavailable for %s: %s', project_id, exc)
        await set_status(
            db,
            project_id,
            status='failed',
            requested_by=requested_by,
            error=str(exc),
        )
        return
    except Exception:
        # Persist a generic, user-safe message; the polling endpoint
        # exposes this status, so keep raw exception detail in logs only.
        LOGGER.exception('commit-sync run failed for %s', project_id)
        await set_status(
            db,
            project_id,
            status='failed',
            requested_by=requested_by,
            error='Commit sync failed. See server logs for details.',
        )
        raise
    LOGGER.info(
        'commit-sync for %s recorded %d commits, %d tags',
        project_id,
        commits,
        tags,
    )
    await set_status(
        db,
        project_id,
        status='success',
        requested_by=requested_by,
        commits=commits,
        tags=tags,
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
            'dead-lettered commit-sync msg %s after %s deliveries',
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
        except Exception:
            LOGGER.exception('commit-sync failed for %s', fields)
            continue
        await client.xack(STREAM, GROUP, msg_id)


async def consume_commit_sync(
    client: valkey.Valkey,
    db: graph.Graph,
    consumer: str | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Run the commit-sync consumer loop until *stop* is set."""
    # Derive a per-process consumer name so concurrent workers don't share
    # a Pending Entries List and stale-claim each other's in-flight jobs.
    consumer = (
        consumer or f'{CONSUMER_PREFIX}-{socket.gethostname()}-{os.getpid()}'
    )
    await ensure_group(client)
    LOGGER.info('Commit-sync consumer loop running (consumer=%s)', consumer)
    while stop is None or not stop.is_set():
        stale = await _claim_stale(client, consumer)
        if stale:
            try:
                await _handle_entries(client, stale, db, check_dlq=True)
            except Exception:
                LOGGER.exception('commit-sync stale-entry handling failed')
                await asyncio.sleep(1)
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
                LOGGER.exception('commit-sync entry handling failed')
                await asyncio.sleep(1)
                break
