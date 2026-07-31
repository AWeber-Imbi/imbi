"""Read-analytics ingest and reporting for documents.

Three surfaces:

- ``POST .../read-events`` -- the heartbeat sink. Fire-and-forget: it
  always answers 202 and a ClickHouse failure is logged, never
  surfaced. A reader already has their document; a failed analytics
  write must not look like a failed read.
- ``GET .../analytics`` (+ ``/readers``) -- one document's numbers.
- ``GET /document-analytics`` -- the org-wide report, whose main job
  is surfacing stale and never-read documents.

Every query filters to ``surface = 'web'`` unless asked otherwise:
human readership is the default answer, and agent fetches (MCP,
Assistant, Slackbot, API) would otherwise inflate it.

The write policy -- clamping, classification, finalization -- lives in
:mod:`_document_reads`; this module is the HTTP surface over it.
"""

import asyncio
import datetime
import logging
import typing

import fastapi
import fastapi.responses
import pydantic

from imbi.api.auth import permissions
from imbi.api.endpoints import _document_reads, _document_scope
from imbi.api.endpoints._pagination import (
    build_link_header,
    decode_cursor,
    encode_cursor,
)
from imbi.common import clickhouse, graph, valkey

LOGGER = logging.getLogger(__name__)

document_analytics_router = fastapi.APIRouter(tags=['Documents'])
document_analytics_org_router = fastapi.APIRouter(tags=['Documents'])

DEFAULT_LIMIT: int = 50
MAX_LIMIT: int = 500
#: Cap on heartbeats accepted in one request. A `sendBeacon` flush
#: carries at most a couple; anything larger is a client bug or an
#: attempt to bulk-write history.
MAX_EVENTS_PER_REQUEST: int = 20
DEFAULT_TREND_DAYS: int = 30

IDENTITY_PERMISSION = 'document:analytics:read_identities'


class ReadEvent(pydantic.BaseModel):
    """One heartbeat from a reading client."""

    session_id: str = pydantic.Field(min_length=1, max_length=64)
    seq: int = pydantic.Field(ge=0, le=1_000_000)
    session_started_at: datetime.datetime
    engaged_ms: int
    max_scroll_pct: int = pydantic.Field(default=0, ge=0, le=100)
    is_final: bool = False
    surface: _document_reads.Surface = 'web'


class ReadEventBatch(pydantic.BaseModel):
    events: list[ReadEvent] = pydantic.Field(min_length=1)


class SurfaceCount(pydantic.BaseModel):
    surface: str
    views: int


class TrendPoint(pydantic.BaseModel):
    day: datetime.date
    views: int
    readers: int


class DocumentAnalyticsResponse(pydantic.BaseModel):
    last_read_at: datetime.datetime | None = None
    readers: int = 0
    views: int = 0
    reads: int = 0
    median_engaged_seconds: int = 0
    p90_engaged_seconds: int = 0
    completion_rate: float = 0.0
    estimated_read_seconds: int = 0
    by_surface: list[SurfaceCount] = []
    trend: list[TrendPoint] = []
    identities_visible: bool = False


class ReaderRef(pydantic.BaseModel):
    principal: str
    last_read_at: datetime.datetime | None = None
    views: int = 0
    reads: int = 0
    engaged_seconds: int = 0


class ReaderListResponse(pydantic.BaseModel):
    data: list[ReaderRef]


class DocumentReadSummary(pydantic.BaseModel):
    document_id: str
    title: str = ''
    last_read_at: datetime.datetime | None = None
    readers: int = 0
    views: int = 0


class OrgAnalyticsResponse(pydantic.BaseModel):
    data: list[DocumentReadSummary]


# Collapses duplicate rows for one session before anything is counted.
# ``document_read_sessions`` is a ReplacingMergeTree, so the client's own
# final flush and a reaper sweep that raced it can both be live until a
# background merge runs. Counting them directly would double the session.
# Deduping explicitly makes every number independent of merge state.
_DEDUPED_SESSIONS = """
    SELECT session_id,
           argMax(principal, finalized_at)        AS principal,
           argMax(surface, finalized_at)          AS surface,
           argMax(document_id, finalized_at)      AS document_id,
           argMax(engaged_ms, finalized_at)       AS engaged_ms,
           argMax(is_view, finalized_at)          AS is_view,
           argMax(is_read, finalized_at)          AS is_read,
           argMax(started_at, finalized_at)       AS started_at,
           argMax(ended_at, finalized_at)         AS ended_at
    FROM imbi.document_read_sessions
    WHERE {filters}
    GROUP BY session_id
"""


