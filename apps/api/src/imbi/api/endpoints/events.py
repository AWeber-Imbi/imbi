"""Events log endpoints.

System-generated events (project attribute changes, etc.) are written here
internally. These are read-only from the API's perspective.

The global router lives at /events; the project-scoped router is mounted at
/organizations/{org_slug}/projects/{project_id}/events.
"""

from __future__ import annotations

import datetime
import typing

import fastapi
import fastapi.encoders
import fastapi.responses
import pydantic
from imbi_common import clickhouse

from imbi_api.auth import permissions
from imbi_api.endpoints._pagination import (
    build_link_header,
    decode_cursor,
    encode_cursor,
    parse_iso,
)

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
        params['since'] = parse_iso(since, 'since')
        clauses.append('recorded_at >= {since:DateTime64(3)}')
    if until is not None:
        params['until'] = parse_iso(until, 'until')
        clauses.append('recorded_at < {until:DateTime64(3)}')

    if cursor is not None:
        decoded = decode_cursor(cursor)
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
        next_cursor = encode_cursor(last['recorded_at'], last['id'])

    body = {'data': [_row_to_response(r) for r in rows]}
    response = fastapi.responses.JSONResponse(
        fastapi.encoders.jsonable_encoder(body)
    )
    response.headers['Link'] = build_link_header(request, next_cursor)
    return response


@events_router.get('/', response_model=EventsPage)
async def list_events(
    request: fastapi.Request,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:events:read'),
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
    """List events across every organization (admin / audit feed).

    Per-project event access lives on the org-scoped router; this
    endpoint is gated on ``admin:events:read`` because the unscoped
    cursor would otherwise expose events for projects the caller has
    no permission on.
    """
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
