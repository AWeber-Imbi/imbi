"""Project logs plugin endpoints."""

import asyncio
import datetime
import logging
import typing

import fastapi
from imbi_common import graph
from imbi_common.plugins.base import (
    LogFilter,
    LogHistogramBucket,
    LogQuery,
    LogResult,
    LogsPlugin,
    PluginContext,
)
from imbi_common.plugins.errors import (
    CursorExpiredError,
    PluginCredentialsMissing,
)

from imbi_api.auth import permissions
from imbi_api.domain import models
from imbi_api.endpoints._helpers import lookup_project_slugs
from imbi_api.identity import resolution as identity_resolution
from imbi_api.identity.host_integration import attach_identity
from imbi_api.plugins import call_with_timeout
from imbi_api.plugins.credentials import get_plugin_credentials
from imbi_api.plugins.resolution import ResolvedPlugin, resolve_plugin

LOGGER = logging.getLogger(__name__)

project_logs_router = fastapi.APIRouter(tags=['Project: Logs'])

_VALID_FILTER_OPS = frozenset({'eq', 'ne', 'contains', 'starts_with', 'regex'})


def _parse_filters(raw: list[str]) -> list[LogFilter]:
    """Parse ``?filter=field:op:value`` query strings."""
    filters: list[LogFilter] = []
    for item in raw:
        parts = item.split(':', 2)
        if len(parts) != 3:
            raise fastapi.HTTPException(
                status_code=400,
                detail=(
                    f'Invalid filter format {item!r}; expected field:op:value'
                ),
            )
        field, op, value = parts
        if op not in _VALID_FILTER_OPS:
            raise fastapi.HTTPException(
                status_code=400,
                detail=(
                    f'Unknown filter op {op!r};'
                    f' allowed: {sorted(_VALID_FILTER_OPS)}'
                ),
            )
        filters.append(LogFilter(field=field, op=op, value=value))  # type: ignore[arg-type]
    return filters


async def _search_one_env(
    *,
    ctx_template: PluginContext,
    resolved: ResolvedPlugin,
    credentials: dict[str, typing.Any],
    query: LogQuery,
    environment: str | None,
) -> LogResult:
    """Run a single (env-scoped) plugin search.

    The caller is responsible for hydrating identity and resolving
    plugin credentials once — those operations don't vary by
    environment, so doing them inside each fan-out task would
    downgrade shared identity / credential failures into per-env
    warnings.
    """
    ctx = ctx_template.model_copy(update={'environment': environment})
    handler = typing.cast(LogsPlugin, resolved.entry.handler_cls())
    return await call_with_timeout(handler.search(ctx, credentials, query))


def _to_response_entries(
    entries: list[typing.Any],
) -> list[models.LogEntryResponse]:
    return [
        models.LogEntryResponse(
            timestamp=e.timestamp,
            message=e.message,
            level=e.level,
            raw=e.raw,
        )
        for e in entries
    ]


