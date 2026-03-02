"""Project type management endpoints."""

import logging
import typing

import fastapi
import pydantic
from imbi_common import blueprints, models, neo4j
from neo4j import exceptions

from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

project_types_router = fastapi.APIRouter(
    prefix='/project-types',
    tags=['Project Types'],
)


@project_types_router.post('/', status_code=201)
async def create_project_type(
    data: dict[str, typing.Any],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project_type:create'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Create a new project type linked to an organization.

    Parameters:
        data: Project type data including base fields and
            ``organization_slug``.

    Returns:
        The created project type.

    Raises:
        400: Invalid data or missing organization_slug
        404: Organization not found
        409: Project type with slug already exists

    """
    payload = dict(data)
    org_slug = payload.pop('organization_slug', None)
    if not org_slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='organization_slug is required',
        )
    payload.pop('organization', None)

    dynamic_model = await blueprints.get_model(
        models.ProjectType,
    )

    try:
        project_type = dynamic_model(
            organization=models.Organization(
                name='',
                slug=org_slug,
            ),
            **payload,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning(
            'Validation error creating project type: %s',
            e,
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    props = project_type.model_dump(
        exclude={'organization'},
    )

    query: typing.LiteralString = """
    MATCH (o:Organization {slug: $org_slug})
    CREATE (pt:ProjectType $props)
    CREATE (pt)-[:BELONGS_TO]->(o)
    RETURN pt{.*, organization: o{.*}} AS project_type
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
            detail=(
                f'Project type with slug {props["slug"]!r} already exists'
            ),
        ) from e

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Organization with slug {org_slug!r} not found'),
        )

    return typing.cast(
        dict[str, typing.Any],
        records[0]['project_type'],
    )


@project_types_router.get('/')
async def list_project_types(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project_type:read'),
        ),
    ],
) -> list[dict[str, typing.Any]]:
    """List all project types.

    Returns:
        Project types ordered by name, each including their
        organization.

    """
    query: typing.LiteralString = """
    MATCH (pt:ProjectType)-[:BELONGS_TO]->(o:Organization)
    RETURN pt{.*, organization: o{.*}} AS project_type
    ORDER BY pt.name
    """
    project_types: list[dict[str, typing.Any]] = []
    async with neo4j.run(query) as result:
        records = await result.data()
        for record in records:
            project_types.append(record['project_type'])
    return project_types


@project_types_router.get('/{slug}')
async def get_project_type(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project_type:read'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Get a project type by slug.

    Parameters:
        slug: Project type slug identifier.

    Returns:
        Project type with organization.

    Raises:
        404: Project type not found

    """
    query: typing.LiteralString = """
    MATCH (pt:ProjectType {slug: $slug})
          -[:BELONGS_TO]->(o:Organization)
    RETURN pt{.*, organization: o{.*}} AS project_type
    """
    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Project type with slug {slug!r} not found'),
        )
    return typing.cast(
        dict[str, typing.Any],
        records[0]['project_type'],
    )


@project_types_router.put('/{slug}')
async def update_project_type(
    slug: str,
    data: dict[str, typing.Any],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project_type:update'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Update a project type.

    Parameters:
        slug: Project type slug from URL.
        data: Updated project type data.

    Returns:
        The updated project type.

    Raises:
        400: Validation error
        404: Project type not found

    """
    payload = dict(data)
    if 'slug' not in payload:
        payload['slug'] = slug

    payload.pop('organization_slug', None)
    payload.pop('organization', None)

    dynamic_model = await blueprints.get_model(
        models.ProjectType,
    )

    query: typing.LiteralString = """
    MATCH (pt:ProjectType {slug: $slug})
          -[:BELONGS_TO]->(o:Organization)
    RETURN pt{.*, organization: o{.*}} AS project_type
    """
    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Project type with slug {slug!r} not found'),
        )

    existing = records[0]['project_type']

    try:
        project_type = dynamic_model(
            organization=existing['organization'],
            **payload,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning(
            'Validation error updating project type: %s',
            e,
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    props = project_type.model_dump(
        exclude={'organization'},
    )

    update_query: typing.LiteralString = """
    MATCH (pt:ProjectType {slug: $slug})
          -[:BELONGS_TO]->(o:Organization)
    SET pt = $props
    RETURN pt{.*, organization: o{.*}} AS project_type
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
                f'Project type with slug {payload["slug"]!r} already exists'
            ),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Project type with slug {slug!r} not found'),
        )

    return typing.cast(
        dict[str, typing.Any],
        updated[0]['project_type'],
    )


@project_types_router.delete('/{slug}', status_code=204)
async def delete_project_type(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'project_type:delete',
            ),
        ),
    ],
) -> None:
    """Delete a project type.

    Parameters:
        slug: Project type slug to delete.

    Raises:
        404: Project type not found

    """
    deleted = await neo4j.delete_node(
        models.ProjectType,
        {'slug': slug},
    )
    if not deleted:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Project type with slug {slug!r} not found'),
        )
