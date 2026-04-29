"""Tag management endpoints.

Tags are org-scoped, slug-identified labels. Today they attach to
``Note`` nodes via ``TAGGED_WITH``; the edge type is generic so
future work can attach the same tags to ``Project``/``Service``
nodes without schema changes.
"""

import datetime
import logging
import typing

import fastapi
import nanoid
import psycopg.errors
import pydantic
import slugify
from imbi_common import graph, models

from imbi_api import patch as json_patch
from imbi_api.auth import permissions
from imbi_api.relationships import build_relationships

LOGGER = logging.getLogger(__name__)

tags_router = fastapi.APIRouter(tags=['Tags'])


class TagCreate(pydantic.BaseModel):
    name: str
    slug: str | None = None
    description: str | None = None


class OrganizationRef(pydantic.BaseModel):
    name: str
    slug: str


class TagResponse(pydantic.BaseModel):
    id: str
    name: str
    slug: str
    description: str | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    organization: OrganizationRef
    relationships: dict[str, models.RelationshipLink] | None = None


def _tag_relationships(
    request: fastapi.Request,
    org_slug: str,
    tag_slug: str,
    note_count: int,
) -> dict[str, models.RelationshipLink]:
    return build_relationships(
        request.app.url_path_for(
            'get_tag', org_slug=org_slug, tag_slug=tag_slug
        ),
        {'notes': ('/notes', note_count)},
    )


@tags_router.post('/', status_code=201, response_model=TagResponse)
async def create_tag(
    org_slug: str,
    data: TagCreate,
    request: fastapi.Request,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('tag:create')),
    ],
) -> dict[str, typing.Any]:
    """Create a new tag in an organization."""
    tag_slug = data.slug or slugify.slugify(data.name)
    now = datetime.datetime.now(datetime.UTC)
    params: dict[str, typing.Any] = {
        'org_slug': org_slug,
        'id': nanoid.generate(),
        'name': data.name,
        'slug': tag_slug,
        'description': data.description,
        'created_at': now.isoformat(),
        'updated_at': now.isoformat(),
    }
    query: typing.LiteralString = """
    MATCH (o:Organization {{slug: {org_slug}}})
    CREATE (t:Tag {{
        id: {id},
        name: {name},
        slug: {slug},
        description: {description},
        created_at: {created_at},
        updated_at: {updated_at}
    }})
    CREATE (t)-[:BELONGS_TO]->(o)
    RETURN t, o
    """
    try:
        records = await db.execute(query, params, columns=['t', 'o'])
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Tag with slug {tag_slug!r} already exists',
        ) from e
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization {org_slug!r} not found',
        )
    tag: dict[str, typing.Any] = graph.parse_agtype(records[0]['t'])
    org = graph.parse_agtype(records[0]['o'])
    tag['organization'] = org
    tag['relationships'] = _tag_relationships(
        request, org_slug, tag['slug'], 0
    )
    return tag


@tags_router.get('/', response_model=list[TagResponse])
async def list_tags(
    org_slug: str,
    request: fastapi.Request,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('tag:read')),
    ],
) -> list[dict[str, typing.Any]]:
    """List tags in an organization, each with a note count."""
    query: typing.LiteralString = """
    MATCH (t:Tag)-[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (n:Note)-[:TAGGED_WITH]->(t)
    WITH t, o, count(DISTINCT n) AS note_count
    RETURN t, o, note_count
    ORDER BY t.name
    """
    records = await db.execute(
        query,
        {'org_slug': org_slug},
        columns=['t', 'o', 'note_count'],
    )
    results: list[dict[str, typing.Any]] = []
    for record in records:
        tag = graph.parse_agtype(record['t'])
        tag['organization'] = graph.parse_agtype(record['o'])
        tag['relationships'] = _tag_relationships(
            request,
            org_slug,
            tag['slug'],
            graph.parse_agtype(record['note_count']) or 0,
        )
        results.append(tag)
    return results


