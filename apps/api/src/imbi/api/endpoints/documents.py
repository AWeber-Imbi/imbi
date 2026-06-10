"""Documents with tag support, attachable to multiple vertex kinds.

A document is attached to exactly one owning vertex via an
``ATTACHED_TO`` edge — a ``Project``, a ``ProjectType``, or a ``User``
— and may optionally be tagged with org-scoped ``Tag`` nodes via
``TAGGED_WITH``.

The top-level ``documents_router`` supports the org-wide index
(filterable by tag, project, project type, or user) plus generic
single-document read/write/delete that works regardless of where the
document is attached. ``documents_project_router``,
``documents_project_type_router``, and ``documents_user_router``
handle list + create scoped to a single attachment target.
"""

import datetime
import logging
import typing

import fastapi
import fastapi.responses
import nanoid
import pydantic
from imbi_common import graph

from imbi_api import patch as json_patch
from imbi_api.auth import permissions
from imbi_api.endpoints._helpers import fetch_or_404
from imbi_api.endpoints._pagination import (
    build_link_header,
    decode_cursor,
    encode_cursor,
)

LOGGER = logging.getLogger(__name__)

documents_router = fastapi.APIRouter(tags=['Documents'])
documents_project_router = fastapi.APIRouter(tags=['Documents'])
documents_project_type_router = fastapi.APIRouter(tags=['Documents'])
documents_user_router = fastapi.APIRouter(tags=['Documents'])

DEFAULT_LIMIT: int = 50
MAX_LIMIT: int = 500

_DOCUMENT_READONLY_PATHS: frozenset[str] = frozenset(
    [
        '/id',
        '/project_id',
        '/attached_to',
        '/comment_count',
        '/created_by',
        '/created_by_name',
        '/created_at',
        '/updated_by',
        '/updated_at',
    ]
)


class TagRef(pydantic.BaseModel):
    name: str
    slug: str


class AttachmentRef(pydantic.BaseModel):
    """The vertex a document hangs off of.

    ``id`` is the project id, the project-type slug, or the user
    email depending on ``kind``. ``team`` and ``project_types`` are
    only populated for ``kind='project'``.
    """

    kind: typing.Literal['project', 'project_type', 'user']
    id: str
    name: str
    team: str | None = None
    project_types: list[str] = []


class DocumentResponse(pydantic.BaseModel):
    id: str
    title: str = ''
    content: str
    created_by: str
    created_by_name: str | None = None
    created_at: datetime.datetime
    updated_by: str | None = None
    updated_at: datetime.datetime | None = None
    project_id: str | None = None
    attached_to: AttachmentRef | None = None
    is_pinned: bool = False
    comment_count: int = 0
    tags: list[TagRef] = []


class DocumentCreate(pydantic.BaseModel):
    title: str = pydantic.Field(min_length=1, max_length=200)
    content: str = pydantic.Field(min_length=1)
    tags: list[str] = pydantic.Field(
        default_factory=list,
        description='Tag slugs to attach. Must already exist in the org.',
    )


class DocumentListResponse(pydantic.BaseModel):
    data: list[DocumentResponse]


