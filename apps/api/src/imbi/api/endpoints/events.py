"""Events log endpoints.

System-generated events (project attribute changes, etc.) are written here
internally. These are read-only from the API's perspective.

The global router lives at /events; the project-scoped router is mounted at
/organizations/{org_slug}/projects/{project_id}/events.
"""

from __future__ import annotations

import datetime
import json
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
    integration: str
    attributed_to: str
    metadata: dict[str, typing.Any]
    payload: dict[str, typing.Any]


class EventsPage(pydantic.BaseModel):
    data: list[EventRecord]


#: Columns to return on every read. ``metadata`` and ``payload`` are
#: ClickHouse ``JSON`` columns; clickhouse-connect returns nested
#: array-of-tuple paths in their internal binary form (Python
#: ``bytes``) that fastapi's encoder can't serialize. Wrapping them
#: in :func:`toJSONString` forces ClickHouse to serialize each value
#: as JSON text we then ``json.loads`` server-side, so the response
#: encoder only sees ``dict`` / ``list`` / scalar trees.
_SELECT_COLUMNS: str = (
    'id, project_id, recorded_at, type, integration, '
    'attributed_to, toJSONString(metadata) AS metadata, '
    'toJSONString(payload) AS payload'
)


def _parse_json_column(value: object, column_name: str) -> object:
    """Parse a ``toJSONString``-serialized JSON column into Python.

    Defensive: a malformed value gets returned as a marker dict so a
    single bad row doesn't sink the whole list response.
    """
    if isinstance(value, dict | list):
        # clickhouse-connect can hand back an already-parsed structure
        # (with non-UTF-8 ``bytes`` buried in string values); pass it
        # through so the response encoder decodes those bytes leniently.
        return typing.cast(object, value)
    if isinstance(value, bytes):
        value = value.decode('utf-8', errors='replace')
    if not isinstance(value, str):
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {
            '__raw__': value,
            '__error__': f'invalid JSON in {column_name}',
        }


def _row_to_response(row: dict[str, typing.Any]) -> dict[str, typing.Any]:
    out: dict[str, typing.Any] = {}
    for k, v in row.items():
        if isinstance(v, datetime.datetime) and v.tzinfo is None:
            out[k] = v.replace(tzinfo=datetime.UTC)
        elif k in ('metadata', 'payload'):
            out[k] = _parse_json_column(v, k)
        else:
            out[k] = v
    return out


def _events_response(body: object) -> fastapi.responses.JSONResponse:
    """Serialize an events response body to JSON.

    Both read paths (the list feed and the by-id lookup) route through
    here so they share one decode policy: ClickHouse can hand back raw
    ``bytes`` for JSON string values that aren't valid UTF-8 (e.g.
    cp1252 smart quotes in webhook payloads); decode them leniently so
    one bad row can't 500 the response.
    """
    return fastapi.responses.JSONResponse(
        fastapi.encoders.jsonable_encoder(
            body,
            custom_encoder={bytes: lambda o: o.decode(errors='replace')},
        )
    )


_FILTER_FIELDS: tuple[str, ...] = (
    'project_id',
    'type',
    'attributed_to',
    'integration',
)


async def _list_impl(
    *,
    request: fastapi.Request,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    forced_filters: dict[str, str] | None = None,
    query_filters: dict[str, str | None] | None = None,
    event_type: str | None = None,
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

    if event_type is not None:
        # ``metadata.event_type`` carries the resolved per-source
        # event-type label written by the gateway (e.g. 'pull_request',
        # 'push'). The top-level ``type`` column is the event
        # *category* — clients filter ``type='webhook'`` for the
        # webhook-history view and use this field to narrow further.
        clauses.append(
            "CAST(metadata.event_type, 'String') = {event_type:String}"
        )
        params['event_type'] = event_type

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
        f'SELECT {_SELECT_COLUMNS} FROM events WHERE '  # noqa: S608
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
    response = _events_response(body)
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
    event_type: str | None = None,
    attributed_to: str | None = None,
    integration: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> fastapi.Response:
    """List events across every organization (admin / audit feed).

    ``type`` is the event *category* (e.g. 'webhook'); ``event_type``
    narrows further by the per-source label in
    ``metadata.event_type`` (e.g. 'pull_request', 'push').

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
            'integration': integration,
        },
        event_type=event_type,
        since=since,
        until=until,
    )


@events_router.get('/{event_id}', response_model=EventRecord)
async def get_event(
    event_id: str,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('admin:events:read'),
        ),
    ],
) -> fastapi.Response:
    """Fetch a single event by id.

    Powers the webhook-history deep-link landing in the admin UI:
    visiting a shared event URL must work even when the event has
    aged past the default cursor page.
    """
    rows = await clickhouse.query(
        f'SELECT {_SELECT_COLUMNS} FROM events '  # noqa: S608
        'WHERE id = {event_id:String}',
        {'event_id': event_id},
    )
    if not rows:
        raise fastapi.HTTPException(status_code=404, detail='Event not found')
    return _events_response(_row_to_response(rows[0]))


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
    event_type: str | None = None,
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
        event_type=event_type,
        since=since,
        until=until,
    )
