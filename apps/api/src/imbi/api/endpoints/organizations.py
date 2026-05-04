"""Organization management endpoints."""

import datetime
import logging
import typing

import fastapi
import psycopg.errors
import pydantic
from imbi_common import graph, models

from imbi_api import patch as json_patch
from imbi_api.auth import permissions
from imbi_api.relationships import build_relationships

from .environments import environments_router
from .events import events_project_router
from .link_definitions import link_definitions_router
from .note_templates import note_templates_router
from .notes import notes_project_router, notes_router
from .operations_log import operations_log_project_router
from .project_configuration import project_configuration_router
from .project_logs import project_logs_router
from .project_plugins import project_plugins_router
from .project_type_plugins import project_type_plugins_router
from .project_types import project_types_router
from .projects import projects_router
from .releases import releases_router
from .service_plugins import service_plugins_router
from .tags import tags_router
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
    events_project_router,
    prefix='/{org_slug}/projects/{project_id}/events',
)
organizations_router.include_router(
    operations_log_project_router,
    prefix='/{org_slug}/projects/{project_id}/operations-log',
)
organizations_router.include_router(
    releases_router,
    prefix='/{org_slug}/projects/{project_id}/releases',
)
organizations_router.include_router(
    project_services_router,
    prefix='/{org_slug}/projects/{project_id}/services',
)
organizations_router.include_router(
    tags_router,
    prefix='/{org_slug}/tags',
)
organizations_router.include_router(
    notes_router,
    prefix='/{org_slug}/notes',
)
organizations_router.include_router(
    notes_project_router,
    prefix='/{org_slug}/projects/{project_id}/notes',
)
organizations_router.include_router(
    note_templates_router,
    prefix='/{org_slug}/note-templates',
)
organizations_router.include_router(
    service_plugins_router,
    prefix='/{org_slug}/third-party-services/{slug}/plugins',
)
organizations_router.include_router(
    project_type_plugins_router,
    prefix='/{org_slug}/project-types/{pt_slug}/plugins',
)
organizations_router.include_router(
    project_plugins_router,
    prefix='/{org_slug}/projects/{project_id}/plugins',
)
organizations_router.include_router(
    project_configuration_router,
    prefix='/{org_slug}/projects/{project_id}/configuration',
)
organizations_router.include_router(
    project_logs_router,
    prefix='/{org_slug}/projects/{project_id}/logs',
)


@organizations_router.post('/', status_code=201)
async def create_organization(
    org: models.Organization,
    request: fastapi.Request,
    db: graph.Pool,
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
        created = await db.create(org)
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(f'Organization with slug {org.slug!r} already exists'),
        ) from e
    result = created.model_dump()
    slug = result['slug']
    result['relationships'] = build_relationships(
        request.app.url_path_for('get_organization', slug=slug),
        {
            'teams': ('/teams', 0),
            'members': ('/members', 0),
            'projects': ('/projects', 0),
        },
    )
    return result