def _str_list(value: typing.Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items = typing.cast('list[object]', value)
    return [str(v) for v in items]


def _parse_document_row(
    record: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    document: dict[str, typing.Any] = graph.parse_agtype(record['n'])
    project: dict[str, typing.Any] | None = graph.parse_agtype(record['p'])
    team: dict[str, typing.Any] | None = graph.parse_agtype(record['team'])
    project_type: dict[str, typing.Any] | None = graph.parse_agtype(
        record['pt']
    )
    user: dict[str, typing.Any] | None = graph.parse_agtype(record['u'])
    ptype_names = _str_list(graph.parse_agtype(record['ptype_names']))
    author: dict[str, typing.Any] | None = graph.parse_agtype(record['author'])
    raw_tags: list[typing.Any] = graph.parse_agtype(record['tags']) or []
    tags: list[dict[str, str]] = []
    for t in raw_tags:
        if not isinstance(t, dict):
            continue
        entry = typing.cast(dict[str, typing.Any], t)
        slug = entry.get('slug')
        if not slug:
            continue
        tags.append(
            {'name': str(entry.get('name', '')), 'slug': str(slug)},
        )

    attached: dict[str, typing.Any] | None = None
    if project:
        attached = {
            'kind': 'project',
            'id': str(project.get('id', '')),
            'name': str(project.get('name', '')),
            'team': str(team.get('name', '')) if team else None,
            'project_types': ptype_names,
        }
    elif project_type:
        attached = {
            'kind': 'project_type',
            'id': str(project_type.get('slug', '')),
            'name': str(project_type.get('name', '')),
        }
    elif user:
        attached = {
            'kind': 'user',
            'id': str(user.get('email', '')),
            'name': str(user.get('display_name', '')),
        }

    document['project_id'] = project.get('id', '') if project else None
    document['attached_to'] = attached
    document['tags'] = tags
    document['comment_count'] = int(
        graph.parse_agtype(record['comment_count']) or 0
    )
    document['created_by_name'] = (
        str(author.get('display_name', '')) or None if author else None
    )
    # Defaults for rows written before these columns landed.
    document['is_pinned'] = bool(document.get('is_pinned', False))
    document['title'] = str(document.get('title') or '')
    return document


# Resolves the document's attachment target. Requires ``o`` (the org)
# and ``n`` (the document) in scope; emits ``n, o, p, team, pt, u``
# with the org-membership guarantee enforced. Filter fragments are
# appended to the WHERE clause by callers.
_ATTACHMENT_MATCH: typing.LiteralString = """
    OPTIONAL MATCH (n)-[:ATTACHED_TO]->(p:Project)
          -[:OWNED_BY]->(team:Team)-[:BELONGS_TO]->(o)
    OPTIONAL MATCH (n)-[:ATTACHED_TO]->(pt:ProjectType)-[:BELONGS_TO]->(o)
    OPTIONAL MATCH (n)-[:ATTACHED_TO]->(u:User)-[:MEMBER_OF]->(o)
    WITH n, o, p, team, pt, u
    WHERE (p IS NOT NULL OR pt IS NOT NULL OR u IS NOT NULL)
"""

# Enrichment tail used by every query that returns a document. Runs
# with ``n, p, team, pt, u`` in scope and emits the full column set.
# Aggregates run stepwise so each OPTIONAL MATCH cannot multiply the
# rows of the next.
_ENRICH_TAIL: typing.LiteralString = """
    OPTIONAL MATCH (p)-[:TYPE]->(ptype:ProjectType)
    WITH n, p, team, pt, u,
         collect(CASE WHEN ptype IS NOT NULL
                      THEN ptype.name END) AS raw_ptype_names
    WITH n, p, team, pt, u,
         [x IN raw_ptype_names WHERE x IS NOT NULL] AS ptype_names
    OPTIONAL MATCH (n)-[:TAGGED_WITH]->(tag:Tag)
    WITH n, p, team, pt, u, ptype_names,
         collect(CASE WHEN tag IS NOT NULL
                      THEN tag{{.name, .slug}}
                      END) AS raw_tags
    WITH n, p, team, pt, u, ptype_names,
         [t IN raw_tags WHERE t IS NOT NULL] AS tags
    OPTIONAL MATCH (c:Comment)-[:IN_THREAD]->(:CommentThread)
          -[:ON_DOCUMENT]->(n)
    WITH n, p, team, pt, u, ptype_names, tags,
         count(c) AS comment_count
    OPTIONAL MATCH (author:User {{email: n.created_by}})
    RETURN n, p, team, pt, u, ptype_names, tags, comment_count, author
"""

_DOCUMENT_COLUMNS: list[str] = [
    'n',
    'p',
    'team',
    'pt',
    'u',
    'ptype_names',
    'tags',
    'comment_count',
    'author',
]


async def _attach_tags(
    db: graph.Pool,
    org_slug: str,
    document_id: str,
    tag_slugs: list[str],
) -> None:
    """Create ``TAGGED_WITH`` edges from document -> tags.

    Split from the CREATE/SET query because AGE's Cypher translator does
    not support ``FOREACH``; a plain ``UNWIND`` + ``MATCH`` + ``CREATE``
    is portable.
    """
    if not tag_slugs:
        return
    query: typing.LiteralString = """
    MATCH (n:Document {{id: {document_id}}}),
          (:Organization {{slug: {org_slug}}})<-[:BELONGS_TO]-(t:Tag)
    WHERE t.slug IN {tag_slugs}
    CREATE (n)-[:TAGGED_WITH]->(t)
    RETURN count(t) AS attached
    """
    await db.execute(
        query,
        {
            'document_id': document_id,
            'org_slug': org_slug,
            'tag_slugs': tag_slugs,
        },
        columns=['attached'],
    )


async def _detach_all_tags(
    db: graph.Pool,
    document_id: str,
) -> None:
    """Remove every ``TAGGED_WITH`` edge from ``document``."""
    query: typing.LiteralString = """
    MATCH (n:Document {{id: {document_id}}})-[tw:TAGGED_WITH]->(:Tag)
    DELETE tw
    RETURN count(tw) AS removed
    """
    await db.execute(query, {'document_id': document_id}, columns=['removed'])


async def _validate_tag_slugs(
    db: graph.Pool, org_slug: str, tag_slugs: list[str]
) -> None:
    if not tag_slugs:
        return
    query: typing.LiteralString = """
    MATCH (o:Organization {{slug: {org_slug}}})
    UNWIND {slugs} AS tag_slug
    OPTIONAL MATCH (t:Tag {{slug: tag_slug}})-[:BELONGS_TO]->(o)
    RETURN tag_slug, t IS NOT NULL AS found
    """
    records = await db.execute(
        query,
        {'org_slug': org_slug, 'slugs': tag_slugs},
        columns=['tag_slug', 'found'],
    )
    missing = [
        graph.parse_agtype(r['tag_slug'])
        for r in records
        if not graph.parse_agtype(r['found'])
    ]
    if missing:
        raise fastapi.HTTPException(
            status_code=422,
            detail=f'Tag slug(s) not found: {sorted(missing)!r}',
        )


_DOCUMENT_CREATE_FRAGMENT: typing.LiteralString = """
    CREATE (n:Document {{
        id: {id},
        title: {title},
        content: {content},
        created_by: {created_by},
        created_at: {created_at},
        is_pinned: {is_pinned}
    }})
    CREATE (n)-[:ATTACHED_TO]->(target)
    RETURN n.id AS id
"""


async def _create_document_impl(
    db: graph.Pool,
    auth: permissions.AuthContext,
    org_slug: str,
    data: DocumentCreate,
    anchor_match: typing.LiteralString,
    anchor_params: dict[str, typing.Any],
    not_found_detail: str,
) -> dict[str, typing.Any]:
    """Create a document attached to the vertex bound as ``target``."""
    tag_slugs = list(dict.fromkeys(data.tags))
    await _validate_tag_slugs(db, org_slug, tag_slugs)

    now = datetime.datetime.now(datetime.UTC)
    document_id = nanoid.generate()
    records = await db.execute(
        anchor_match + _DOCUMENT_CREATE_FRAGMENT,
        {
            **anchor_params,
            'org_slug': org_slug,
            'id': document_id,
            'title': data.title,
            'content': data.content,
            'created_by': auth.principal_name,
            'created_at': now.isoformat(),
            'is_pinned': False,
        },
        columns=['id'],
    )
    if not records:
        raise fastapi.HTTPException(status_code=404, detail=not_found_detail)

    if tag_slugs:
        await _attach_tags(db, org_slug, document_id, tag_slugs)

    document = await _fetch_document(db, org_slug, document_id)
    if document is None:
        raise fastapi.HTTPException(
            status_code=500,
            detail='Document created but could not be read back',
        )
    return document


@documents_project_router.post(
    '/', status_code=201, response_model=DocumentResponse
)
async def create_document(
    org_slug: str,
    project_id: str,
    data: DocumentCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:create')),
    ],
) -> dict[str, typing.Any]:
    """Create a document attached to a project, optionally with tags."""
    anchor: typing.LiteralString = """
    MATCH (target:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    """
    return await _create_document_impl(
        db,
        auth,
        org_slug,
        data,
        anchor,
        {'project_id': project_id},
        f'Project {project_id!r} not found',
    )


@documents_project_type_router.post(
    '/', status_code=201, response_model=DocumentResponse
)
async def create_project_type_document(
    org_slug: str,
    type_slug: str,
    data: DocumentCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:create')),
    ],
) -> dict[str, typing.Any]:
    """Create a document attached to a project type."""
    anchor: typing.LiteralString = """
    MATCH (target:ProjectType {{slug: {type_slug}}})
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    """
    return await _create_document_impl(
        db,
        auth,
        org_slug,
        data,
        anchor,
        {'type_slug': type_slug},
        f'Project type {type_slug!r} not found',
    )


