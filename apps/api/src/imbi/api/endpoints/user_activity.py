"""User profile activity endpoints.

Aggregates per-user activity from ClickHouse (`operations_log`,
`events`) and the AGE graph (`Document`, `Release`, `Upload`,
`Conversation`) into a small set of read-only endpoints that power the
v2 UI's user profile page.

All endpoints are mounted on the existing :data:`users_router` so they
share the ``/users`` prefix and the OpenAPI tag.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import typing
import zoneinfo

import fastapi
import fastapi.encoders
import fastapi.responses
import pydantic

from imbi.api.auth import permissions
from imbi.api.endpoints._pagination import (
    build_link_header,
    decode_cursor,
    encode_cursor,
    parse_iso,
)
from imbi.api.endpoints.users import users_router
from imbi.common import clickhouse, graph

LOGGER = logging.getLogger(__name__)


DEFAULT_WINDOW_DAYS: int = 365
DEFAULT_ACTIVITY_LIMIT: int = 20
MAX_ACTIVITY_LIMIT: int = 100


ActivitySource = typing.Literal[
    'operations_log',
    'events',
    'document',
    'release',
    'upload',
    'conversation',
]


class ContributionBucket(pydantic.BaseModel):
    date: datetime.date
    count: int
    by_source: dict[str, int]


class ContributionsResponse(pydantic.BaseModel):
    total: int
    since: datetime.datetime
    until: datetime.datetime
    tz: str
    buckets: list[ContributionBucket]


class DeploymentStats(pydantic.BaseModel):
    total: int
    rolled_back: int
    success_rate: float | None


class StatsResponse(pydantic.BaseModel):
    since: datetime.datetime
    until: datetime.datetime
    deployments: DeploymentStats
    projects_touched: int
    deployments_by_environment: dict[str, int]


class IdentityRecord(pydantic.BaseModel):
    provider: str
    provider_user_id: str
    email: str | None = None
    display_name: str | None = None
    linked_at: datetime.datetime | None = None
    last_used: datetime.datetime | None = None


class IdentitiesResponse(pydantic.BaseModel):
    primary: IdentityRecord | None
    all: list[IdentityRecord]


class ActivityRecord(pydantic.BaseModel):
    id: str
    source: ActivitySource
    occurred_at: datetime.datetime
    summary: str
    type: str
    environment_slug: str | None = None
    project_id: str | None = None
    project_slug: str | None = None
    link: str | None = None


class ActivityResponse(pydantic.BaseModel):
    data: list[ActivityRecord]


def _resolve_tz(tz: str) -> zoneinfo.ZoneInfo:
    """Validate ``tz`` as an IANA timezone, returning a ZoneInfo.

    Raises a 400 ``HTTPException`` for unknown identifiers so we never
    forward invalid values into ClickHouse date functions.
    """
    try:
        return zoneinfo.ZoneInfo(tz)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as err:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Invalid timezone identifier: {tz!r}',
        ) from err


def _resolve_window(
    since: str | None,
    until: str | None,
) -> tuple[datetime.datetime, datetime.datetime]:
    end = (
        parse_iso(until, 'until')
        if until is not None
        else datetime.datetime.now(datetime.UTC)
    )
    start = (
        parse_iso(since, 'since')
        if since is not None
        else end - datetime.timedelta(days=DEFAULT_WINDOW_DAYS)
    )
    if start >= end:
        raise fastapi.HTTPException(
            status_code=400,
            detail='`since` must be earlier than `until`',
        )
    return start, end


async def _ensure_user_exists(db: graph.Graph, email: str) -> None:
    rows = await db.execute(
        'MATCH (u:User {{email: {email}}}) RETURN u.id AS id LIMIT 1',
        {'email': email},
        ['id'],
    )
    if not rows:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'User with email {email!r} not found',
        )


async def _resolve_user_subjects(db: graph.Graph, email: str) -> list[str]:
    """Return the user's external identity subjects.

    Includes both legacy ``OAuthIdentity`` provider_user_ids and current
    ``IdentityConnection`` subjects so the events leg can match either
    attribution mechanism.
    """
    rows = await db.execute(
        """
        MATCH (u:User {{email: {email}}})
        OPTIONAL MATCH (u)-[:HAS_IDENTITY]->(c:IdentityConnection)
        OPTIONAL MATCH (oi:OAuthIdentity)-[:OAUTH_IDENTITY]->(u)
        RETURN
            collect(DISTINCT c.subject) AS conn_subjects,
            collect(DISTINCT oi.provider_user_id) AS oauth_subjects
        """,
        {'email': email},
        ['conn_subjects', 'oauth_subjects'],
    )
    if not rows:
        return []
    subjects: set[str] = set()
    for column in ('conn_subjects', 'oauth_subjects'):
        parsed = graph.parse_agtype(rows[0].get(column))
        if isinstance(parsed, list):
            items: list[typing.Any] = parsed  # pyright: ignore[reportUnknownVariableType]
            for value in items:
                if value:
                    subjects.add(str(value))
    return sorted(subjects)


def _coerce_dt(value: typing.Any) -> datetime.datetime | None:
    if value is None:
        return None
    parsed = graph.parse_agtype(value) if not isinstance(value, str) else value
    if not parsed:
        return None
    if isinstance(parsed, datetime.datetime):
        dt = parsed
    else:
        try:
            dt = datetime.datetime.fromisoformat(str(parsed))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt.astimezone(datetime.UTC)


# ---------------------------------------------------------------------------
# /contributions
# ---------------------------------------------------------------------------


async def _opslog_buckets(
    *,
    email: str,
    since: datetime.datetime,
    until: datetime.datetime,
    tz: str,
) -> dict[datetime.date, int]:
    sql: str = (
        'SELECT toDate(toStartOfDay(occurred_at, {tz:String})) AS d, '
        'count() AS c '
        'FROM operations_log FINAL '
        'WHERE is_deleted = 0 '
        '  AND performed_by = {email:String} '
        '  AND occurred_at >= {since:DateTime64(3)} '
        '  AND occurred_at <  {until:DateTime64(3)} '
        'GROUP BY d'
    )
    rows = await clickhouse.query(
        sql,
        {'email': email, 'since': since, 'until': until, 'tz': tz},
    )
    return {row['d']: int(row['c']) for row in rows if row.get('d')}


async def _events_buckets(
    *,
    subjects: list[str],
    since: datetime.datetime,
    until: datetime.datetime,
    tz: str,
) -> dict[datetime.date, int]:
    if not subjects:
        return {}
    sql: str = (
        'SELECT toDate(toStartOfDay(recorded_at, {tz:String})) AS d, '
        'count() AS c '
        'FROM events '
        'WHERE attributed_to IN {subjects:Array(String)} '
        '  AND recorded_at >= {since:DateTime64(3)} '
        '  AND recorded_at <  {until:DateTime64(3)} '
        'GROUP BY d'
    )
    rows = await clickhouse.query(
        sql,
        {'subjects': subjects, 'since': since, 'until': until, 'tz': tz},
    )
    return {row['d']: int(row['c']) for row in rows if row.get('d')}


_GRAPH_BUCKET_QUERIES: dict[str, str] = {
    'document': """
        MATCH (n:Document)
        WHERE (n.created_by = {email}
               OR n.updated_by = {email})
          AND n.created_at >= {since}
          AND n.created_at <  {until}
        RETURN n.created_at AS ts
    """,
    'release': """
        MATCH (r:Release {{created_by: {email}}})
        WHERE r.created_at >= {since}
          AND r.created_at <  {until}
        RETURN r.created_at AS ts
    """,
    'upload': """
        MATCH (u:Upload {{uploaded_by: {email}}})
        WHERE u.created_at >= {since}
          AND u.created_at <  {until}
        RETURN u.created_at AS ts
    """,
    'conversation': """
        MATCH (c:Conversation {{user_email: {email}}})
        WHERE c.created_at >= {since}
          AND c.created_at <  {until}
        RETURN c.created_at AS ts
    """,
}


async def _graph_buckets(
    db: graph.Graph,
    *,
    label: str,
    email: str,
    since: datetime.datetime,
    until: datetime.datetime,
    zone: zoneinfo.ZoneInfo,
) -> dict[datetime.date, int]:
    template = _GRAPH_BUCKET_QUERIES[label]
    rows = await db.execute(
        template,
        {
            'email': email,
            'since': since.isoformat(),
            'until': until.isoformat(),
        },
        ['ts'],
    )

    counts: dict[datetime.date, int] = {}
    for row in rows:
        dt = _coerce_dt(row.get('ts'))
        if dt is None:
            continue
        local = dt.astimezone(zone)
        day = local.date()
        counts[day] = counts.get(day, 0) + 1
    return counts


@users_router.get(
    '/{email}/contributions', response_model=ContributionsResponse
)
async def get_user_contributions(
    email: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:read')),
    ],
    since: str | None = None,
    until: str | None = None,
    tz: str = 'UTC',
) -> ContributionsResponse:
    """Return per-day contribution counts for the user.

    Aggregates ClickHouse opslog/events with graph-authored items (Document,
    Release, Upload, Conversation) into one daily map keyed by the
    requested ``tz``.
    """
    await _ensure_user_exists(db, email)
    zone = _resolve_tz(tz)
    start, end = _resolve_window(since, until)

    subjects = await _resolve_user_subjects(db, email)
    legs = await asyncio.gather(
        _opslog_buckets(email=email, since=start, until=end, tz=tz),
        _events_buckets(subjects=subjects, since=start, until=end, tz=tz),
        _graph_buckets(
            db,
            label='document',
            email=email,
            since=start,
            until=end,
            zone=zone,
        ),
        _graph_buckets(
            db,
            label='release',
            email=email,
            since=start,
            until=end,
            zone=zone,
        ),
        _graph_buckets(
            db,
            label='upload',
            email=email,
            since=start,
            until=end,
            zone=zone,
        ),
        _graph_buckets(
            db,
            label='conversation',
            email=email,
            since=start,
            until=end,
            zone=zone,
        ),
    )
    leg_names = (
        'operations_log',
        'events',
        'document',
        'release',
        'upload',
        'conversation',
    )

    by_day: dict[datetime.date, dict[str, int]] = {}
    total = 0
    for source, leg in zip(leg_names, legs, strict=True):
        for day, count in leg.items():
            total += count
            day_map = by_day.setdefault(day, {})
            day_map[source] = day_map.get(source, 0) + count

    buckets = [
        ContributionBucket(
            date=day,
            count=sum(by_source.values()),
            by_source=dict(by_source),
        )
        for day, by_source in sorted(by_day.items())
    ]
    return ContributionsResponse(
        total=total,
        since=start,
        until=end,
        tz=tz,
        buckets=buckets,
    )


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------


async def _projects_touched(
    db: graph.Graph,
    *,
    email: str,
    subjects: list[str],
    since: datetime.datetime,
    until: datetime.datetime,
) -> int:
    """Distinct project_ids the user touched across all activity sources."""
    project_ids: set[str] = set()

    opslog_rows = await clickhouse.query(
        'SELECT DISTINCT project_id FROM operations_log FINAL '
        'WHERE is_deleted = 0 '
        '  AND performed_by = {email:String} '
        '  AND occurred_at >= {since:DateTime64(3)} '
        '  AND occurred_at <  {until:DateTime64(3)}',
        {'email': email, 'since': since, 'until': until},
    )
    for row in opslog_rows:
        pid = row.get('project_id')
        if pid:
            project_ids.add(str(pid))

    if subjects:
        events_rows = await clickhouse.query(
            'SELECT DISTINCT project_id FROM events '
            'WHERE attributed_to IN {subjects:Array(String)} '
            '  AND recorded_at >= {since:DateTime64(3)} '
            '  AND recorded_at <  {until:DateTime64(3)}',
            {'subjects': subjects, 'since': since, 'until': until},
        )
        for row in events_rows:
            pid = row.get('project_id')
            if pid:
                project_ids.add(str(pid))

    graph_rows = await db.execute(
        """
        MATCH (p:Project)
        OPTIONAL MATCH (p)<-[:ATTACHED_TO]-(n:Document)
        WHERE (n.created_by = {email} OR n.updated_by = {email})
          AND n.created_at >= {since}
          AND n.created_at <  {until}
        WITH p, count(n) AS document_count
        OPTIONAL MATCH (p)-[:HAS_RELEASE]->(r:Release {{created_by: {email}}})
        WHERE r.created_at >= {since} AND r.created_at < {until}
        WITH p, document_count, count(r) AS release_count
        WHERE document_count + release_count > 0
        RETURN DISTINCT p.id AS project_id
        """,
        {
            'email': email,
            'since': since.isoformat(),
            'until': until.isoformat(),
        },
        ['project_id'],
    )
    for row in graph_rows:
        pid = graph.parse_agtype(row.get('project_id'))
        if pid:
            project_ids.add(str(pid))

    return len(project_ids)


@users_router.get('/{email}/stats', response_model=StatsResponse)
async def get_user_stats(
    email: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:read')),
    ],
    since: str | None = None,
    until: str | None = None,
    tz: str = 'UTC',
) -> StatsResponse:
    """Return summary deployment / project tiles for the profile page."""
    _resolve_tz(tz)  # validate even though stats does not bucket by tz
    await _ensure_user_exists(db, email)
    start, end = _resolve_window(since, until)
    subjects = await _resolve_user_subjects(db, email)

    deploy_totals_sql = (
        'SELECT '
        "countIf(entry_type = 'Deployed') AS deployed, "
        "countIf(entry_type = 'Rolled Back') AS rolled_back "
        'FROM operations_log FINAL '
        'WHERE is_deleted = 0 '
        '  AND performed_by = {email:String} '
        '  AND occurred_at >= {since:DateTime64(3)} '
        '  AND occurred_at <  {until:DateTime64(3)}'
    )
    by_env_sql = (
        'SELECT environment_slug, count() AS c '
        'FROM operations_log FINAL '
        'WHERE is_deleted = 0 '
        '  AND performed_by = {email:String} '
        "  AND entry_type = 'Deployed' "
        '  AND occurred_at >= {since:DateTime64(3)} '
        '  AND occurred_at <  {until:DateTime64(3)} '
        'GROUP BY environment_slug'
    )
    params = {'email': email, 'since': start, 'until': end}

    totals_rows, env_rows, projects_touched = await asyncio.gather(
        clickhouse.query(deploy_totals_sql, params),
        clickhouse.query(by_env_sql, params),
        _projects_touched(
            db,
            email=email,
            subjects=subjects,
            since=start,
            until=end,
        ),
    )

    totals = totals_rows[0] if totals_rows else {}
    deployed = int(totals.get('deployed', 0) or 0)
    rolled_back = int(totals.get('rolled_back', 0) or 0)
    success_rate: float | None = None
    if deployed > 0:
        success_rate = max(0.0, 1.0 - (rolled_back / deployed))

    deploys_by_env = {
        str(row['environment_slug']): int(row['c'])
        for row in env_rows
        if row.get('environment_slug')
    }

    return StatsResponse(
        since=start,
        until=end,
        deployments=DeploymentStats(
            total=deployed,
            rolled_back=rolled_back,
            success_rate=success_rate,
        ),
        projects_touched=projects_touched,
        deployments_by_environment=deploys_by_env,
    )


# ---------------------------------------------------------------------------
# /identities
# ---------------------------------------------------------------------------


@users_router.get('/{email}/identities', response_model=IdentitiesResponse)
async def get_user_identities(
    email: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:read')),
    ],
) -> IdentitiesResponse:
    """Return the user's linked OAuth identities (no tokens)."""
    await _ensure_user_exists(db, email)

    rows = await db.execute(
        """
        MATCH (oi:OAuthIdentity)-[:OAUTH_IDENTITY]->(u:User {{email: {email}}})
        RETURN oi.provider AS provider,
               oi.provider_user_id AS provider_user_id,
               oi.email AS email,
               oi.display_name AS display_name,
               oi.linked_at AS linked_at,
               oi.last_used AS last_used
        """,
        {'email': email},
        [
            'provider',
            'provider_user_id',
            'email',
            'display_name',
            'linked_at',
            'last_used',
        ],
    )

    identities: list[IdentityRecord] = []
    for row in rows:
        identities.append(
            IdentityRecord(
                provider=str(graph.parse_agtype(row.get('provider')) or ''),
                provider_user_id=str(
                    graph.parse_agtype(row.get('provider_user_id')) or ''
                ),
                email=(
                    str(graph.parse_agtype(row.get('email')))
                    if row.get('email') is not None
                    else None
                ),
                display_name=(
                    str(graph.parse_agtype(row.get('display_name')))
                    if row.get('display_name') is not None
                    else None
                ),
                linked_at=_coerce_dt(row.get('linked_at')),
                last_used=_coerce_dt(row.get('last_used')),
            )
        )

    def _sort_key(rec: IdentityRecord) -> tuple[float, float]:
        last = rec.last_used.timestamp() if rec.last_used else 0.0
        linked = rec.linked_at.timestamp() if rec.linked_at else 0.0
        return (last, linked)

    sorted_identities = sorted(identities, key=_sort_key, reverse=True)
    primary = sorted_identities[0] if sorted_identities else None
    return IdentitiesResponse(primary=primary, all=sorted_identities)


