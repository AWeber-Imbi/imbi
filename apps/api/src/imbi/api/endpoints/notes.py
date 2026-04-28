"""Project notes with tag support.

Notes are project-scoped via a required ``ATTACHED_TO`` edge and may
optionally be tagged with org-scoped ``Tag`` nodes via ``TAGGED_WITH``.
The top-level ``notes_router`` supports cross-project search filtered
by tag; ``notes_project_router`` handles CRUD scoped to a single
project.
"""

import base64
import datetime
import logging
import typing
import urllib.parse

import fastapi
import fastapi.responses
import nanoid
import pydantic
from imbi_common import graph

from imbi_api import patch as json_patch
from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

notes_router = fastapi.APIRouter(tags=['Notes'])
notes_project_router = fastapi.APIRouter(tags=['Notes'])

DEFAULT_LIMIT: int = 50
MAX_LIMIT: int = 500

_NOTE_READONLY_PATHS: frozenset[str] = frozenset(
    [
        '/id',
        '/project_id',
        '/created_by',
        '/created_at',
        '/updated_by',
        '/updated_at',
    ]
)


class TagRef(pydantic.BaseModel):
    name: str
    slug: str


class NoteResponse(pydantic.BaseModel):
    id: str
    title: str = ''
    content: str
    created_by: str
    created_at: datetime.datetime
    updated_by: str | None = None
    updated_at: datetime.datetime | None = None
    project_id: str
    is_pinned: bool = False
    tags: list[TagRef] = []


class NoteCreate(pydantic.BaseModel):
    title: str = pydantic.Field(min_length=1, max_length=200)
    content: str = pydantic.Field(min_length=1)
    tags: list[str] = pydantic.Field(
        default_factory=list,
        description='Tag slugs to attach. Must already exist in the org.',
    )


class NoteListResponse(pydantic.BaseModel):
    data: list[NoteResponse]


def _encode_cursor(created_at: datetime.datetime, note_id: str) -> str:
    payload = f'{created_at.isoformat()}|{note_id}'.encode()
    return base64.urlsafe_b64encode(payload).rstrip(b'=').decode('ascii')


def _decode_cursor(
    cursor: str,
) -> tuple[datetime.datetime, str] | None:
    if not cursor:
        return None
    padding = '=' * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding).decode('utf-8')
    except (ValueError, UnicodeDecodeError):
        return None
    if '|' not in raw:
        return None
    ts_str, _, note_id = raw.partition('|')
    if not note_id:
        return None
    try:
        ts = datetime.datetime.fromisoformat(ts_str)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.UTC)
    return ts.astimezone(datetime.UTC), note_id


def _build_link_header(
    request: fastapi.Request, next_cursor: str | None
) -> str:
    url = request.url
    base_params = {
        k: v for k, v in request.query_params.multi_items() if k != 'cursor'
    }

    def _url_with(params: dict[str, str]) -> str:
        base = f'{url.scheme}://{url.netloc}{url.path}'
        if not params:
            return base
        return f'{base}?{urllib.parse.urlencode(params)}'

    links = [f'<{_url_with(base_params)}>; rel="first"']
    if next_cursor is not None:
        next_params = dict(base_params)
        next_params['cursor'] = next_cursor
        links.append(f'<{_url_with(next_params)}>; rel="next"')
    return ', '.join(links)


def _parse_note_row(record: dict[str, typing.Any]) -> dict[str, typing.Any]:
    note: dict[str, typing.Any] = graph.parse_agtype(record['n'])
    project: dict[str, typing.Any] = graph.parse_agtype(record['p'])
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
    note['project_id'] = project.get('id', '')
    note['tags'] = tags
    # Defaults for rows written before these columns landed.
    note['is_pinned'] = bool(note.get('is_pinned', False))
    note['title'] = str(note.get('title') or '')
    return note


# Tail fragment used by every query that returns a note. Always runs
# on ``n, p`` already in scope and emits ``n, p, tags`` columns.
_TAGS_TAIL: typing.LiteralString = """
    OPTIONAL MATCH (n)-[:TAGGED_WITH]->(tag:Tag)
    WITH n, p, collect(CASE WHEN tag IS NOT NULL
                            THEN tag{{.name, .slug}}
                            END) AS raw_tags
    WITH n, p, [t IN raw_tags WHERE t IS NOT NULL] AS tags
    RETURN n, p, tags
"""


async def _attach_tags(
    db: graph.Pool,
    org_slug: str,
    note_id: str,
    tag_slugs: list[str],
) -> None:
    """Create ``TAGGED_WITH`` edges from note -> tags.

    Split from the CREATE/SET query because AGE's Cypher translator does
    not support ``FOREACH``; a plain ``UNWIND`` + ``MATCH`` + ``CREATE``
    is portable.
    """
    if not tag_slugs:
        return
    query: typing.LiteralString = """
    MATCH (n:Note {{id: {note_id}}}),
          (:Organization {{slug: {org_slug}}})<-[:BELONGS_TO]-(t:Tag)
    WHERE t.slug IN {tag_slugs}
    CREATE (n)-[:TAGGED_WITH]->(t)
    RETURN count(t) AS attached
    """
    await db.execute(
        query,
        {'note_id': note_id, 'org_slug': org_slug, 'tag_slugs': tag_slugs},
        columns=['attached'],
    )