@documents_user_router.post(
    '/', status_code=201, response_model=DocumentResponse
)
async def create_user_document(
    org_slug: str,
    email: str,
    data: DocumentCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:create')),
    ],
) -> dict[str, typing.Any]:
    """Create a document attached to a user (org member)."""
    anchor: typing.LiteralString = """
    MATCH (target:User {{email: {email}}})
          -[:MEMBER_OF]->(:Organization {{slug: {org_slug}}})
    """
    return await _create_document_impl(
        db,
        auth,
        org_slug,
        data,
        anchor,
        {'email': email},
        f'User {email!r} not found',
    )


async def _list_documents_impl(
    *,
    request: fastapi.Request,
    db: graph.Pool,
    org_slug: str,
    project_id: str | None = None,
    project_type_slug: str | None = None,
    user_email: str | None = None,
    tag_slug: str | None = None,
    limit: int,
    cursor: str | None,
) -> fastapi.Response:
    if limit < 1 or limit > MAX_LIMIT:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'limit must be 1..{MAX_LIMIT}',
        )

    attachment_filters = sum(
        value is not None
        for value in (project_id, project_type_slug, user_email)
    )
    if attachment_filters > 1:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Only one attachment filter (project, project_type, '
            'user) may be specified at a time',
        )

    params: dict[str, typing.Any] = {
        'org_slug': org_slug,
        'row_limit': limit + 1,
    }
    filters = ''
    if project_id is not None:
        filters += ' AND p.id = {project_id}'
        params['project_id'] = project_id
    if project_type_slug is not None:
        filters += ' AND pt.slug = {project_type_slug}'
        params['project_type_slug'] = project_type_slug
    if user_email is not None:
        filters += ' AND u.email = {user_email}'
        params['user_email'] = user_email

    tag_match = ''
    if tag_slug is not None:
        tag_match = (
            ' MATCH (n)-[:TAGGED_WITH]->'
            '(:Tag {{slug: {tag_slug}}})-[:BELONGS_TO]->(o)'
        )
        params['tag_slug'] = tag_slug

    cursor_clause = ''
    if cursor is not None:
        decoded = decode_cursor(cursor)
        if decoded is None:
            raise fastapi.HTTPException(
                status_code=400, detail='Invalid cursor'
            )
        cursor_ts, cursor_id = decoded
        cursor_clause = (
            ' AND (n.created_at < {cursor_ts}'
            ' OR (n.created_at = {cursor_ts} AND n.id < {cursor_id}))'
        )
        params['cursor_ts'] = cursor_ts.isoformat()
        params['cursor_id'] = cursor_id

    query: str = (
        """
    MATCH (o:Organization {{slug: {org_slug}}})
    MATCH (n:Document)"""
        + tag_match
        + _ATTACHMENT_MATCH
        + filters
        + cursor_clause
        + """
    WITH DISTINCT n, p, team, pt, u,
         n.created_at AS sort_ts, n.id AS sort_id
    ORDER BY sort_ts DESC, sort_id DESC
    LIMIT {row_limit}
    """
        + _ENRICH_TAIL
    )

    records = await db.execute(query, params, columns=_DOCUMENT_COLUMNS)
    next_cursor: str | None = None
    parsed = [_parse_document_row(r) for r in records]
    if len(parsed) > limit:
        parsed = parsed[:limit]
        last = parsed[-1]
        last_ts = last['created_at']
        if isinstance(last_ts, str):
            last_ts = datetime.datetime.fromisoformat(last_ts)
        next_cursor = encode_cursor(last_ts, last['id'])

    adapter = pydantic.TypeAdapter(list[DocumentResponse])
    response = fastapi.responses.JSONResponse(
        {
            'data': adapter.dump_python(
                [DocumentResponse.model_validate(n) for n in parsed],
                mode='json',
            )
        }
    )
    response.headers['Link'] = build_link_header(request, next_cursor)
    return response