# ---------------------------------------------------------------------------
# /activity
# ---------------------------------------------------------------------------


async def _opslog_activity(
    *,
    email: str,
    before: datetime.datetime,
    limit: int,
) -> list[ActivityRecord]:
    sql: str = (
        'SELECT id, occurred_at, entry_type, environment_slug, '
        'project_id, project_slug, description, version '
        'FROM operations_log FINAL '
        'WHERE is_deleted = 0 '
        '  AND performed_by = {email:String} '
        '  AND occurred_at <= {before:DateTime64(3)} '
        'ORDER BY occurred_at DESC, id DESC '
        'LIMIT {row_limit:UInt32}'
    )
    rows = await clickhouse.query(
        sql,
        {'email': email, 'before': before, 'row_limit': limit},
    )
    out: list[ActivityRecord] = []
    for row in rows:
        ts = row['occurred_at']
        if isinstance(ts, datetime.datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.UTC)
        version = row.get('version')
        env = row.get('environment_slug') or ''
        entry_type = str(row.get('entry_type') or '')
        version_part = f' {version}' if version else ''
        env_part = f' to {env}' if env else ''
        description = row.get('description') or ''
        summary = f'{entry_type}{version_part}{env_part}'
        if description:
            summary = f'{summary} — {description}'
        out.append(
            ActivityRecord(
                id=str(row['id']),
                source='operations_log',
                occurred_at=ts,
                summary=summary,
                type=entry_type,
                environment_slug=env or None,
                project_id=row.get('project_id') or None,
                project_slug=row.get('project_slug') or None,
                link=(
                    f'/operations-log/{row["id"]}' if row.get('id') else None
                ),
            )
        )
    return out


