"""Environment management endpoints."""

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

environments_router = fastapi.APIRouter(tags=['Environments'])


def _add_relationships(
    env: dict[str, typing.Any],
    project_count: int = 0,
) -> dict[str, typing.Any]:
    """Attach relationships sub-object to an environment dict."""
    env['relationships'] = {
        'projects': relationship_link(
            f'/api/projects?environment={env["slug"]}',
            project_count,
        ),
    }
    return env


@environments_router.post('/', status_code=201)
async def create_environment(
    org_slug: str,
    data: dict[str, typing.Any],
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

    dynamic_model = await blueprints.get_model(models.Environment)

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
    props = environment.model_dump(exclude={'organization'})

    query: typing.LiteralString = """
    MATCH (o:Organization {slug: $org_slug})
    CREATE (e:Environment $props)
    CREATE (e)-[:BELONGS_TO]->(o)
    RETURN e{.*, organization: o{.*}} AS environment
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
            detail=(f'Environment with slug {props["slug"]!r} already exists'),
        ) from e

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Organization with slug {org_slug!r} not found'),
        )

    return _add_relationships(records[0]['environment'])


@environments_router.get('/')
async def list_environments(
    org_slug: str,
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
        Environments ordered by name, each including their
        organization and relationships.

    """
    query: typing.LiteralString = """
    MATCH (e:Environment)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    OPTIONAL MATCH (p:Project)-[:DEPLOYED_IN]->(e)
    WITH e, o, count(DISTINCT p) AS project_count
    RETURN e{.*, organization: o{.*}} AS environment,
           project_count
    ORDER BY e.name
    """
    environments: list[dict[str, typing.Any]] = []
    records = await neo4j.query(query, org_slug=org_slug)
    for record in records:
        env = record['environment']
        _add_relationships(env, record['project_count'])
        environments.append(env)
    return environments


@environments_router.get('/{slug}')
async def get_environment(
    org_slug: str,
    slug: str,
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
    query: typing.LiteralString = """
    MATCH (e:Environment {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    OPTIONAL MATCH (p:Project)-[:DEPLOYED_IN]->(e)
    WITH e, o, count(DISTINCT p) AS project_count
    RETURN e{.*, organization: o{.*}} AS environment,
           project_count
    """
    records = await neo4j.query(
        query,
        slug=slug,
        org_slug=org_slug,
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Environment with slug {slug!r} not found'),
        )
    return _add_relationships(
        records[0]['environment'],
        records[0]['project_count'],
    )


@environments_router.put('/{slug}')
async def update_environment(
    org_slug: str,
    slug: str,
    data: dict[str, typing.Any],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('environment:update'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Update an environment.

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Environment slug from URL.
        data: Updated environment data.

    Returns:
        The updated environment.

    Raises:
        400: Validation error
        404: Environment not found

    """
    payload = dict(data)
    if 'slug' not in payload:
        payload['slug'] = slug

    payload.pop('organization_slug', None)
    payload.pop('organization', None)

    dynamic_model = await blueprints.get_model(models.Environment)

    query: typing.LiteralString = """
    MATCH (e:Environment {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    RETURN e{.*, organization: o{.*}} AS environment
    """
    records = await neo4j.query(
        query,
        slug=slug,
        org_slug=org_slug,
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Environment with slug {slug!r} not found'),
        )

    existing = records[0]['environment']

    try:
        environment = dynamic_model(
            organization=existing['organization'],
            **payload,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning(
            'Validation error updating environment: %s',
            e,
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    environment.created_at = existing.get('created_at')
    environment.updated_at = datetime.datetime.now(datetime.UTC)
    props = environment.model_dump(exclude={'organization'})

    update_query: typing.LiteralString = """
    MATCH (e:Environment {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    SET e = $props
    WITH e, o
    OPTIONAL MATCH (p:Project)-[:DEPLOYED_IN]->(e)
    WITH e, o, count(DISTINCT p) AS project_count
    RETURN e{.*, organization: o{.*}} AS environment,
           project_count
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
                f'Environment with slug {payload["slug"]!r} already exists'
            ),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Environment with slug {slug!r} not found'),
        )

    return _add_relationships(
        updated[0]['environment'],
        updated[0]['project_count'],
    )


@environments_router.delete('/{slug}', status_code=204)
async def delete_environment(
    org_slug: str,
    slug: str,
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
    query: typing.LiteralString = """
    MATCH (e:Environment {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    DETACH DELETE e
    RETURN count(e) AS deleted
    """
    records = await neo4j.query(
        query,
        slug=slug,
        org_slug=org_slug,
    )

    if not records or records[0].get('deleted', 0) == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Environment with slug {slug!r} not found'),
        )
