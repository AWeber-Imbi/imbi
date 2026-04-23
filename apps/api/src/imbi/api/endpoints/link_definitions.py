"""Link definition management endpoints."""

import datetime
import logging
import typing

import fastapi
import psycopg.errors
import pydantic
from imbi_common import blueprints, graph, models

from imbi_api import patch as json_patch
from imbi_api.auth import permissions
from imbi_api.graph_sql import props_template, set_clause
from imbi_api.relationships import build_relationships

LOGGER = logging.getLogger(__name__)

link_definitions_router = fastapi.APIRouter(
    tags=['Link Definitions'],
)


def _projects_relationship(
    project_count: int,
) -> dict[str, models.RelationshipLink]:
    """Build the ``projects`` relationship for a link definition.

    The href is intentionally empty because ``list_projects`` does not
    yet support a ``link_definition`` query filter; only the count is
    meaningful today.
    """
    return build_relationships(
        '',
        {'projects': ('', project_count)},
    )


class LinkDefinitionCreate(pydantic.BaseModel):
    """Request model for creating a link definition."""

    name: str
    slug: str
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    url_template: str | None = None


class OrganizationRef(pydantic.BaseModel):
    """Minimal organization reference."""

    name: str
    slug: str


class LinkDefinitionResponse(pydantic.BaseModel):
    """Response model for a link definition."""

    name: str
    slug: str
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    url_template: str | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    organization: OrganizationRef
    relationships: dict[str, models.RelationshipLink] | None = None


@link_definitions_router.post('/', status_code=201)
async def create_link_definition(
    org_slug: str,
    data: LinkDefinitionCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'link_definition:create',
            ),
        ),
    ],
) -> dict[str, typing.Any]:
    """Create a new link definition linked to an organization.

    Parameters:
        org_slug: Organization slug from URL path.
        data: Link definition data.

    Returns:
        The created link definition.

    Raises:
        400: Invalid data
        404: Organization not found
        409: Link definition with slug already exists

    """
    payload = data.model_dump()

    try:
        link_def = models.LinkDefinition(
            organization=models.Organization(
                name='',
                slug=org_slug,
            ),
            **payload,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning(
            'Validation error creating link definition: %s',
            e,
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    now = datetime.datetime.now(datetime.UTC)
    link_def.created_at = now
    link_def.updated_at = now
    props = link_def.model_dump(
        mode='json',
        exclude={'organization'},
    )

    create_tpl = props_template(props)
    query = (
        f'MATCH (o:Organization {{{{slug: {{org_slug}}}}}})'
        f' CREATE (ld:LinkDefinition {create_tpl})'
        f' CREATE (ld)-[:BELONGS_TO]->(o)'
        f' RETURN ld, o'
    )
    params = {**props, 'org_slug': org_slug}
    try:
        records = await db.execute(
            query,
            params,
            columns=['ld', 'o'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Link definition with slug {props["slug"]!r} already exists'
            ),
        ) from e

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Organization with slug {org_slug!r} not found'),
        )

    result: dict[str, typing.Any] = graph.parse_agtype(
        records[0]['ld'],
    )
    org = graph.parse_agtype(records[0]['o'])
    result['organization'] = org
    result['relationships'] = _projects_relationship(0)
    return result


@link_definitions_router.get('/')
async def list_link_definitions(
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'link_definition:read',
            ),
        ),
    ],
) -> list[dict[str, typing.Any]]:
    """List all link definitions in an organization.

    Parameters:
        org_slug: Organization slug from URL path.

    Returns:
        Link definitions ordered by name, each including
        their organization.

    """
    query = """
    MATCH (ld:LinkDefinition)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(:Team)
                   -[:BELONGS_TO]->(o)
        WHERE p.links CONTAINS ('"' + ld.slug + '":')
    WITH ld, o, count(DISTINCT p) AS project_count
    RETURN ld, o, project_count
    ORDER BY ld.name
    """
    records = await db.execute(
        query,
        {'org_slug': org_slug},
        columns=['ld', 'o', 'project_count'],
    )
    results: list[dict[str, typing.Any]] = []
    for record in records:
        ld = graph.parse_agtype(record['ld'])
        org = graph.parse_agtype(record['o'])
        ld['organization'] = org
        pc = graph.parse_agtype(record['project_count'])
        ld['relationships'] = _projects_relationship(pc or 0)
        results.append(ld)
    return results


