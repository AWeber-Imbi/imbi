"""Organization management endpoints."""

import datetime
import logging
import typing

import fastapi
from imbi_common import models, neo4j
from neo4j import exceptions

from imbi_api.auth import permissions
from imbi_api.relationships import relationship_link

from .environments import environments_router
from .link_definitions import link_definitions_router
from .project_types import project_types_router
from .projects import projects_router
from .teams import teams_router
from .third_party_services import third_party_services_router
from .webhooks import project_services_router, webhooks_router

LOGGER = logging.getLogger(__name__)

organizations_router = fastapi.APIRouter(
    prefix='/organizations', tags=['Organizations']
)

organizations_router.include_router(
    teams_router,
    prefix='/{org_slug}/teams',
)
organizations_router.include_router(
    environments_router,
    prefix='/{org_slug}/environments',
)
organizations_router.include_router(
    link_definitions_router,
    prefix='/{org_slug}/link-definitions',
)
organizations_router.include_router(
    project_types_router,
    prefix='/{org_slug}/project-types',
)
organizations_router.include_router(
    projects_router,
    prefix='/{org_slug}/projects',
)
organizations_router.include_router(
    third_party_services_router,
    prefix='/{org_slug}/third-party-services',
)
organizations_router.include_router(
    webhooks_router,
    prefix='/{org_slug}/webhooks',
)
organizations_router.include_router(
    project_services_router,
    prefix='/{org_slug}/projects/{project_id}/services',
)


def _add_relationships(
    org: dict[str, typing.Any],
    team_count: int = 0,
    member_count: int = 0,
    project_count: int = 0,
) -> dict[str, typing.Any]:
    """Attach relationships sub-object to an organization dict."""
    slug = org['slug']
    org['relationships'] = {
        'teams': relationship_link(
            f'/api/organizations/{slug}/teams',
            team_count,
        ),
        'members': relationship_link(
            f'/api/organizations/{slug}/members',
            member_count,
        ),
        'projects': relationship_link(
            f'/api/organizations/{slug}/projects',
            project_count,
        ),
    }
    return org


@organizations_router.post('/', status_code=201)
async def create_organization(
    org: models.Organization,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('organization:create'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Create a new organization.

    Parameters:
        org: Organization data.

    Returns:
        The created organization.

    Raises:
        409: Organization with slug already exists.

    """
    now = datetime.datetime.now(datetime.UTC)
    org.created_at = now
    org.updated_at = now
    try:
        created = await neo4j.create_node(org)
    except exceptions.ConstraintError as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(f'Organization with slug {org.slug!r} already exists'),
        ) from e
    result = created.model_dump()
    return _add_relationships(result)


@organizations_router.get('/')
async def list_organizations(
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('organization:read'),
        ),
    ],
) -> list[dict[str, typing.Any]]:
    """Retrieve all organizations ordered by name.

    Returns:
        List of organizations with relationships.

    """
    query: typing.LiteralString = """
    MATCH (o:Organization)
    OPTIONAL MATCH (t:Team)-[:BELONGS_TO]->(o)
    OPTIONAL MATCH (u:User)-[:MEMBER_OF]->(o)
    WITH o, count(DISTINCT t) AS team_count,
            count(DISTINCT u) AS member_count
    OPTIONAL MATCH (t2:Team)-[:BELONGS_TO]->(o)
    OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(t2)
    WITH o, team_count, member_count,
         count(DISTINCT p) AS project_count
    RETURN o{.*} AS organization,
           team_count, member_count, project_count
    ORDER BY o.name
    """
    organizations: list[dict[str, typing.Any]] = []
    records = await neo4j.query(query)
    for record in records:
        org = record['organization']
        _add_relationships(
            org,
            record['team_count'],
            record['member_count'],
            record['project_count'],
        )
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
) -> dict[str, typing.Any]:
    """Retrieve an organization by slug.

    Parameters:
        slug: Organization slug identifier.

    Returns:
        The organization with relationships.

    Raises:
        404: Organization not found.

    """
    query: typing.LiteralString = """
    MATCH (o:Organization {slug: $slug})
    OPTIONAL MATCH (t:Team)-[:BELONGS_TO]->(o)
    OPTIONAL MATCH (u:User)-[:MEMBER_OF]->(o)
    WITH o, count(DISTINCT t) AS team_count,
            count(DISTINCT u) AS member_count
    OPTIONAL MATCH (t2:Team)-[:BELONGS_TO]->(o)
    OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(t2)
    WITH o, team_count, member_count,
         count(DISTINCT p) AS project_count
    RETURN o{.*} AS organization,
           team_count, member_count, project_count
    """
    records = await neo4j.query(query, slug=slug)

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization with slug {slug!r} not found',
        )
    return _add_relationships(
        records[0]['organization'],
        records[0]['team_count'],
        records[0]['member_count'],
        records[0]['project_count'],
    )


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
) -> dict[str, typing.Any]:
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

    org.created_at = existing.created_at
    org.updated_at = datetime.datetime.now(datetime.UTC)
    try:
        await neo4j.upsert(org, {'slug': slug})
    except exceptions.ConstraintError as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(f'Organization with slug {org.slug!r} already exists'),
        ) from e

    # Return with relationship counts
    count_query: typing.LiteralString = """
    MATCH (o:Organization {slug: $slug})
    OPTIONAL MATCH (t:Team)-[:BELONGS_TO]->(o)
    OPTIONAL MATCH (u:User)-[:MEMBER_OF]->(o)
    WITH o, count(DISTINCT t) AS team_count,
            count(DISTINCT u) AS member_count
    OPTIONAL MATCH (t2:Team)-[:BELONGS_TO]->(o)
    OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(t2)
    WITH o, team_count, member_count,
         count(DISTINCT p) AS project_count
    RETURN team_count, member_count, project_count
    """
    records = await neo4j.query(
        count_query,
        slug=org.slug,
    )

    counts = records[0] if records else {}
    org_dict = org.model_dump()
    return _add_relationships(
        org_dict,
        counts.get('team_count', 0),
        counts.get('member_count', 0),
        counts.get('project_count', 0),
    )


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
    records = await neo4j.query(query, slug=slug)
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
