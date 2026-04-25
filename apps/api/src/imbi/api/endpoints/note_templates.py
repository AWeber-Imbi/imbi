"""Note template management endpoints.

Templates are scoped to an organization and seed a new
``Note``'s title, content, and tag set when a user creates a note
from one. ``project_type_slugs`` filters the templates that apply
to a given project type.
"""

import datetime
import logging
import typing

import fastapi
import pydantic
from imbi_common import graph

from imbi_api import patch as json_patch
from imbi_api.auth import permissions
from imbi_api.graph_sql import props_template, set_clause

LOGGER = logging.getLogger(__name__)

note_templates_router = fastapi.APIRouter(tags=['Note Templates'])

_TEMPLATE_READONLY_PATHS: frozenset[str] = frozenset(
    [
        '/id',
        '/organization',
        '/created_at',
        '/updated_at',
    ]
)


class TagRef(pydantic.BaseModel):
    name: str
    slug: str


class OrganizationRef(pydantic.BaseModel):
    name: str
    slug: str


class NoteTemplateBase(pydantic.BaseModel):
    name: str = pydantic.Field(min_length=1)
    slug: str = pydantic.Field(min_length=1)
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    title: str | None = None
    content: str = ''
    tags: list[str] = pydantic.Field(
        default=[],
        description='Tag slugs to attach. Must already exist in the org.',
    )
    project_type_slugs: list[str] = []
    sort_order: int = 0


class NoteTemplateCreate(NoteTemplateBase):
    pass


class NoteTemplateUpdate(pydantic.BaseModel):
    name: str | None = pydantic.Field(default=None, min_length=1)
    slug: str | None = pydantic.Field(default=None, min_length=1)
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    project_type_slugs: list[str] | None = None
    sort_order: int | None = None


class NoteTemplateResponse(pydantic.BaseModel):
    id: str
    name: str
    slug: str
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    title: str | None = None
    content: str = ''
    tags: list[TagRef] = []
    project_type_slugs: list[str] = []
    sort_order: int = 0
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None
    organization: OrganizationRef


_TAGS_TAIL: typing.LiteralString = """
    OPTIONAL MATCH (nt)-[:TAGGED_WITH]->(tag:Tag)
    WITH nt, o, collect(CASE WHEN tag IS NOT NULL
                              THEN tag{{.name, .slug}}
                              END) AS raw_tags
    WITH nt, o, [t IN raw_tags WHERE t IS NOT NULL] AS tags
    RETURN nt, o, tags
"""


