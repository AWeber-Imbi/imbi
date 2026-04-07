"""Team management endpoints."""

import datetime
import logging
import typing

import fastapi
import pydantic
from imbi_common import blueprints, models, neo4j
from neo4j import exceptions

from imbi_api.auth import permissions
from imbi_api.relationships import relationship_link

LOGGER = logging.getLogger(__name__)

teams_router = fastapi.APIRouter(tags=['Teams'])


def _add_relationships(
    team: dict[str, typing.Any],
    org_slug: str,
    project_count: int = 0,
    member_count: int = 0,
) -> dict[str, typing.Any]:
    """Attach relationships sub-object to a team dict."""
    slug = team['slug']
    team['relationships'] = {
        'projects': relationship_link(
            f'/api/projects?team={slug}',
            project_count,
        ),
        'members': relationship_link(
            f'/api/organizations/{org_slug}/teams/{slug}/members',
            member_count,
        ),
    }
    return team


@teams_router.post('/', status_code=201)
async def create_team(
    org_slug: str,
    data: dict[str, typing.Any],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:create')),
    ],
) -> dict[str, typing.Any]:
    """Create a new team linked to an organization.

    Parameters:
        org_slug: Organization slug from URL path.
        data: Team data including base fields.

    Returns:
        The created team.

    Raises:
        400: Invalid data
        404: Organization not found
        409: Team with slug already exists

    """
    dynamic_model = await blueprints.get_model(models.Team)

    # Defensive copy: remove organization fields to prevent
    # duplicate keyword arguments when unpacking into model
    payload = dict(data)
    payload.pop('organization_slug', None)
    payload.pop('organization', None)

    # Validate team fields (without organization relationship)
    try:
        team = dynamic_model(
            organization=models.Organization(
                name='',
                slug=org_slug,
            ),
            **payload,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning('Validation error creating team: %s', e)
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    # Build property SET clause from model fields (exclude
    # relationship fields)
    now = datetime.datetime.now(datetime.UTC)
    team.created_at = now
    team.updated_at = now
    props = team.model_dump(
        exclude={'organization'},
    )

    query: typing.LiteralString = """
    MATCH (o:Organization {slug: $org_slug})
    CREATE (t:Team $props)
    CREATE (t)-[:BELONGS_TO]->(o)
    RETURN t{.*, organization: o{.*}} AS team
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
            detail=(f'Team with slug {props["slug"]!r} already exists'),
        ) from e

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Organization with slug {org_slug!r} not found'),
        )

    return _add_relationships(records[0]['team'], org_slug)


@teams_router.get('/')
async def list_teams(
    org_slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:read')),
    ],
) -> list[dict[str, typing.Any]]:
    """List all teams in an organization.

    Parameters:
        org_slug: Organization slug from URL path.

    Returns:
        Teams ordered by name, each including their
        organization and relationships.

    """
    query: typing.LiteralString = """
    MATCH (t:Team)-[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(t)
    OPTIONAL MATCH (u:User)-[:MEMBER_OF]->(t)
    WITH t, o, count(DISTINCT p) AS project_count,
                count(DISTINCT u) AS member_count
    RETURN t{.*, organization: o{.*}} AS team,
           project_count, member_count
    ORDER BY t.name
    """
    teams: list[dict[str, typing.Any]] = []
    records = await neo4j.query(query, org_slug=org_slug)
    for record in records:
        team = record['team']
        _add_relationships(
            team,
            org_slug,
            record['project_count'],
            record['member_count'],
        )
        teams.append(team)
    return teams


@teams_router.get('/{slug}')
async def get_team(
    org_slug: str,
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:read')),
    ],
) -> dict[str, typing.Any]:
    """Get a team by slug.

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Team slug identifier.

    Returns:
        Team with organization and relationships.

    Raises:
        404: Team not found

    """
    query: typing.LiteralString = """
    MATCH (t:Team {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(t)
    OPTIONAL MATCH (u:User)-[:MEMBER_OF]->(t)
    WITH t, o, count(DISTINCT p) AS project_count,
                count(DISTINCT u) AS member_count
    RETURN t{.*, organization: o{.*}} AS team,
           project_count, member_count
    """
    records = await neo4j.query(
        query,
        slug=slug,
        org_slug=org_slug,
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {slug!r} not found',
        )
    return _add_relationships(
        records[0]['team'],
        org_slug,
        records[0]['project_count'],
        records[0]['member_count'],
    )


@teams_router.put('/{slug}')
async def update_team(
    org_slug: str,
    slug: str,
    data: dict[str, typing.Any],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:update')),
    ],
) -> dict[str, typing.Any]:
    """Update a team.

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Team slug from URL.
        data: Updated team data.

    Returns:
        The updated team.

    Raises:
        400: Slug mismatch or validation error
        404: Team not found

    """
    # Defensive copy: avoid mutating the caller's input
    payload = dict(data)

    # If no slug in body, default to the URL slug (no rename)
    if 'slug' not in payload:
        payload['slug'] = slug

    # Remove organization fields (not updatable)
    payload.pop('organization_slug', None)
    payload.pop('organization', None)

    dynamic_model = await blueprints.get_model(models.Team)

    # Fetch team with its organization relationship
    query: typing.LiteralString = """
    MATCH (t:Team {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    RETURN t{.*, organization: o{.*}} AS team
    """
    records = await neo4j.query(
        query,
        slug=slug,
        org_slug=org_slug,
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {slug!r} not found',
        )

    existing = records[0]['team']

    try:
        team = dynamic_model(
            organization=existing['organization'],
            **payload,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning(
            'Validation error updating team: %s',
            e,
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    # Build property SET from model fields, excluding relationship
    team.created_at = existing.get('created_at')
    team.updated_at = datetime.datetime.now(datetime.UTC)
    props = team.model_dump(exclude={'organization'})

    update_query: typing.LiteralString = """
    MATCH (t:Team {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    SET t = $props
    WITH t, o
    OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(t)
    OPTIONAL MATCH (u:User)-[:MEMBER_OF]->(t)
    WITH t, o, count(DISTINCT p) AS project_count,
                count(DISTINCT u) AS member_count
    RETURN t{.*, organization: o{.*}} AS team,
           project_count, member_count
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
            detail=(f'Team with slug {payload["slug"]!r} already exists'),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {slug!r} not found',
        )

    return _add_relationships(
        updated[0]['team'],
        org_slug,
        updated[0]['project_count'],
        updated[0]['member_count'],
    )


@teams_router.delete('/{slug}', status_code=204)
async def delete_team(
    org_slug: str,
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:delete')),
    ],
) -> None:
    """Delete a team.

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Team slug to delete.

    Raises:
        404: Team not found

    """
    query: typing.LiteralString = """
    MATCH (t:Team {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    DETACH DELETE t
    RETURN count(t) AS deleted
    """
    records = await neo4j.query(
        query,
        slug=slug,
        org_slug=org_slug,
    )

    if not records or records[0].get('deleted', 0) == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {slug!r} not found',
        )


@teams_router.get('/{slug}/members')
async def list_team_members(
    org_slug: str,
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:read')),
    ],
) -> list[dict[str, typing.Any]]:
    """List members of a team.

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Team slug identifier.

    Returns:
        List of members with email and display_name.

    Raises:
        404: Team not found

    """
    query: typing.LiteralString = """
    MATCH (t:Team {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    OPTIONAL MATCH (u:User)-[:MEMBER_OF]->(t)
    RETURN t, collect({
        email: u.email,
        display_name: u.display_name,
        is_active: COALESCE(u.is_active, false),
        is_admin: COALESCE(u.is_admin, false)
    }) AS members
    """
    records = await neo4j.query(
        query,
        slug=slug,
        org_slug=org_slug,
    )

    if not records or not records[0].get('t'):
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {slug!r} not found',
        )
    members = records[0].get('members', [])
    return [m for m in members if m.get('email')]


@teams_router.post('/{slug}/members', status_code=201)
async def add_team_member(
    org_slug: str,
    slug: str,
    data: dict[str, str],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:update')),
    ],
) -> dict[str, str]:
    """Add a user to a team.

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Team slug identifier.
        data: Must contain ``email`` of user to add.

    Returns:
        Confirmation with email and team slug.

    Raises:
        400: Missing email
        404: User or team not found

    """
    email = data.get('email')
    if not email:
        raise fastapi.HTTPException(
            status_code=400,
            detail='email is required',
        )

    query: typing.LiteralString = """
    MATCH (u:User {email: $email})
    MATCH (t:Team {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    MERGE (u)-[:MEMBER_OF]->(t)
    RETURN u, t
    """
    records = await neo4j.query(
        query,
        email=email,
        slug=slug,
        org_slug=org_slug,
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'User {email!r} or team {slug!r} not found'),
        )
    return {'email': email, 'team': slug}


@teams_router.delete(
    '/{slug}/members/{email}',
    status_code=204,
)
async def remove_team_member(
    org_slug: str,
    slug: str,
    email: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:update')),
    ],
) -> None:
    """Remove a user from a team.

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Team slug identifier.
        email: Email of the user to remove.

    Raises:
        404: Membership not found

    """
    query: typing.LiteralString = """
    MATCH (u:User {email: $email})-[m:MEMBER_OF]->(t:Team {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    DELETE m
    RETURN count(m) AS deleted
    """
    records = await neo4j.query(
        query,
        email=email,
        slug=slug,
        org_slug=org_slug,
    )

    if not records or records[0].get('deleted', 0) == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Membership for {email!r} in team {slug!r} not found'),
        )
