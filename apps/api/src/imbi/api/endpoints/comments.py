"""Page-level threaded comments on documents.

Comments hang off a ``Document`` via a ``CommentThread`` vertex
(``ON_DOCUMENT`` edge) containing one or more ``Comment`` vertices
(``IN_THREAD`` edge). The root comment is the oldest comment in a thread;
replies follow in ``created_at`` order.

``kind='page'`` threads persist the anchor properties as empty strings /
``0`` and surface ``anchor: null``. ``kind='inline'`` threads carry an
anchor (quote/prefix/suffix/start) and round-trip it on read.

Modeled on :mod:`imbi.api.endpoints.documents`: raw Cypher via
``db.execute(...)`` + ``graph.parse_agtype(...)`` with local Pydantic
request/response models (no dependency on ``imbi.common.models`` comment
types).
"""

import datetime
import logging
import typing

import fastapi
import nanoid
import pydantic

from imbi.api.auth import permissions
from imbi.api.endpoints import _search_index
from imbi.common import graph, iggy, models
from imbi.common import patch as json_patch

LOGGER = logging.getLogger(__name__)

comments_router = fastapi.APIRouter(tags=['Comments'])

# Event type written to the ClickHouse ``events`` table so comment activity
# surfaces in the project + user activity feeds.
_COMMENT_EVENT_TYPE: typing.LiteralString = 'document-comment'


async def _emit_comment_event(
    *,
    project_id: str | None,
    document_id: str,
    thread_id: str,
    comment_id: str,
    kind: str,
    action: str,
    principal: str,
    body: str,
) -> None:
    """Best-effort: record a comment as an ``events`` row.

    Mirrors the project-change emit in ``projects.py``. Never raises -- a
    failed analytics write must not fail the comment request.
    """
    try:
        await iggy.publish_rows(
            'events',
            'comments',
            [
                {
                    'id': nanoid.generate(),
                    'project_id': project_id or '',
                    'recorded_at': datetime.datetime.now(datetime.UTC),
                    'type': _COMMENT_EVENT_TYPE,
                    'integration': 'internal',
                    'attributed_to': principal,
                    'metadata': {},
                    'payload': {
                        'document_id': document_id,
                        'thread_id': thread_id,
                        'comment_id': comment_id,
                        'kind': kind,
                        'action': action,
                        'excerpt': body[:140],
                    },
                }
            ],
        )
    except Exception:
        LOGGER.exception(
            'Failed to emit comment event for document %s', document_id
        )


# Every thread field except ``/resolved`` is read-only over the PATCH API.
_THREAD_READONLY_PATHS: frozenset[str] = frozenset(
    [
        '/id',
        '/document_id',
        '/kind',
        '/anchor',
        '/resolved_by',
        '/resolved_at',
        '/created_by',
        '/created_at',
        '/updated_at',
    ]
)

# Every comment field except ``/body`` and ``/mentions`` is read-only over
# the PATCH API.
_COMMENT_READONLY_PATHS: frozenset[str] = frozenset(
    [
        '/id',
        '/thread_id',
        '/author',
        '/acknowledged_by',
        '/edited',
        '/created_at',
        '/updated_at',
    ]
)


class AnchorModel(pydantic.BaseModel):
    quote: str
    prefix: str
    suffix: str
    start: int


class CommentResponse(pydantic.BaseModel):
    id: str
    thread_id: str
    author: str
    body: str
    mentions: list[str] = []
    acknowledged_by: list[str] = []
    edited: bool = False
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None


class CommentThreadResponse(pydantic.BaseModel):
    id: str
    document_id: str
    kind: str
    resolved: bool
    resolved_by: str | None = None
    resolved_at: datetime.datetime | None = None
    anchor: AnchorModel | None = None
    created_by: str
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None
    comments: list[CommentResponse] = []


class CommentThreadListResponse(pydantic.BaseModel):
    data: list[CommentThreadResponse]


class CommentThreadCreate(pydantic.BaseModel):
    kind: typing.Literal['page', 'inline'] = 'page'
    body: str = pydantic.Field(min_length=1)
    anchor: AnchorModel | None = None
    mentions: list[str] = []

    @pydantic.model_validator(mode='after')
    def _validate_anchor(self) -> typing.Self:
        if self.kind == 'inline':
            if self.anchor is None or not self.anchor.quote.strip():
                raise ValueError(
                    'inline threads require an anchor with a non-empty quote'
                )
        else:
            self.anchor = None
        return self


