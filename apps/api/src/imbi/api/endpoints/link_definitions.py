"""Link definition management endpoints."""

import datetime
import logging
import typing

import fastapi
import pydantic
from imbi_common import models, neo4j
from neo4j import exceptions

from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

link_definitions_router = fastapi.APIRouter(
    tags=['Link Definitions'],
)


class LinkDefinitionCreate(pydantic.BaseModel):
    """Request model for creating a link definition."""

    name: str
    slug: str
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    url_template: str | None = None


class LinkDefinitionUpdate(pydantic.BaseModel):
    """Request model for updating a link definition."""

    name: str | None = None
    slug: str | None = None
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
    props = link_def.model_dump(exclude={'organization'})

    query: typing.LiteralString = """
    MATCH (o:Organization {slug: $org_slug})
    CREATE (ld:LinkDefinition $props)
    CREATE (ld)-[:BELONGS_TO]->(o)
    RETURN ld{.*, organization: o{.*}} AS link_definition
    """
    try:
        records = await neo4j.query(
            query,
            org_slug=org_slug,
            props=props,
        )
    except exceptions.ConstraintError as e:
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

    result: dict[str, typing.Any] = records[0]['link_definition']
    return result


@link_definitions_router.get('/')
async def list_link_definitions(
    org_slug: str,
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
    query: typing.LiteralString = """
    MATCH (ld:LinkDefinition)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    RETURN ld{.*, organization: o{.*}} AS link_definition
    ORDER BY ld.name
    """
    records = await neo4j.query(query, org_slug=org_slug)
    return [record['link_definition'] for record in records]


@link_definitions_router.get('/{slug}')
async def get_link_definition(
    org_slug: str,
    slug: str,
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
    query: typing.LiteralString = """
    MATCH (ld:LinkDefinition {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    RETURN ld{.*, organization: o{.*}} AS link_definition
    """
    records = await neo4j.query(
        query,
        slug=slug,
        org_slug=org_slug,
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Link definition with slug {slug!r} not found'),
        )
    result: dict[str, typing.Any] = records[0]['link_definition']
    return result


@link_definitions_router.put('/{slug}')
async def update_link_definition(
    org_slug: str,
    slug: str,
    data: LinkDefinitionUpdate,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'link_definition:write',
            ),
        ),
    ],
) -> dict[str, typing.Any]:
    """Update a link definition.

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Link definition slug from URL.
        data: Updated link definition data.

    Returns:
        The updated link definition.

    Raises:
        400: Validation error
        404: Link definition not found

    """
    payload = data.model_dump(exclude_unset=True)
    if 'slug' not in payload:
        payload['slug'] = slug

    query: typing.LiteralString = """
    MATCH (ld:LinkDefinition {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    RETURN ld{.*, organization: o{.*}} AS link_definition
    """
    records = await neo4j.query(
        query,
        slug=slug,
        org_slug=org_slug,
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Link definition with slug {slug!r} not found'),
        )

    existing = records[0]['link_definition']

    try:
        link_def = models.LinkDefinition(
            organization=existing['organization'],
            **payload,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning(
            'Validation error updating link definition: %s',
            e,
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    link_def.created_at = existing.get('created_at')
    link_def.updated_at = datetime.datetime.now(datetime.UTC)
    props = link_def.model_dump(exclude={'organization'})

    update_query: typing.LiteralString = """
    MATCH (ld:LinkDefinition {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    SET ld = $props
    RETURN ld{.*, organization: o{.*}} AS link_definition
    """
    try:
        updated = await neo4j.query(
            update_query,
            slug=slug,
            org_slug=org_slug,
            props=props,
        )
    except exceptions.ConstraintError as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Link definition with slug {payload["slug"]!r} already exists'
            ),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Link definition with slug {slug!r} not found'),
        )

    result: dict[str, typing.Any] = updated[0]['link_definition']
    return result


@link_definitions_router.delete('/{slug}', status_code=204)
async def delete_link_definition(
    org_slug: str,
    slug: str,
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
    query: typing.LiteralString = """
    MATCH (ld:LinkDefinition {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    DETACH DELETE ld
    RETURN count(ld) AS deleted
    """
    records = await neo4j.query(
        query,
        slug=slug,
        org_slug=org_slug,
    )

    if not records or records[0].get('deleted', 0) == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Link definition with slug {slug!r} not found'),
        )