@documents_router.get('/', response_model=DocumentListResponse)
async def list_documents(
    request: fastapi.Request,
    org_slug: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    tag: str | None = None,
    project_id: str | None = None,
    project_type: str | None = None,
    user: str | None = None,
) -> fastapi.Response:
    """Org-wide document index.

    Filter by tag slug, project id, project-type slug, and/or user
    email.
    """
    return await _list_documents_impl(
        request=request,
        db=db,
        org_slug=org_slug,
        project_id=project_id,
        project_type_slug=project_type,
        user_email=user,
        tag_slug=tag,
        limit=limit,
        cursor=cursor,
    )


@documents_project_router.get('/', response_model=DocumentListResponse)
async def list_project_documents(
    request: fastapi.Request,
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    tag: str | None = None,
) -> fastapi.Response:
    """List documents attached to a specific project."""
    return await _list_documents_impl(
        request=request,
        db=db,
        org_slug=org_slug,
        project_id=project_id,
        tag_slug=tag,
        limit=limit,
        cursor=cursor,
    )


@documents_project_type_router.get('/', response_model=DocumentListResponse)
async def list_project_type_documents(
    request: fastapi.Request,
    org_slug: str,
    type_slug: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    tag: str | None = None,
) -> fastapi.Response:
    """List documents attached to a specific project type."""
    return await _list_documents_impl(
        request=request,
        db=db,
        org_slug=org_slug,
        project_type_slug=type_slug,
        tag_slug=tag,
        limit=limit,
        cursor=cursor,
    )


