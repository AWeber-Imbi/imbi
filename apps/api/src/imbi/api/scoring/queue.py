"""Score-recompute queue (Valkey Streams).

Producers must call :func:`enqueue_recompute` *after* the originating
DB commit completes; the 5s debounce key relies on workers reading
post-commit state at recompute time.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import typing
from collections import abc

from valkey import asyncio as valkey

from imbi.common import blueprints, clickhouse, graph, models
from imbi.common.scoring import (
    AgePolicy,
    AnalysisResultPolicy,
    AttributePolicy,
    ConditionPolicy,
    DeploymentStatusPolicy,
    LinkPresencePolicy,
    PresencePolicy,
    clear_score,
    compute_score,
    record_score_change,
)

Policy = (
    AttributePolicy
    | PresencePolicy
    | LinkPresencePolicy
    | AgePolicy
    | AnalysisResultPolicy
    | DeploymentStatusPolicy
    | ConditionPolicy
)

STREAM = 'imbi:score-recompute'
GROUP = 'score-workers'
CONSUMER_PREFIX = 'worker'
DLQ = 'imbi:score-recompute:dlq'
DEBOUNCE_PREFIX = 'imbi:score-recompute:debounce'
DEBOUNCE_SECONDS = 5
MAX_DELIVERIES = 5
CLAIM_IDLE_MS = 60_000
DAILY_TICK_KEY_PREFIX = 'imbi:score-recompute:daily'
DAILY_TICK_HOUR_UTC = 6
DAILY_TICK_POLL_SECONDS = 3600.0

LOGGER = logging.getLogger(__name__)

ChangeReason = typing.Literal[
    'attribute_change',
    'blueprint_change',
    'policy_change',
    'bulk_rescore',
    'scheduled_recompute',
    'deployment_status_change',
    'dependency_change',
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


async def enqueue_recompute_bulk(
    client: valkey.Valkey | None,
    project_ids: abc.Iterable[str],
    reason: ChangeReason,
    requested_by: str | None = None,
) -> int:
    """Pipeline-batched version of :func:`enqueue_recompute`.

    Sends every debounce ``SET NX EX`` in one pipeline round trip,
    then sends every ``XADD`` for the acquired ids in a second
    pipeline. Returns the count of newly-enqueued jobs (the ones
    whose debounce SET succeeded).

    Designed for the admin-initiated bulk rescore path where
    ``project_ids`` may be in the thousands — the previous
    ``asyncio.gather`` over per-id calls produced 2N round trips
    plus N debounce-fail rejections taking a full round trip each.
    """
    ids = list(project_ids)
    if client is None or not ids:
        return 0
    requester = requested_by or 'system'
    try:
        async with client.pipeline(transaction=False) as pipe:
            for pid in ids:
                pipe.set(  # pyright: ignore[reportUnknownMemberType]
                    f'{DEBOUNCE_PREFIX}:{pid}',
                    b'1',
                    ex=DEBOUNCE_SECONDS,
                    nx=True,
                )
            # ``execute()`` is typed as ``list[Unknown]`` by valkey-py
            # — cast to the concrete shape we actually get from ``SET
            # NX EX``: ``True`` on acquire, ``None`` on conflict.
            set_results = typing.cast(
                'list[bool | None]', await pipe.execute()
            )
        accepted = [
            pid for pid, ok in zip(ids, set_results, strict=True) if ok
        ]
        if not accepted:
            return 0
        async with client.pipeline(transaction=False) as pipe:
            for pid in accepted:
                pipe.xadd(  # pyright: ignore[reportUnknownMemberType]
                    STREAM,
                    {
                        'project_id': pid,
                        'reason': reason,
                        'requested_by': requester,
                    },
                )
            await pipe.execute()
    except Exception:
        LOGGER.exception('enqueue_recompute_bulk failed (%d ids)', len(ids))
        return 0
    return len(accepted)


async def ensure_group(client: valkey.Valkey) -> None:
    try:
        await client.xgroup_create(STREAM, GROUP, id='$', mkstream=True)
    except Exception as err:  # noqa: BLE001
        msg = str(err)
        if 'BUSYGROUP' not in msg:
            LOGGER.warning('xgroup_create failed: %s', err)


async def affected_projects(
    db: graph.Graph,
    policy: Policy,
) -> list[str]:
    """Project ids that the policy applies to.

    For attribute/presence/age policies, ``policy.attribute_name`` must
    exist on the blueprint-extended Project model. For link_presence,
    analysis_result, deployment_status, and condition policies, no
    attribute check is required — they key off project links /
    analysis-report results / deployment edges / dependency relationships
    instead. In all cases, the result is intersected with the policy's
    TARGETS edges when set.
    """
    if not isinstance(
        policy,
        (
            LinkPresencePolicy,
            AnalysisResultPolicy,
            DeploymentStatusPolicy,
            ConditionPolicy,
        ),
    ):
        extended = await blueprints.get_model(db, models.Project)
        if policy.attribute_name not in extended.model_fields:
            return []
    if not policy.targets:
        return await all_project_ids(db)
    id_lists = await asyncio.gather(
        *[projects_of_type(db, slug) for slug in policy.targets]
    )
    seen: set[str] = set()
    result: list[str] = []
    for pids in id_lists:
        for pid in pids:
            if pid not in seen:
                seen.add(pid)
                result.append(pid)
    return result


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


_CONDITION_POLICY_EXISTS_QUERY: typing.LiteralString = (
    "MATCH (p:ScoringPolicy {{enabled: true, category: 'condition'}})"
    ' RETURN p.id AS id LIMIT 1'
)

_DEPENDENTS_QUERY: typing.LiteralString = (
    'MATCH (b:Project)-[:DEPENDS_ON]->(:Project {{id: {project_id}}})'
    ' RETURN b.id AS id'
)


async def condition_policies_exist(db: graph.Graph) -> bool:
    """Whether any enabled ``condition`` scoring policy is defined.

    Guards the dependent-cascade fan-out: relationship-aware scoring only
    matters when a condition policy exists, so the dependents query is
    skipped entirely otherwise.
    """
    try:
        rows = await db.execute(_CONDITION_POLICY_EXISTS_QUERY, {}, ['id'])
    except Exception:
        LOGGER.exception('condition_policies_exist check failed')
        return False
    return bool(rows)


async def dependent_project_ids(db: graph.Graph, project_id: str) -> list[str]:
    """Ids of projects with an outgoing ``DEPENDS_ON`` edge to *project_id*.

    These are the projects whose condition-policy scores can change when
    *project_id*'s attributes change (one hop — a relationship leaf reads
    the neighbour's attribute, not its score, so there is no transitive
    cascade).
    """
    try:
        rows = await db.execute(
            _DEPENDENTS_QUERY, {'project_id': project_id}, ['id']
        )
    except Exception:
        LOGGER.exception(
            'dependent_project_ids lookup failed for %s', project_id
        )
        return []
    return [v for r in rows if (v := graph.parse_agtype(r['id']))]


async def enqueue_dependents(
    client: valkey.Valkey | None,
    db: graph.Graph,
    project_id: str,
    reason: ChangeReason = 'dependency_change',
) -> int:
    """Enqueue re-score for projects that depend on *project_id*.

    No-op (returns 0) when no enabled condition policy exists, so the
    fan-out query is only paid for when relationship scoring is in use.
    """
    if client is None:
        return 0
    if not await condition_policies_exist(db):
        return 0
    dependents = await dependent_project_ids(db, project_id)
    return await enqueue_recompute_bulk(client, dependents, reason)


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
    LOGGER.info(
        'Recomputing score for project %s (reason: %s)', project_id, reason
    )
    score, breakdown = await compute_score(db, project_id)
    if score is None:
        LOGGER.info(
            'No applicable policies for %s; clearing score', project_id
        )
        await clear_score(db, project)
    else:
        LOGGER.info(
            'Project %s score: %.1f -> %.1f', project_id, previous, score
        )
        await record_score_change(
            ch, db, project, score, previous, reason, breakdown
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
    LOGGER.info(
        'Score recompute consumer loop running (consumer=%s)', consumer
    )
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


async def _enqueue_all(
    client: valkey.Valkey,
    db: graph.Graph,
    reason: ChangeReason,
) -> tuple[int, int]:
    project_ids = await all_project_ids(db)
    if not project_ids:
        return 0, 0
    results = await asyncio.gather(
        *[enqueue_recompute(client, pid, reason) for pid in project_ids]
    )
    return sum(results), len(project_ids)


async def run_daily_tick(
    client: valkey.Valkey,
    db: graph.Graph,
    *,
    hour_utc: int = DAILY_TICK_HOUR_UTC,
    poll_seconds: float = DAILY_TICK_POLL_SECONDS,
    stop: asyncio.Event | None = None,
    clock: typing.Callable[[], datetime.datetime] | None = None,
) -> None:
    """Once per UTC day at *hour_utc*, enqueue every project.

    Cross-worker single-firing is achieved via a Valkey SETNX with a
    25h TTL keyed by the current UTC date — only the first worker to
    cross the threshold each day performs the enqueue.
    """
    _now = clock or (lambda: datetime.datetime.now(datetime.UTC))
    LOGGER.info(
        'Daily scoring tick loop running (hour_utc=%s, poll=%.0fs)',
        hour_utc,
        poll_seconds,
    )
    while stop is None or not stop.is_set():
        now = _now()
        if now.hour >= hour_utc:
            try:
                await _try_daily_tick(client, db, now.date())
            except Exception:
                LOGGER.exception(
                    'daily scoring tick iteration failed (date=%s)',
                    now.date().isoformat(),
                )
        if stop is None:
            await asyncio.sleep(poll_seconds)
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
        except TimeoutError:
            continue


async def _try_daily_tick(
    client: valkey.Valkey,
    db: graph.Graph,
    date: datetime.date,
) -> None:
    key = f'{DAILY_TICK_KEY_PREFIX}:{date.isoformat()}'
    try:
        acquired = await client.set(key, b'1', ex=25 * 3600, nx=True)
    except Exception:
        LOGGER.exception('daily-tick lock acquisition failed')
        return
    if not acquired:
        return
    enqueued, total = await _enqueue_all(client, db, 'scheduled_recompute')
    LOGGER.info(
        'Daily scoring tick enqueued %s/%s projects for %s',
        enqueued,
        total,
        date.isoformat(),
    )
