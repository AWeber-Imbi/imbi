"""Global maintenance operation endpoints (admin Maintenance page).

The operation list is registry-driven (:mod:`imbi.api.maintenance`):
the UI renders whatever this returns, so adding an operation to the
registry is all that is required for a new button to appear.
"""

import datetime
import json
import logging
import typing

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
from imbi.api.maintenance import (
    OPERATIONS,
    MaintenanceSlug,
    OperationDefinition,
    state,
)
from imbi.api.scoring import OptionalValkeyClient
from imbi.common import clickhouse, graph

LOGGER = logging.getLogger(__name__)

maintenance_router = fastapi.APIRouter(
    prefix='/maintenance', tags=['Admin: Maintenance']
)

RequireRead = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(
        permissions.require_permission('admin:maintenance:read'),
    ),
]
RequireManage = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(
        permissions.require_permission('admin:maintenance:manage'),
    ),
]


class MaintenanceProgress(pydantic.BaseModel):
    """Counters for an operation's current or last run."""

    total: int = 0
    remaining: int = 0
    in_flight: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0


class MaintenanceOperation(pydantic.BaseModel):
    """One registry operation merged with its run state."""

    slug: str
    label: str
    description: str
    running: bool
    state: state.RunState
    progress: MaintenanceProgress | None = None
    started_at: datetime.datetime | None = None
    started_by: str | None = None
    completed_at: datetime.datetime | None = None
    #: Per-project failure detail; only populated on the per-operation
    #: GET to keep the list response small.
    failures: dict[str, str] | None = None


class MaintenanceRunResponse(pydantic.BaseModel):
    """Acknowledgement that a run was started."""

    run_id: str
    total: int


def _to_operation(
    definition: OperationDefinition,
    status: state.RunStatus,
    failures: dict[str, str] | None = None,
) -> MaintenanceOperation:
    progress: MaintenanceProgress | None = None
    if status.state != 'idle':
        progress = MaintenanceProgress(
            total=status.total,
            remaining=status.remaining,
            in_flight=status.in_flight,
            succeeded=status.succeeded,
            failed=status.failed,
            skipped=status.skipped,
        )
    return MaintenanceOperation(
        slug=definition.slug,
        label=definition.label,
        description=definition.description,
        running=status.state == 'running',
        state=status.state,
        progress=progress,
        started_at=status.started_at,
        started_by=status.started_by,
        completed_at=status.completed_at,
        failures=failures,
    )


def _definition_or_404(slug: str) -> OperationDefinition:
    definition = OPERATIONS.get(typing.cast('MaintenanceSlug', slug))
    if definition is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Unknown maintenance operation {slug!r}'
        )
    return definition


@maintenance_router.get('/operations')
async def list_maintenance_operations(
    auth: RequireRead,
    client: OptionalValkeyClient,
) -> list[MaintenanceOperation]:
    """The operation registry merged with each operation's run state."""
    _ = auth
    if client is None:
        raise fastapi.HTTPException(
            status_code=503,
            detail='Maintenance state is unavailable '
            '(Valkey is not connected).',
        )
    results: list[MaintenanceOperation] = []
    for definition in OPERATIONS.values():
        status = await state.read_status(client, definition.slug)
        results.append(_to_operation(definition, status))
    return results


@maintenance_router.get('/operations/{slug}')
async def get_maintenance_operation(
    slug: str,
    auth: RequireRead,
    client: OptionalValkeyClient,
) -> MaintenanceOperation:
    """One operation's run state, including per-project failures."""
    _ = auth
    definition = _definition_or_404(slug)
    if client is None:
        raise fastapi.HTTPException(
            status_code=503,
            detail='Maintenance state is unavailable '
            '(Valkey is not connected).',
        )
    status = await state.read_status(client, definition.slug)
    failures = await state.read_failures(client, definition.slug)
    return _to_operation(definition, status, failures or None)


@maintenance_router.post('/operations/{slug}/run', status_code=202)
async def run_maintenance_operation(
    slug: str,
    auth: RequireManage,
    db: graph.Pool,
    client: OptionalValkeyClient,
) -> MaintenanceRunResponse:
    """Start a global run of the operation across all projects."""
    definition = _definition_or_404(slug)
    if client is None:
        raise fastapi.HTTPException(
            status_code=503,
            detail='Queueing is unavailable (Valkey is not connected).',
        )
    project_ids = await definition.enumerate(db)
    status = await state.start_run(
        client, definition.slug, project_ids, auth.principal_name
    )
    if status is None:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'{definition.label} is already running.',
        )
    LOGGER.info(
        'maintenance %s run %s started by %s (%d projects)',
        definition.slug,
        status.run_id,
        auth.principal_name,
        status.total,
    )
    return MaintenanceRunResponse(
        run_id=status.run_id or '', total=status.total
    )