async def _events_activity(
    *,
    subjects: list[str],
    before: datetime.datetime,
    limit: int,
) -> list[ActivityRecord]:
    if not subjects:
        return []
    sql: str = (
        'SELECT id, recorded_at, type, integration, '
        'project_id, metadata '
        'FROM events '
        'WHERE attributed_to IN {subjects:Array(String)} '
        '  AND recorded_at <= {before:DateTime64(3)} '
        'ORDER BY recorded_at DESC, id DESC '
        'LIMIT {row_limit:UInt32}'
    )
    rows = await clickhouse.query(
        sql,
        {'subjects': subjects, 'before': before, 'row_limit': limit},
    )
    out: list[ActivityRecord] = []
    for row in rows:
        ts = row['recorded_at']
        if isinstance(ts, datetime.datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.UTC)
        meta_raw: typing.Any = row.get('metadata') or {}
        meta_summary: str | None = None
        if isinstance(meta_raw, dict):
            meta_dict = typing.cast(
                'dict[str, typing.Any]',
                meta_raw,  # pyright: ignore[reportUnknownArgumentType]
            )
            value = meta_dict.get('summary')
            if isinstance(value, str):
                meta_summary = value
        type_str = str(row.get('type') or '')
        service = str(row.get('integration') or '')
        head = type_str
        if service:
            head = f'{type_str} via {service}' if type_str else service
        summary = f'{head} — {meta_summary}' if meta_summary else head
        out.append(
            ActivityRecord(
                id=str(row['id']),
                source='events',
                occurred_at=ts,
                summary=summary,
                type=type_str,
                project_id=row.get('project_id') or None,
            )
        )
    return out