class CommentBodyCreate(pydantic.BaseModel):
    body: str = pydantic.Field(min_length=1)
    mentions: list[str] = []


def _str_list(value: typing.Any) -> list[str]:
    """Coerce a parsed agtype value into a list of strings."""
    if not isinstance(value, list):
        return []
    items = typing.cast('list[object]', value)
    return [str(v) for v in items]


def _parse_comment(record: typing.Any) -> dict[str, typing.Any]:
    """Build a ``CommentResponse``-shaped dict from a parsed comment map."""
    comment: dict[str, typing.Any] = graph.parse_agtype(record)
    return {
        'id': comment['id'],
        'thread_id': comment.get('thread_id', ''),
        'author': comment.get('author', ''),
        'body': comment.get('body', ''),
        'mentions': _str_list(comment.get('mentions')),
        'acknowledged_by': _str_list(comment.get('acknowledged_by')),
        'edited': bool(comment.get('edited', False)),
        'created_at': comment.get('created_at'),
        'updated_at': comment.get('updated_at'),
    }


def _parse_thread_row(record: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Build a ``CommentThreadResponse``-shaped dict from a thread row.

    Expects columns ``t`` (thread), ``d`` (document), and ``comments``
    (a list of comment maps already ordered oldest-first).
    """
    thread: dict[str, typing.Any] = graph.parse_agtype(record['t'])
    document: dict[str, typing.Any] = graph.parse_agtype(record['d'])
    raw_comments: list[typing.Any] = graph.parse_agtype(record['comments'])
    comments = [
        _parse_comment(c) for c in (raw_comments or []) if isinstance(c, dict)
    ]
    kind = thread.get('kind', 'page')
    anchor: dict[str, typing.Any] | None = None
    quote = thread.get('anchor_quote') or ''
    if kind != 'page' and quote:
        anchor = {
            'quote': str(quote),
            'prefix': str(thread.get('anchor_prefix') or ''),
            'suffix': str(thread.get('anchor_suffix') or ''),
            'start': int(thread.get('anchor_start') or 0),
        }
    return {
        'id': thread['id'],
        'document_id': document.get('id', ''),
        'kind': kind,
        'resolved': bool(thread.get('resolved', False)),
        'resolved_by': thread.get('resolved_by'),
        'resolved_at': thread.get('resolved_at'),
        'anchor': anchor,
        'created_by': thread.get('created_by', ''),
        'created_at': thread.get('created_at'),
        'updated_at': thread.get('updated_at'),
        'comments': comments,
    }


# Tail fragment that collects a thread's comments oldest-first. Runs with
# ``t, d`` in scope and emits ``t, d, comments``.
#
# Comments are collected as **map projections** (``c{.id, ...}``), never as
# raw vertices: ``graph.parse_agtype`` only strips a trailing ``::vertex``
# suffix, so a ``collect()`` of raw vertices yields a list-string with inner
# ``::vertex`` suffixes that ``json.loads`` rejects -- it falls back to the
# raw string, which then iterates character-by-character into an empty list.
# Map projections serialize as plain JSON maps and round-trip cleanly. This
# mirrors ``documents.py`` ``_TAGS_TAIL``.
_COMMENTS_TAIL: typing.LiteralString = """
    OPTIONAL MATCH (c:Comment)-[:IN_THREAD]->(t)
    WITH t, d, c ORDER BY c.created_at ASC, c.id ASC
    WITH t, d, collect(CASE WHEN c IS NOT NULL
                            THEN c{{.id, .thread_id, .author, .body,
                                    .mentions, .acknowledged_by, .edited,
                                    .created_at, .updated_at}}
                            END) AS raw_comments
    WITH t, d, [x IN raw_comments WHERE x IS NOT NULL] AS comments
    RETURN t, d, comments
"""

# Document-ownership join used by every query to scope the document to
# the organization through whichever vertex it is attached to (project,
# project type, or user). When ``{project_id}`` is non-null the document
# must additionally be attached to that project — this keeps the
# project-scoped comment routes from resolving another project's
# document.
_DOC_JOIN: typing.LiteralString = """
    MATCH (d:Document {{id: {document_id}}})
    OPTIONAL MATCH (d)-[:ATTACHED_TO]->(p:Project)
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (d)-[:ATTACHED_TO]->(pt:ProjectType)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (d)-[:ATTACHED_TO]->(u:User)
          -[:MEMBER_OF]->(:Organization {{slug: {org_slug}}})
          <-[:BELONGS_TO]-(d)
    WITH d, p, pt, u
    WHERE ({project_id} IS NULL
           AND (p IS NOT NULL OR pt IS NOT NULL OR u IS NOT NULL))
       OR (p IS NOT NULL AND p.id = {project_id})
    WITH DISTINCT d
"""


async def _verify_document(
    db: graph.Pool,
    org_slug: str,
    project_id: str | None,
    document_id: str,
) -> None:
    """Raise 404 unless the document belongs to the org.

    When ``project_id`` is provided the document must be attached to
    that project.
    """
    query: str = _DOC_JOIN + 'RETURN d.id AS id'
    records = await db.execute(
        query,
        {
            'document_id': document_id,
            'project_id': project_id,
            'org_slug': org_slug,
        },
        columns=['id'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Document {document_id!r} not found',
        )


async def _fetch_thread(
    db: graph.Pool,
    org_slug: str,
    project_id: str | None,
    document_id: str,
    thread_id: str,
) -> dict[str, typing.Any] | None:
    """Return a single thread (with ordered comments) or ``None``."""
    query: str = (
        _DOC_JOIN
        + """
    MATCH (t:CommentThread {{id: {thread_id}}})-[:ON_DOCUMENT]->(d)
    WITH DISTINCT t, d
    """
        + _COMMENTS_TAIL
    )
    records = await db.execute(
        query,
        {
            'document_id': document_id,
            'project_id': project_id,
            'org_slug': org_slug,
            'thread_id': thread_id,
        },
        columns=['t', 'd', 'comments'],
    )
    if not records:
        return None
    return _parse_thread_row(records[0])


async def _fetch_comment(
    db: graph.Pool,
    org_slug: str,
    project_id: str | None,
    document_id: str,
    thread_id: str,
    comment_id: str,
) -> dict[str, typing.Any] | None:
    """Return a single comment dict or ``None``."""
    query: str = (
        _DOC_JOIN
        + """
    MATCH (c:Comment {{id: {comment_id}}})
          -[:IN_THREAD]->(t:CommentThread {{id: {thread_id}}})
          -[:ON_DOCUMENT]->(d)
    RETURN c
    """
    )
    records = await db.execute(
        query,
        {
            'document_id': document_id,
            'project_id': project_id,
            'org_slug': org_slug,
            'thread_id': thread_id,
            'comment_id': comment_id,
        },
        columns=['c'],
    )
    if not records:
        return None
    return _parse_comment(records[0]['c'])


@comments_router.get('', response_model=CommentThreadListResponse)
async def list_comment_threads(
    org_slug: str,
    document_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
    project_id: str | None = None,
) -> dict[str, typing.Any]:
    """List every comment thread on a document, comments oldest-first."""
    await _verify_document(db, org_slug, project_id, document_id)
    query: str = (
        _DOC_JOIN
        + """
    MATCH (t:CommentThread)-[:ON_DOCUMENT]->(d)
    WITH DISTINCT t, d, t.created_at AS sort_ts, t.id AS sort_id
    ORDER BY sort_ts ASC, sort_id ASC
    """
        + _COMMENTS_TAIL
    )
    records = await db.execute(
        query,
        {
            'document_id': document_id,
            'project_id': project_id,
            'org_slug': org_slug,
        },
        columns=['t', 'd', 'comments'],
    )
    return {'data': [_parse_thread_row(r) for r in records]}


@comments_router.post(
    '', status_code=201, response_model=CommentThreadResponse
)
async def create_comment_thread(
    org_slug: str,
    document_id: str,
    data: CommentThreadCreate,
    db: graph.Pool,
    background_tasks: fastapi.BackgroundTasks,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('comment:create')),
    ],
    project_id: str | None = None,
) -> dict[str, typing.Any]:
    """Create a thread, its ``ON_DOCUMENT`` edge, and the root comment."""
    await _verify_document(db, org_slug, project_id, document_id)

    now = datetime.datetime.now(datetime.UTC)
    thread_id = nanoid.generate()
    comment_id = nanoid.generate()
    anchor = data.anchor
    query: typing.LiteralString = (
        _DOC_JOIN
        + """
    CREATE (t:CommentThread {{
        id: {thread_id},
        kind: {kind},
        resolved: {resolved},
        resolved_by: {resolved_by},
        resolved_at: {resolved_at},
        anchor_quote: {anchor_quote},
        anchor_prefix: {anchor_prefix},
        anchor_suffix: {anchor_suffix},
        anchor_start: {anchor_start},
        created_by: {created_by},
        created_at: {created_at},
        updated_at: {updated_at}
    }})
    CREATE (t)-[:ON_DOCUMENT]->(d)
    CREATE (c:Comment {{
        id: {comment_id},
        thread_id: {thread_id},
        author: {author},
        body: {body},
        mentions: {mentions},
        acknowledged_by: {acknowledged_by},
        edited: {edited},
        created_at: {created_at},
        updated_at: {updated_at}
    }})
    CREATE (c)-[:IN_THREAD]->(t)
    RETURN t.id AS id
    """
    )
    records = await db.execute(
        query,
        {
            'document_id': document_id,
            'project_id': project_id,
            'org_slug': org_slug,
            'thread_id': thread_id,
            'kind': data.kind,
            'resolved': False,
            'resolved_by': None,
            'resolved_at': None,
            'anchor_quote': anchor.quote if anchor else '',
            'anchor_prefix': anchor.prefix if anchor else '',
            'anchor_suffix': anchor.suffix if anchor else '',
            'anchor_start': anchor.start if anchor else 0,
            'created_by': auth.principal_name,
            'created_at': now.isoformat(),
            'updated_at': None,
            'comment_id': comment_id,
            'author': auth.principal_name,
            'body': data.body,
            'mentions': list(data.mentions),
            'acknowledged_by': [],
            'edited': False,
        },
        columns=['id'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Document {document_id!r} not found',
        )
    thread = await _fetch_thread(
        db, org_slug, project_id, document_id, thread_id
    )
    if thread is None:
        raise fastapi.HTTPException(
            status_code=500,
            detail='Thread created but could not be read back',
        )
    await _emit_comment_event(
        project_id=project_id,
        document_id=document_id,
        thread_id=thread_id,
        comment_id=comment_id,
        kind=data.kind,
        action='created',
        principal=auth.principal_name,
        body=data.body,
    )
    background_tasks.add_task(
        _search_index.index,
        db,
        models.Comment,
        comment_id,
    )
    return thread


@comments_router.post(
    '/{thread_id}/comments',
    status_code=201,
    response_model=CommentResponse,
)
async def create_reply(
    org_slug: str,
    document_id: str,
    thread_id: str,
    data: CommentBodyCreate,
    db: graph.Pool,
    background_tasks: fastapi.BackgroundTasks,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('comment:create')),
    ],
    project_id: str | None = None,
) -> dict[str, typing.Any]:
    """Add a reply comment to an existing thread."""
    now = datetime.datetime.now(datetime.UTC)
    comment_id = nanoid.generate()
    query: typing.LiteralString = (
        _DOC_JOIN
        + """
    MATCH (t:CommentThread {{id: {thread_id}}})-[:ON_DOCUMENT]->(d)
    CREATE (c:Comment {{
        id: {comment_id},
        thread_id: {thread_id},
        author: {author},
        body: {body},
        mentions: {mentions},
        acknowledged_by: {acknowledged_by},
        edited: {edited},
        created_at: {created_at},
        updated_at: {updated_at}
    }})
    CREATE (c)-[:IN_THREAD]->(t)
    RETURN c
    """
    )
    records = await db.execute(
        query,
        {
            'document_id': document_id,
            'project_id': project_id,
            'org_slug': org_slug,
            'thread_id': thread_id,
            'comment_id': comment_id,
            'author': auth.principal_name,
            'body': data.body,
            'mentions': list(data.mentions),
            'acknowledged_by': [],
            'edited': False,
            'created_at': now.isoformat(),
            'updated_at': None,
        },
        columns=['c'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Thread {thread_id!r} not found',
        )
    await _emit_comment_event(
        project_id=project_id,
        document_id=document_id,
        thread_id=thread_id,
        comment_id=comment_id,
        kind='',
        action='replied',
        principal=auth.principal_name,
        body=data.body,
    )
    background_tasks.add_task(
        _search_index.index,
        db,
        models.Comment,
        comment_id,
    )
    return _parse_comment(records[0]['c'])


@comments_router.patch('/{thread_id}', response_model=CommentThreadResponse)
async def patch_comment_thread(
    org_slug: str,
    document_id: str,
    thread_id: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('comment:write')),
    ],
    project_id: str | None = None,
) -> dict[str, typing.Any]:
    """Resolve or reopen a thread via JSON Patch (only ``/resolved``)."""
    existing = await _fetch_thread(
        db, org_slug, project_id, document_id, thread_id
    )
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Thread {thread_id!r} not found'
        )

    current = {'resolved': bool(existing.get('resolved', False))}
    patched = json_patch.apply_patch(
        current, operations, _THREAD_READONLY_PATHS
    )
    resolved = patched.get('resolved')
    if not isinstance(resolved, bool):
        raise fastapi.HTTPException(
            status_code=400, detail='resolved must be a boolean'
        )

    now = datetime.datetime.now(datetime.UTC)
    resolved_by = auth.principal_name if resolved else None
    resolved_at = now.isoformat() if resolved else None
    query: typing.LiteralString = (
        _DOC_JOIN
        + """
    MATCH (t:CommentThread {{id: {thread_id}}})-[:ON_DOCUMENT]->(d)
    SET t.resolved = {resolved},
        t.resolved_by = {resolved_by},
        t.resolved_at = {resolved_at},
        t.updated_at = {updated_at}
    RETURN t.id AS id
    """
    )
    records = await db.execute(
        query,
        {
            'document_id': document_id,
            'project_id': project_id,
            'org_slug': org_slug,
            'thread_id': thread_id,
            'resolved': resolved,
            'resolved_by': resolved_by,
            'resolved_at': resolved_at,
            'updated_at': now.isoformat(),
        },
        columns=['id'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Thread {thread_id!r} not found'
        )
    thread = await _fetch_thread(
        db, org_slug, project_id, document_id, thread_id
    )
    if thread is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Thread {thread_id!r} not found'
        )
    return thread


@comments_router.patch(
    '/{thread_id}/comments/{comment_id}',
    response_model=CommentResponse,
)
async def patch_comment(
    org_slug: str,
    document_id: str,
    thread_id: str,
    comment_id: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    background_tasks: fastapi.BackgroundTasks,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('comment:write')),
    ],
    project_id: str | None = None,
) -> dict[str, typing.Any]:
    """Edit a comment via JSON Patch (only ``/body`` and ``/mentions``).

    Author-only.
    """
    existing = await _fetch_comment(
        db, org_slug, project_id, document_id, thread_id, comment_id
    )
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Comment {comment_id!r} not found'
        )
    if existing['author'] != auth.principal_name:
        raise fastapi.HTTPException(
            status_code=403,
            detail='Only the comment author may edit it',
        )

    current = {
        'body': existing['body'],
        'mentions': list(existing['mentions']),
    }
    patched = json_patch.apply_patch(
        current, operations, _COMMENT_READONLY_PATHS
    )
    try:
        update = CommentBodyCreate(
            body=patched.get('body'),  # type: ignore[arg-type]
            mentions=patched.get('mentions'),  # type: ignore[arg-type]
        )
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    now = datetime.datetime.now(datetime.UTC)
    query: typing.LiteralString = (
        _DOC_JOIN
        + """
    MATCH (c:Comment {{id: {comment_id}}})
          -[:IN_THREAD]->(:CommentThread {{id: {thread_id}}})
          -[:ON_DOCUMENT]->(d)
    SET c.body = {body},
        c.mentions = {mentions},
        c.edited = {edited},
        c.updated_at = {updated_at}
    RETURN c
    """
    )
    records = await db.execute(
        query,
        {
            'document_id': document_id,
            'project_id': project_id,
            'org_slug': org_slug,
            'thread_id': thread_id,
            'comment_id': comment_id,
            'body': update.body,
            'mentions': list(update.mentions),
            'edited': True,
            'updated_at': now.isoformat(),
        },
        columns=['c'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Comment {comment_id!r} not found'
        )
    if update.body != existing['body']:
        background_tasks.add_task(
            _search_index.index,
            db,
            models.Comment,
            comment_id,
        )
    return _parse_comment(records[0]['c'])


@comments_router.post(
    '/{thread_id}/comments/{comment_id}/acknowledge',
    response_model=CommentResponse,
)
async def acknowledge_comment(
    org_slug: str,
    document_id: str,
    thread_id: str,
    comment_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('comment:write')),
    ],
    project_id: str | None = None,
) -> dict[str, typing.Any]:
    """Toggle the principal in the comment's ``acknowledged_by`` array."""
    existing = await _fetch_comment(
        db, org_slug, project_id, document_id, thread_id, comment_id
    )
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Comment {comment_id!r} not found'
        )

    # Toggle app-side, then write the whole array back (avoids AGE list
    # manipulation in Cypher).
    acknowledged = list(existing.get('acknowledged_by', []))
    principal = auth.principal_name
    if principal in acknowledged:
        acknowledged = [a for a in acknowledged if a != principal]
    else:
        acknowledged.append(principal)

    query: typing.LiteralString = (
        _DOC_JOIN
        + """
    MATCH (c:Comment {{id: {comment_id}}})
          -[:IN_THREAD]->(:CommentThread {{id: {thread_id}}})
          -[:ON_DOCUMENT]->(d)
    SET c.acknowledged_by = {acknowledged_by}
    RETURN c
    """
    )
    records = await db.execute(
        query,
        {
            'document_id': document_id,
            'project_id': project_id,
            'org_slug': org_slug,
            'thread_id': thread_id,
            'comment_id': comment_id,
            'acknowledged_by': acknowledged,
        },
        columns=['c'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Comment {comment_id!r} not found'
        )
    return _parse_comment(records[0]['c'])


class AttentionComment(pydantic.BaseModel):
    document_id: str
    document_title: str
    project_id: str | None = None
    thread_id: str
    anchor_text: str | None = None
    comment_id: str
    author_email: str
    author_name: str | None = None
    body: str
    created_at: datetime.datetime
    reason: typing.Literal['owner', 'mention']


class AttentionCommentListResponse(pydantic.BaseModel):
    data: list[AttentionComment]


# Open threads in the org on a document that the caller created, or with
# a comment that mentions the caller. For each thread, find the newest
# comment by another author (max() and match-back, because AGE loses an
# ORDER BY in WITH), break a created_at tie on the highest id, and keep
# the row only if the caller did not reply after it and did not
# acknowledge it. A caller reply with the same created_at counts as
# after it only when its id is higher (the same tie-break).
_ATTENTION_QUERY: typing.LiteralString = """
    MATCH (o:Organization {{slug: {org_slug}}})
    MATCH (t:CommentThread)-[:ON_DOCUMENT]->(d:Document)
    WHERE coalesce(t.resolved, false) = false
    OPTIONAL MATCH (d)-[:ATTACHED_TO]->(p:Project)
          -[:OWNED_BY]->(:Team)-[:BELONGS_TO]->(o)
    OPTIONAL MATCH (d)-[:ATTACHED_TO]->(pt:ProjectType)-[:BELONGS_TO]->(o)
    OPTIONAL MATCH (d)-[:ATTACHED_TO]->(u:User)-[:MEMBER_OF]->(o)
          <-[:BELONGS_TO]-(d)
    WITH t, d, p, pt, u
    WHERE p IS NOT NULL OR pt IS NOT NULL OR u IS NOT NULL
    WITH DISTINCT t, d, p
    MATCH (c:Comment)-[:IN_THREAD]->(t)
    WITH t, d, p,
         max(CASE WHEN c.author <> {principal}
                  THEN c.created_at END) AS newest_at,
         max(CASE WHEN c.author = {principal}
                  THEN c.created_at END) AS mine_at,
         count(CASE WHEN {principal} IN c.mentions
                    THEN 1 END) AS mention_count
    WHERE newest_at IS NOT NULL
      AND (mine_at IS NULL OR mine_at <= newest_at)
      AND (d.created_by = {principal} OR mention_count > 0)
    MATCH (n:Comment)-[:IN_THREAD]->(t)
    WHERE n.created_at = newest_at
    WITH t, d, p, mention_count,
         max(CASE WHEN n.author <> {principal} THEN n.id END) AS newest_id,
         max(CASE WHEN n.author = {principal} THEN n.id END) AS mine_id
    WHERE mine_id IS NULL OR mine_id < newest_id
    MATCH (n:Comment {{id: newest_id}})-[:IN_THREAD]->(t)
    WHERE NOT {principal} IN coalesce(n.acknowledged_by, [])
    OPTIONAL MATCH (a:User {{email: n.author}})
    RETURN d.id AS document_id, d.title AS document_title,
           p.id AS project_id, t.id AS thread_id,
           t.anchor_quote AS anchor_text, n.id AS comment_id,
           n.author AS author_email, a.display_name AS author_name,
           n.body AS body, n.created_at AS created_at,
           CASE WHEN d.created_by = {principal}
                THEN 'owner' ELSE 'mention' END AS reason
"""

_ATTENTION_COLUMNS: list[str] = list(AttentionComment.model_fields)

attention_router = fastapi.APIRouter(tags=['Comments'])


@attention_router.get(
    '/attention', response_model=AttentionCommentListResponse
)
async def list_attention_comments(
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
    limit: typing.Annotated[int, fastapi.Query(ge=1, le=100)] = 20,
) -> dict[str, typing.Any]:
    """List open threads that wait on the caller, newest first.

    A thread waits on the caller when the caller created its document
    or a comment in it mentions the caller, and the caller did not
    reply after or acknowledge the newest comment by another author.
    """
    records = await db.execute(
        _ATTENTION_QUERY,
        {'org_slug': org_slug, 'principal': auth.principal_name},
        columns=_ATTENTION_COLUMNS,
    )
    rows = [
        {k: graph.parse_agtype(r[k]) for k in _ATTENTION_COLUMNS}
        for r in records
    ]
    for row in rows:
        row['document_title'] = row['document_title'] or ''
        row['anchor_text'] = row['anchor_text'] or None
    rows.sort(key=lambda row: row['created_at'], reverse=True)
    return {'data': rows[:limit]}


@comments_router.delete('/{thread_id}/comments/{comment_id}', status_code=204)
async def delete_comment(
    org_slug: str,
    document_id: str,
    thread_id: str,
    comment_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('comment:delete')),
    ],
    project_id: str | None = None,
) -> None:
    """Delete a comment. Author-only. Deletes the thread if it was the
    root and no other comments remain.
    """
    existing = await _fetch_comment(
        db, org_slug, project_id, document_id, thread_id, comment_id
    )
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Comment {comment_id!r} not found'
        )
    if existing['author'] != auth.principal_name:
        raise fastapi.HTTPException(
            status_code=403,
            detail='Only the comment author may delete it',
        )

    # Determine whether this is the root (oldest) comment and whether any
    # other comments remain in the thread.
    thread = await _fetch_thread(
        db, org_slug, project_id, document_id, thread_id
    )
    if thread is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Thread {thread_id!r} not found'
        )
    comments = thread.get('comments', [])
    is_root = bool(comments) and comments[0]['id'] == comment_id
    is_only = len(comments) <= 1

    if is_root and is_only:
        # Remove the whole thread (and its ON_DOCUMENT edge) plus the
        # root comment.
        query: typing.LiteralString = (
            _DOC_JOIN
            + """
    MATCH (c:Comment {{id: {comment_id}}})
          -[:IN_THREAD]->(t:CommentThread {{id: {thread_id}}})
          -[:ON_DOCUMENT]->(d)
    DETACH DELETE c, t
    RETURN 1 AS deleted
    """
        )
    else:
        query = (
            _DOC_JOIN
            + """
    MATCH (c:Comment {{id: {comment_id}}})
          -[:IN_THREAD]->(:CommentThread {{id: {thread_id}}})
          -[:ON_DOCUMENT]->(d)
    DETACH DELETE c
    RETURN 1 AS deleted
    """
        )
    records = await db.execute(
        query,
        {
            'document_id': document_id,
            'project_id': project_id,
            'org_slug': org_slug,
            'thread_id': thread_id,
            'comment_id': comment_id,
        },
        columns=['deleted'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Comment {comment_id!r} not found'
        )
    await _search_index.drop(db, models.Comment, comment_id)