def _session_source(filters: str) -> str:
    return _DEDUPED_SESSIONS.format(filters=filters)


def _surface_filter(surface: str) -> str:
    """SQL fragment restricting to one surface, or all of them."""
    return '' if surface == 'all' else ' AND surface = {surface:String}'


def _self_filter(include_self: bool) -> str:
    """Exclude the document's own author unless asked to include them.

    Editing a document should not inflate its readership.
    """
    return '' if include_self else ' AND principal != {author:String}'


async def _identities_setting(db: graph.Pool, org_slug: str) -> str:
    """The org's ``document_analytics_identities`` setting."""
    query: typing.LiteralString = (
        'MATCH (o:Organization {{slug: {org_slug}}}) '
        'RETURN o.document_analytics_identities AS setting'
    )
    records = await db.execute(
        query, {'org_slug': org_slug}, columns=['setting']
    )
    if not records:
        return 'authors_only'
    setting = graph.parse_agtype(records[0]['setting'])
    return str(setting) if setting else 'authors_only'


def _may_see_identities(
    auth: permissions.AuthContext, setting: str, author: str | None
) -> bool:
    """Whether ``auth`` may see *which people* read this document.

    A principal always sees their own history, which is handled by the
    caller; this governs seeing everyone else's.
    """
    if setting == 'disabled':
        return False
    holds_permission = IDENTITY_PERMISSION in auth.permissions or auth.is_admin
    if setting == 'enabled':
        return holds_permission
    # authors_only: the document's author sees its readers regardless of
    # role -- learning who reads your own work is not surveillance.
    return holds_permission or (
        author is not None and auth.principal_name == author
    )


@document_analytics_router.post('/read-events', status_code=202)
async def record_read_events(
    org_slug: str,
    document_id: str,
    batch: ReadEventBatch,
    db: graph.Pool,
    client: valkey.Client,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
    background_tasks: fastapi.BackgroundTasks,
) -> fastapi.Response:
    """Accept a batch of read heartbeats.

    Always 202, even when the write fails: the reader has already got
    what they came for and an analytics error is not their problem.
    Returns 404 only when the document does not resolve within the org,
    which is an authorization answer rather than an ingest one.
    """
    if len(batch.events) > MAX_EVENTS_PER_REQUEST:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'At most {MAX_EVENTS_PER_REQUEST} events per request',
        )

    meta = await _document_reads.load_document_meta(
        db, client, org_slug, document_id
    )
    if meta is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Document {document_id!r} not found'
        )

    now = datetime.datetime.now(datetime.UTC)
    rows: list[_document_reads.DocumentReadEventRow] = []
    finalize: list[str] = []
    for event in batch.events:
        engaged, clamped = _document_reads.clamp_engaged_ms(event.engaged_ms)
        rows.append(
            _document_reads.DocumentReadEventRow(
                org_slug=org_slug,
                document_id=document_id,
                session_id=event.session_id,
                seq=event.seq,
                principal=auth.principal_name,
                surface=event.surface,
                project_id=meta.project_id,
                document_version=meta.document_version,
                estimated_read_ms=meta.estimated_read_ms,
                session_started_at=event.session_started_at,
                recorded_at=now,
                engaged_ms=engaged,
                max_scroll_pct=event.max_scroll_pct,
                clamped=int(clamped),
                is_final=int(event.is_final),
            )
        )
        if event.is_final:
            finalize.append(event.session_id)

    # Both run after the response so ClickHouse latency never lands in
    # the reader's request.
    background_tasks.add_task(_document_reads.record_events, rows)
    if finalize:
        background_tasks.add_task(
            _document_reads.finalize_sessions, sorted(set(finalize))
        )
    return fastapi.Response(status_code=202)


_SUMMARY_SQL = """
SELECT maxIf(ended_at, is_read)                  AS last_read_at,
       uniqExactIf(principal, is_read)           AS readers,
       countIf(is_view)                          AS views,
       countIf(is_read)                          AS reads,
       quantileIf(0.5)(engaged_ms, is_view)      AS median_engaged_ms,
       quantileIf(0.9)(engaged_ms, is_view)      AS p90_engaged_ms
FROM ({source})
"""

_SURFACE_SQL = """
SELECT surface, countIf(is_view) AS views
FROM ({source})
GROUP BY surface
ORDER BY views DESC
"""