_GRAPH_ACTIVITY_QUERIES: dict[str, str] = {
    'document': """
        MATCH (n:Document)-[:ATTACHED_TO]->(p:Project)
        WHERE (n.created_by = {email} OR n.updated_by = {email})
          AND n.created_at <= {before}
        RETURN n.id AS id,
               n.created_at AS ts,
               n.title AS title,
               n.created_by AS created_by,
               n.updated_by AS updated_by,
               p.id AS project_id,
               p.slug AS project_slug,
               p.name AS project_name
        ORDER BY n.created_at DESC, n.id DESC
        LIMIT {row_limit}
    """,
    'release': """
        MATCH (r:Release)<-[:HAS_RELEASE]-(p:Project)
        WHERE r.created_by = {email}
          AND r.created_at <= {before}
        RETURN r.id AS id,
               r.created_at AS ts,
               r.tag AS tag,
               r.committish AS committish,
               r.title AS title,
               p.id AS project_id,
               p.slug AS project_slug,
               p.name AS project_name
        ORDER BY r.created_at DESC, r.id DESC
        LIMIT {row_limit}
    """,
    'upload': """
        MATCH (u:Upload {{uploaded_by: {email}}})
        WHERE u.created_at <= {before}
        RETURN u.id AS id,
               u.created_at AS ts,
               u.filename AS filename
        ORDER BY u.created_at DESC, u.id DESC
        LIMIT {row_limit}
    """,
    'conversation': """
        MATCH (c:Conversation {{user_email: {email}}})
        WHERE c.created_at <= {before}
        RETURN c.id AS id,
               c.created_at AS ts,
               c.title AS title
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT {row_limit}
    """,
}