async def _detach_all_tags(
    db: graph.Pool,
    note_id: str,
) -> None:
    """Remove every ``TAGGED_WITH`` edge from ``note``."""
    query: typing.LiteralString = """
    MATCH (n:Note {{id: {note_id}}})-[tw:TAGGED_WITH]->(:Tag)
    DELETE tw
    RETURN count(tw) AS removed
    """
    await db.execute(query, {'note_id': note_id}, columns=['removed'])


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


@notes_project_router.post('/', status_code=201, response_model=NoteResponse)
async def create_note(
    org_slug: str,
    project_id: str,
    data: NoteCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('note:create')),
    ],
) -> dict[str, typing.Any]:
    """Create a note attached to a project, optionally with tags."""
    tag_slugs = list(dict.fromkeys(data.tags))
    await _validate_tag_slugs(db, org_slug, tag_slugs)

    now = datetime.datetime.now(datetime.UTC)
    note_id = nanoid.generate()
    create_query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    CREATE (n:Note {{
        id: {id},
        title: {title},
        content: {content},
        created_by: {created_by},
        created_at: {created_at},
        is_pinned: {is_pinned}
    }})
    CREATE (n)-[:ATTACHED_TO]->(p)
    RETURN n.id AS id
    """
    records = await db.execute(
        create_query,
        {
            'org_slug': org_slug,
            'project_id': project_id,
            'id': note_id,
            'title': data.title,
            'content': data.content,
            'created_by': auth.principal_name,
            'created_at': now.isoformat(),
            'is_pinned': False,
        },
        columns=['id'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )

    if tag_slugs:
        await _attach_tags(db, org_slug, note_id, tag_slugs)

    note = await _fetch_note(db, org_slug, project_id, note_id)
    if note is None:
        raise fastapi.HTTPException(
            status_code=500, detail='Note created but could not be read back'
        )
    return note


async def _list_notes_impl(
    *,
    request: fastapi.Request,
    db: graph.Pool,
    org_slug: str,
    project_id: str | None,
    tag_slug: str | None,
    limit: int,
    cursor: str | None,
) -> fastapi.Response:
    if limit < 1 or limit > MAX_LIMIT:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'limit must be 1..{MAX_LIMIT}',
        )

    params: dict[str, typing.Any] = {
        'org_slug': org_slug,
        'row_limit': limit + 1,
    }
    project_predicate = ''
    if project_id is not None:
        project_predicate = ' AND p.id = {project_id}'
        params['project_id'] = project_id

    tag_match = ''
    if tag_slug is not None:
        tag_match = (
            ' MATCH (n)-[:TAGGED_WITH]->'
            '(:Tag {{slug: {tag_slug}}})-[:BELONGS_TO]->(o)'
        )
        params['tag_slug'] = tag_slug

    cursor_clause = ''
    if cursor is not None:
        decoded = _decode_cursor(cursor)
        if decoded is None:
            raise fastapi.HTTPException(
                status_code=400, detail='Invalid cursor'
            )
        cursor_ts, cursor_id = decoded
        cursor_clause = (
            ' WHERE n.created_at < {cursor_ts}'
            ' OR (n.created_at = {cursor_ts} AND n.id < {cursor_id})'
        )
        params['cursor_ts'] = cursor_ts.isoformat()
        params['cursor_id'] = cursor_id

    query: str = (
        """
    MATCH (o:Organization {{slug: {org_slug}}})
    MATCH (n:Note)-[:ATTACHED_TO]->(p:Project)
          -[:OWNED_BY]->(:Team)-[:BELONGS_TO]->(o)
    WHERE 1 = 1"""
        + project_predicate
        + tag_match
        + cursor_clause
        + """
    WITH DISTINCT n, p, n.created_at AS sort_ts, n.id AS sort_id
    ORDER BY sort_ts DESC, sort_id DESC
    LIMIT {row_limit}
    """
        + _TAGS_TAIL
    )

    records = await db.execute(query, params, columns=['n', 'p', 'tags'])
    next_cursor: str | None = None
    parsed = [_parse_note_row(r) for r in records]
    if len(parsed) > limit:
        parsed = parsed[:limit]
        last = parsed[-1]
        last_ts = last['created_at']
        if isinstance(last_ts, str):
            last_ts = datetime.datetime.fromisoformat(last_ts)
        next_cursor = _encode_cursor(last_ts, last['id'])

    adapter = pydantic.TypeAdapter(list[NoteResponse])
    response = fastapi.responses.JSONResponse(
        {
            'data': adapter.dump_python(
                [NoteResponse.model_validate(n) for n in parsed],
                mode='json',
            )
        }
    )
    response.headers['Link'] = _build_link_header(request, next_cursor)
    return response


@notes_router.get('/', response_model=NoteListResponse)
async def list_notes(
    request: fastapi.Request,
    org_slug: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('note:read')),
    ],
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    tag: str | None = None,
    project_id: str | None = None,
) -> fastapi.Response:
    """Cross-project note search. Filter by tag slug and/or project id."""
    return await _list_notes_impl(
        request=request,
        db=db,
        org_slug=org_slug,
        project_id=project_id,
        tag_slug=tag,
        limit=limit,
        cursor=cursor,
    )


@notes_project_router.get('/', response_model=NoteListResponse)
async def list_project_notes(
    request: fastapi.Request,
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('note:read')),
    ],
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    tag: str | None = None,
) -> fastapi.Response:
    """List notes attached to a specific project."""
    return await _list_notes_impl(
        request=request,
        db=db,
        org_slug=org_slug,
        project_id=project_id,
        tag_slug=tag,
        limit=limit,
        cursor=cursor,
    )


async def _fetch_note(
    db: graph.Pool,
    org_slug: str,
    project_id: str,
    note_id: str,
) -> dict[str, typing.Any] | None:
    query: str = (
        """
    MATCH (n:Note {{id: {note_id}}})
          -[:ATTACHED_TO]->(p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    WITH DISTINCT n, p
    """
        + _TAGS_TAIL
    )
    records = await db.execute(
        query,
        {
            'note_id': note_id,
            'project_id': project_id,
            'org_slug': org_slug,
        },
        columns=['n', 'p', 'tags'],
    )
    if not records:
        return None
    return _parse_note_row(records[0])


@notes_project_router.get('/{note_id}', response_model=NoteResponse)
async def get_note(
    org_slug: str,
    project_id: str,
    note_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('note:read')),
    ],
) -> dict[str, typing.Any]:
    """Retrieve a single note."""
    note = await _fetch_note(db, org_slug, project_id, note_id)
    if note is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Note {note_id!r} not found'
        )
    return note


class NoteUpdate(pydantic.BaseModel):
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


@notes_project_router.patch('/{note_id}', response_model=NoteResponse)
async def patch_note(
    org_slug: str,
    project_id: str,
    note_id: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('note:write')),
    ],
) -> dict[str, typing.Any]:
    """Update note content and/or tag attachments via JSON Patch."""
    existing = await _fetch_note(db, org_slug, project_id, note_id)
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Note {note_id!r} not found'
        )

    current = {
        'title': str(existing.get('title') or ''),
        'content': existing['content'],
        'tags': [t['slug'] for t in existing.get('tags', [])],
        'is_pinned': bool(existing.get('is_pinned', False)),
    }
    patched = json_patch.apply_patch(current, operations, _NOTE_READONLY_PATHS)
    # Only validate fields the patch actually touched. The merged ``patched``
    # dict carries every field from ``current`` (incl. legacy values that
    # may not satisfy ``NoteUpdate`` constraints), so validating it whole
    # would reject a ``/is_pinned`` patch on a note with an empty title.
    touched: set[str] = set()
    for op in operations:
        if op.path.startswith('/'):
            head = op.path.split('/', 2)[1]
            if head:
                touched.add(head)
    try:
        update = NoteUpdate(**{k: patched[k] for k in touched if k in patched})
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

    now = datetime.datetime.now(datetime.UTC)
    set_query: typing.LiteralString = """
    MATCH (n:Note {{id: {note_id}}})
          -[:ATTACHED_TO]->(:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    SET n.title = {title},
        n.content = {content},
        n.updated_by = {updated_by},
        n.updated_at = {updated_at},
        n.is_pinned = {is_pinned}
    RETURN n.id AS id
    """
    records = await db.execute(
        set_query,
        {
            'org_slug': org_slug,
            'project_id': project_id,
            'note_id': note_id,
            'title': new_title,
            'content': new_content,
            'updated_by': auth.principal_name,
            'updated_at': now.isoformat(),
            'is_pinned': new_is_pinned,
        },
        columns=['id'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Note {note_id!r} not found'
        )

    if replace_tags:
        await _detach_all_tags(db, note_id)
        await _attach_tags(db, org_slug, note_id, new_tags)

    note = await _fetch_note(db, org_slug, project_id, note_id)
    if note is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Note {note_id!r} not found'
        )
    return note


@notes_project_router.delete('/{note_id}', status_code=204)
async def delete_note(
    org_slug: str,
    project_id: str,
    note_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('note:delete')),
    ],
) -> None:
    """Delete a note."""
    query: typing.LiteralString = """
    MATCH (n:Note {{id: {note_id}}})
          -[:ATTACHED_TO]->(p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    DETACH DELETE n
    RETURN n
    """
    records = await db.execute(
        query,
        {
            'note_id': note_id,
            'project_id': project_id,
            'org_slug': org_slug,
        },
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Note {note_id!r} not found'
        )