_TREND_SQL = """
SELECT toDate(started_at)              AS day,
       countIf(is_view)                AS views,
       uniqExactIf(principal, is_read) AS readers
FROM ({source})
GROUP BY day
ORDER BY day
"""


def _document_filters(surface: str, include_self: bool) -> str:
    return (
        'org_slug = {org_slug:String} AND document_id = {document_id:String}'
        + _surface_filter(surface)
        + _self_filter(include_self)
    )


@document_analytics_router.get(
    '/analytics', response_model=DocumentAnalyticsResponse
)
async def get_document_analytics(
    org_slug: str,
    document_id: str,
    db: graph.Pool,
    client: valkey.Client,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('document:analytics:read')
        ),
    ],
    surface: str = 'web',
    include_self: bool = False,
    trend_days: int = DEFAULT_TREND_DAYS,
) -> DocumentAnalyticsResponse:
    """Aggregate read analytics for one document."""
    if trend_days < 1 or trend_days > 365:
        raise fastapi.HTTPException(
            status_code=400, detail='trend_days must be 1..365'
        )
    # Independent of each other and of the ClickHouse reads below, so
    # they cost one round trip rather than two. The meta lookup doubles
    # as the org-scoped existence check and carries the author.
    meta, setting = await asyncio.gather(
        _document_reads.load_document_meta(db, client, org_slug, document_id),
        _identities_setting(db, org_slug),
    )
    if meta is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Document {document_id!r} not found'
        )
    author = meta.created_by

    params: dict[str, typing.Any] = {
        'org_slug': org_slug,
        'document_id': document_id,
        'surface': surface,
        'author': author,
    }
    source = _session_source(_document_filters(surface, include_self))
    trend_source = _session_source(
        _document_filters(surface, include_self)
        + ' AND started_at > now() - INTERVAL {trend_days:UInt32} DAY'
    )

    try:
        # Three independent scans of the same partition; running them
        # concurrently costs the slowest rather than the sum.
        summary_rows, surface_rows, trend_rows = await asyncio.gather(
            clickhouse.query(_SUMMARY_SQL.format(source=source), params),
            clickhouse.query(
                _SURFACE_SQL.format(
                    source=_session_source(
                        _document_filters('all', include_self)
                    )
                ),
                params,
            ),
            clickhouse.query(
                _TREND_SQL.format(source=trend_source),
                {**params, 'trend_days': trend_days},
            ),
        )
    except Exception:
        LOGGER.exception(
            'failed to read analytics for document %s', document_id
        )
        raise fastapi.HTTPException(
            status_code=503, detail='Analytics store unavailable'
        ) from None

    summary = summary_rows[0] if summary_rows else {}
    views = int(summary.get('views') or 0)
    reads = int(summary.get('reads') or 0)

    return DocumentAnalyticsResponse(
        last_read_at=clickhouse.as_utc_or_none(summary.get('last_read_at')),
        readers=int(summary.get('readers') or 0),
        views=views,
        reads=reads,
        median_engaged_seconds=int(
            float(summary.get('median_engaged_ms') or 0) / 1000
        ),
        p90_engaged_seconds=int(
            float(summary.get('p90_engaged_ms') or 0) / 1000
        ),
        completion_rate=(reads / views) if views else 0.0,
        estimated_read_seconds=int(meta.estimated_read_ms / 1000),
        by_surface=[
            SurfaceCount(
                surface=str(row.get('surface') or ''),
                views=int(row.get('views') or 0),
            )
            for row in surface_rows
        ],
        trend=[
            TrendPoint(
                day=row['day'],
                views=int(row.get('views') or 0),
                readers=int(row.get('readers') or 0),
            )
            for row in trend_rows
        ],
        identities_visible=_may_see_identities(auth, setting, author),
    )


_READERS_SQL = """
SELECT principal,
       max(ended_at)      AS last_read_at,
       countIf(is_view)   AS views,
       countIf(is_read)   AS reads,
       sum(engaged_ms)    AS engaged_ms
FROM ({source})
GROUP BY principal
{having}
ORDER BY last_read_at DESC, principal DESC
LIMIT {{row_limit:UInt32}}
"""