@project_logs_router.get('/')
async def search_logs(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:logs:read'),
        ),
    ],
    source: str | None = fastapi.Query(default=None),
    environment: list[str] = fastapi.Query(  # noqa: B008
        default_factory=list,
    ),
    start_time: str | None = fastapi.Query(default=None),
    end_time: str | None = fastapi.Query(default=None),
    cursor: str | None = fastapi.Query(default=None),
    limit: int = fastapi.Query(default=100, ge=1, le=1000),
    raw_filters: list[str] = fastapi.Query(  # noqa: B008
        default_factory=list,
        alias='filter',
    ),
) -> models.LogResultResponse:
    """Search project logs via the assigned logs plugin.

    ``environment`` is a repeated query param: ``?environment=production
    &environment=staging``.  When two or more envs are passed, the
    endpoint fans out one identity-scoped search per env in parallel,
    merges entries by timestamp (desc), and returns the first ``limit``
    entries.  Pagination via ``cursor`` is only supported for
    single-env searches; multi-env returns ``next_cursor=None`` and
    surfaces partial-failure / truncation notes via ``warnings``.
    """
    resolved = await resolve_plugin(db, project_id, 'logs', source)

    now = datetime.datetime.now(datetime.UTC)
    try:
        start_dt = (
            datetime.datetime.fromisoformat(start_time)
            if start_time
            else now - datetime.timedelta(minutes=30)
        )
        end_dt = datetime.datetime.fromisoformat(end_time) if end_time else now
    except ValueError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Invalid datetime format: {exc}',
        ) from exc

    # ``fromisoformat`` accepts naive timestamps; coerce them to UTC so
    # plugin handlers always receive aware datetimes (matches the pattern
    # in events.py / operations_log.py).
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=datetime.UTC)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=datetime.UTC)

    filters = _parse_filters(raw_filters)
    if cursor and len(environment) > 1:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                'Pagination is only supported for single-environment '
                'searches; received multiple environments with a cursor'
            ),
        )
    query = LogQuery(
        start_time=start_dt,
        end_time=end_dt,
        filters=filters,
        limit=limit,
        cursor=cursor,
    )

    project_slug, team_slug = await lookup_project_slugs(db, project_id)
    ctx_template = PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        assignment_options=resolved.options,
    )
    # Hydrate identity and resolve plugin credentials once before
    # fanning out — neither depends on ``ctx.environment`` and doing
    # them per-task would downgrade shared identity / credential
    # failures into per-env warnings on multi-env requests.
    identity_options = (
        await identity_resolution.load_plugin_options(
            db, resolved.identity_plugin_id
        )
        if resolved.identity_plugin_id
        else None
    )
    ctx_template = await attach_identity(
        db, ctx_template, resolved, auth, identity_options=identity_options
    )
    try:
        credentials = await get_plugin_credentials(
            db, resolved.plugin_id, resolved.entry
        )
    except PluginCredentialsMissing as exc:
        raise fastapi.HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    envs: list[str | None] = list(environment) if environment else [None]

    if len(envs) == 1:
        try:
            result = await _search_one_env(
                ctx_template=ctx_template,
                resolved=resolved,
                credentials=credentials,
                query=query,
                environment=envs[0],
            )
        except CursorExpiredError as exc:
            raise fastapi.HTTPException(
                status_code=409,
                detail={
                    'error': 'cursor_expired',
                    'message': str(exc),
                },
            ) from exc
        return models.LogResultResponse(
            entries=_to_response_entries(result.entries),
            next_cursor=result.next_cursor,
            total=result.total,
            warnings=result.warnings,
        )

    # Multi-env fan-out.  Identity / credentials are already resolved
    # above; per-env failures from ``handler.search`` are surfaced as
    # warnings rather than failing the whole request — partial
    # results are still useful.
    raw_results = await asyncio.gather(
        *(
            _search_one_env(
                ctx_template=ctx_template,
                resolved=resolved,
                credentials=credentials,
                query=query,
                environment=env,
            )
            for env in envs
        ),
        return_exceptions=True,
    )

    merged_entries: list[typing.Any] = []
    warnings: list[str] = []
    total: int = 0
    for env, result_or_exc in zip(envs, raw_results, strict=True):
        if isinstance(result_or_exc, Exception):
            LOGGER.warning(
                'Log search failed for env=%s: %s', env, result_or_exc
            )
            warnings.append(
                f'Search for environment {env!r} failed: {result_or_exc}'
            )
            continue
        if isinstance(result_or_exc, BaseException):
            # CancelledError / KeyboardInterrupt / SystemExit must
            # propagate — never downgrade them to a partial-failure
            # warning.
            raise result_or_exc
        merged_entries.extend(result_or_exc.entries)
        warnings.extend(result_or_exc.warnings)
        if result_or_exc.total is not None:
            total += result_or_exc.total
    merged_entries.sort(key=lambda e: e.timestamp, reverse=True)
    truncated = merged_entries[:limit]
    return models.LogResultResponse(
        entries=_to_response_entries(truncated),
        next_cursor=None,
        total=total or None,
        warnings=warnings,
    )


async def _histogram_one_env(
    *,
    ctx_template: PluginContext,
    resolved: ResolvedPlugin,
    credentials: dict[str, typing.Any],
    query: LogQuery,
    bucket_count: int,
    environment: str | None,
) -> list[LogHistogramBucket]:
    ctx = ctx_template.model_copy(update={'environment': environment})
    handler = typing.cast(LogsPlugin, resolved.entry.handler_cls())
    return await call_with_timeout(
        handler.histogram(ctx, credentials, query, bucket_count)
    )