@documents_user_router.get('/', response_model=DocumentListResponse)
async def list_user_documents(
    request: fastapi.Request,
    org_slug: str,
    email: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    tag: str | None = None,
) -> fastapi.Response:
    """List documents attached to a specific user."""
    return await _list_documents_impl(
        request=request,
        db=db,
        org_slug=org_slug,
        user_email=email,
        tag_slug=tag,
        limit=limit,
        cursor=cursor,
    )


def _scope_filter(
    project_id: str | None,
) -> tuple[typing.LiteralString, dict[str, typing.Any]]:
    """Optional project constraint for the generic document queries."""
    if project_id is None:
        return '', {}
    return ' AND p.id = {project_id}', {'project_id': project_id}


async def _fetch_document(
    db: graph.Pool,
    org_slug: str,
    document_id: str,
    project_id: str | None = None,
) -> dict[str, typing.Any] | None:
    scope, scope_params = _scope_filter(project_id)
    query: str = (
        """
    MATCH (o:Organization {{slug: {org_slug}}})
    MATCH (n:Document {{id: {document_id}}})"""
        + _ATTACHMENT_MATCH
        + scope
        + """
    WITH DISTINCT n, p, team, pt, u
    """
        + _ENRICH_TAIL
    )
    records = await db.execute(
        query,
        {
            'document_id': document_id,
            'org_slug': org_slug,
            **scope_params,
        },
        columns=_DOCUMENT_COLUMNS,
    )
    if not records:
        return None
    return _parse_document_row(records[0])


