"""Team management endpoints."""

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

teams_router = fastapi.APIRouter(tags=['Teams'])


@teams_router.post('/', status_code=201)
async def create_team(
    org_slug: str,
    data: dict[str, typing.Any],
    db: graph.Pool,
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
    dynamic_model = await blueprints.get_model(db, models.Team)

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
        mode='json',
        exclude={'organization'},
    )

    create_tpl = props_template(props)
    query = (
        f'MATCH (o:Organization {{{{slug: {{org_slug}}}}}})'
        f' CREATE (t:Team {create_tpl})'
        f' CREATE (t)-[:BELONGS_TO]->(o)'
        f' RETURN t, o'
    )
    params = {**props, 'org_slug': org_slug}
    try:
        records = await db.execute(
            query,
            params,
            columns=['t', 'o'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(f'Team with slug {props["slug"]!r} already exists'),
        ) from e

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Organization with slug {org_slug!r} not found'),
        )

    team_props: dict[str, typing.Any] = graph.parse_agtype(records[0]['t'])
    org_props = graph.parse_agtype(records[0]['o'])
    team_props['organization'] = org_props
    slug = team_props['slug']
    team_props['relationships'] = build_relationships(
        '',
        {
            'projects': (f'/api/projects?team={slug}', 0),
            'members': (
                f'/api/organizations/{org_slug}/teams/{slug}/members',
                0,
            ),
        },
    )
    return team_props