@document_analytics_router.get(
    '/analytics/readers', response_model=ReaderListResponse
)
async def list_document_readers(
    request: fastapi.Request,
    org_slug: str,
    document_id: str,
    db: graph.Pool,
    client: valkey.Client,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('document:analytics:read')
        ),
    ],
    surface: str = 'web',
    include_self: bool = False,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> fastapi.Response:
    """Per-reader detail: who read it, when, how often, how long.

    Gated by ``document:analytics:read_identities`` and the org's
    ``document_analytics_identities`` setting -- a named list of who
    read what is a different kind of data from an aggregate count.
    """
    if limit < 1 or limit > MAX_LIMIT:
        raise fastapi.HTTPException(
            status_code=400, detail=f'limit must be 1..{MAX_LIMIT}'
        )
    meta, setting = await asyncio.gather(
        _document_reads.load_document_meta(db, client, org_slug, document_id),
        _identities_setting(db, org_slug),
    )
    if meta is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Document {document_id!r} not found'
        )
    author = meta.created_by
    if not _may_see_identities(auth, setting, author):
        raise fastapi.HTTPException(
            status_code=403,
            detail='Not permitted to see who read this document',
        )

    params: dict[str, typing.Any] = {
        'org_slug': org_slug,
        'document_id': document_id,
        'surface': surface,
        'author': author,
        'row_limit': limit + 1,
    }
    having = ''
    if cursor is not None:
        decoded = decode_cursor(cursor)
        if decoded is None:
            raise fastapi.HTTPException(
                status_code=400, detail='Invalid cursor'
            )
        cursor_ts, cursor_principal = decoded
        having = (
            'HAVING (last_read_at < {cursor_ts:DateTime64(3)}'
            ' OR (last_read_at = {cursor_ts:DateTime64(3)}'
            ' AND principal < {cursor_principal:String}))'
        )
        params['cursor_ts'] = cursor_ts
        params['cursor_principal'] = cursor_principal

    sql = _READERS_SQL.format(
        source=_session_source(_document_filters(surface, include_self)),
        having=having,
    )
    try:
        rows = await clickhouse.query(sql, params)
    except Exception:
        LOGGER.exception('failed to list readers for document %s', document_id)
        raise fastapi.HTTPException(
            status_code=503, detail='Analytics store unavailable'
        ) from None

    readers = [
        ReaderRef(
            principal=str(row.get('principal') or ''),
            last_read_at=clickhouse.as_utc_or_none(row.get('last_read_at')),
            views=int(row.get('views') or 0),
            reads=int(row.get('reads') or 0),
            engaged_seconds=int(int(row.get('engaged_ms') or 0) / 1000),
        )
        for row in rows
    ]
    next_cursor: str | None = None
    if len(readers) > limit:
        readers = readers[:limit]
        last = readers[-1]
        if last.last_read_at is not None:
            next_cursor = encode_cursor(last.last_read_at, last.principal)

    adapter = pydantic.TypeAdapter(list[ReaderRef])
    response = fastapi.responses.JSONResponse(
        {'data': adapter.dump_python(readers, mode='json')}
    )
    response.headers['Link'] = build_link_header(request, next_cursor)
    return response


_ORG_SQL = """
SELECT document_id,
       max(ended_at)                   AS last_read_at,
       uniqExactIf(principal, is_read) AS readers,
       countIf(is_view)                AS views
FROM ({source})
GROUP BY document_id
{having}
ORDER BY {order}
LIMIT {{row_limit:UInt32}}
"""

_ORG_ORDER = {
    'most-read': 'readers DESC, views DESC',
    'least-read': 'readers ASC, views ASC',
    'stale': 'last_read_at ASC',
}

OrgMode = typing.Literal['most-read', 'least-read', 'stale', 'never-read']