def _graph_summary(label: str, row: dict[str, typing.Any]) -> str:
    if label == 'document':
        title = graph.parse_agtype(row.get('title')) or '(untitled)'
        proj = (
            graph.parse_agtype(row.get('project_name'))
            or graph.parse_agtype(row.get('project_slug'))
            or 'a project'
        )
        return f'Wrote document "{title}" on {proj}'
    if label == 'release':
        tag = graph.parse_agtype(row.get('tag'))
        committish = graph.parse_agtype(row.get('committish'))
        display = str(tag) if tag else (str(committish) if committish else '')
        proj = (
            graph.parse_agtype(row.get('project_name'))
            or graph.parse_agtype(row.get('project_slug'))
            or 'a project'
        )
        return f'Released {display} of {proj}'.strip()
    if label == 'upload':
        filename = graph.parse_agtype(row.get('filename')) or '(unknown)'
        return f'Uploaded {filename}'
    if label == 'conversation':
        title = graph.parse_agtype(row.get('title')) or '(untitled)'
        return f'Started conversation: {title}'
    return label


_LABEL_TO_SOURCE: dict[str, ActivitySource] = {
    'document': 'document',
    'release': 'release',
    'upload': 'upload',
    'conversation': 'conversation',
}

_LABEL_TO_TYPE: dict[str, str] = {
    'document': 'Document',
    'release': 'Release',
    'upload': 'Upload',
    'conversation': 'Conversation',
}