@maintenance_router.post('/operations/{slug}/cancel')
async def cancel_maintenance_operation(
    slug: str,
    auth: RequireManage,
    client: OptionalValkeyClient,
) -> MaintenanceOperation:
    """Cancel the operation's in-progress run."""
    definition = _definition_or_404(slug)
    if client is None:
        raise fastapi.HTTPException(
            status_code=503,
            detail='Queueing is unavailable (Valkey is not connected).',
        )
    cancelled = await state.cancel_run(client, definition.slug)
    if not cancelled:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'{definition.label} is not running.',
        )
    LOGGER.info(
        'maintenance %s run cancelled by %s',
        definition.slug,
        auth.principal_name,
    )
    status = await state.read_status(client, definition.slug)
    return _to_operation(definition, status)


DEFAULT_LOG_LIMIT = 50
MAX_LOG_LIMIT = 500

#: ``detail`` is a ClickHouse ``JSON`` column; clickhouse-connect
#: returns those as nested array-of-tuple paths in their internal
#: binary form, not as a ``dict``. ``toJSONString`` makes ClickHouse
#: serialize it to text we parse here, the same way the events
#: endpoint reads its JSON columns.
_LOG_COLUMNS = (
    'id, occurred_at, run_id, attempt_id, item_id, slug, event_type, '
    'disposition, action, project_id, project_slug, message, '
    'toJSONString(detail) AS detail, duration_ms, started_by'
)


class MaintenanceLogEntry(pydantic.BaseModel):
    """One row of the maintenance activity log."""

    id: str
    occurred_at: datetime.datetime
    run_id: str
    attempt_id: str
    item_id: str
    slug: str
    event_type: str
    disposition: str
    action: str
    project_id: str
    project_slug: str
    message: str
    detail: dict[str, typing.Any]
    duration_ms: int
    started_by: str


class MaintenanceLogCounts(pydantic.BaseModel):
    """Attempt outcomes across the whole filter set, not just this page."""

    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    deferred: int = 0


class MaintenanceLogResponse(pydantic.BaseModel):
    """A page of log rows plus the counts the filter chips render."""

    counts: MaintenanceLogCounts | None = None
    data: list[MaintenanceLogEntry]


def _log_detail(value: object) -> dict[str, typing.Any]:
    """Parse the ``toJSONString``-serialized ``detail`` column.

    Defensive: anything that is not a JSON object -- an unparseable
    value, or a scalar written by an older row -- becomes an empty
    dict rather than sinking the whole page.
    """
    if isinstance(value, dict):
        return typing.cast('dict[str, typing.Any]', value)
    if isinstance(value, bytes):
        value = value.decode('utf-8', errors='replace')
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        LOGGER.warning('maintenance log row has unparseable detail')
        return {}
    if not isinstance(parsed, dict):
        return {}
    return typing.cast('dict[str, typing.Any]', parsed)


def _log_row(row: dict[str, typing.Any]) -> MaintenanceLogEntry:
    detail = _log_detail(row.get('detail'))
    return MaintenanceLogEntry(
        id=str(row['id']),
        occurred_at=clickhouse.as_utc(row['occurred_at']),
        run_id=str(row['run_id']),
        attempt_id=str(row['attempt_id']),
        item_id=str(row['item_id']),
        slug=str(row['slug']),
        event_type=str(row['event_type']),
        disposition=str(row['disposition']),
        action=str(row['action']),
        project_id=str(row['project_id']),
        project_slug=str(row['project_slug']),
        message=str(row['message']),
        detail=detail,
        duration_ms=int(row['duration_ms'] or 0),
        started_by=str(row['started_by']),
    )


async def _log_counts(
    where: str, params: dict[str, typing.Any]
) -> MaintenanceLogCounts:
    """Attempt outcomes for the filter set, disposition filter excluded.

    Counted over ``event_type = 'attempt'`` only: activity rows carry a
    disposition too, and including them would report events rather than
    outcomes -- a run of 2,000 projects can write many times that many
    activity rows.
    """
    # `where` is built from a fixed column allowlist; every value is a
    # bound parameter.
    sql = (
        "SELECT countIf(disposition = 'succeeded') AS succeeded, "  # noqa: S608
        "countIf(disposition = 'skipped') AS skipped, "
        "countIf(disposition = 'failed') AS failed, "
        "countIf(disposition = 'deferred') AS deferred "
        f'FROM maintenance_log WHERE {where}'
    )
    rows = await clickhouse.query(sql, params)
    if not rows:
        return MaintenanceLogCounts()
    row = rows[0]
    return MaintenanceLogCounts(
        succeeded=int(row['succeeded']),
        skipped=int(row['skipped']),
        failed=int(row['failed']),
        deferred=int(row['deferred']),
    )