@document_analytics_org_router.get('', response_model=OrgAnalyticsResponse)
async def get_org_document_analytics(
    org_slug: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('document:analytics:read')
        ),
    ],
    mode: OrgMode = 'most-read',
    surface: str = 'web',
    stale_days: int = 90,
    limit: int = DEFAULT_LIMIT,
) -> OrgAnalyticsResponse:
    """Org-wide read report.

    ``never-read`` is answered from the graph rather than ClickHouse --
    a document with no sessions has nothing to select -- by listing the
    org's documents and subtracting the ones that have been read.
    """
    if limit < 1 or limit > MAX_LIMIT:
        raise fastapi.HTTPException(
            status_code=400, detail=f'limit must be 1..{MAX_LIMIT}'
        )

    if mode == 'never-read':
        # The only mode that genuinely needs every document: what it
        # reports is the ones ClickHouse has never heard of.
        titles, read_ids = await asyncio.gather(
            _org_document_titles(db, org_slug),
            _read_document_ids(org_slug, surface),
        )
        never = [
            DocumentReadSummary(document_id=doc_id, title=title)
            for doc_id, title in titles.items()
            if doc_id not in read_ids
        ]
        return OrgAnalyticsResponse(
            data=sorted(never, key=lambda d: d.title)[:limit]
        )

    filters = 'org_slug = {org_slug:String}' + _surface_filter(surface)
    having = ''
    params: dict[str, typing.Any] = {
        'org_slug': org_slug,
        'surface': surface,
        'row_limit': limit,
    }
    if mode == 'stale':
        having = (
            'HAVING last_read_at < now() - INTERVAL {stale_days:UInt32} DAY'
        )
        params['stale_days'] = stale_days

    sql = _ORG_SQL.format(
        source=_session_source(filters),
        having=having,
        order=_ORG_ORDER[mode],
    )
    try:
        rows = await clickhouse.query(sql, params)
    except Exception:
        LOGGER.exception('failed to read org analytics for %s', org_slug)
        raise fastapi.HTTPException(
            status_code=503, detail='Analytics store unavailable'
        ) from None

    # Titles are fetched for the page ClickHouse returned, not for every
    # document in the org -- these modes decorate at most ``limit`` rows.
    titles = await _document_titles_by_id(
        db, org_slug, [str(row.get('document_id') or '') for row in rows]
    )
    return OrgAnalyticsResponse(
        data=[
            DocumentReadSummary(
                document_id=str(row.get('document_id') or ''),
                title=titles.get(str(row.get('document_id') or ''), ''),
                last_read_at=clickhouse.as_utc_or_none(
                    row.get('last_read_at')
                ),
                readers=int(row.get('readers') or 0),
                views=int(row.get('views') or 0),
            )
            for row in rows
        ]
    )


async def _org_document_titles(
    db: graph.Pool, org_slug: str
) -> dict[str, str]:
    """Every document in the org, as ``{id: title}``.

    Titles are joined in application code rather than duplicated into
    ClickHouse: the analytics tables key on ``document_id`` only, so a
    renamed document never leaves a stale title behind in a report.
    """
    query: typing.LiteralString = (
        _document_scope.ALL_IN_ORG
        + '    RETURN DISTINCT d.id AS id, d.title AS title'
    )
    records = await db.execute(
        query, {'org_slug': org_slug}, columns=['id', 'title']
    )
    return _parse_titles(records)


async def _document_titles_by_id(
    db: graph.Pool, org_slug: str, document_ids: list[str]
) -> dict[str, str]:
    """Titles for a known set of documents, as ``{id: title}``.

    Bounded companion to :func:`_org_document_titles` for the modes that
    only need to decorate the page ClickHouse already narrowed down.
    """
    ids = [doc_id for doc_id in dict.fromkeys(document_ids) if doc_id]
    if not ids:
        return {}
    query: typing.LiteralString = (
        # ``ALL_IN_ORG`` ends mid-WHERE, so this continues that clause
        # rather than opening a second one.
        _document_scope.ALL_IN_ORG
        + '      AND d.id IN {document_ids}\n'
        + '    RETURN DISTINCT d.id AS id, d.title AS title'
    )
    records = await db.execute(
        query,
        {'org_slug': org_slug, 'document_ids': ids},
        columns=['id', 'title'],
    )
    return _parse_titles(records)


def _parse_titles(
    records: list[dict[str, typing.Any]],
) -> dict[str, str]:
    titles: dict[str, str] = {}
    for record in records:
        doc_id = graph.parse_agtype(record['id'])
        if not doc_id:
            continue
        title = graph.parse_agtype(record['title'])
        titles[str(doc_id)] = str(title) if title else ''
    return titles


_READ_DOCUMENT_IDS_SQL = """
SELECT DISTINCT document_id
FROM imbi.document_read_sessions
WHERE org_slug = {{org_slug:String}} AND is_view = 1
{surface_filter}
"""


async def _read_document_ids(org_slug: str, surface: str) -> set[str]:
    """Ids of documents with at least one view, for ``never-read``."""
    # The only interpolated value is a module literal from
    # ``_surface_filter``; ``org_slug`` and ``surface`` reach ClickHouse
    # as bound parameters, never as interpolated text.
    sql = _READ_DOCUMENT_IDS_SQL.format(
        surface_filter=_surface_filter(surface)
    )
    try:
        rows = await clickhouse.query(
            sql, {'org_slug': org_slug, 'surface': surface}
        )
    except Exception:
        LOGGER.exception('failed to list read documents for %s', org_slug)
        raise fastapi.HTTPException(
            status_code=503, detail='Analytics store unavailable'
        ) from None
    return {str(row['document_id']) for row in rows if row.get('document_id')}
