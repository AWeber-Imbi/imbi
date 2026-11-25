"""Tag management endpoints.

Tags are org-scoped, slug-identified labels. They attach to
``Document``, ``DocumentTemplate`` and ``Agent`` nodes via
``TAGGED_WITH``; the edge type is generic so future work can attach
the same tags to other nodes without schema changes.
"""

import datetime
import logging
import typing

import fastapi
import nanoid
import pydantic
import slugify

from imbi.api import tags as org_tags
from imbi.api.auth import permissions
from imbi.api.endpoints._helpers import conflict_on_unique_violation
from imbi.api.relationships import RelationshipSpec, build_relationships
from imbi.common import graph, models
from imbi.common import patch as json_patch

LOGGER = logging.getLogger(__name__)

tags_router = fastapi.APIRouter(tags=['Tags'])


#: Same shape as ``Environment.label_color``.
HEX_COLOR_PATTERN = r'^#[0-9A-Fa-f]{6}$'


class TagCreate(pydantic.BaseModel):
    name: str = pydantic.Field(min_length=1)
    slug: str | None = pydantic.Field(default=None, min_length=1)
    description: str | None = None
    color: str | None = pydantic.Field(default=None, pattern=HEX_COLOR_PATTERN)


class OrganizationRef(pydantic.BaseModel):
    name: str
    slug: str


class TagResponse(pydantic.BaseModel):
    id: str
    name: str
    slug: str
    description: str | None = None
    color: str | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    organization: OrganizationRef
    relationships: dict[str, models.RelationshipLink] | None = None


class TagMerge(pydantic.BaseModel):
    target: str = pydantic.Field(min_length=1)


#: Ends each query that returns a tag with its usage counts.
_COUNTS_TAIL: typing.LiteralString = """
    OPTIONAL MATCH (n)-[:TAGGED_WITH]->(t)
    RETURN t, o,
           count(CASE WHEN label(n) = 'Document' THEN 1 END)
               AS document_count,
           count(CASE WHEN label(n) = 'Agent' THEN 1 END) AS agent_count
"""

_COUNTS_COLUMNS = ['t', 'o', 'document_count', 'agent_count']


def _tag_relationships(
    request: fastapi.Request,
    org_slug: str,
    tag_slug: str,
    document_count: int,
    agent_count: int,
) -> dict[str, models.RelationshipLink]:
    return build_relationships(
        request.app.url_path_for(
            'get_tag', org_slug=org_slug, tag_slug=tag_slug
        ),
        {
            'documents': RelationshipSpec('/documents', document_count),
            'agents': RelationshipSpec('/agents', agent_count),
        },
    )