def _parse_template_row(
    record: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    template: dict[str, typing.Any] = graph.parse_agtype(record['nt'])
    org: dict[str, typing.Any] = graph.parse_agtype(record['o'])
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
    template['organization'] = {
        'name': str(org.get('name', '')),
        'slug': str(org.get('slug', '')),
    }
    template['tags'] = tags
    template.setdefault('project_type_slugs', [])
    template.setdefault('sort_order', 0)
    return template


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


async def _attach_tags(
    db: graph.Pool,
    org_slug: str,
    template_slug: str,
    tag_slugs: list[str],
) -> None:
    if not tag_slugs:
        return
    # MERGE keeps this idempotent — defensive against any future caller
    # that doesn't first run ``_detach_all_tags``. The TAGGED_WITH edge
    # carries no properties, so no AGE MERGE-with-properties pitfall.
    query: typing.LiteralString = """
    MATCH (nt:NoteTemplate {{slug: {tpl_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}}),
          (t:Tag)-[:BELONGS_TO]->(o)
    WHERE t.slug IN {tag_slugs}
    MERGE (nt)-[:TAGGED_WITH]->(t)
    RETURN count(t) AS attached
    """
    await db.execute(
        query,
        {
            'tpl_slug': template_slug,
            'org_slug': org_slug,
            'tag_slugs': tag_slugs,
        },
        columns=['attached'],
    )


async def _detach_all_tags(
    db: graph.Pool, org_slug: str, template_slug: str
) -> None:
    query: typing.LiteralString = """
    MATCH (nt:NoteTemplate {{slug: {tpl_slug}}})
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}}),
          (nt)-[tw:TAGGED_WITH]->(:Tag)
    DELETE tw
    RETURN count(tw) AS removed
    """
    await db.execute(
        query,
        {'tpl_slug': template_slug, 'org_slug': org_slug},
        columns=['removed'],
    )


async def _fetch_template(
    db: graph.Pool, org_slug: str, slug: str
) -> dict[str, typing.Any] | None:
    query: str = (
        """
    MATCH (nt:NoteTemplate {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    WITH DISTINCT nt, o
    """
        + _TAGS_TAIL
    )
    records = await db.execute(
        query,
        {'slug': slug, 'org_slug': org_slug},
        columns=['nt', 'o', 'tags'],
    )
    if not records:
        return None
    return _parse_template_row(records[0])


@note_templates_router.post(
    '/', status_code=201, response_model=NoteTemplateResponse
)
async def create_note_template(
    org_slug: str,
    data: NoteTemplateCreate,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('note_template:create'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Create a note template scoped to ``org_slug``."""
    tag_slugs = list(dict.fromkeys(data.tags))
    await _validate_tag_slugs(db, org_slug, tag_slugs)

    # Slugs are unique per-org, not globally — enforce in app code.
    duplicate_query: typing.LiteralString = """
    MATCH (nt:NoteTemplate {{slug: {slug}}})
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    RETURN nt.slug AS slug
    """
    existing = await db.execute(
        duplicate_query,
        {'slug': data.slug, 'org_slug': org_slug},
        columns=['slug'],
    )
    if existing:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Note template with slug {data.slug!r} already exists',
        )

    now = datetime.datetime.now(datetime.UTC)
    props: dict[str, typing.Any] = {
        'id': data.slug,
        'name': data.name,
        'slug': data.slug,
        'description': data.description,
        'icon': str(data.icon) if data.icon else None,
        'title': data.title,
        'content': data.content,
        'project_type_slugs': data.project_type_slugs,
        'sort_order': data.sort_order,
        'created_at': now.isoformat(),
        'updated_at': now.isoformat(),
    }
    create_tpl = props_template(props)
    query = (
        f'MATCH (o:Organization {{{{slug: {{org_slug}}}}}})'
        f' CREATE (nt:NoteTemplate {create_tpl})'
        f' CREATE (nt)-[:BELONGS_TO]->(o)'
        f' RETURN nt, o'
    )
    params = {**props, 'org_slug': org_slug}
    records = await db.execute(query, params, columns=['nt', 'o'])

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization with slug {org_slug!r} not found',
        )

    if tag_slugs:
        await _attach_tags(db, org_slug, data.slug, tag_slugs)

    template = await _fetch_template(db, org_slug, data.slug)
    if template is None:
        raise fastapi.HTTPException(
            status_code=500,
            detail='Note template created but could not be read back',
        )
    return template


@note_templates_router.get('/', response_model=list[NoteTemplateResponse])
async def list_note_templates(
    org_slug: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('note_template:read'),
        ),
    ],
    project_type: str | None = None,
) -> list[dict[str, typing.Any]]:
    """List note templates for an organization.

    ``project_type`` (optional): when provided, only templates that
    apply to the given project-type slug are returned. Templates with
    an empty ``project_type_slugs`` apply to every project type.
    """
    query: str = (
        """
    MATCH (nt:NoteTemplate)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    WITH DISTINCT nt, o
    ORDER BY nt.sort_order, nt.name
    """
        + _TAGS_TAIL
    )
    records = await db.execute(
        query,
        {'org_slug': org_slug},
        columns=['nt', 'o', 'tags'],
    )
    results: list[dict[str, typing.Any]] = []
    for record in records:
        template = _parse_template_row(record)
        raw_slugs = typing.cast(
            list[typing.Any] | None,
            template.get('project_type_slugs'),
        )
        slugs: list[str] = [str(s) for s in (raw_slugs or [])]
        if project_type is not None and slugs and project_type not in slugs:
            continue
        results.append(template)
    return results


@note_templates_router.get('/{slug}', response_model=NoteTemplateResponse)
async def get_note_template(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('note_template:read'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Get a note template by slug."""
    template = await _fetch_template(db, org_slug, slug)
    if template is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Note template with slug {slug!r} not found',
        )
    return template


async def _persist_update(
    db: graph.Pool,
    org_slug: str,
    original_slug: str,
    payload: dict[str, typing.Any],
    tag_slugs: list[str] | None,
    existing_created_at: str | None,
) -> dict[str, typing.Any]:
    now = datetime.datetime.now(datetime.UTC)
    props = {**payload}
    props['created_at'] = existing_created_at or now.isoformat()
    props['updated_at'] = now.isoformat()
    if 'icon' in props and props['icon'] is not None:
        props['icon'] = str(props['icon'])

    new_slug = props.get('slug', original_slug)
    if new_slug != original_slug:
        duplicate_query: typing.LiteralString = """
        MATCH (nt:NoteTemplate {{slug: {slug}}})
              -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
        RETURN nt.slug AS slug
        """
        existing = await db.execute(
            duplicate_query,
            {'slug': new_slug, 'org_slug': org_slug},
            columns=['slug'],
        )
        if existing:
            raise fastapi.HTTPException(
                status_code=409,
                detail=(
                    f'Note template with slug {new_slug!r} already exists'
                ),
            )

    set_stmt = set_clause('nt', props)
    update_query = (
        f'MATCH (nt:NoteTemplate {{{{slug: {{slug}}}}}})'
        f' -[:BELONGS_TO]->'
        f'(:Organization {{{{slug: {{org_slug}}}}}})'
        f' {set_stmt}'
        f' RETURN nt.slug AS slug'
    )
    params = {**props, 'slug': original_slug, 'org_slug': org_slug}
    records = await db.execute(update_query, params, columns=['slug'])

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Note template with slug {original_slug!r} not found'),
        )
    new_slug = graph.parse_agtype(records[0]['slug']) or props.get(
        'slug', original_slug
    )

    if tag_slugs is not None:
        await _detach_all_tags(db, org_slug, new_slug)
        await _attach_tags(db, org_slug, new_slug, tag_slugs)

    template = await _fetch_template(db, org_slug, new_slug)
    if template is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Note template with slug {new_slug!r} not found',
        )
    return template


