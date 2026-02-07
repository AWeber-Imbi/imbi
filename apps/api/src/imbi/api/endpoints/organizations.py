"""Organization management endpoints."""

import logging
import typing

import fastapi
from imbi_common import models, neo4j
from neo4j import exceptions

from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

organizations_router = fastapi.APIRouter(
    prefix='/organizations', tags=['Organizations']
)


@organizations_router.post('/', status_code=201)
async def create_organization(
    org: models.Organization,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('organization:create'),
        ),
    ],
) -> models.Organization:
    """Create a new organization.

    Parameters:
        org: Organization data.

    Returns:
        The created organization.

    Raises:
        409: Organization with slug already exists.

    """
    try:
        created = await neo4j.create_node(org)
        return typing.cast(models.Organization, created)
    except exceptions.ConstraintError as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(f'Organization with slug {org.slug!r} already exists'),
        ) from e


@organizations_router.get('/')
async def list_organizations(
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('organization:read'),
        ),
    ],
) -> list[models.Organization]:
    """Retrieve all organizations ordered by name.

    Returns:
        List of organizations.

    """
    organizations: list[models.Organization] = []
    async for org in neo4j.fetch_nodes(
        models.Organization,
        order_by='name',
    ):
        organizations.append(org)
    return organizations


@organizations_router.get('/{slug}')
async def get_organization(
    slug: str,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('organization:read'),
        ),
    ],
) -> models.Organization:
    """Retrieve an organization by slug.

    Parameters:
        slug: Organization slug identifier.

    Returns:
        The organization.

    Raises:
        404: Organization not found.

    """
    org = await neo4j.fetch_node(
        models.Organization,
        {'slug': slug},
    )
    if org is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization with slug {slug!r} not found',
        )
    return org


@organizations_router.put('/{slug}')
async def update_organization(
    slug: str,
    org: models.Organization,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('organization:update'),
        ),
    ],
) -> models.Organization:
    """Update an existing organization.

    Parameters:
        slug: Organization slug from URL (identifies existing record).
        org: Updated organization data.

    Returns:
        The updated organization.

    Raises:
        404: Organization not found.
        409: Slug rename conflicts with existing organization.

    """
    existing = await neo4j.fetch_node(
        models.Organization,
        {'slug': slug},
    )
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization with slug {slug!r} not found',
        )

    try:
        await neo4j.upsert(org, {'slug': slug})
    except exceptions.ConstraintError as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(f'Organization with slug {org.slug!r} already exists'),
        ) from e
    return org


@organizations_router.get('/{slug}/members')
async def list_organization_members(
    slug: str,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('organization:read'),
        ),
    ],
) -> list[dict[str, typing.Any]]:
    """List all members of an organization with their roles.

    Parameters:
        slug: Organization slug identifier.

    Returns:
        Members with email, display_name, and role.

    Raises:
        404: Organization not found.

    """
    query: typing.LiteralString = """
    MATCH (o:Organization {slug: $slug})
    OPTIONAL MATCH (u:User)-[m:MEMBER_OF]->(o)
    RETURN o, collect({
        email: u.email,
        display_name: u.display_name,
        role: m.role
    }) AS members
    """
    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()
        if not records or not records[0].get('o'):
            raise fastapi.HTTPException(
                status_code=404,
                detail=(f'Organization with slug {slug!r} not found'),
            )
        members = records[0].get('members', [])
        return [m for m in members if m.get('email')]


@organizations_router.delete('/{slug}', status_code=204)
async def delete_organization(
    slug: str,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('organization:delete'),
        ),
    ],
) -> None:
    """Delete an organization.

    Parameters:
        slug: Organization slug to delete.

    Raises:
        404: Organization not found.

    """
    deleted = await neo4j.delete_node(
        models.Organization,
        {'slug': slug},
    )
    if not deleted:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Organization with slug {slug!r} not found'),
        )
