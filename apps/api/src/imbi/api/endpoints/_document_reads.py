"""Read-tracking ingest and session finalization (ClickHouse write side).

Owns the engagement policy: what a heartbeat is allowed to claim
(:func:`clamp_engaged_ms`), what counts as a view versus a read
(:func:`classify`), and how an open session becomes a finalized one
(:func:`finalize_sessions`). The read-side endpoints live in
``document_analytics.py``.

Engaged time is measured entirely on the client -- only it can know
whether the tab was visible, focused, and being interacted with. The
server's job is to bound what a client can claim: every heartbeat
delta is clamped to slightly more than one heartbeat interval, so a
clock jump, a suspended debugger, or a hand-rolled client cannot
inflate a document's numbers. A clamped delta is stored clamped *and*
flagged, so the distortion is visible rather than silent.

Ingest is best-effort in the same sense as the version-history
recorder: the reader already got their document, so a failed
ClickHouse write is logged rather than surfaced.
"""

import datetime
import logging
import typing

import pydantic
from valkey import asyncio as valkey_asyncio

from imbi.api.endpoints import _document_scope
from imbi.common import clickhouse, graph

LOGGER = logging.getLogger(__name__)

Surface = typing.Literal['web', 'mcp', 'assistant', 'slackbot', 'api']

#: How often the client sends a heartbeat while a reader is engaged.
HEARTBEAT_INTERVAL_SECONDS = 15
#: Ceiling on a single heartbeat's claimed engaged time. The 1.5x cushion
#: absorbs a late beat (a busy main thread, a slow network) without
#: letting a beat claim time it could not have accumulated.
MAX_ENGAGED_DELTA_MS = int(HEARTBEAT_INTERVAL_SECONDS * 1500)
#: Engaged time below which a session is not a view at all. Filters
#: index-page prefetches, mis-clicks, and immediate back-navigations.
VIEW_FLOOR_MS = 5_000
#: Scroll depth at which a long document counts as read.
READ_SCROLL_PCT = 80
#: Reading speed used to derive a document's estimated read time.
WORDS_PER_MINUTE = 220
#: A session with no heartbeat for this long is finalized by the reaper.
SESSION_IDLE_TIMEOUT_SECONDS = 300
#: Lifetime of a cached document read-meta entry.
META_CACHE_TTL_SECONDS = 300

_META_KEY_PREFIX = 'imbi:document:readmeta'


class DocumentReadMeta(pydantic.BaseModel):
    """Facts about a document needed to record and classify a read.

    Also carries ``created_by`` so the analytics endpoints can exclude
    the author's own views without a second traversal of the same
    org-scoping join -- resolving the document already answers it.
    """

    project_id: str = ''
    document_version: int = 0
    estimated_read_ms: int = 0
    created_by: str = ''


class DocumentReadEventRow(pydantic.BaseModel):
    """One row in the ``document_read_events`` ClickHouse table."""

    org_slug: str
    document_id: str
    session_id: str
    seq: int
    principal: str
    surface: str
    project_id: str
    document_version: int
    estimated_read_ms: int
    session_started_at: datetime.datetime
    recorded_at: datetime.datetime
    engaged_ms: int
    max_scroll_pct: int
    clamped: int
    is_final: int


class DocumentReadSessionRow(pydantic.BaseModel):
    """One row in the ``document_read_sessions`` ClickHouse table."""

    org_slug: str
    document_id: str
    session_id: str
    principal: str
    surface: str
    project_id: str
    document_version: int
    started_at: datetime.datetime
    ended_at: datetime.datetime
    engaged_ms: int
    max_scroll_pct: int
    is_view: int
    is_read: int
    finalized_at: datetime.datetime


def estimated_read_ms(content: str) -> int:
    """Milliseconds an average reader needs for ``content``.

    Whitespace-delimited word count over :data:`WORDS_PER_MINUTE`. Used
    as the dwell threshold that marks a *short* document as read -- long
    documents reach the read threshold by scroll depth first.
    """
    words = len(content.split())
    if not words:
        return 0
    return int(words / WORDS_PER_MINUTE * 60_000)


def clamp_engaged_ms(value: int) -> tuple[int, bool]:
    """Bound a heartbeat's claimed engaged time.

    Returns the value to store and whether it was clamped. Negative
    values clamp to zero: a client that reports one has a broken clock,
    and subtracting time is never a legitimate correction.
    """
    if value < 0:
        return 0, True
    if value > MAX_ENGAGED_DELTA_MS:
        return MAX_ENGAGED_DELTA_MS, True
    return value, False