@maintenance_router.get('/log', response_model=MaintenanceLogResponse)
async def list_maintenance_log(
    request: fastapi.Request,
    auth: RequireRead,
    event_type: str | None = 'attempt',
    disposition: typing.Annotated[list[str] | None, fastapi.Query()] = None,
    slug: str | None = None,
    run_id: str | None = None,
    attempt_id: str | None = None,
    project_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = DEFAULT_LOG_LIMIT,
    cursor: str | None = None,
) -> fastapi.Response:
    """The maintenance activity log, newest first, keyset paginated.

    Defaults to ``event_type=attempt`` -- one row per work item per
    claim, which is the view the Activity tab opens on. Pass
    ``event_type=activity`` with an ``attempt_id`` to expand one of
    those, or an empty ``event_type`` for the raw stream.

    ``counts`` is computed for the whole filter set with the
    ``disposition`` filter left out, so the filter chips can show totals
    without a second request. It is returned on the first page only:
    recomputing ninety days of counts on every "load more" buys nothing.
    """
    _ = auth
    if limit < 1 or limit > MAX_LOG_LIMIT:
        raise fastapi.HTTPException(
            status_code=400, detail=f'limit must be 1..{MAX_LOG_LIMIT}'
        )
    # Built in three layers: the shared filters, what the counts add on
    # top of them, and what the page adds. The counts describe the whole
    # filter set, so they see neither the disposition filter nor the
    # cursor.
    shared: list[str] = []
    params: dict[str, typing.Any] = {}
    for field, value in (
        ('slug', slug),
        ('run_id', run_id),
        ('attempt_id', attempt_id),
        ('project_id', project_id),
    ):
        if value is not None:
            shared.append(f'{field} = {{{field}:String}}')
            params[field] = value
    if since is not None:
        params['since'] = parse_iso(since, 'since')
        shared.append('occurred_at >= {since:DateTime64(3)}')
    if until is not None:
        params['until'] = parse_iso(until, 'until')
        shared.append('occurred_at < {until:DateTime64(3)}')

    count_params = dict(params)
    count_where = ' AND '.join([*shared, "event_type = 'attempt'"])

    clauses = list(shared)
    if event_type:
        clauses.append('event_type = {event_type:String}')
        params['event_type'] = event_type
    if disposition:
        clauses.append('disposition IN {dispositions:Array(String)}')
        params['dispositions'] = list(disposition)
    if cursor is not None:
        decoded = decode_cursor(cursor)
        if decoded is None:
            raise fastapi.HTTPException(
                status_code=400, detail='Invalid cursor'
            )
        params['cursor_ts'], params['cursor_id'] = decoded
        clauses.append(
            '(occurred_at, id) < '
            '({cursor_ts:DateTime64(3)}, {cursor_id:String})'
        )
    params['row_limit'] = limit + 1
    where = ' AND '.join(clauses) if clauses else '1'
    # As above: allowlisted columns, bound values.
    sql = (
        f'SELECT {_LOG_COLUMNS} FROM maintenance_log WHERE {where} '  # noqa: S608
        'ORDER BY occurred_at DESC, id DESC LIMIT {row_limit:UInt32}'
    )
    try:
        rows = await clickhouse.query(sql, params)
        counts = (
            await _log_counts(count_where, count_params)
            if cursor is None
            else None
        )
    except clickhouse.client.DatabaseError as exc:
        raise fastapi.HTTPException(
            status_code=503,
            detail='The maintenance log is unavailable '
            '(ClickHouse is not reachable).',
        ) from exc
    next_cursor: str | None = None
    if len(rows) > limit:
        rows.pop()
        last = rows[-1]
        next_cursor = encode_cursor(
            clickhouse.as_utc(last['occurred_at']), str(last['id'])
        )
    body = MaintenanceLogResponse(
        counts=counts, data=[_log_row(row) for row in rows]
    )
    response = fastapi.responses.JSONResponse(
        fastapi.encoders.jsonable_encoder(body.model_dump(mode='json'))
    )
    response.headers['Link'] = build_link_header(request, next_cursor)
    return response
