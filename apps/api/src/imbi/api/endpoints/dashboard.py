"""Admin dashboard system-health status endpoint.

Probes the datastores in-process (PostgreSQL/AGE, ClickHouse, Valkey)
and the sibling HTTP services via their ``/status`` endpoints. Every
check runs concurrently with a short timeout so the endpoint never
blocks on a degraded dependency.
"""

import asyncio
import datetime
import logging
import time
import typing

import fastapi
import httpx
import pydantic

from imbi.api import settings, version
from imbi.api.auth import permissions
from imbi.common import clickhouse, graph, valkey

LOGGER = logging.getLogger(__name__)

dashboard_router = fastapi.APIRouter(prefix='/admin/dashboard', tags=['Admin'])

# Per-check timeout, in seconds. Keeps the endpoint responsive even when
# a dependency is hung rather than cleanly down.
_CHECK_TIMEOUT = 2.0


class DatastoreStatus(pydantic.BaseModel):
    """Health of a single backing datastore."""

    name: str
    role: str
    status: typing.Literal['ok', 'error']
    latency_ms: float | None = None
    # Bytes on disk (Postgres/ClickHouse) or resident memory (Valkey,
    # which is in-memory). ``None`` when the size probe failed. For
    # ClickHouse this is the Imbi application database; ``total_bytes``
    # carries the whole-server footprint (incl. ``system.*``).
    size_bytes: int | None = None
    total_bytes: int | None = None
    detail: str | None = None


class ServiceStatus(pydantic.BaseModel):
    """Health of a single Imbi service."""

    name: str
    status: typing.Literal['up', 'down']
    version: str | None = None
    latency_ms: float | None = None
    detail: str | None = None


class DashboardStatus(pydantic.BaseModel):
    """Aggregate system-health snapshot for the admin dashboard."""

    checked_at: datetime.datetime
    datastores: list[DatastoreStatus]
    services: list[ServiceStatus]


class MetricSeries(pydantic.BaseModel):
    """A windowed count plus per-day counts (oldest day first)."""

    total: int
    daily: list[int]


class EnvironmentCount(pydantic.BaseModel):
    """Release count for one environment over the window."""

    slug: str
    count: int


class DashboardMetrics(pydantic.BaseModel):
    """7-day activity metrics with daily breakdowns for the tiles."""

    since: datetime.datetime
    releases: MetricSeries
    events: MetricSeries
    ops_log: MetricSeries
    pull_requests: MetricSeries
    releases_by_environment: list[EnvironmentCount]


def _ms(start: float) -> float:
    """Milliseconds elapsed since *start* (``time.perf_counter()``)."""
    return round((time.perf_counter() - start) * 1000, 1)


async def _postgres_size(db: graph.Graph) -> int | None:
    """Total on-disk size of the current PostgreSQL database, in bytes."""
    try:
        async with db.pool.connection() as conn:
            cursor = await conn.execute(
                'SELECT pg_database_size(current_database())'
            )
            row = await cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except Exception as err:  # noqa: BLE001
        LOGGER.warning('PostgreSQL size probe failed: %s', err)
        return None


async def _check_postgres(db: graph.Graph) -> DatastoreStatus:
    """Round-trip a trivial Cypher query through AGE/PostgreSQL."""
    start = time.perf_counter()
    try:
        await asyncio.wait_for(db.execute('RETURN 1'), _CHECK_TIMEOUT)
    except Exception as err:  # noqa: BLE001
        LOGGER.warning('PostgreSQL health check failed: %s', err)
        return DatastoreStatus(
            name='PostgreSQL',
            role='Primary data',
            status='error',
            detail=str(err),
        )
    latency = _ms(start)
    # Size is best-effort; a timeout must not fail the (already-ok) check.
    try:
        size = await asyncio.wait_for(_postgres_size(db), _CHECK_TIMEOUT)
    except TimeoutError:
        LOGGER.warning('PostgreSQL size probe timed out')
        size = None
    return DatastoreStatus(
        name='PostgreSQL',
        role='Primary data',
        status='ok',
        latency_ms=latency,
        size_bytes=size,
    )


async def _check_clickhouse() -> DatastoreStatus:
    """Probe ClickHouse for the app-database and whole-server disk size.

    ``size`` is the active-part footprint of the connected (Imbi)
    database; ``total`` spans every database, including ``system.*``.
    """
    start = time.perf_counter()
    try:
        rows = await asyncio.wait_for(
            clickhouse.query(
                'SELECT'
                ' sumIf(bytes_on_disk, database = currentDatabase()) AS size,'
                ' sum(bytes_on_disk) AS total'
                ' FROM system.parts WHERE active'
            ),
            _CHECK_TIMEOUT,
        )
    except Exception as err:  # noqa: BLE001
        LOGGER.warning('ClickHouse health check failed: %s', err)
        return DatastoreStatus(
            name='ClickHouse',
            role='Timeseries data',
            status='error',
            detail=str(err),
        )
    row = rows[0] if rows else {}
    size_raw = row.get('size')
    total_raw = row.get('total')
    return DatastoreStatus(
        name='ClickHouse',
        role='Timeseries data',
        status='ok',
        latency_ms=_ms(start),
        size_bytes=int(size_raw) if size_raw is not None else None,
        total_bytes=int(total_raw) if total_raw is not None else None,
    )


