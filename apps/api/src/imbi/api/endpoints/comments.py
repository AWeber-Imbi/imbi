"""Page-level threaded comments on project documents.

Comments hang off a project ``Document`` via a ``CommentThread`` vertex
(``ON_DOCUMENT`` edge) containing one or more ``Comment`` vertices
(``IN_THREAD`` edge). The root comment is the oldest comment in a thread;
replies follow in ``created_at`` order.

Phase 1 only creates ``kind='page'`` threads — the anchor properties are
persisted as empty strings / ``0`` and surfaced as ``anchor: null``.
Inline-anchored threads are a later phase.

Modeled on :mod:`imbi_api.endpoints.documents`: raw Cypher via
``db.execute(...)`` + ``graph.parse_agtype(...)`` with local Pydantic
request/response models (no dependency on ``imbi_common.models`` comment
types).
"""

import datetime
import logging
import typing

import fastapi
import nanoid
import pydantic
from imbi_common import graph

from imbi_api import patch as json_patch
from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

comments_router = fastapi.APIRouter(tags=['Comments'])

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

# Every comment field except ``/body`` is read-only over the PATCH API.
_COMMENT_READONLY_PATHS: frozenset[str] = frozenset(
    [
        '/id',
        '/thread_id',
        '/author',
        '/mentions',
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
    kind: typing.Literal['page'] = 'page'
    body: str = pydantic.Field(min_length=1)
    anchor: AnchorModel | None = None
    mentions: list[str] = []


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
_COMMENTS_TAIL: typing.LiteralString = """
    OPTIONAL MATCH (c:Comment)-[:IN_THREAD]->(t)
    WITH t, d, c ORDER BY c.created_at ASC, c.id ASC
    WITH t, d, collect(CASE WHEN c IS NOT NULL THEN c END) AS raw_comments
    WITH t, d, [x IN raw_comments WHERE x IS NOT NULL] AS comments
    RETURN t, d, comments
"""

# Document-ownership join used by every query to scope to project -> org.
_DOC_JOIN: typing.LiteralString = """
    MATCH (d:Document {{id: {document_id}}})
          -[:ATTACHED_TO]->(:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
"""


async def _verify_document(
    db: graph.Pool,
    org_slug: str,
    project_id: str,
    document_id: str,
) -> None:
    """Raise 404 unless the document belongs to the project -> org."""
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
    project_id: str,
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
    project_id: str,
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
    project_id: str,
    document_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
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
    project_id: str,
    document_id: str,
    data: CommentThreadCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('comment:create')),
    ],
) -> dict[str, typing.Any]:
    """Create a thread, its ``ON_DOCUMENT`` edge, and the root comment."""
    await _verify_document(db, org_slug, project_id, document_id)

    now = datetime.datetime.now(datetime.UTC)
    thread_id = nanoid.generate()
    comment_id = nanoid.generate()
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
            'kind': 'page',
            'resolved': False,
            'resolved_by': None,
            'resolved_at': None,
            'anchor_quote': '',
            'anchor_prefix': '',
            'anchor_suffix': '',
            'anchor_start': 0,
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
    return thread


@comments_router.post(
    '/{thread_id}/comments',
    status_code=201,
    response_model=CommentResponse,
)
async def create_reply(
    org_slug: str,
    project_id: str,
    document_id: str,
    thread_id: str,
    data: CommentBodyCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('comment:create')),
    ],
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
    return _parse_comment(records[0]['c'])


@comments_router.patch('/{thread_id}', response_model=CommentThreadResponse)
async def patch_comment_thread(
    org_slug: str,
    project_id: str,
    document_id: str,
    thread_id: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('comment:write')),
    ],
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
    project_id: str,
    document_id: str,
    thread_id: str,
    comment_id: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('comment:write')),
    ],
) -> dict[str, typing.Any]:
    """Edit a comment body via JSON Patch (only ``/body``). Author-only."""
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

    current = {'body': existing['body']}
    patched = json_patch.apply_patch(
        current, operations, _COMMENT_READONLY_PATHS
    )
    try:
        update = CommentBodyCreate(body=patched.get('body'))  # type: ignore[arg-type]
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
            'edited': True,
            'updated_at': now.isoformat(),
        },
        columns=['c'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Comment {comment_id!r} not found'
        )
    return _parse_comment(records[0]['c'])


@comments_router.post(
    '/{thread_id}/comments/{comment_id}/acknowledge',
    response_model=CommentResponse,
)
async def acknowledge_comment(
    org_slug: str,
    project_id: str,
    document_id: str,
    thread_id: str,
    comment_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('comment:write')),
    ],
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


@comments_router.delete('/{thread_id}/comments/{comment_id}', status_code=204)
async def delete_comment(
    org_slug: str,
    project_id: str,
    document_id: str,
    thread_id: str,
    comment_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('comment:delete')),
    ],
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
