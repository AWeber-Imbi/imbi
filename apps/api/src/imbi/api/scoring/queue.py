"""Score-recompute queue (Valkey Streams).

Producers must call :func:`enqueue_recompute` *after* the originating
DB commit completes; the 5s debounce key relies on workers reading
post-commit state at recompute time.
"""

from __future__ import annotations

import asyncio
import logging
import typing
from collections import abc

from imbi_common import blueprints, clickhouse, graph, models
from imbi_common.scoring import (
    AttributePolicy,
    compute_score,
    record_score_change,
)
from valkey import asyncio as valkey

STREAM = 'imbi:score-recompute'
GROUP = 'score-workers'
CONSUMER_PREFIX = 'worker'
DLQ = 'imbi:score-recompute:dlq'
DEBOUNCE_PREFIX = 'imbi:score-recompute:debounce'
DEBOUNCE_SECONDS = 5
MAX_DELIVERIES = 5
CLAIM_IDLE_MS = 60_000

LOGGER = logging.getLogger(__name__)

ChangeReason = typing.Literal[
    'attribute_change',
    'blueprint_change',
    'policy_change',
    'bulk_rescore',
]


async def enqueue_recompute(
    client: valkey.Valkey | None,
    project_id: str,
    reason: ChangeReason,
    requested_by: str | None = None,
) -> bool:
    """Debounce-then-XADD a recompute job. Returns True if enqueued.

    Tolerates *client* being ``None`` (returns False) so trigger sites
    can run in environments where Valkey is unavailable.
    """
    if client is None:
        return False
    try:
        key = f'{DEBOUNCE_PREFIX}:{project_id}'
        acquired = await client.set(key, b'1', ex=DEBOUNCE_SECONDS, nx=True)
        if not acquired:
            return False
        fields: dict[str, str] = {
            'project_id': project_id,
            'reason': reason,
            'requested_by': requested_by or 'system',
        }
        await client.xadd(STREAM, fields)
    except Exception:
        LOGGER.exception('enqueue_recompute failed for %s', project_id)
        return False
    return True


async def ensure_group(client: valkey.Valkey) -> None:
    try:
        await client.xgroup_create(STREAM, GROUP, id='$', mkstream=True)
    except Exception as err:  # noqa: BLE001
        msg = str(err)
        if 'BUSYGROUP' not in msg:
            LOGGER.warning('xgroup_create failed: %s', err)


async def affected_projects(
    db: graph.Graph,
    policy: AttributePolicy,
) -> list[str]:
    """Project ids whose effective attribute set includes
    policy.attribute_name. Intersected with TARGETS edges if any are set.
    """
    extended = await blueprints.get_model(db, models.Project)
    if policy.attribute_name not in extended.model_fields:
        return []
    query: typing.LiteralString = (
        'MATCH (sp:ScoringPolicy {{slug: {slug}}})'
        ' OPTIONAL MATCH (sp)-[:TARGETS]->(pt:ProjectType)'
        ' WITH collect(pt.slug) AS targets'
        ' MATCH (p:Project)'
        ' OPTIONAL MATCH (p)-[:TYPE]->(ppt:ProjectType)'
        ' WITH p, targets, collect(ppt.slug) AS p_types'
        ' WHERE size(targets) = 0 OR'
        ' any(t IN p_types WHERE t IN targets)'
        ' RETURN p.id AS id'
    )
    rows = await db.execute(query, {'slug': policy.slug}, ['id'])
    return [v for r in rows if (v := graph.parse_agtype(r['id']))]


async def projects_of_type(
    db: graph.Graph, project_type_slug: str
) -> list[str]:
    query: typing.LiteralString = (
        'MATCH (p:Project)-[:TYPE]'
        '->(pt:ProjectType {{slug: {slug}}})'
        ' RETURN p.id AS id'
    )
    rows = await db.execute(query, {'slug': project_type_slug}, ['id'])
    return [v for r in rows if (v := graph.parse_agtype(r['id']))]


async def all_project_ids(
    db: graph.Graph,
    project_type_slug: str | None = None,
) -> list[str]:
    if project_type_slug:
        return await projects_of_type(db, project_type_slug)
    rows = await db.execute('MATCH (p:Project) RETURN p.id AS id', {}, ['id'])
    return [v for r in rows if (v := graph.parse_agtype(r['id']))]


async def _process_message(
    db: graph.Graph,
    ch: clickhouse.client.Clickhouse,
    fields: dict[str, str],
) -> None:
    project_id = fields.get('project_id')
    reason = fields.get('reason') or 'attribute_change'
    if not project_id:
        return
    matches = await db.match(models.Project, {'id': project_id})
    if not matches:
        LOGGER.info('Project %s not found; skipping recompute', project_id)
        return
    project = matches[0]
    previous = project.score if project.score is not None else 0.0
    score, _ = await compute_score(db, project_id)
    await record_score_change(ch, db, project, score, previous, reason)


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
            'dead-lettered score-recompute msg %s after %s deliveries',
            msg_id,
            delivered,
        )
        return True
    return False


async def _handle_entries(
    client: valkey.Valkey,
    entries: list[tuple[bytes, abc.Mapping[bytes | str, bytes | str]]],
    db: graph.Graph,
    ch: clickhouse.client.Clickhouse,
    check_dlq: bool = False,
) -> None:
    for msg_id, raw_fields in entries:
        fields = _decode_fields(raw_fields)
        if check_dlq and await _maybe_dead_letter(client, msg_id, fields):
            continue
        try:
            await _process_message(db, ch, fields)
        except Exception:
            LOGGER.exception('recompute failed for %s', fields)
            continue
        await client.xack(STREAM, GROUP, msg_id)


async def consume_recompute(
    client: valkey.Valkey,
    db: graph.Graph,
    ch: clickhouse.client.Clickhouse,
    consumer: str = f'{CONSUMER_PREFIX}-0',
    stop: asyncio.Event | None = None,
) -> None:
    """Run the recompute consumer loop until *stop* is set."""
    await ensure_group(client)
    while stop is None or not stop.is_set():
        stale = await _claim_stale(client, consumer)
        if stale:
            await _handle_entries(client, stale, db, ch, check_dlq=True)
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
        for _stream, entries in response:
            await _handle_entries(client, entries, db, ch)