def classify(
    *, surface: str, engaged_ms: int, max_scroll_pct: int, read_ms: int
) -> tuple[bool, bool]:
    """Decide whether a finalized session is a view and/or a read.

    A view needs :data:`VIEW_FLOOR_MS` of engaged time. A read needs a
    view that also reached :data:`READ_SCROLL_PCT` scroll depth *or*
    dwelled for the document's estimated read time -- long documents
    qualify by scrolling, short ones by dwelling.

    Non-web surfaces (MCP, Assistant, Slackbot, API) have no attention
    to measure, so they record as a view -- the document was fetched --
    and never as a read. Reporting filters to ``web`` by default, so
    these never mix into human numbers.
    """
    if surface != 'web':
        return True, False
    if engaged_ms < VIEW_FLOOR_MS:
        return False, False
    is_read = max_scroll_pct >= READ_SCROLL_PCT or (
        read_ms > 0 and engaged_ms >= read_ms
    )
    return True, is_read


def _meta_key(org_slug: str, document_id: str) -> str:
    return f'{_META_KEY_PREFIX}:{org_slug}:{document_id}'


# Resolves the document within the org through whichever vertex it is
# attached to, and returns everything needed to stamp and classify a
# read. ``content`` is only used to derive the estimated read time; it is
# never stored on a read event.
_META_QUERY: typing.LiteralString = (
    _document_scope.BY_ID
    + '    RETURN p.id AS project_id, d.version AS version,'
    + ' d.content AS content, d.created_by AS created_by'
)


async def load_document_meta(
    db: graph.Pool,
    client: valkey_asyncio.Valkey | None,
    org_slug: str,
    document_id: str,
) -> DocumentReadMeta | None:
    """Read-meta for a document, cached in Valkey.

    Returns ``None`` when the document does not resolve within the org,
    which is how the ingest endpoint rejects a read event for a document
    the caller cannot see.

    The cache exists because heartbeats arrive every few seconds per
    open reader; a graph round-trip per beat would be wasted load for
    facts that change only when the document is edited. A stale entry
    costs at most :data:`META_CACHE_TTL_SECONDS` of reads classified
    against the previous revision's length.
    """
    key = _meta_key(org_slug, document_id)
    if client is not None:
        try:
            cached = await client.get(key)
        except Exception:  # noqa: BLE001
            LOGGER.debug('read-meta cache read failed', exc_info=True)
            cached = None
        if cached is not None:
            try:
                raw = cached.decode() if isinstance(cached, bytes) else cached
                return DocumentReadMeta.model_validate_json(raw)
            except (ValueError, pydantic.ValidationError):
                LOGGER.debug('discarding malformed read-meta cache entry')

    records = await db.execute(
        _META_QUERY,
        {'document_id': document_id, 'org_slug': org_slug},
        columns=['project_id', 'version', 'content', 'created_by'],
    )
    if not records:
        return None
    project_id = graph.parse_agtype(records[0]['project_id'])
    version = graph.parse_agtype(records[0]['version'])
    content = graph.parse_agtype(records[0]['content'])
    created_by = graph.parse_agtype(records[0]['created_by'])
    meta = DocumentReadMeta(
        project_id=str(project_id) if project_id else '',
        document_version=int(version or 1),
        estimated_read_ms=estimated_read_ms(str(content or '')),
        created_by=str(created_by) if created_by else '',
    )
    if client is not None:
        try:
            await client.set(
                key, meta.model_dump_json(), ex=META_CACHE_TTL_SECONDS
            )
        except Exception:  # noqa: BLE001
            LOGGER.debug('read-meta cache write failed', exc_info=True)
    return meta


async def record_events(rows: list[DocumentReadEventRow]) -> None:
    """Insert heartbeat rows. Best-effort; never raises."""
    if not rows:
        return
    try:
        await clickhouse.insert(
            'document_read_events',
            typing.cast('list[pydantic.BaseModel]', rows),
        )
    except Exception:
        LOGGER.exception(
            'failed to record %d read event(s) for document %s',
            len(rows),
            rows[0].document_id,
        )


# Aggregates a session's heartbeats into the facts a finalized row needs.
#
# The inner GROUP BY collapses duplicate deliveries of the same
# ``(session_id, seq)`` before anything is summed. The raw table is a
# ReplacingMergeTree, so a retried heartbeat and its twin can both be
# live until a background merge runs -- summing them directly would
# double-count that beat's engaged time. Deduping explicitly makes the
# result independent of merge state, which ``FINAL`` would not do
# cheaply here: ``session_id`` is the third key column, so filtering on
# it alone cannot use the primary key.
_SESSION_AGGREGATE_SQL = """
SELECT org_slug,
       document_id,
       session_id,
       any(principal)          AS principal,
       any(surface)            AS surface,
       any(project_id)         AS project_id,
       max(document_version)   AS document_version,
       max(estimated_read_ms)  AS estimated_read_ms,
       min(session_started_at) AS started_at,
       max(recorded_at)        AS ended_at,
       sum(engaged_ms)         AS engaged_ms,
       max(max_scroll_pct)     AS max_scroll_pct
FROM (
    SELECT org_slug,
           document_id,
           session_id,
           seq,
           argMax(principal, recorded_at)          AS principal,
           argMax(surface, recorded_at)            AS surface,
           argMax(project_id, recorded_at)         AS project_id,
           argMax(document_version, recorded_at)   AS document_version,
           argMax(estimated_read_ms, recorded_at)  AS estimated_read_ms,
           min(session_started_at)                 AS session_started_at,
           max(recorded_at)                        AS recorded_at,
           argMax(engaged_ms, recorded_at)         AS engaged_ms,
           argMax(max_scroll_pct, recorded_at)     AS max_scroll_pct
    FROM imbi.document_read_events
    WHERE session_id IN {session_ids:Array(String)}
    GROUP BY org_slug, document_id, session_id, seq
)
GROUP BY org_slug, document_id, session_id
"""