@documents_router.get('/{document_id}', response_model=DocumentResponse)
async def get_org_document(
    org_slug: str,
    document_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
) -> dict[str, typing.Any]:
    """Retrieve a single document regardless of attachment kind."""
    return await fetch_or_404(
        _fetch_document,
        db,
        org_slug,
        document_id,
        detail=f'Document {document_id!r} not found',
    )


@documents_project_router.get(
    '/{document_id}', response_model=DocumentResponse
)
async def get_document(
    org_slug: str,
    project_id: str,
    document_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
) -> dict[str, typing.Any]:
    """Retrieve a single project document."""
    return await fetch_or_404(
        _fetch_document,
        db,
        org_slug,
        document_id,
        project_id,
        detail=f'Document {document_id!r} not found',
    )


class DocumentUpdate(pydantic.BaseModel):
    title: str | None = pydantic.Field(
        default=None, min_length=1, max_length=200
    )
    content: str | None = pydantic.Field(default=None, min_length=1)
    tags: list[str] | None = None
    is_pinned: bool | None = None


def _resolve_patched_field(
    field: str,
    touched: set[str],
    new_value: typing.Any,
    fallback: typing.Any,
) -> typing.Any:
    """Return the resolved value for a non-nullable field after a JSON Patch.

    If the patch touched ``field`` and ``new_value`` is ``None`` (an explicit
    ``null``), raise 400 — silent no-ops would make the response disagree with
    the patch document. Otherwise return ``new_value`` when touched, else
    ``fallback``.
    """
    if field in touched:
        if new_value is None:
            raise fastapi.HTTPException(
                status_code=400, detail=f'{field} cannot be null'
            )
        return new_value
    return fallback


