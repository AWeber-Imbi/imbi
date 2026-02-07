"""Team management endpoints."""

import logging
import typing

import fastapi
import pydantic
from imbi_common import blueprints, models, neo4j
from neo4j import exceptions

from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

teams_router = fastapi.APIRouter(prefix='/teams', tags=['Teams'])


@teams_router.post('/', status_code=201)
async def create_team(
    data: dict[str, typing.Any],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:create')),
    ],
) -> dict[str, typing.Any]:
    """Create a new team linked to an organization.

    Parameters:
        data: Team data including base fields and
            ``organization_slug``.

    Returns:
        The created team.

    Raises:
        400: Invalid data or missing organization_slug
        404: Organization not found
        409: Team with slug already exists

    """
    org_slug = data.pop('organization_slug', None)
    if not org_slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='organization_slug is required',
        )

    dynamic_model = await blueprints.get_model(models.Team)

    # Validate team fields (without organization relationship)
    try:
        team = dynamic_model(
            organization=models.Organization(
                name='',
                slug=org_slug,
            ),
            **data,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning('Validation error creating team: %s', e)
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    # Build property SET clause from model fields (exclude
    # relationship fields)
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
        async with neo4j.run(
            query,
            org_slug=org_slug,
            props=props,
        ) as result:
            records = await result.data()
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

    return typing.cast(
        dict[str, typing.Any],
        records[0]['team'],
    )


@teams_router.get('/')
async def list_teams(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:read')),
    ],
) -> list[dict[str, typing.Any]]:
    """List all teams.

    Returns:
        Teams ordered by name, each including their
        organization.

    """
    query: typing.LiteralString = """
    MATCH (t:Team)-[:BELONGS_TO]->(o:Organization)
    RETURN t{.*, organization: o{.*}} AS team
    ORDER BY t.name
    """
    teams: list[dict[str, typing.Any]] = []
    async with neo4j.run(query) as result:
        records = await result.data()
        for record in records:
            teams.append(record['team'])
    return teams


@teams_router.get('/{slug}')
async def get_team(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:read')),
    ],
) -> dict[str, typing.Any]:
    """Get a team by slug.

    Parameters:
        slug: Team slug identifier.

    Returns:
        Team with organization.

    Raises:
        404: Team not found

    """
    query: typing.LiteralString = """
    MATCH (t:Team {slug: $slug})-[:BELONGS_TO]->(o:Organization)
    RETURN t{.*, organization: o{.*}} AS team
    """
    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {slug!r} not found',
        )
    return typing.cast(
        dict[str, typing.Any],
        records[0]['team'],
    )


@teams_router.put('/{slug}')
async def update_team(
    slug: str,
    data: dict[str, typing.Any],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:update')),
    ],
) -> dict[str, typing.Any]:
    """Update a team.

    Parameters:
        slug: Team slug from URL.
        data: Updated team data.

    Returns:
        The updated team.

    Raises:
        400: Slug mismatch or validation error
        404: Team not found

    """
    # If no slug in body, default to the URL slug (no rename)
    if 'slug' not in data:
        data['slug'] = slug

    # Remove organization_slug if present (not updatable)
    data.pop('organization_slug', None)

    dynamic_model = await blueprints.get_model(models.Team)

    # Fetch team with its organization relationship
    query: typing.LiteralString = """
    MATCH (t:Team {slug: $slug})-[:BELONGS_TO]->(o:Organization)
    RETURN t{.*, organization: o{.*}} AS team
    """
    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {slug!r} not found',
        )

    existing = records[0]['team']

    try:
        team = dynamic_model(
            organization=existing['organization'],
            **data,
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
    props = team.model_dump(exclude={'organization'})

    update_query: typing.LiteralString = """
    MATCH (t:Team {slug: $slug})-[:BELONGS_TO]->(o:Organization)
    SET t = $props
    RETURN t{.*, organization: o{.*}} AS team
    """
    try:
        async with neo4j.run(
            update_query,
            slug=slug,
            props=props,
        ) as result:
            updated = await result.data()
    except exceptions.ConstraintError as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(f'Team with slug {data["slug"]!r} already exists'),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {slug!r} not found',
        )

    return typing.cast(
        dict[str, typing.Any],
        updated[0]['team'],
    )


@teams_router.delete('/{slug}', status_code=204)
async def delete_team(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:delete')),
    ],
) -> None:
    """Delete a team.

    Parameters:
        slug: Team slug to delete.

    Raises:
        404: Team not found

    """
    deleted = await neo4j.delete_node(
        models.Team,
        {'slug': slug},
    )
    if not deleted:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {slug!r} not found',
        )


@teams_router.get('/{slug}/members')
async def list_team_members(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:read')),
    ],
) -> list[dict[str, typing.Any]]:
    """List members of a team.

    Parameters:
        slug: Team slug identifier.

    Returns:
        List of members with email and display_name.

    Raises:
        404: Team not found

    """
    query: typing.LiteralString = """
    MATCH (t:Team {slug: $slug})
    OPTIONAL MATCH (u:User)-[:MEMBER_OF]->(t)
    RETURN t, collect({
        email: u.email,
        display_name: u.display_name
    }) AS members
    """
    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()

    if not records or not records[0].get('t'):
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {slug!r} not found',
        )
    members = records[0].get('members', [])
    return [m for m in members if m.get('email')]


@teams_router.post('/{slug}/members', status_code=201)
async def add_team_member(
    slug: str,
    data: dict[str, str],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:update')),
    ],
) -> dict[str, str]:
    """Add a user to a team.

    Parameters:
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
    MERGE (u)-[:MEMBER_OF]->(t)
    RETURN u, t
    """
    async with neo4j.run(
        query,
        email=email,
        slug=slug,
    ) as result:
        records = await result.data()

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
    slug: str,
    email: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:update')),
    ],
) -> None:
    """Remove a user from a team.

    Parameters:
        slug: Team slug identifier.
        email: Email of the user to remove.

    Raises:
        404: Membership not found

    """
    query: typing.LiteralString = """
    MATCH (u:User {email: $email})-[m:MEMBER_OF]->(t:Team {slug: $slug})
    DELETE m
    RETURN count(m) AS deleted
    """
    async with neo4j.run(
        query,
        email=email,
        slug=slug,
    ) as result:
        records = await result.data()

    if not records or records[0].get('deleted', 0) == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Membership for {email!r} in team {slug!r} not found'),
        )