@link_definitions_router.get('/{slug}')
async def get_link_definition(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'link_definition:read',
            ),
        ),
    ],
) -> dict[str, typing.Any]:
    """Get a link definition by slug.

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Link definition slug identifier.

    Returns:
        Link definition with organization.

    Raises:
        404: Link definition not found

    """
    query = """
    MATCH (ld:LinkDefinition {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(:Team)
                   -[:BELONGS_TO]->(o)
        WHERE p.links CONTAINS ('"' + ld.slug + '":')
    WITH ld, o, count(DISTINCT p) AS project_count
    RETURN ld, o, project_count
    """
    records = await db.execute(
        query,
        {'slug': slug, 'org_slug': org_slug},
        columns=['ld', 'o', 'project_count'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Link definition with slug {slug!r} not found'),
        )

    result: dict[str, typing.Any] = graph.parse_agtype(
        records[0]['ld'],
    )
    org = graph.parse_agtype(records[0]['o'])
    result['organization'] = org
    pc = graph.parse_agtype(records[0]['project_count'])
    result['relationships'] = _projects_relationship(pc or 0)
    return result


async def _persist_link_definition(
    original_slug: str,
    org_slug: str,
    ld_model: type,
    existing_org: dict[str, typing.Any],
    payload: dict[str, typing.Any],
    existing_created_at: str | None,
    db: graph.Pool,
) -> dict[str, typing.Any]:
    """Validate, stamp timestamps, and persist a link definition to the graph.

    Parameters:
        original_slug: Current slug to match on in Cypher.
        org_slug: Organization slug for the BELONGS_TO edge.
        ld_model: Dynamic Pydantic model (from blueprints.get_model).
        existing_org: Parsed org dict from the graph (for organization
            field).
        payload: New field values (slug, name, description, etc.).
        existing_created_at: ISO string from existing node or None.
        db: Graph database connection.

    Returns:
        Updated link definition dict with organization and relationships.

    Raises:
        HTTPException 400: Validation error.
        HTTPException 404: Link definition not found.
        HTTPException 409: Slug conflict.

    """
    try:
        link_def = ld_model(
            organization=existing_org,
            **payload,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning(
            'Validation error persisting link definition: %s',
            e,
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    link_def.created_at = (
        datetime.datetime.fromisoformat(existing_created_at)
        if existing_created_at
        else datetime.datetime.now(datetime.UTC)
    )
    link_def.updated_at = datetime.datetime.now(datetime.UTC)
    props = link_def.model_dump(
        mode='json',
        exclude={'organization'},
    )

    set_stmt = set_clause('ld', props)
    update_query = (
        f'MATCH (ld:LinkDefinition {{{{slug: {{slug}}}}}})'
        f' -[:BELONGS_TO]->(o:Organization'
        f' {{{{slug: {{org_slug}}}}}})'
        f' {set_stmt}'
        f' WITH ld, o'
        f' OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(:Team)'
        f' -[:BELONGS_TO]->(o)'
        f' WHERE p.links CONTAINS'
        f" ('\"' + ld.slug + '\":')"
        f' WITH ld, o, count(DISTINCT p) AS project_count'
        f' RETURN ld, o, project_count'
    )
    params = {**props, 'slug': original_slug, 'org_slug': org_slug}
    try:
        updated = await db.execute(
            update_query,
            params,
            columns=['ld', 'o', 'project_count'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Link definition with slug'
                f' {payload.get("slug", original_slug)!r}'
                f' already exists'
            ),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Link definition with slug {original_slug!r} not found'),
        )

    result: dict[str, typing.Any] = graph.parse_agtype(updated[0]['ld'])
    org = graph.parse_agtype(updated[0]['o'])
    result['organization'] = org
    pc = graph.parse_agtype(updated[0]['project_count'])
    result['relationships'] = _projects_relationship(pc or 0)
    return result


@link_definitions_router.patch('/{slug}')
async def patch_link_definition(
    org_slug: str,
    slug: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'link_definition:write',
            ),
        ),
    ],
) -> dict[str, typing.Any]:
    """Partially update a link definition using JSON Patch (RFC 6902).

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Link definition slug from URL.
        operations: JSON Patch operations.

    Returns:
        The updated link definition.

    Raises:
        400: Invalid patch, read-only path, or validation error.
        404: Link definition not found.
        409: Slug conflict.
        422: Patch test operation failed.

    """
    dynamic_model = await blueprints.get_model(
        db,
        models.LinkDefinition,
    )

    fetch_query = """
    MATCH (ld:LinkDefinition {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN ld, o
    """
    records = await db.execute(
        fetch_query,
        {'slug': slug, 'org_slug': org_slug},
        columns=['ld', 'o'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Link definition with slug {slug!r} not found'),
        )
    existing = graph.parse_agtype(records[0]['ld'])
    existing_org = graph.parse_agtype(records[0]['o'])

    current = dict(existing)
    current.pop('created_at', None)
    current.pop('updated_at', None)
    current.pop('organization', None)

    patched = json_patch.apply_patch(current, operations)
    patched.pop('organization_slug', None)
    patched.pop('organization', None)
    if 'slug' not in patched:
        patched['slug'] = slug

    return await _persist_link_definition(
        slug,
        org_slug,
        dynamic_model,
        existing_org,
        patched,
        existing.get('created_at'),
        db,
    )


@link_definitions_router.delete('/{slug}', status_code=204)
async def delete_link_definition(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'link_definition:delete',
            ),
        ),
    ],
) -> None:
    """Delete a link definition.

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Link definition slug to delete.

    Raises:
        404: Link definition not found

    """
    query = """
    MATCH (ld:LinkDefinition {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    DETACH DELETE ld
    RETURN ld
    """
    records = await db.execute(
        query,
        {'slug': slug, 'org_slug': org_slug},
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Link definition with slug {slug!r} not found'),
        )