@note_templates_router.put('/{slug}', response_model=NoteTemplateResponse)
async def update_note_template(
    org_slug: str,
    slug: str,
    data: NoteTemplateUpdate,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('note_template:write'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Update a note template (whole-or-partial replace)."""
    existing = await _fetch_template(db, org_slug, slug)
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Note template with slug {slug!r} not found',
        )

    incoming = data.model_dump(exclude_unset=True)
    tag_slugs: list[str] | None = None
    if 'tags' in incoming:
        tag_slugs = list(dict.fromkeys(incoming.pop('tags') or []))
        await _validate_tag_slugs(db, org_slug, tag_slugs)

    merged: dict[str, typing.Any] = {
        'name': existing.get('name'),
        'slug': existing.get('slug'),
        'description': existing.get('description'),
        'icon': existing.get('icon'),
        'title': existing.get('title'),
        'content': existing.get('content', ''),
        'project_type_slugs': existing.get('project_type_slugs', []),
        'sort_order': existing.get('sort_order', 0),
    }
    merged.update(incoming)
    merged['id'] = existing.get('id', merged['slug'])

    return await _persist_update(
        db,
        org_slug,
        slug,
        merged,
        tag_slugs,
        existing.get('created_at'),
    )


@note_templates_router.patch('/{slug}', response_model=NoteTemplateResponse)
async def patch_note_template(
    org_slug: str,
    slug: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('note_template:write'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Partially update a note template using JSON Patch (RFC 6902)."""
    existing = await _fetch_template(db, org_slug, slug)
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Note template with slug {slug!r} not found',
        )

    current: dict[str, typing.Any] = {
        'name': existing.get('name'),
        'slug': existing.get('slug'),
        'description': existing.get('description'),
        'icon': existing.get('icon'),
        'title': existing.get('title'),
        'content': existing.get('content', ''),
        'tags': [t['slug'] for t in existing.get('tags', [])],
        'project_type_slugs': existing.get('project_type_slugs', []),
        'sort_order': existing.get('sort_order', 0),
    }
    patched = json_patch.apply_patch(
        current, operations, _TEMPLATE_READONLY_PATHS
    )
    # Re-validate against the schema — apply_patch is type-blind, so a
    # patch like ``/sort_order = 'oops'`` would otherwise reach the DB.
    try:
        patched = NoteTemplateBase.model_validate(patched).model_dump()
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    tag_slugs: list[str] | None = None
    touched: set[str] = set()
    for op in operations:
        if op.path.startswith('/'):
            head = op.path.split('/', 2)[1]
            if head:
                touched.add(head)
    if 'tags' in touched:
        tag_slugs = list(dict.fromkeys(patched.get('tags') or []))
        await _validate_tag_slugs(db, org_slug, tag_slugs)
    patched.pop('tags', None)
    patched['id'] = existing.get('id', patched.get('slug', slug))

    return await _persist_update(
        db,
        org_slug,
        slug,
        patched,
        tag_slugs,
        existing.get('created_at'),
    )


@note_templates_router.delete('/{slug}', status_code=204)
async def delete_note_template(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('note_template:delete'),
        ),
    ],
) -> None:
    """Delete a note template."""
    query: typing.LiteralString = """
    MATCH (nt:NoteTemplate {{slug: {slug}}})
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    DETACH DELETE nt
    RETURN nt
    """
    records = await db.execute(query, {'slug': slug, 'org_slug': org_slug})
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Note template with slug {slug!r} not found',
        )
