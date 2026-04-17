"""Operations log CRUD endpoints.

Writes and the non-project-scoped reads are on the top-level
``operations_log_router``. The project-scoped collection GET lives on
``operations_log_project_router``, which is mounted under
``/organizations/{org_slug}/projects/{project_id}``.

All reads use ``FINAL`` plus ``WHERE is_deleted = 0`` so that the
``ReplacingMergeTree`` dedupes to the latest version and tombstones
are hidden.
"""

from __future__ import annotations

import base64
import datetime
import logging
import threading
import typing
import urllib.parse

import fastapi
import fastapi.encoders
import fastapi.responses
import nanoid
import pydantic
from imbi_common import clickhouse, models

from imbi_api import patch as json_patch
from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

operations_log_router = fastapi.APIRouter(
    prefix='/operations-log', tags=['Operations Log']
)
operations_log_project_router = fastapi.APIRouter(tags=['Operations Log'])

READONLY_PATHS: frozenset[str] = frozenset(
    [
        '/id',
        '/project_id',
        '/occurred_at',
        '/recorded_at',
        '/recorded_by',
        '/row_version',
        '/is_deleted',
    ]
)

DEFAULT_LIMIT: int = 50
MAX_LIMIT: int = 500


def _encode_cursor(occurred_at: datetime.datetime, entry_id: str) -> str:
    """Encode a (timestamp, id) cursor as urlsafe base64."""
    payload = f'{occurred_at.isoformat()}|{entry_id}'.encode()
    return base64.urlsafe_b64encode(payload).rstrip(b'=').decode('ascii')


def _decode_cursor(
    cursor: str,
) -> tuple[datetime.datetime, str] | None:
    """Decode a cursor string. Return None for any malformed input."""
    if not cursor:
        return None
    padding = '=' * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding).decode('utf-8')
    except (ValueError, UnicodeDecodeError):
        return None
    if '|' not in raw:
        return None
    ts_str, _, entry_id = raw.partition('|')
    if not entry_id:
        return None
    try:
        ts = datetime.datetime.fromisoformat(ts_str)
    except ValueError:
        return None
    return ts, entry_id