async def _check_valkey() -> DatastoreStatus:
    """Read Valkey ``INFO memory`` for liveness and resident size."""
    start = time.perf_counter()
    try:
        client = valkey.get_client()
        info = await asyncio.wait_for(
            client.info('memory'),  # pyright: ignore[reportUnknownMemberType]
            _CHECK_TIMEOUT,
        )
    except Exception as err:  # noqa: BLE001
        LOGGER.warning('Valkey health check failed: %s', err)
        return DatastoreStatus(
            name='Valkey',
            role='Cache, Session, & Queues',
            status='error',
            detail=str(err),
        )
    mem = (
        typing.cast('dict[str, typing.Any]', info)
        if isinstance(info, dict)
        else {}
    )
    raw = mem.get('used_memory')
    size = int(raw) if raw is not None else None
    return DatastoreStatus(
        name='Valkey',
        role='Cache, Session, & Queues',
        status='ok',
        latency_ms=_ms(start),
        size_bytes=size,
    )


async def _check_service(
    client: httpx.AsyncClient, name: str, base_url: str
) -> ServiceStatus:
    """Probe a sibling service's ``/status`` endpoint for liveness."""
    if not base_url:
        return ServiceStatus(name=name, status='down', detail='not configured')
    start = time.perf_counter()
    try:
        response = await client.get(
            f'{base_url}/status', timeout=_CHECK_TIMEOUT
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as err:  # noqa: BLE001
        LOGGER.warning('%s health check failed: %s', name, err)
        return ServiceStatus(
            name=name, status='down', latency_ms=_ms(start), detail=str(err)
        )
    return ServiceStatus(
        name=name,
        status='up',
        version=payload.get('version'),
        latency_ms=_ms(start),
    )


@dashboard_router.get('/status', response_model=DashboardStatus)
async def get_dashboard_status(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:dashboard:read')
        ),
    ],
) -> DashboardStatus:
    """Return a system-health snapshot of datastores and services."""
    internal = settings.get_internal_services()
    async with httpx.AsyncClient() as http_client:
        datastores, services = await asyncio.gather(
            asyncio.gather(
                _check_postgres(db),
                _check_clickhouse(),
                _check_valkey(),
            ),
            asyncio.gather(
                _check_service(
                    http_client, 'Assistant', internal.assistant_url
                ),
                _check_service(http_client, 'Gateway', internal.gateway_url),
                _check_service(http_client, 'MCP', internal.mcp_url),
                _check_service(http_client, 'Slackbot', internal.slackbot_url),
            ),
        )
    # The API is this process -- report its own version without an HTTP hop.
    api_status = ServiceStatus(
        name='API', status='up', version=version, latency_ms=0.0
    )
    return DashboardStatus(
        checked_at=datetime.datetime.now(datetime.UTC),
        datastores=list(datastores),
        services=[api_status, *services],
    )


_METRICS_WINDOW_DAYS = 7


def _build_series(
    rows: list[dict[str, typing.Any]], days: list[str]
) -> MetricSeries:
    """Align ``{day, c}`` ClickHouse rows onto the *days* grid."""
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row.get('day'))[:10]] = int(row.get('c') or 0)
    daily = [counts.get(day, 0) for day in days]
    return MetricSeries(total=sum(daily), daily=daily)


@dashboard_router.get('/metrics', response_model=DashboardMetrics)
async def get_dashboard_metrics(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:dashboard:read')
        ),
    ],
) -> DashboardMetrics:
    """Return 7-day activity metrics with per-day counts for the tiles."""
    today = datetime.datetime.now(datetime.UTC).date()
    start_date = today - datetime.timedelta(days=_METRICS_WINDOW_DAYS - 1)
    since = datetime.datetime.combine(
        start_date, datetime.time.min, tzinfo=datetime.UTC
    )
    days = [
        (start_date + datetime.timedelta(days=offset)).isoformat()
        for offset in range(_METRICS_WINDOW_DAYS)
    ]
    params: dict[str, typing.Any] = {'since': since}
    # One scan of the (FINAL, merge-on-read) deploy rows yields both the
    # per-day series and the per-environment rollup.
    deploys, events, ops, prs = await asyncio.gather(
        clickhouse.query(
            'SELECT toDate(occurred_at) AS day,'
            ' environment_slug AS slug, count() AS c'
            ' FROM operations_log FINAL'
            " WHERE is_deleted = 0 AND entry_type = 'Deployed'"
            ' AND occurred_at >= {since:DateTime64(3)}'
            ' GROUP BY day, environment_slug',
            params,
        ),
        clickhouse.query(
            'SELECT toDate(recorded_at) AS day, count() AS c'
            ' FROM events WHERE recorded_at >= {since:DateTime64(3)}'
            ' GROUP BY day',
            params,
        ),
        clickhouse.query(
            'SELECT toDate(occurred_at) AS day, count() AS c'
            ' FROM operations_log FINAL'
            ' WHERE is_deleted = 0'
            ' AND occurred_at >= {since:DateTime64(3)}'
            ' GROUP BY day',
            params,
        ),
        clickhouse.query(
            'SELECT toDate(created_at) AS day, count() AS c'
            ' FROM pull_requests FINAL'
            ' WHERE created_at >= {since:DateTime64(3)}'
            ' GROUP BY day',
            params,
        ),
    )
    releases_by_day: dict[str, int] = {}
    by_env: dict[str, int] = {}
    for row in deploys:
        count = int(row.get('c') or 0)
        day = str(row.get('day'))[:10]
        releases_by_day[day] = releases_by_day.get(day, 0) + count
        slug = row.get('slug')
        if slug:
            by_env[str(slug)] = by_env.get(str(slug), 0) + count
    releases_daily = [releases_by_day.get(day, 0) for day in days]
    environments = [
        EnvironmentCount(slug=slug, count=count)
        for slug, count in sorted(
            by_env.items(), key=lambda item: item[1], reverse=True
        )
    ]
    return DashboardMetrics(
        since=since,
        releases=MetricSeries(total=sum(releases_daily), daily=releases_daily),
        events=_build_series(events, days),
        ops_log=_build_series(ops, days),
        pull_requests=_build_series(prs, days),
        releases_by_environment=environments,
    )