def _tag_from_record(
    request: fastapi.Request,
    org_slug: str,
    record: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Build a tag response from a row that ends in ``_COUNTS_TAIL``."""
    tag: dict[str, typing.Any] = graph.parse_agtype(record['t'])
    tag['organization'] = graph.parse_agtype(record['o'])
    tag['relationships'] = _tag_relationships(
        request,
        org_slug,
        tag['slug'],
        graph.parse_agtype(record['document_count']) or 0,
        graph.parse_agtype(record['agent_count']) or 0,
    )
    return tag


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
        'color': data.color,
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
        color: {color},
        created_at: {created_at},
        updated_at: {updated_at},
        org_id: o.id
    }})
    CREATE (t)-[:BELONGS_TO]->(o)
    RETURN t, o
    """
    with conflict_on_unique_violation(
        f'Tag with slug {tag_slug!r} already exists',
    ):
        records = await db.execute(query, params, columns=['t', 'o'])
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization {org_slug!r} not found',
        )
    tag: dict[str, typing.Any] = graph.parse_agtype(records[0]['t'])
    org = graph.parse_agtype(records[0]['o'])
    tag['organization'] = org
    tag['relationships'] = _tag_relationships(
        request, org_slug, tag['slug'], 0, 0
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
    """List tags in an organization, each with usage counts."""
    query: typing.LiteralString = (
        """
    MATCH (t:Tag)-[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    """
        + _COUNTS_TAIL
        + ' ORDER BY t.name'
    )
    records = await db.execute(
        query, {'org_slug': org_slug}, columns=_COUNTS_COLUMNS
    )
    return [_tag_from_record(request, org_slug, r) for r in records]


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
    query: typing.LiteralString = (
        """
    MATCH (t:Tag {{slug: {tag_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    """
        + _COUNTS_TAIL
    )
    records = await db.execute(
        query,
        {'tag_slug': tag_slug, 'org_slug': org_slug},
        columns=_COUNTS_COLUMNS,
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Tag {tag_slug!r} not found',
        )
    return _tag_from_record(request, org_slug, records[0])


class TagUpdate(pydantic.BaseModel):
    name: str | None = pydantic.Field(default=None, min_length=1)
    slug: str | None = pydantic.Field(default=None, min_length=1)
    description: str | None = None
    color: str | None = pydantic.Field(default=None, pattern=HEX_COLOR_PATTERN)


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
    """Update a tag via JSON Patch (name/slug/description/color)."""
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

    current = {
        'name': existing.get('name'),
        'slug': existing.get('slug'),
        'description': existing.get('description'),
        'color': existing.get('color'),
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
    # The patch starts from the current color, so ``null`` here means
    # that the patch removed the color.
    new_color = update.color

    update_query: typing.LiteralString = (
        """
    MATCH (t:Tag {{slug: {tag_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    SET t.name = {name},
        t.slug = {slug},
        t.description = {description},
        t.color = {color},
        t.updated_at = {updated_at}
    WITH t, o
    """
        + _COUNTS_TAIL
    )
    with conflict_on_unique_violation(
        f'Tag with slug {new_slug!r} already exists',
    ):
        updated = await db.execute(
            update_query,
            {
                'tag_slug': tag_slug,
                'org_slug': org_slug,
                'name': new_name,
                'slug': new_slug,
                'description': new_description,
                'color': new_color,
                'updated_at': now.isoformat(),
            },
            columns=_COUNTS_COLUMNS,
        )
    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Tag {tag_slug!r} not found',
        )
    return _tag_from_record(request, org_slug, updated[0])


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


@tags_router.post('/{tag_slug}/merge', response_model=TagResponse)
async def merge_tag(
    org_slug: str,
    tag_slug: str,
    data: TagMerge,
    request: fastapi.Request,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('tag:delete')),
    ],
) -> dict[str, typing.Any]:
    """Merge a tag into ``target``, then delete it.

    Every node tagged with the source tag is tagged with the target
    instead. ``MERGE`` makes sure that a node that already has the
    target tag does not get a second edge.
    """
    if data.target == tag_slug:
        raise fastapi.HTTPException(
            status_code=422, detail='Cannot merge a tag into itself'
        )
    ids = await org_tags.ids_by_slug(db, org_slug, [tag_slug, data.target])
    for slug in (tag_slug, data.target):
        if slug not in ids:
            raise fastapi.HTTPException(
                status_code=404, detail=f'Tag {slug!r} not found'
            )
    # One statement, so the move and the delete succeed or fail
    # together. The source is deleted before the edges are made, so that
    # a source that nothing uses is deleted too (``UNWIND`` of an empty
    # list gives no rows).
    merge_query: typing.LiteralString = """
    MATCH (s:Tag {{id: {source_id}}}), (t:Tag {{id: {target_id}}})
    OPTIONAL MATCH (n)-[:TAGGED_WITH]->(s)
    WITH s, t, collect(n) AS nodes
    DETACH DELETE s
    WITH t, nodes
    UNWIND nodes AS n
    MERGE (n)-[:TAGGED_WITH]->(t)
    """
    await db.execute(
        merge_query,
        {'source_id': ids[tag_slug], 'target_id': ids[data.target]},
        [],
    )
    return await get_tag(org_slug, data.target, request, db, _auth)