def _row_to_response(row: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Strip internal bookkeeping columns before returning to the client."""
    return {
        k: v
        for k, v in row.items()
        if k not in {'_row_version', 'row_version', 'is_deleted'}
    }


def _model_to_row(entry: models.OperationLog) -> dict[str, typing.Any]:
    """Build the ClickHouse row dict from a validated model.

    Uses by_alias=True so the ``_row_version`` column name is emitted
    instead of the Python field name ``row_version``. ``is_deleted`` is
    coerced to UInt8 (0/1) for the ClickHouse UInt8 column.
    """
    dumped = entry.model_dump(by_alias=True, mode='python')
    dumped['is_deleted'] = 1 if entry.is_deleted else 0
    return dumped


async def _insert_row(row: dict[str, typing.Any]) -> None:
    """Insert a single row into operations_log.

    Calls the class method directly with explicit column names/values
    because the module-level ``clickhouse.insert`` wrapper only accepts
    pydantic models and loses the alias during serialization.
    """
    await clickhouse.client.Clickhouse.get_instance().insert(
        'operations_log',
        [list(row.values())],
        list(row.keys()),
    )


@operations_log_router.post('/', status_code=201)
async def create_operation_log(
    data: dict[str, typing.Any],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('operations_log:create'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Create a new operations log entry."""
    payload = dict(data)
    for server_field in (
        'id',
        'recorded_at',
        'recorded_by',
        '_row_version',
        'row_version',
        'is_deleted',
    ):
        payload.pop(server_field, None)

    try:
        entry = models.OperationLog(
            id=nanoid.generate(),
            recorded_at=datetime.datetime.now(datetime.UTC),
            recorded_by=auth.principal_name,
            **payload,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning(
            'Validation error creating opslog entry on fields=%s',
            [tuple(err['loc']) for err in e.errors()],
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    if entry.performed_by is None:
        entry.performed_by = entry.recorded_by

    row = _model_to_row(entry)
    await _insert_row(row)
    return _row_to_response(fastapi.encoders.jsonable_encoder(row))


_SINGLE_ENTRY_SQL: typing.Final[str] = (
    'SELECT * FROM operations_log FINAL '
    'WHERE id = {id:String} AND is_deleted = 0 LIMIT 1'
)


async def _fetch_current(
    entry_id: str,
) -> dict[str, typing.Any] | None:
    """Fetch the current (non-deleted) row for an entry id."""
    rows = await clickhouse.query(_SINGLE_ENTRY_SQL, {'id': entry_id})
    return rows[0] if rows else None


_row_version_lock = threading.Lock()
_row_version_last: int = 0


def _next_row_version(current_version: int) -> int:
    """Return a strictly-increasing ``_row_version`` value.

    ClickHouse ``ReplacingMergeTree`` requires the version column to
    strictly increase per key to guarantee deterministic last-write-wins
    replacement. We combine millisecond-precision wall time with a
    process-wide monotonic guard so two concurrent writers observing the
    same ``current_version`` in the same millisecond still produce
    distinct, strictly-increasing versions; the result is also kept
    greater than ``current_version`` to remain safe against any
    older/current values already in ClickHouse.
    """
    global _row_version_last
    now_ms = int(datetime.datetime.now(datetime.UTC).timestamp() * 1000)
    with _row_version_lock:
        candidate = max(now_ms, _row_version_last + 1, current_version + 1)
        _row_version_last = candidate
        return candidate


_FILTER_FIELDS: tuple[str, ...] = (
    'project_id',
    'project_slug',
    'environment_slug',
    'entry_type',
    'ticket_slug',
    'performed_by',
)


def _parse_iso(value: str, field_name: str) -> datetime.datetime:
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as err:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Invalid ISO timestamp for {field_name!r}',
        ) from err
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def _build_link_header(
    request: fastapi.Request,
    next_cursor: str | None,
) -> str:
    url = request.url
    base_params = {
        k: v for k, v in request.query_params.multi_items() if k != 'cursor'
    }

    def _url_with(params: dict[str, str]) -> str:
        scheme_host_path = f'{url.scheme}://{url.netloc}{url.path}'
        if not params:
            return scheme_host_path
        return f'{scheme_host_path}?{urllib.parse.urlencode(params)}'

    links = [f'<{_url_with(base_params)}>; rel="first"']
    if next_cursor is not None:
        next_params = dict(base_params)
        next_params['cursor'] = next_cursor
        links.append(f'<{_url_with(next_params)}>; rel="next"')
    return ', '.join(links)


async def _list_impl(
    *,
    request: fastapi.Request,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    forced_filters: dict[str, str] | None = None,
    query_filters: dict[str, str | None] | None = None,
    since: str | None = None,
    until: str | None = None,
) -> fastapi.Response:
    """Core implementation for listing operations log entries.

    ``forced_filters`` are applied unconditionally (e.g. project_id from the
    URL path). ``query_filters`` come from query-string parameters and are
    applied only when non-None.
    """
    if limit < 1 or limit > MAX_LIMIT:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'limit must be 1..{MAX_LIMIT}',
        )

    clauses: list[str] = ['is_deleted = 0']
    params: dict[str, typing.Any] = {}

    all_filters: dict[str, str | None] = {
        **(query_filters or {}),
        **(forced_filters or {}),
    }

    for field in _FILTER_FIELDS:
        value = all_filters.get(field)
        if value is not None:
            clauses.append(f'{field} = {{{field}:String}}')
            params[field] = value

    if since is not None:
        params['since'] = _parse_iso(since, 'since')
        clauses.append('occurred_at >= {since:DateTime64(3)}')
    if until is not None:
        params['until'] = _parse_iso(until, 'until')
        clauses.append('occurred_at < {until:DateTime64(3)}')

    if cursor is not None:
        decoded = _decode_cursor(cursor)
        if decoded is None:
            raise fastapi.HTTPException(
                status_code=400, detail='Invalid cursor'
            )
        cursor_ts, cursor_id = decoded
        params['cursor_ts'] = cursor_ts
        params['cursor_id'] = cursor_id
        clauses.append(
            '(occurred_at, id) < '
            '({cursor_ts:DateTime64(3)}, {cursor_id:String})'
        )

    where = ' AND '.join(clauses)
    sql: str = (
        'SELECT * FROM operations_log FINAL WHERE '  # noqa: S608
        + where
        + f' ORDER BY occurred_at DESC, id DESC LIMIT {limit + 1}'
    )

    rows = await clickhouse.query(sql, params)
    next_cursor: str | None = None
    if len(rows) > limit:
        rows.pop()
        last = rows[-1]
        next_cursor = _encode_cursor(last['occurred_at'], last['id'])

    body = [_row_to_response(r) for r in rows]
    response = fastapi.responses.JSONResponse(
        fastapi.encoders.jsonable_encoder(body)
    )
    response.headers['Link'] = _build_link_header(request, next_cursor)
    return response


@operations_log_router.get('/')
async def list_operation_logs(
    request: fastapi.Request,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('operations_log:read'),
        ),
    ],
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    project_id: str | None = None,
    project_slug: str | None = None,
    environment_slug: str | None = None,
    entry_type: str | None = None,
    ticket_slug: str | None = None,
    performed_by: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> fastapi.Response:
    """List operations log entries (newest first, keyset paginated)."""
    return await _list_impl(
        request=request,
        limit=limit,
        cursor=cursor,
        query_filters={
            'project_id': project_id,
            'project_slug': project_slug,
            'environment_slug': environment_slug,
            'entry_type': entry_type,
            'ticket_slug': ticket_slug,
            'performed_by': performed_by,
        },
        since=since,
        until=until,
    )


