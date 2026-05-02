"""Events log endpoints.

System-generated events (project attribute changes, etc.) are written here
internally. These are read-only from the API's perspective.

The global router lives at /events; the project-scoped router is mounted at
/organizations/{org_slug}/projects/{project_id}/events.
"""

from __future__ import annotations

import base64
import datetime
import typing
import urllib.parse

import fastapi
import fastapi.encoders
import fastapi.responses
import pydantic
from imbi_common import clickhouse

from imbi_api.auth import permissions

events_router = fastapi.APIRouter(prefix='/events', tags=['Events'])
events_project_router = fastapi.APIRouter(tags=['Events'])

DEFAULT_LIMIT: int = 50
MAX_LIMIT: int = 500


class EventRecord(pydantic.BaseModel):
    id: str
    project_id: str
    recorded_at: datetime.datetime
    type: str
    third_party_service: str
    attributed_to: str
    metadata: dict[str, typing.Any]
    payload: dict[str, typing.Any]


class EventsPage(pydantic.BaseModel):
    data: list[EventRecord]


def _encode_cursor(recorded_at: datetime.datetime, entry_id: str) -> str:
    raw = f'{recorded_at.isoformat()}|{entry_id}'.encode()
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _decode_cursor(cursor: str) -> tuple[datetime.datetime, str] | None:
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
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.UTC)
    return ts.astimezone(datetime.UTC), entry_id


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


def _row_to_response(row: dict[str, typing.Any]) -> dict[str, typing.Any]:
    out: dict[str, typing.Any] = {}
    for k, v in row.items():
        if isinstance(v, datetime.datetime) and v.tzinfo is None:
            v = v.replace(tzinfo=datetime.UTC)
        out[k] = v
    return out


_FILTER_FIELDS: tuple[str, ...] = (
    'project_id',
    'type',
    'attributed_to',
    'third_party_service',
)


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
    if limit < 1 or limit > MAX_LIMIT:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'limit must be 1..{MAX_LIMIT}',
        )

    clauses: list[str] = []
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
        clauses.append('recorded_at >= {since:DateTime64(3)}')
    if until is not None:
        params['until'] = _parse_iso(until, 'until')
        clauses.append('recorded_at < {until:DateTime64(3)}')

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
            '(recorded_at, id) < '
            '({cursor_ts:DateTime64(3)}, {cursor_id:String})'
        )

    where = ' AND '.join(clauses) if clauses else '1=1'
    params['row_limit'] = limit + 1
    sql: str = (
        'SELECT * FROM events WHERE '  # noqa: S608
        + where
        + ' ORDER BY recorded_at DESC, id DESC LIMIT {row_limit:UInt32}'
    )

    rows = await clickhouse.query(sql, params)
    next_cursor: str | None = None
    if len(rows) > limit:
        rows.pop()
        last = rows[-1]
        next_cursor = _encode_cursor(last['recorded_at'], last['id'])

    body = {'data': [_row_to_response(r) for r in rows]}
    response = fastapi.responses.JSONResponse(
        fastapi.encoders.jsonable_encoder(body)
    )
    response.headers['Link'] = _build_link_header(request, next_cursor)
    return response


@events_router.get('/', response_model=EventsPage)
async def list_events(
    request: fastapi.Request,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    project_id: str | None = None,
    type: str | None = None,
    attributed_to: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> fastapi.Response:
    """List events (newest first, keyset paginated)."""
    return await _list_impl(
        request=request,
        limit=limit,
        cursor=cursor,
        query_filters={
            'project_id': project_id,
            'type': type,
            'attributed_to': attributed_to,
        },
        since=since,
        until=until,
    )


@events_project_router.get('/', response_model=EventsPage)
async def list_project_events(
    request: fastapi.Request,
    org_slug: str,
    project_id: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    type: str | None = None,
    attributed_to: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> fastapi.Response:
    """List events for a specific project."""
    del org_slug
    return await _list_impl(
        request=request,
        limit=limit,
        cursor=cursor,
        forced_filters={'project_id': project_id},
        query_filters={
            'type': type,
            'attributed_to': attributed_to,
        },
        since=since,
        until=until,
    )