@tags_router.get('/{tag_slug}', response_model=TagResponse, name='get_tag')
async def get_tag(
    org_slug: str,
    tag_slug: str,
    request: fastapi.Request,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('tag:read')),
    ],
) -> dict[str, typing.Any]:
    """Retrieve a single tag by slug."""
    query: typing.LiteralString = """
    MATCH (t:Tag {{slug: {tag_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (n:Note)-[:TAGGED_WITH]->(t)
    WITH t, o, count(DISTINCT n) AS note_count
    RETURN t, o, note_count
    """
    records = await db.execute(
        query,
        {'tag_slug': tag_slug, 'org_slug': org_slug},
        columns=['t', 'o', 'note_count'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Tag {tag_slug!r} not found',
        )
    tag: dict[str, typing.Any] = graph.parse_agtype(records[0]['t'])
    tag['organization'] = graph.parse_agtype(records[0]['o'])
    tag['relationships'] = _tag_relationships(
        request,
        org_slug,
        tag['slug'],
        graph.parse_agtype(records[0]['note_count']) or 0,
    )
    return tag


class TagUpdate(pydantic.BaseModel):
    name: str | None = None
    slug: str | None = None
    description: str | None = None


_TAG_READONLY_PATHS: frozenset[str] = frozenset(
    ['/id', '/created_at', '/updated_at', '/organization']
)


@tags_router.patch('/{tag_slug}', response_model=TagResponse)
async def patch_tag(
    org_slug: str,
    tag_slug: str,
    operations: list[json_patch.PatchOperation],
    request: fastapi.Request,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('tag:write')),
    ],
) -> dict[str, typing.Any]:
    """Update a tag via JSON Patch (name/slug/description)."""
    fetch_query: typing.LiteralString = """
    MATCH (t:Tag {{slug: {tag_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN t, o
    """
    records = await db.execute(
        fetch_query,
        {'tag_slug': tag_slug, 'org_slug': org_slug},
        columns=['t', 'o'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Tag {tag_slug!r} not found',
        )
    existing = graph.parse_agtype(records[0]['t'])
    org = graph.parse_agtype(records[0]['o'])

    current = {
        'name': existing.get('name'),
        'slug': existing.get('slug'),
        'description': existing.get('description'),
    }
    patched = json_patch.apply_patch(current, operations, _TAG_READONLY_PATHS)
    try:
        update = TagUpdate(**patched)
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    now = datetime.datetime.now(datetime.UTC)
    new_name = update.name if update.name is not None else existing.get('name')
    new_slug = update.slug if update.slug is not None else existing.get('slug')
    new_description = (
        update.description
        if update.description is not None
        else existing.get('description')
    )

    update_query: typing.LiteralString = """
    MATCH (t:Tag {{slug: {tag_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    SET t.name = {name},
        t.slug = {slug},
        t.description = {description},
        t.updated_at = {updated_at}
    WITH t, o
    OPTIONAL MATCH (n:Note)-[:TAGGED_WITH]->(t)
    WITH t, o, count(DISTINCT n) AS note_count
    RETURN t, o, note_count
    """
    try:
        updated = await db.execute(
            update_query,
            {
                'tag_slug': tag_slug,
                'org_slug': org_slug,
                'name': new_name,
                'slug': new_slug,
                'description': new_description,
                'updated_at': now.isoformat(),
            },
            columns=['t', 'o', 'note_count'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Tag with slug {new_slug!r} already exists',
        ) from e
    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Tag {tag_slug!r} not found',
        )
    tag: dict[str, typing.Any] = graph.parse_agtype(updated[0]['t'])
    tag['organization'] = org
    tag['relationships'] = _tag_relationships(
        request,
        org_slug,
        tag['slug'],
        graph.parse_agtype(updated[0]['note_count']) or 0,
    )
    return tag


@tags_router.delete('/{tag_slug}', status_code=204)
async def delete_tag(
    org_slug: str,
    tag_slug: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('tag:delete')),
    ],
) -> None:
    """Delete a tag. Any ``TAGGED_WITH`` edges are removed."""
    query: typing.LiteralString = """
    MATCH (t:Tag {{slug: {tag_slug}}})
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    DETACH DELETE t
    RETURN t
    """
    records = await db.execute(
        query, {'tag_slug': tag_slug, 'org_slug': org_slug}
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Tag {tag_slug!r} not found',
        )