@operations_log_project_router.get('/')
async def list_project_operation_logs(
    request: fastapi.Request,
    org_slug: str,
    project_id: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('operations_log:read'),
        ),
    ],
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    environment_slug: str | None = None,
    entry_type: str | None = None,
    ticket_slug: str | None = None,
    performed_by: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> fastapi.Response:
    """List operations log entries for a specific project."""
    del org_slug
    return await _list_impl(
        request=request,
        limit=limit,
        cursor=cursor,
        forced_filters={'project_id': project_id},
        query_filters={
            'environment_slug': environment_slug,
            'entry_type': entry_type,
            'ticket_slug': ticket_slug,
            'performed_by': performed_by,
        },
        since=since,
        until=until,
    )


@operations_log_router.get('/{entry_id}')
async def get_operation_log(
    entry_id: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('operations_log:read'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Get a single operations log entry."""
    row = await _fetch_current(entry_id)
    if row is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Operations log entry {entry_id!r} not found',
        )
    return _row_to_response(row)


@operations_log_router.patch('/{entry_id}')
async def patch_operation_log(
    entry_id: str,
    operations: list[json_patch.PatchOperation],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('operations_log:update'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Apply a JSON Patch to an operations log entry."""
    current = await _fetch_current(entry_id)
    if current is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Operations log entry {entry_id!r} not found',
        )

    target = dict(current)
    target['row_version'] = target.pop('_row_version')
    target.pop('is_deleted', None)

    patched = json_patch.apply_patch(target, operations, READONLY_PATHS)

    try:
        entry = models.OperationLog.model_validate(patched)
    except pydantic.ValidationError as e:
        LOGGER.warning(
            'Validation error patching opslog entry on fields=%s',
            [tuple(err['loc']) for err in e.errors()],
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    entry.id = entry_id
    entry.occurred_at = current['occurred_at']
    entry.recorded_at = current['recorded_at']
    entry.recorded_by = current['recorded_by']
    entry.project_id = current['project_id']
    entry.row_version = _next_row_version(int(current['_row_version']))
    entry.is_deleted = False

    row = _model_to_row(entry)
    await _insert_row(row)
    return _row_to_response(fastapi.encoders.jsonable_encoder(row))


@operations_log_router.delete('/{entry_id}', status_code=204)
async def delete_operation_log(
    entry_id: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('operations_log:delete'),
        ),
    ],
) -> fastapi.Response:
    """Soft-delete an operations log entry (tombstone insert)."""
    current = await _fetch_current(entry_id)
    if current is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Operations log entry {entry_id!r} not found',
        )

    tombstone = dict(current)
    tombstone['_row_version'] = _next_row_version(int(current['_row_version']))
    tombstone['is_deleted'] = 1

    await _insert_row(tombstone)
    return fastapi.Response(status_code=204)