@teams_router.get('/')
async def list_teams(
    org_slug: str,
    db: graph.Pool,
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
    query = """
    MATCH (t:Team)-[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(t)
    OPTIONAL MATCH (u:User)-[:MEMBER_OF]->(t)
    WITH t, o, count(DISTINCT p) AS project_count,
                count(DISTINCT u) AS member_count
    RETURN t, o, project_count, member_count
    ORDER BY t.name
    """
    teams: list[dict[str, typing.Any]] = []
    records = await db.execute(
        query,
        {'org_slug': org_slug},
        columns=['t', 'o', 'project_count', 'member_count'],
    )
    for record in records:
        team = graph.parse_agtype(record['t'])
        org = graph.parse_agtype(record['o'])
        team['organization'] = org
        pc = graph.parse_agtype(record['project_count'])
        mc = graph.parse_agtype(record['member_count'])
        slug = team['slug']
        team['relationships'] = build_relationships(
            '',
            {
                'projects': (f'/api/projects?team={slug}', pc or 0),
                'members': (
                    f'/api/organizations/{org_slug}/teams/{slug}/members',
                    mc or 0,
                ),
            },
        )
        teams.append(team)
    return teams


@teams_router.get('/{slug}')
async def get_team(
    org_slug: str,
    slug: str,
    db: graph.Pool,
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
    query = """
    MATCH (t:Team {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(t)
    OPTIONAL MATCH (u:User)-[:MEMBER_OF]->(t)
    WITH t, o, count(DISTINCT p) AS project_count,
                count(DISTINCT u) AS member_count
    RETURN t, o, project_count, member_count
    """
    records = await db.execute(
        query,
        {'slug': slug, 'org_slug': org_slug},
        columns=['t', 'o', 'project_count', 'member_count'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {slug!r} not found',
        )

    team: dict[str, typing.Any] = graph.parse_agtype(records[0]['t'])
    org = graph.parse_agtype(records[0]['o'])
    team['organization'] = org
    pc = graph.parse_agtype(records[0]['project_count'])
    mc = graph.parse_agtype(records[0]['member_count'])
    team['relationships'] = build_relationships(
        '',
        {
            'projects': (f'/api/projects?team={slug}', pc or 0),
            'members': (
                f'/api/organizations/{org_slug}/teams/{slug}/members',
                mc or 0,
            ),
        },
    )
    return team


async def _persist_team(
    original_slug: str,
    org_slug: str,
    team_model: type,
    existing_org: dict[str, typing.Any],
    payload: dict[str, typing.Any],
    existing_created_at: str | None,
    db: graph.Pool,
) -> dict[str, typing.Any]:
    """Validate, stamp timestamps, and persist a team to the graph.

    Parameters:
        original_slug: Current slug to match on in Cypher.
        org_slug: Organization slug for the BELONGS_TO edge.
        team_model: Dynamic Pydantic model (from blueprints.get_model).
        existing_org: Parsed org dict from the graph (for organization
            field).
        payload: New field values (slug, name, description, etc.).
        existing_created_at: ISO string from existing node or None.
        db: Graph database connection.

    Returns:
        Updated team dict with organization and relationships.

    Raises:
        HTTPException 400: Validation error.
        HTTPException 404: Team not found.
        HTTPException 409: Slug conflict.

    """
    try:
        team = team_model(
            organization=existing_org,
            **payload,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning('Validation error persisting team: %s', e)
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    team.created_at = (
        datetime.datetime.fromisoformat(existing_created_at)
        if existing_created_at
        else datetime.datetime.now(datetime.UTC)
    )
    team.updated_at = datetime.datetime.now(datetime.UTC)
    props = team.model_dump(mode='json', exclude={'organization'})

    set_stmt = set_clause('t', props)
    update_query = (
        f'MATCH (t:Team {{{{slug: {{slug}}}}}})'
        f' -[:BELONGS_TO]->(o:Organization {{{{slug: {{org_slug}}}}}})'
        f' {set_stmt}'
        f' WITH t, o'
        f' OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(t)'
        f' OPTIONAL MATCH (u:User)-[:MEMBER_OF]->(t)'
        f' WITH t, o, count(DISTINCT p) AS project_count,'
        f' count(DISTINCT u) AS member_count'
        f' RETURN t, o, project_count, member_count'
    )
    params = {**props, 'slug': original_slug, 'org_slug': org_slug}
    try:
        updated = await db.execute(
            update_query,
            params,
            columns=['t', 'o', 'project_count', 'member_count'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Team with slug'
                f' {payload.get("slug", original_slug)!r}'
                f' already exists'
            ),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {original_slug!r} not found',
        )

    team_data: dict[str, typing.Any] = graph.parse_agtype(updated[0]['t'])
    org_data = graph.parse_agtype(updated[0]['o'])
    team_data['organization'] = org_data
    pc = graph.parse_agtype(updated[0]['project_count'])
    mc = graph.parse_agtype(updated[0]['member_count'])
    slug = team_data['slug']
    team_data['relationships'] = build_relationships(
        '',
        {
            'projects': (f'/api/projects?team={slug}', pc or 0),
            'members': (
                f'/api/organizations/{org_slug}/teams/{slug}/members',
                mc or 0,
            ),
        },
    )
    return team_data


@teams_router.put('/{slug}')
async def update_team(
    org_slug: str,
    slug: str,
    data: dict[str, typing.Any],
    db: graph.Pool,
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

    dynamic_model = await blueprints.get_model(db, models.Team)

    # Fetch team with its organization relationship
    fetch_query = """
    MATCH (t:Team {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN t, o
    """
    records = await db.execute(
        fetch_query,
        {'slug': slug, 'org_slug': org_slug},
        columns=['t', 'o'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {slug!r} not found',
        )

    existing = graph.parse_agtype(records[0]['t'])
    existing_org = graph.parse_agtype(records[0]['o'])

    return await _persist_team(
        slug,
        org_slug,
        dynamic_model,
        existing_org,
        payload,
        existing.get('created_at'),
        db,
    )


@teams_router.patch('/{slug}')
async def patch_team(
    org_slug: str,
    slug: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('team:update')),
    ],
) -> dict[str, typing.Any]:
    """Partially update a team using JSON Patch (RFC 6902).

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Team slug from URL.
        operations: JSON Patch operations.

    Returns:
        The updated team.

    Raises:
        400: Invalid patch, read-only path, or validation error.
        404: Team not found.
        409: Slug conflict.
        422: Patch test operation failed.

    """
    dynamic_model = await blueprints.get_model(db, models.Team)

    fetch_query = """
    MATCH (t:Team {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN t, o
    """
    records = await db.execute(
        fetch_query,
        {'slug': slug, 'org_slug': org_slug},
        columns=['t', 'o'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {slug!r} not found',
        )
    existing = graph.parse_agtype(records[0]['t'])
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

    return await _persist_team(
        slug,
        org_slug,
        dynamic_model,
        existing_org,
        patched,
        existing.get('created_at'),
        db,
    )


@teams_router.delete('/{slug}', status_code=204)
async def delete_team(
    org_slug: str,
    slug: str,
    db: graph.Pool,
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
    query = """
    MATCH (t:Team {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    DETACH DELETE t
    RETURN t
    """
    records = await db.execute(
        query,
        {'slug': slug, 'org_slug': org_slug},
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {slug!r} not found',
        )


@teams_router.get('/{slug}/members')
async def list_team_members(
    org_slug: str,
    slug: str,
    db: graph.Pool,
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
    # First verify the team exists
    team_check = """
    MATCH (t:Team {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN t
    """
    team_records = await db.execute(
        team_check,
        {'slug': slug, 'org_slug': org_slug},
    )
    if not team_records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Team with slug {slug!r} not found',
        )

    # Then fetch members
    member_query = """
    MATCH (u:User)-[:MEMBER_OF]->(t:Team {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN u.email, u.display_name, u.is_active, u.is_admin
    ORDER BY u.email
    """
    records = await db.execute(
        member_query,
        {'slug': slug, 'org_slug': org_slug},
        columns=['email', 'display_name', 'is_active', 'is_admin'],
    )
    members: list[dict[str, typing.Any]] = []
    for record in records:
        email = graph.parse_agtype(record['email'])
        if email:
            members.append(
                {
                    'email': email,
                    'display_name': graph.parse_agtype(
                        record['display_name'],
                    ),
                    'is_active': graph.parse_agtype(
                        record.get('is_active', False),
                    ),
                    'is_admin': graph.parse_agtype(
                        record.get('is_admin', False),
                    ),
                }
            )
    return members


@teams_router.post('/{slug}/members', status_code=201)
async def add_team_member(
    org_slug: str,
    slug: str,
    data: dict[str, str],
    db: graph.Pool,
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

    query = """
    MATCH (u:User {{email: {email}}}),
          (t:Team {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    MERGE (u)-[:MEMBER_OF]->(t)
    RETURN u, t
    """
    records = await db.execute(
        query,
        {'email': email, 'slug': slug, 'org_slug': org_slug},
        columns=['u', 't'],
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
    db: graph.Pool,
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
    query = """
    MATCH (u:User {{email: {email}}})-[m:MEMBER_OF]->
          (t:Team {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    DELETE m
    RETURN m
    """
    records = await db.execute(
        query,
        {'email': email, 'slug': slug, 'org_slug': org_slug},
        columns=['m'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Membership for {email!r} in team {slug!r} not found'),
        )