async def _patch_document_impl(
    db: graph.Pool,
    auth: permissions.AuthContext,
    org_slug: str,
    document_id: str,
    operations: list[json_patch.PatchOperation],
    project_id: str | None = None,
) -> dict[str, typing.Any]:
    existing = await _fetch_document(db, org_slug, document_id, project_id)
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Document {document_id!r} not found'
        )

    current = {
        'title': str(existing.get('title') or ''),
        'content': existing['content'],
        'tags': [t['slug'] for t in existing.get('tags', [])],
        'is_pinned': bool(existing.get('is_pinned', False)),
    }
    patched = json_patch.apply_patch(
        current, operations, _DOCUMENT_READONLY_PATHS
    )
    # Only validate fields the patch actually touched. The merged ``patched``
    # dict carries every field from ``current`` (incl. legacy values that
    # may not satisfy ``DocumentUpdate`` constraints), so validating it whole
    # would reject a ``/is_pinned`` patch on a document with an empty title.
    touched: set[str] = set()
    for op in operations:
        if op.path.startswith('/'):
            head = op.path.split('/', 2)[1]
            if head:
                touched.add(head)
    try:
        update = DocumentUpdate(
            **{k: patched[k] for k in touched if k in patched}
        )
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    # Use ``touched`` (not ``is not None``) so that explicit ``null`` values
    # in the patch document are rejected rather than silently treated as
    # "field omitted". ``apply_patch()`` preserves explicit nulls, so the
    # PATCH result must agree with the patch document.
    new_title = _resolve_patched_field(
        'title', touched, update.title, str(existing.get('title') or '')
    )
    new_content = _resolve_patched_field(
        'content', touched, update.content, existing['content']
    )
    # Replace tag edges only when an op actually targeted ``/tags``.
    replace_tags = 'tags' in touched
    new_tags: list[str] = (
        list(dict.fromkeys(update.tags or []))
        if replace_tags
        else [t['slug'] for t in existing.get('tags', [])]
    )
    if replace_tags:
        await _validate_tag_slugs(db, org_slug, new_tags)
    new_is_pinned = _resolve_patched_field(
        'is_pinned',
        touched,
        update.is_pinned,
        bool(existing.get('is_pinned', False)),
    )

    scope, scope_params = _scope_filter(project_id)
    now = datetime.datetime.now(datetime.UTC)
    set_query: str = (
        """
    MATCH (o:Organization {{slug: {org_slug}}})
    MATCH (n:Document {{id: {document_id}}})"""
        + _ATTACHMENT_MATCH
        + scope
        + """
    SET n.title = {title},
        n.content = {content},
        n.updated_by = {updated_by},
        n.updated_at = {updated_at},
        n.is_pinned = {is_pinned}
    RETURN n.id AS id
    """
    )
    records = await db.execute(
        set_query,
        {
            'org_slug': org_slug,
            'document_id': document_id,
            'title': new_title,
            'content': new_content,
            'updated_by': auth.principal_name,
            'updated_at': now.isoformat(),
            'is_pinned': new_is_pinned,
            **scope_params,
        },
        columns=['id'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Document {document_id!r} not found'
        )

    if replace_tags:
        await _detach_all_tags(db, document_id)
        await _attach_tags(db, org_slug, document_id, new_tags)

    document = await _fetch_document(db, org_slug, document_id, project_id)
    if document is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Document {document_id!r} not found'
        )
    return document


@documents_router.patch('/{document_id}', response_model=DocumentResponse)
async def patch_org_document(
    org_slug: str,
    document_id: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:write')),
    ],
) -> dict[str, typing.Any]:
    """Update a document via JSON Patch regardless of attachment kind."""
    return await _patch_document_impl(
        db, auth, org_slug, document_id, operations
    )


@documents_project_router.patch(
    '/{document_id}', response_model=DocumentResponse
)
async def patch_document(
    org_slug: str,
    project_id: str,
    document_id: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:write')),
    ],
) -> dict[str, typing.Any]:
    """Update document content and/or tag attachments via JSON Patch."""
    return await _patch_document_impl(
        db, auth, org_slug, document_id, operations, project_id
    )


async def _delete_document_impl(
    db: graph.Pool,
    org_slug: str,
    document_id: str,
    project_id: str | None = None,
) -> None:
    scope, scope_params = _scope_filter(project_id)
    query: str = (
        """
    MATCH (o:Organization {{slug: {org_slug}}})
    MATCH (n:Document {{id: {document_id}}})"""
        + _ATTACHMENT_MATCH
        + scope
        + """
    DETACH DELETE n
    RETURN 1 AS deleted
    """
    )
    records = await db.execute(
        query,
        {
            'document_id': document_id,
            'org_slug': org_slug,
            **scope_params,
        },
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Document {document_id!r} not found'
        )


@documents_router.delete('/{document_id}', status_code=204)
async def delete_org_document(
    org_slug: str,
    document_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:delete')),
    ],
) -> None:
    """Delete a document regardless of attachment kind."""
    await _delete_document_impl(db, org_slug, document_id)


@documents_project_router.delete('/{document_id}', status_code=204)
async def delete_document(
    org_slug: str,
    project_id: str,
    document_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:delete')),
    ],
) -> None:
    """Delete a project document."""
    await _delete_document_impl(db, org_slug, document_id, project_id)
