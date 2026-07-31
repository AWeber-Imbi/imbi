"""Thumbs-up likes on documents.

A like is one person's thumbs-up on one document, held as a
``(:User)-[:LIKED {at}]->(:Document)`` edge. Unlike comment
acknowledgements -- which live in an ``acknowledged_by`` array property
on the ``Comment`` vertex -- likes are edges for three reasons:

- Toggling an array property is read-modify-write, so two people liking
  at the same moment can lose one of the likes. A ``MERGE``/``DELETE``
  of an edge is atomic per person.
- The edge carries ``at``, so "who liked this, most recent first" is
  answerable. An array has no ordering and no timestamps.
- A popular document's liker list can grow past what belongs in a
  vertex property that every document read has to load.

Liking requires only ``document:read``: if you can read a document you
can like it, and the liker list is visible to anyone who can read the
document. A like is a public act, which is why it does not sit behind
the ``document:analytics:read_identities`` gate that per-reader
analytics does.

Liking is not reading. Likes never feed the read-analytics counters
(``readers``/``views``/``reads``) and a like never implies a read
event; the two are reported side by side.
"""

import datetime
import logging
import typing

import fastapi
import fastapi.responses
import pydantic

from imbi.api.auth import permissions
from imbi.api.endpoints import _document_events, _document_scope
from imbi.api.endpoints._pagination import (
    build_link_header,
    decode_cursor,
    encode_cursor,
)
from imbi.common import graph

LOGGER = logging.getLogger(__name__)

document_likes_router = fastapi.APIRouter(tags=['Documents'])

DEFAULT_LIMIT: int = 50
MAX_LIMIT: int = 500


class LikeStateResponse(pydantic.BaseModel):
    """The document's like count and whether the caller is one of them."""

    like_count: int = 0
    liked_by_me: bool = False


class LikerRef(pydantic.BaseModel):
    principal: str
    display_name: str | None = None
    liked_at: datetime.datetime


class LikerListResponse(pydantic.BaseModel):
    data: list[LikerRef]


# Emitted by every route so the response always carries current state.
# ``DISTINCT`` guards the count against a duplicate edge: ``MERGE`` makes
# one impossible today, but a count that silently doubles would be a
# nasty way to discover otherwise. Aggregates run stepwise so each
# OPTIONAL MATCH cannot multiply the rows of the next. ``project_id``
# rides along for the activity-feed event and is null for documents
# attached to a project type or a user.
_LIKE_STATE_TAIL: typing.LiteralString = """
    OPTIONAL MATCH (liker:User)-[:LIKED]->(d)
    WITH d, count(DISTINCT liker) AS like_count
    OPTIONAL MATCH (me:User {{email: {principal}}})-[:LIKED]->(d)
    WITH d, like_count, count(me) > 0 AS liked_by_me
    OPTIONAL MATCH (d)-[:ATTACHED_TO]->(proj:Project)
    RETURN like_count, liked_by_me, proj.id AS project_id
"""

_LIKE_STATE_COLUMNS: list[str] = ['like_count', 'liked_by_me', 'project_id']


def _parse_like_state(
    record: dict[str, typing.Any],
) -> tuple[LikeStateResponse, str]:
    """Split a ``_LIKE_STATE_TAIL`` row into response state + project id."""
    project_id = graph.parse_agtype(record['project_id'])
    return (
        LikeStateResponse(
            like_count=int(graph.parse_agtype(record['like_count']) or 0),
            liked_by_me=bool(graph.parse_agtype(record['liked_by_me'])),
        ),
        str(project_id) if project_id else '',
    )


@document_likes_router.put('/like', response_model=LikeStateResponse)
async def like_document(
    org_slug: str,
    document_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
    background_tasks: fastapi.BackgroundTasks,
) -> LikeStateResponse:
    """Like the document as the calling principal.

    Idempotent: liking a document twice leaves one like, and the second
    call does not disturb the original ``at`` timestamp, so a
    double-tapped button cannot reorder the liker list.
    """
    # AGE implements MERGE but not ``ON CREATE SET``, so ``coalesce``
    # carries the original timestamp forward on a repeat like.
    query: typing.LiteralString = (
        _document_scope.BY_ID
        + _document_scope.DISTINCT_DOCUMENT
        + """
    MATCH (me:User {{email: {principal}}})
          -[:MEMBER_OF]->(:Organization {{slug: {org_slug}}})
    MERGE (me)-[l:LIKED]->(d)
    SET l.at = coalesce(l.at, {now})
    WITH d
    """
        + _LIKE_STATE_TAIL
    )
    now = datetime.datetime.now(datetime.UTC)
    records = await db.execute(
        query,
        {
            'document_id': document_id,
            'org_slug': org_slug,
            'principal': auth.principal_name,
            'now': now.isoformat(),
        },
        columns=_LIKE_STATE_COLUMNS,
    )
    if not records:
        # Either the document is not in this org or the caller is not a
        # member of it; both are a 404 from the caller's point of view.
        raise fastapi.HTTPException(
            status_code=404, detail=f'Document {document_id!r} not found'
        )
    state, project_id = _parse_like_state(records[0])
    background_tasks.add_task(
        _document_events.emit_like_event,
        org_slug=org_slug,
        project_id=project_id,
        document_id=document_id,
        principal=auth.principal_name,
        action='like',
        occurred_at=now,
    )
    return state