# AGE requires the SQL ``AS (...)`` column list to match the Cypher
# ``RETURN`` arity; otherwise psycopg raises ``DatatypeMismatch:
# return row and column definition list do not match``.  Keep these
# lists aligned with the ``RETURN`` clauses in
# ``_GRAPH_ACTIVITY_QUERIES`` above.
_GRAPH_ACTIVITY_COLUMNS: dict[str, list[str]] = {
    'document': [
        'id',
        'ts',
        'title',
        'created_by',
        'updated_by',
        'project_id',
        'project_slug',
        'project_name',
    ],
    'release': [
        'id',
        'ts',
        'tag',
        'committish',
        'title',
        'project_id',
        'project_slug',
        'project_name',
    ],
    'upload': ['id', 'ts', 'filename'],
    'conversation': ['id', 'ts', 'title'],
}


async def _graph_activity(
    db: graph.Graph,
    *,
    label: str,
    email: str,
    before: datetime.datetime,
    limit: int,
) -> list[ActivityRecord]:
    template = _GRAPH_ACTIVITY_QUERIES[label]
    rows = await db.execute(
        template,
        {
            'email': email,
            'before': before.isoformat(),
            'row_limit': limit,
        },
        _GRAPH_ACTIVITY_COLUMNS[label],
    )
    out: list[ActivityRecord] = []
    for row in rows:
        ts = _coerce_dt(row.get('ts'))
        if ts is None:
            continue
        entry_id = graph.parse_agtype(row.get('id')) or ''
        project_slug = (
            graph.parse_agtype(row.get('project_slug'))
            if row.get('project_slug') is not None
            else None
        )
        project_id = (
            graph.parse_agtype(row.get('project_id'))
            if row.get('project_id') is not None
            else None
        )
        out.append(
            ActivityRecord(
                id=str(entry_id),
                source=_LABEL_TO_SOURCE[label],
                occurred_at=ts,
                summary=_graph_summary(label, row),
                type=_LABEL_TO_TYPE[label],
                project_id=str(project_id) if project_id else None,
                project_slug=str(project_slug) if project_slug else None,
            )
        )
    return out