@organizations_router.get('/')
async def list_organizations(
    request: fastapi.Request,
    db: graph.Pool,
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
    query: typing.LiteralString = (
        'MATCH (o:Organization)'
        ' OPTIONAL MATCH (t:Team)-[:BELONGS_TO]->(o)'
        ' OPTIONAL MATCH (u:User)-[:MEMBER_OF]->(o)'
        ' WITH o, count(DISTINCT t) AS team_count,'
        '        count(DISTINCT u) AS member_count'
        ' OPTIONAL MATCH (t2:Team)-[:BELONGS_TO]->(o)'
        ' OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(t2)'
        ' WITH o, team_count, member_count,'
        '      count(DISTINCT p) AS project_count'
        ' RETURN o, team_count, member_count, project_count'
        ' ORDER BY o.name'
    )
    organizations: list[dict[str, typing.Any]] = []
    records = await db.execute(
        query,
        columns=['o', 'team_count', 'member_count', 'project_count'],
    )
    for record in records:
        org_data = graph.parse_agtype(record['o'])
        team_count = graph.parse_agtype(record['team_count'])
        member_count = graph.parse_agtype(record['member_count'])
        project_count = graph.parse_agtype(record['project_count'])
        slug = org_data['slug']
        org_data['relationships'] = build_relationships(
            request.app.url_path_for('get_organization', slug=slug),
            {
                'teams': ('/teams', team_count),
                'members': ('/members', member_count),
                'projects': ('/projects', project_count),
            },
        )
        organizations.append(org_data)
    return organizations


@organizations_router.get('/{slug}', name='get_organization')
async def get_organization(
    slug: str,
    request: fastapi.Request,
    db: graph.Pool,
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
    query: typing.LiteralString = (
        'MATCH (o:Organization {{slug: {slug}}})'
        ' OPTIONAL MATCH (t:Team)-[:BELONGS_TO]->(o)'
        ' OPTIONAL MATCH (u:User)-[:MEMBER_OF]->(o)'
        ' WITH o, count(DISTINCT t) AS team_count,'
        '        count(DISTINCT u) AS member_count'
        ' OPTIONAL MATCH (t2:Team)-[:BELONGS_TO]->(o)'
        ' OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(t2)'
        ' WITH o, team_count, member_count,'
        '      count(DISTINCT p) AS project_count'
        ' RETURN o, team_count, member_count, project_count'
    )
    records = await db.execute(
        query,
        {'slug': slug},
        columns=['o', 'team_count', 'member_count', 'project_count'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization with slug {slug!r} not found',
        )
    org_data: dict[str, typing.Any] = graph.parse_agtype(records[0]['o'])
    slug = org_data['slug']
    org_data['relationships'] = build_relationships(
        request.app.url_path_for('get_organization', slug=slug),
        {
            'teams': (
                '/teams',
                graph.parse_agtype(records[0]['team_count']),
            ),
            'members': (
                '/members',
                graph.parse_agtype(records[0]['member_count']),
            ),
            'projects': (
                '/projects',
                graph.parse_agtype(records[0]['project_count']),
            ),
        },
    )
    return org_data


async def _persist_organization(
    original_slug: str,
    org: models.Organization,
    request: fastapi.Request,
    db: graph.Pool,
) -> dict[str, typing.Any]:
    """Execute the Cypher SET + count queries to update an organization.

    Parameters:
        original_slug: The slug that currently identifies the node.
        org: Validated organization model with updated fields.
        db: Graph database connection.

    Returns:
        Organization dict with relationship counts.

    Raises:
        HTTPException 409: Slug rename conflicts with existing org.
        HTTPException 404: Organization vanished between fetch and update.

    """
    update_query: typing.LiteralString = (
        'MATCH (n:Organization {{slug: {original_slug}}})'
        ' SET n.name = {name},'
        ' n.slug = {slug},'
        ' n.description = {description},'
        ' n.icon = {icon},'
        ' n.updated_at = {updated_at}'
        ' RETURN n'
    )
    props = org.model_dump(mode='json')
    params: dict[str, typing.Any] = {
        'original_slug': original_slug,
        'name': props['name'],
        'slug': props['slug'],
        'description': props.get('description'),
        'icon': props.get('icon'),
        'updated_at': props['updated_at'],
    }
    try:
        records = await db.execute(update_query, params)
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Organization with slug {org.slug!r} already exists',
        ) from e
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization with slug {original_slug!r} not found',
        )
    count_query: typing.LiteralString = (
        'MATCH (o:Organization {{slug: {slug}}})'
        ' OPTIONAL MATCH (t:Team)-[:BELONGS_TO]->(o)'
        ' OPTIONAL MATCH (u:User)-[:MEMBER_OF]->(o)'
        ' WITH o, count(DISTINCT t) AS team_count,'
        '        count(DISTINCT u) AS member_count'
        ' OPTIONAL MATCH (t2:Team)-[:BELONGS_TO]->(o)'
        ' OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(t2)'
        ' WITH o, team_count, member_count,'
        '      count(DISTINCT p) AS project_count'
        ' RETURN team_count, member_count, project_count'
    )
    count_records = await db.execute(
        count_query,
        {'slug': org.slug},
        columns=['team_count', 'member_count', 'project_count'],
    )
    counts = count_records[0] if count_records else {}
    org_dict = org.model_dump()
    org_dict['relationships'] = build_relationships(
        request.app.url_path_for('get_organization', slug=org.slug),
        {
            'teams': (
                '/teams',
                graph.parse_agtype(counts.get('team_count', 0)),
            ),
            'members': (
                '/members',
                graph.parse_agtype(counts.get('member_count', 0)),
            ),
            'projects': (
                '/projects',
                graph.parse_agtype(counts.get('project_count', 0)),
            ),
        },
    )
    return org_dict


@organizations_router.patch('/{slug}')
async def patch_organization(
    slug: str,
    operations: list[json_patch.PatchOperation],
    request: fastapi.Request,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('organization:update'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Partially update an organization using JSON Patch (RFC 6902).

    Parameters:
        slug: Organization slug from URL.
        operations: List of JSON Patch operations.

    Returns:
        The updated organization.

    Raises:
        400: Invalid patch, read-only path, or validation error.
        404: Organization not found.
        409: Slug rename conflicts with existing organization.
        422: Patch test operation failed.

    """
    results = await db.match(models.Organization, {'slug': slug})
    existing = results[0] if results else None
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization with slug {slug!r} not found',
        )
    current = existing.model_dump(mode='json')
    current.pop('created_at', None)
    current.pop('updated_at', None)

    patched = json_patch.apply_patch(current, operations)

    try:
        org = models.Organization(**patched)
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    org.created_at = existing.created_at
    org.updated_at = datetime.datetime.now(datetime.UTC)
    return await _persist_organization(slug, org, request, db)


@organizations_router.get('/{slug}/members', name='list_organization_members')
async def list_organization_members(
    slug: str,
    db: graph.Pool,
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
    query: typing.LiteralString = (
        'MATCH (o:Organization {{slug: {slug}}})'
        ' OPTIONAL MATCH (u:User)-[m:MEMBER_OF]->(o)'
        ' RETURN o, collect({{email: u.email,'
        ' display_name: u.display_name,'
        ' role: m.role}}) AS members'
    )
    records = await db.execute(
        query,
        {'slug': slug},
        columns=['o', 'members'],
    )
    if not records or not records[0].get('o'):
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Organization with slug {slug!r} not found'),
        )
    raw_members: typing.Any = graph.parse_agtype(
        records[0].get('members', '[]')
    )
    if isinstance(raw_members, str):
        raw_members = []
    return [m for m in raw_members if m.get('email')]


@organizations_router.delete('/{slug}', status_code=204)
async def delete_organization(
    slug: str,
    db: graph.Pool,
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
    query: typing.LiteralString = (
        'MATCH (n:Organization {{slug: {slug}}}) DETACH DELETE n RETURN n'
    )
    records = await db.execute(query, {'slug': slug})
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Organization with slug {slug!r} not found'),
        )