@document_likes_router.delete('/like', response_model=LikeStateResponse)
async def unlike_document(
    org_slug: str,
    document_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
    background_tasks: fastapi.BackgroundTasks,
) -> LikeStateResponse:
    """Remove the calling principal's like.

    Idempotent: unliking a document the caller never liked succeeds and
    reports the unchanged count.
    """
    query: typing.LiteralString = (
        _document_scope.BY_ID
        + _document_scope.DISTINCT_DOCUMENT
        + """
    OPTIONAL MATCH (me:User {{email: {principal}}})-[l:LIKED]->(d)
    DELETE l
    WITH d
    """
        + _LIKE_STATE_TAIL
    )
    records = await db.execute(
        query,
        {
            'document_id': document_id,
            'org_slug': org_slug,
            'principal': auth.principal_name,
        },
        columns=_LIKE_STATE_COLUMNS,
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Document {document_id!r} not found'
        )
    state, project_id = _parse_like_state(records[0])
    background_tasks.add_task(
        _document_events.emit_like_event,
        org_slug=org_slug,
        project_id=project_id,
        document_id=document_id,
        principal=auth.principal_name,
        action='unlike',
        occurred_at=datetime.datetime.now(datetime.UTC),
    )
    return state


@document_likes_router.get('/likes', response_model=LikerListResponse)
async def list_document_likers(
    request: fastapi.Request,
    org_slug: str,
    document_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> fastapi.Response:
    """List who liked the document, most recent first."""
    if limit < 1 or limit > MAX_LIMIT:
        raise fastapi.HTTPException(
            status_code=400, detail=f'limit must be 1..{MAX_LIMIT}'
        )

    params: dict[str, typing.Any] = {
        'document_id': document_id,
        'org_slug': org_slug,
        'row_limit': limit + 1,
    }
    cursor_clause: typing.LiteralString = ''
    if cursor is not None:
        decoded = decode_cursor(cursor)
        if decoded is None:
            raise fastapi.HTTPException(
                status_code=400, detail='Invalid cursor'
            )
        cursor_ts, cursor_email = decoded
        cursor_clause = (
            ' WHERE (l.at < {cursor_ts}'
            ' OR (l.at = {cursor_ts} AND liker.email < {cursor_email}))'
        )
        params['cursor_ts'] = cursor_ts.isoformat()
        params['cursor_email'] = cursor_email

    query: str = (
        _document_scope.BY_ID
        + _document_scope.DISTINCT_DOCUMENT
        + """
    MATCH (liker:User)-[l:LIKED]->(d)"""
        + cursor_clause
        + """
    RETURN liker.email AS email,
           liker.display_name AS display_name,
           l.at AS liked_at
    ORDER BY liked_at DESC, email DESC
    LIMIT {row_limit}
    """
    )
    records = await db.execute(
        query, params, columns=['email', 'display_name', 'liked_at']
    )

    likers: list[LikerRef] = []
    for record in records:
        email = graph.parse_agtype(record['email'])
        liked_at_raw = graph.parse_agtype(record['liked_at'])
        if not email or not liked_at_raw:
            continue
        display_name = graph.parse_agtype(record['display_name'])
        likers.append(
            LikerRef(
                principal=str(email),
                display_name=str(display_name) if display_name else None,
                liked_at=datetime.datetime.fromisoformat(str(liked_at_raw)),
            )
        )

    next_cursor: str | None = None
    if len(likers) > limit:
        likers = likers[:limit]
        next_cursor = encode_cursor(likers[-1].liked_at, likers[-1].principal)

    adapter = pydantic.TypeAdapter(list[LikerRef])
    response = fastapi.responses.JSONResponse(
        {'data': adapter.dump_python(likers, mode='json')}
    )
    response.headers['Link'] = build_link_header(request, next_cursor)
    return response
