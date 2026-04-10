"""Environment management endpoints."""

import datetime
import logging
import typing

import fastapi
import psycopg.errors
import pydantic
from imbi_common import blueprints, graph, models

from imbi_api.auth import permissions
from imbi_api.relationships import relationship_link

LOGGER = logging.getLogger(__name__)

environments_router = fastapi.APIRouter(tags=['Environments'])


def _props_template(props: dict[str, typing.Any]) -> str:
    """Build a Cypher property-map template with double-escaped braces.

    Each key becomes ``key: {key}`` inside doubled braces so that
    ``psycopg.sql.SQL.format()`` resolves them correctly::

        >>> _props_template({'name': 'x', 'slug': 'y'})
        '{{name: {name}, slug: {slug}}}'

    """
    if not props:
        return ''
    pairs = [f'{k}: {{{k}}}' for k in props]
    return '{{' + ', '.join(pairs) + '}}'


def _set_clause(
    alias: str,
    props: dict[str, typing.Any],
) -> str:
    """Build a Cypher SET clause from a property dict.

    Returns a string like ``SET e.name = {name}, e.slug = {slug}``.

    """
    if not props:
        return ''
    assignments = ', '.join(f'{alias}.{k} = {{{k}}}' for k in props)
    return f'SET {assignments}'


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

    create_tpl = _props_template(props)
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

    env_props = graph.parse_agtype(records[0]['e'])
    org_props = graph.parse_agtype(records[0]['o'])
    env_props['organization'] = org_props
    return _add_relationships(env_props)


@environments_router.get('/')
async def list_environments(
    org_slug: str,
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
        _add_relationships(env, pc or 0)
        environments.append(env)
    return environments


@environments_router.get('/{slug}')
async def get_environment(
    org_slug: str,
    slug: str,
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

    env = graph.parse_agtype(records[0]['e'])
    org = graph.parse_agtype(records[0]['o'])
    env['organization'] = org
    env.setdefault('sort_order', 0)
    pc = graph.parse_agtype(records[0]['project_count'])
    return _add_relationships(env, pc or 0)


@environments_router.put('/{slug}')
async def update_environment(
    org_slug: str,
    slug: str,
    data: dict[str, typing.Any],
    db: graph.Pool,
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
    existing['organization'] = existing_org

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

    raw_created = existing.get('created_at')
    environment.created_at = (
        datetime.datetime.fromisoformat(raw_created)
        if raw_created
        else datetime.datetime.now(datetime.UTC)
    )
    environment.updated_at = datetime.datetime.now(datetime.UTC)
    props = environment.model_dump(
        mode='json',
        exclude={'organization'},
    )

    set_stmt = _set_clause('e', props)
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
    params = {**props, 'slug': slug, 'org_slug': org_slug}
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
                f'Environment with slug {payload["slug"]!r} already exists'
            ),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Environment with slug {slug!r} not found'),
        )

    env = graph.parse_agtype(updated[0]['e'])
    org = graph.parse_agtype(updated[0]['o'])
    env['organization'] = org
    env.setdefault('sort_order', 0)
    pc = graph.parse_agtype(updated[0]['project_count'])
    return _add_relationships(env, pc or 0)


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