@project_logs_router.get('/histogram')
async def get_log_histogram(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:logs:read'),
        ),
    ],
    source: str | None = fastapi.Query(default=None),
    environment: list[str] = fastapi.Query(  # noqa: B008
        default_factory=list,
    ),
    start_time: str | None = fastapi.Query(default=None),
    end_time: str | None = fastapi.Query(default=None),
    bucket_count: int = fastapi.Query(default=60, ge=1, le=1440),
    raw_filters: list[str] = fastapi.Query(  # noqa: B008
        default_factory=list,
        alias='filter',
    ),
) -> list[models.LogHistogramBucketResponse]:
    """Return time-bucketed event counts for the histogram view.

    Returns an empty list when the assigned plugin does not support
    histograms (``PluginManifest.supports_histogram`` is ``False``).
    Multi-env requests fan out one histogram per env and sum bucket
    counts at matching timestamps; per-level counts are aggregated
    across envs.
    """
    resolved = await resolve_plugin(db, project_id, 'logs', source)
    handler = typing.cast(LogsPlugin, resolved.entry.handler_cls())
    if not handler.manifest.supports_histogram:
        return []

    now = datetime.datetime.now(datetime.UTC)
    try:
        start_dt = (
            datetime.datetime.fromisoformat(start_time)
            if start_time
            else now - datetime.timedelta(minutes=30)
        )
        end_dt = datetime.datetime.fromisoformat(end_time) if end_time else now
    except ValueError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Invalid datetime format: {exc}',
        ) from exc

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=datetime.UTC)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=datetime.UTC)

    filters = _parse_filters(raw_filters)
    query = LogQuery(
        start_time=start_dt,
        end_time=end_dt,
        filters=filters,
    )

    project_slug, team_slug = await lookup_project_slugs(db, project_id)
    ctx_template = PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        assignment_options=resolved.options,
    )
    # Hydrate identity and resolve plugin credentials once before the
    # fan-out — see the equivalent comment in ``search_logs``.
    identity_options = (
        await identity_resolution.load_plugin_options(
            db, resolved.identity_plugin_id
        )
        if resolved.identity_plugin_id
        else None
    )
    ctx_template = await attach_identity(
        db, ctx_template, resolved, auth, identity_options=identity_options
    )
    try:
        credentials = await get_plugin_credentials(
            db, resolved.plugin_id, resolved.entry
        )
    except PluginCredentialsMissing as exc:
        raise fastapi.HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    envs: list[str | None] = list(environment) if environment else [None]

    if len(envs) == 1:
        buckets = await _histogram_one_env(
            ctx_template=ctx_template,
            resolved=resolved,
            credentials=credentials,
            query=query,
            bucket_count=bucket_count,
            environment=envs[0],
        )
        return [
            models.LogHistogramBucketResponse(
                timestamp=b.timestamp,
                count=b.count,
                levels=b.levels,
            )
            for b in buckets
        ]

    # Multi-env fan-out: sum bucket counts at matching timestamps,
    # aggregate level breakdowns.  Failures from any env are logged
    # and that env's contribution is dropped — the histogram is not
    # the place to surface partial-failure warnings (the search
    # endpoint already does).
    raw_results = await asyncio.gather(
        *(
            _histogram_one_env(
                ctx_template=ctx_template,
                resolved=resolved,
                credentials=credentials,
                query=query,
                bucket_count=bucket_count,
                environment=env,
            )
            for env in envs
        ),
        return_exceptions=True,
    )
    summed: dict[datetime.datetime, dict[str, int | dict[str, int]]] = {}
    for env, result_or_exc in zip(envs, raw_results, strict=True):
        if isinstance(result_or_exc, Exception):
            LOGGER.warning(
                'Histogram failed for env=%s: %s', env, result_or_exc
            )
            continue
        if isinstance(result_or_exc, BaseException):
            raise result_or_exc
        for b in result_or_exc:
            slot = summed.setdefault(b.timestamp, {'count': 0, 'levels': {}})
            slot['count'] = typing.cast(int, slot['count']) + b.count
            levels_dict = typing.cast(dict[str, int], slot['levels'])
            for lvl, n in (b.levels or {}).items():
                levels_dict[lvl] = levels_dict.get(lvl, 0) + n
    return [
        models.LogHistogramBucketResponse(
            timestamp=ts,
            count=typing.cast(int, slot['count']),
            levels=typing.cast(dict[str, int], slot['levels']),
        )
        for ts, slot in sorted(summed.items())
    ]


@project_logs_router.get('/schema')
async def get_log_schema(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:logs:read'),
        ),
    ],
    source: str | None = fastapi.Query(default=None),
    environment: str | None = fastapi.Query(default=None),
) -> list[dict[str, typing.Any]]:
    """Get the log schema (available fields) for the assigned logs plugin."""
    resolved = await resolve_plugin(db, project_id, 'logs', source)
    project_slug, team_slug = await lookup_project_slugs(db, project_id)
    ctx = PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        environment=environment,
        assignment_options=resolved.options,
    )
    ctx = await attach_identity(db, ctx, resolved, auth)
    try:
        credentials = await get_plugin_credentials(
            db, resolved.plugin_id, resolved.entry
        )
    except PluginCredentialsMissing as exc:
        raise fastapi.HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    handler = typing.cast(LogsPlugin, resolved.entry.handler_cls())
    return await call_with_timeout(handler.schema(ctx, credentials))