@users_router.get('/{email}/activity', response_model=ActivityResponse)
async def get_user_activity(
    request: fastapi.Request,
    email: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:read')),
    ],
    limit: int = DEFAULT_ACTIVITY_LIMIT,
    cursor: str | None = None,
) -> fastapi.Response:
    """Cursor-paginated, mixed-source activity feed for the user."""
    if limit < 1 or limit > MAX_ACTIVITY_LIMIT:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'limit must be 1..{MAX_ACTIVITY_LIMIT}',
        )
    await _ensure_user_exists(db, email)

    before = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)
    cursor_id: str | None = None
    if cursor is not None:
        decoded = decode_cursor(cursor)
        if decoded is None:
            raise fastapi.HTTPException(
                status_code=400, detail='Invalid cursor'
            )
        before, cursor_id = decoded

    subjects = await _resolve_user_subjects(db, email)
    per_source = limit + 1
    legs = await asyncio.gather(
        _opslog_activity(email=email, before=before, limit=per_source),
        _events_activity(subjects=subjects, before=before, limit=per_source),
        _graph_activity(
            db, label='document', email=email, before=before, limit=per_source
        ),
        _graph_activity(
            db,
            label='release',
            email=email,
            before=before,
            limit=per_source,
        ),
        _graph_activity(
            db,
            label='upload',
            email=email,
            before=before,
            limit=per_source,
        ),
        _graph_activity(
            db,
            label='conversation',
            email=email,
            before=before,
            limit=per_source,
        ),
    )

    merged: list[ActivityRecord] = []
    for leg in legs:
        merged.extend(leg)
    merged.sort(
        key=lambda r: (r.occurred_at, r.id),
        reverse=True,
    )
    if cursor_id is not None:
        merged = [
            r for r in merged if (r.occurred_at, r.id) < (before, cursor_id)
        ]

    next_cursor: str | None = None
    has_more = len(merged) > limit
    if has_more:
        merged = merged[:limit]
    if has_more and merged:
        last = merged[-1]
        next_cursor = encode_cursor(last.occurred_at, last.id)

    body = ActivityResponse(data=merged)
    response = fastapi.responses.JSONResponse(
        fastapi.encoders.jsonable_encoder(body.model_dump(mode='json'))
    )
    response.headers['Link'] = build_link_header(request, next_cursor)
    return response
