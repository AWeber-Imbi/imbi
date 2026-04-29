"""Environment management endpoints."""

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
from imbi_api.relationships import relationship_link

LOGGER = logging.getLogger(__name__)

environments_router = fastapi.APIRouter(tags=['Environments'])


def _environment_relationships(
    request: fastapi.Request,
    org_slug: str,
    env_slug: str,
    project_count: int,
) -> dict[str, models.RelationshipLink]:
    projects_url = request.app.url_path_for('list_projects', org_slug=org_slug)
    return {
        'projects': relationship_link(
            f'{projects_url}?environment={env_slug}',
            project_count,
        ),
    }


@environments_router.post('/', status_code=201)
async def create_environment(
    org_slug: str,
    data: dict[str, typing.Any],
    request: fastapi.Request,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('environment:create'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Create a new environment linked to an organization.

    Parameters:
        org_slug: Organization slug from URL path.
        data: Environment data including base fields.

    Returns:
        The created environment.

    Raises:
        400: Invalid data
        404: Organization not found
        409: Environment with slug already exists

    """
    payload = dict(data)
    payload.pop('organization_slug', None)
    payload.pop('organization', None)

    dynamic_model = await blueprints.get_model(
        db,
        models.Environment,
    )

    try:
        environment = dynamic_model(
            organization=models.Organization(
                name='',
                slug=org_slug,
            ),
            **payload,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning(
            'Validation error creating environment: %s',
            e,
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    now = datetime.datetime.now(datetime.UTC)
    environment.created_at = now
    environment.updated_at = now
    props = environment.model_dump(
        mode='json',
        exclude={'organization'},
    )

    create_tpl = props_template(props)
    query = (
        f'MATCH (o:Organization {{{{slug: {{org_slug}}}}}})'
        f' CREATE (e:Environment {create_tpl})'
        f' CREATE (e)-[:BELONGS_TO]->(o)'
        f' RETURN e, o'
    )
    params = {**props, 'org_slug': org_slug}
    try:
        records = await db.execute(
            query,
            params,
            columns=['e', 'o'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(f'Environment with slug {props["slug"]!r} already exists'),
        ) from e

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Organization with slug {org_slug!r} not found'),
        )

    env_props: dict[str, typing.Any] = graph.parse_agtype(records[0]['e'])
    org_props = graph.parse_agtype(records[0]['o'])
    env_props['organization'] = org_props
    env_props['relationships'] = _environment_relationships(
        request, org_slug, env_props['slug'], 0
    )
    return env_props


@environments_router.get('/')
async def list_environments(
    org_slug: str,
    request: fastapi.Request,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('environment:read'),
        ),
    ],
) -> list[dict[str, typing.Any]]:
    """List all environments in an organization.

    Parameters:
        org_slug: Organization slug from URL path.

    Returns:
        Environments ordered by sort_order then name, each including
        their organization and relationships.

    """
    query = """
    MATCH (e:Environment)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (p:Project)-[:DEPLOYED_IN]->(e)
    WITH e, o, count(DISTINCT p) AS project_count
    RETURN e, o, project_count
    ORDER BY coalesce(e.sort_order, 0), e.name
    """
    environments: list[dict[str, typing.Any]] = []
    records = await db.execute(
        query,
        {'org_slug': org_slug},
        columns=['e', 'o', 'project_count'],
    )
    for record in records:
        env = graph.parse_agtype(record['e'])
        org = graph.parse_agtype(record['o'])
        env['organization'] = org
        env.setdefault('sort_order', 0)
        pc = graph.parse_agtype(record['project_count'])
        env['relationships'] = _environment_relationships(
            request, org_slug, env['slug'], pc or 0
        )
        environments.append(env)
    return environments


@environments_router.get('/{slug}')
async def get_environment(
    org_slug: str,
    slug: str,
    request: fastapi.Request,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('environment:read'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Get an environment by slug.

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Environment slug identifier.

    Returns:
        Environment with organization and relationships.

    Raises:
        404: Environment not found

    """
    query = """
    MATCH (e:Environment {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (p:Project)-[:DEPLOYED_IN]->(e)
    WITH e, o, count(DISTINCT p) AS project_count
    RETURN e, o, project_count
    """
    records = await db.execute(
        query,
        {'slug': slug, 'org_slug': org_slug},
        columns=['e', 'o', 'project_count'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Environment with slug {slug!r} not found'),
        )

    env: dict[str, typing.Any] = graph.parse_agtype(records[0]['e'])
    org = graph.parse_agtype(records[0]['o'])
    env['organization'] = org
    env.setdefault('sort_order', 0)
    pc = graph.parse_agtype(records[0]['project_count'])
    env['relationships'] = _environment_relationships(
        request, org_slug, env['slug'], pc or 0
    )
    return env


async def _persist_environment(
    original_slug: str,
    org_slug: str,
    env_model: type,
    existing_org: dict[str, typing.Any],
    payload: dict[str, typing.Any],
    existing_created_at: str | None,
    request: fastapi.Request,
    db: graph.Pool,
) -> dict[str, typing.Any]:
    """Validate, stamp timestamps, and persist an environment to the graph.

    Parameters:
        original_slug: Current slug to match on in Cypher.
        org_slug: Organization slug for the BELONGS_TO edge.
        env_model: Dynamic Pydantic model (from blueprints.get_model).
        existing_org: Parsed org dict from the graph (for organization
            field).
        payload: New field values (slug, name, description, etc.).
        existing_created_at: ISO string from existing node or None.
        db: Graph database connection.

    Returns:
        Updated environment dict with organization and relationships.

    Raises:
        HTTPException 400: Validation error.
        HTTPException 404: Environment not found.
        HTTPException 409: Slug conflict.

    """
    try:
        environment = env_model(
            organization=existing_org,
            **payload,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning(
            'Validation error persisting environment: %s',
            e,
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    environment.created_at = (
        datetime.datetime.fromisoformat(existing_created_at)
        if existing_created_at
        else datetime.datetime.now(datetime.UTC)
    )
    environment.updated_at = datetime.datetime.now(datetime.UTC)
    props = environment.model_dump(
        mode='json',
        exclude={'organization'},
    )

    set_stmt = set_clause('e', props)
    update_query = (
        f'MATCH (e:Environment {{{{slug: {{slug}}}}}})'
        f' -[:BELONGS_TO]->(o:Organization'
        f' {{{{slug: {{org_slug}}}}}})'
        f' {set_stmt}'
        f' WITH e, o'
        f' OPTIONAL MATCH (p:Project)-[:DEPLOYED_IN]->(e)'
        f' WITH e, o, count(DISTINCT p) AS project_count'
        f' RETURN e, o, project_count'
    )
    params = {**props, 'slug': original_slug, 'org_slug': org_slug}
    try:
        updated = await db.execute(
            update_query,
            params,
            columns=['e', 'o', 'project_count'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Environment with slug'
                f' {payload.get("slug", original_slug)!r}'
                f' already exists'
            ),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Environment with slug {original_slug!r} not found'),
        )

    env: dict[str, typing.Any] = graph.parse_agtype(updated[0]['e'])
    org = graph.parse_agtype(updated[0]['o'])
    env['organization'] = org
    env.setdefault('sort_order', 0)
    pc = graph.parse_agtype(updated[0]['project_count'])
    env['relationships'] = _environment_relationships(
        request, org_slug, env['slug'], pc or 0
    )
    return env


@environments_router.patch('/{slug}')
async def patch_environment(
    org_slug: str,
    slug: str,
    operations: list[json_patch.PatchOperation],
    request: fastapi.Request,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('environment:update'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Partially update an environment using JSON Patch (RFC 6902).

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Environment slug from URL.
        operations: JSON Patch operations.

    Returns:
        The updated environment.

    Raises:
        400: Invalid patch, read-only path, or validation error.
        404: Environment not found.
        409: Slug conflict.
        422: Patch test operation failed.

    """
    dynamic_model = await blueprints.get_model(
        db,
        models.Environment,
    )

    fetch_query = """
    MATCH (e:Environment {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN e, o
    """
    records = await db.execute(
        fetch_query,
        {'slug': slug, 'org_slug': org_slug},
        columns=['e', 'o'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Environment with slug {slug!r} not found'),
        )
    existing = graph.parse_agtype(records[0]['e'])
    existing_org = graph.parse_agtype(records[0]['o'])

    current = dict(existing)
    current.pop('created_at', None)
    current.pop('updated_at', None)
    current.pop('organization', None)
    current.setdefault('sort_order', 0)

    patched = json_patch.apply_patch(current, operations)
    patched.pop('organization_slug', None)
    patched.pop('organization', None)
    if 'slug' not in patched:
        patched['slug'] = slug

    return await _persist_environment(
        slug,
        org_slug,
        dynamic_model,
        existing_org,
        patched,
        existing.get('created_at'),
        request,
        db,
    )


@environments_router.delete('/{slug}', status_code=204)
async def delete_environment(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('environment:delete'),
        ),
    ],
) -> None:
    """Delete an environment.

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Environment slug to delete.

    Raises:
        404: Environment not found

    """
    query = """
    MATCH (e:Environment {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    DETACH DELETE e
    RETURN e
    """
    records = await db.execute(
        query,
        {'slug': slug, 'org_slug': org_slug},
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Environment with slug {slug!r} not found'),
        )