async def finalize_sessions(session_ids: list[str]) -> int:
    """Write a finalized row for each of ``session_ids``.

    Returns the number of sessions written. Idempotent: the sessions
    table dedups on ``session_id``, so the client's own final flush and
    a reaper sweep racing each other converge on one row rather than
    double-counting the session. Best-effort; never raises.
    """
    if not session_ids:
        return 0
    try:
        aggregates = await clickhouse.query(
            _SESSION_AGGREGATE_SQL, {'session_ids': session_ids}
        )
    except Exception:
        LOGGER.exception('failed to aggregate %d session(s)', len(session_ids))
        return 0

    now = datetime.datetime.now(datetime.UTC)
    rows: list[pydantic.BaseModel] = []
    for row in aggregates:
        surface = str(row.get('surface') or 'web')
        engaged = int(row.get('engaged_ms') or 0)
        scroll = int(row.get('max_scroll_pct') or 0)
        read_ms = int(row.get('estimated_read_ms') or 0)
        is_view, is_read = classify(
            surface=surface,
            engaged_ms=engaged,
            max_scroll_pct=scroll,
            read_ms=read_ms,
        )
        rows.append(
            DocumentReadSessionRow(
                org_slug=str(row.get('org_slug') or ''),
                document_id=str(row.get('document_id') or ''),
                session_id=str(row.get('session_id') or ''),
                principal=str(row.get('principal') or ''),
                surface=surface,
                project_id=str(row.get('project_id') or ''),
                document_version=int(row.get('document_version') or 0),
                started_at=clickhouse.as_utc(row['started_at']),
                ended_at=clickhouse.as_utc(row['ended_at']),
                engaged_ms=engaged,
                max_scroll_pct=scroll,
                is_view=int(is_view),
                is_read=int(is_read),
                finalized_at=now,
            )
        )
    if not rows:
        return 0
    try:
        await clickhouse.insert('document_read_sessions', rows)
    except Exception:
        LOGGER.exception('failed to finalize %d session(s)', len(rows))
        return 0
    return len(rows)


#: How far back the reaper looks for sessions still open. The sweep runs
#: every minute, so anything unfinalized is normally minutes old; a day
#: is generous cover for an instance that was down. A session older than
#: this is left to the raw table's own TTL, which is the same outcome as
#: never having been finalized.
SWEEP_LOOKBACK_HOURS = 24

# Sessions whose last heartbeat has aged past the idle timeout and that
# have no finalized row yet.
#
# Both sides are pinned to the same recent window so neither scans more
# than the other needs: without the `recorded_at` bound the outer scan
# reads whole partitions, since `session_started_at` is not part of the
# table's `ORDER BY` and only prunes by partition. The anti-join is a
# LEFT JOIN rather than `NOT IN` so the right side stays a bounded
# hash-side rather than a materialized id set.
_STALE_SESSION_SQL = """
SELECT e.session_id AS session_id
FROM (
    SELECT session_id, max(recorded_at) AS last_beat
    FROM imbi.document_read_events
    WHERE session_started_at > now() - INTERVAL {lookback_hours:UInt32} HOUR
      AND recorded_at > now() - INTERVAL {lookback_hours:UInt32} HOUR
    GROUP BY session_id
    HAVING last_beat < now() - INTERVAL {idle_seconds:UInt32} SECOND
) AS e
LEFT JOIN (
    SELECT DISTINCT session_id
    FROM imbi.document_read_sessions
    WHERE started_at > now() - INTERVAL {lookback_hours:UInt32} HOUR
) AS s USING (session_id)
WHERE s.session_id = ''
LIMIT {batch:UInt32}
"""


async def stale_session_ids(batch: int = 500) -> list[str]:
    """Sessions with no heartbeat since the idle timeout and no final row."""
    try:
        rows = await clickhouse.query(
            _STALE_SESSION_SQL,
            {
                'idle_seconds': SESSION_IDLE_TIMEOUT_SECONDS,
                'lookback_hours': SWEEP_LOOKBACK_HOURS,
                'batch': batch,
            },
        )
    except Exception:
        LOGGER.exception('failed to list stale read sessions')
        return []
    return [str(row['session_id']) for row in rows if row.get('session_id')]
