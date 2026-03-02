"""Environment management endpoints."""

import logging
import typing

import fastapi
import pydantic
from imbi_common import blueprints, models, neo4j
from neo4j import exceptions

from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

environments_router = fastapi.APIRouter(
    prefix='/environments',
    tags=['Environments'],
)


@environments_router.post('/', status_code=201)
async def create_environment(
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
        data: Environment data including base fields and
            ``organization_slug``.

    Returns:
        The created environment.

    Raises:
        400: Invalid data or missing organization_slug
        404: Organization not found
        409: Environment with slug already exists

    """
    payload = dict(data)
    org_slug = payload.pop('organization_slug', None)
    if not org_slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='organization_slug is required',
        )
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

    props = environment.model_dump(exclude={'organization'})

    query: typing.LiteralString = """
    MATCH (o:Organization {slug: $org_slug})
    CREATE (e:Environment $props)
    CREATE (e)-[:BELONGS_TO]->(o)
    RETURN e{.*, organization: o{.*}} AS environment
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
            detail=(f'Environment with slug {props["slug"]!r} already exists'),
        ) from e

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Organization with slug {org_slug!r} not found'),
        )

    return typing.cast(
        dict[str, typing.Any],
        records[0]['environment'],
    )


@environments_router.get('/')
async def list_environments(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('environment:read'),
        ),
    ],
) -> list[dict[str, typing.Any]]:
    """List all environments.

    Returns:
        Environments ordered by name, each including their
        organization.

    """
    query: typing.LiteralString = """
    MATCH (e:Environment)-[:BELONGS_TO]->(o:Organization)
    RETURN e{.*, organization: o{.*}} AS environment
    ORDER BY e.name
    """
    environments: list[dict[str, typing.Any]] = []
    async with neo4j.run(query) as result:
        records = await result.data()
        for record in records:
            environments.append(record['environment'])
    return environments


@environments_router.get('/{slug}')
async def get_environment(
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
        slug: Environment slug identifier.

    Returns:
        Environment with organization.

    Raises:
        404: Environment not found

    """
    query: typing.LiteralString = """
    MATCH (e:Environment {slug: $slug})-[:BELONGS_TO]->(o:Organization)
    RETURN e{.*, organization: o{.*}} AS environment
    """
    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Environment with slug {slug!r} not found'),
        )
    return typing.cast(
        dict[str, typing.Any],
        records[0]['environment'],
    )


@environments_router.put('/{slug}')
async def update_environment(
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
    MATCH (e:Environment {slug: $slug})-[:BELONGS_TO]->(o:Organization)
    RETURN e{.*, organization: o{.*}} AS environment
    """
    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()

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

    props = environment.model_dump(exclude={'organization'})

    update_query: typing.LiteralString = """
    MATCH (e:Environment {slug: $slug})-[:BELONGS_TO]->(o:Organization)
    SET e = $props
    RETURN e{.*, organization: o{.*}} AS environment
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
            detail=(
                f'Environment with slug {payload["slug"]!r} already exists'
            ),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Environment with slug {slug!r} not found'),
        )

    return typing.cast(
        dict[str, typing.Any],
        updated[0]['environment'],
    )


@environments_router.delete('/{slug}', status_code=204)
async def delete_environment(
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
        slug: Environment slug to delete.

    Raises:
        404: Environment not found

    """
    deleted = await neo4j.delete_node(
        models.Environment,
        {'slug': slug},
    )
    if not deleted:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Environment with slug {slug!r} not found'),
        )
