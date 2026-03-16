"""Project type management endpoints."""

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

project_types_router = fastapi.APIRouter(tags=['Project Types'])


def _add_relationships(
    pt: dict[str, typing.Any],
    project_count: int = 0,
) -> dict[str, typing.Any]:
    """Attach relationships sub-object to a project type dict."""
    pt['relationships'] = {
        'projects': relationship_link(
            f'/api/projects?project-type={pt["slug"]}',
            project_count,
        ),
    }
    return pt


@project_types_router.post('/', status_code=201)
async def create_project_type(
    org_slug: str,
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
        org_slug: Organization slug from URL path.
        data: Project type data including base fields.

    Returns:
        The created project type.

    Raises:
        400: Invalid data
        404: Organization not found
        409: Project type with slug already exists

    """
    payload = dict(data)
    payload.pop('organization_slug', None)
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

    now = datetime.datetime.now(datetime.UTC)
    project_type.created_at = now
    project_type.updated_at = now
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
        records = await neo4j.query(
            query,
            org_slug=org_slug,
            props=props,
        )
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

    return _add_relationships(records[0]['project_type'])


@project_types_router.get('/')
async def list_project_types(
    org_slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project_type:read'),
        ),
    ],
) -> list[dict[str, typing.Any]]:
    """List all project types in an organization.

    Parameters:
        org_slug: Organization slug from URL path.

    Returns:
        Project types ordered by name, each including their
        organization and relationships.

    """
    query: typing.LiteralString = """
    MATCH (pt:ProjectType)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    OPTIONAL MATCH (p:Project)-[:TYPE]->(pt)
    WITH pt, o, count(DISTINCT p) AS project_count
    RETURN pt{.*, organization: o{.*}} AS project_type,
           project_count
    ORDER BY pt.name
    """
    project_types: list[dict[str, typing.Any]] = []
    records = await neo4j.query(query, org_slug=org_slug)
    for record in records:
        pt = record['project_type']
        _add_relationships(pt, record['project_count'])
        project_types.append(pt)
    return project_types


@project_types_router.get('/{slug}')
async def get_project_type(
    org_slug: str,
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
        org_slug: Organization slug from URL path.
        slug: Project type slug identifier.

    Returns:
        Project type with organization and relationships.

    Raises:
        404: Project type not found

    """
    query: typing.LiteralString = """
    MATCH (pt:ProjectType {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    OPTIONAL MATCH (p:Project)-[:TYPE]->(pt)
    WITH pt, o, count(DISTINCT p) AS project_count
    RETURN pt{.*, organization: o{.*}} AS project_type,
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
            detail=(f'Project type with slug {slug!r} not found'),
        )
    return _add_relationships(
        records[0]['project_type'],
        records[0]['project_count'],
    )


@project_types_router.put('/{slug}')
async def update_project_type(
    org_slug: str,
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
        org_slug: Organization slug from URL path.
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
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    RETURN pt{.*, organization: o{.*}} AS project_type
    """
    records = await neo4j.query(
        query,
        slug=slug,
        org_slug=org_slug,
    )

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

    project_type.created_at = existing.get('created_at')
    project_type.updated_at = datetime.datetime.now(datetime.UTC)
    props = project_type.model_dump(
        exclude={'organization'},
    )

    update_query: typing.LiteralString = """
    MATCH (pt:ProjectType {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    SET pt = $props
    WITH pt, o
    OPTIONAL MATCH (p:Project)-[:TYPE]->(pt)
    WITH pt, o, count(DISTINCT p) AS project_count
    RETURN pt{.*, organization: o{.*}} AS project_type,
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
                f'Project type with slug {payload["slug"]!r} already exists'
            ),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Project type with slug {slug!r} not found'),
        )

    return _add_relationships(
        updated[0]['project_type'],
        updated[0]['project_count'],
    )


@project_types_router.delete('/{slug}', status_code=204)
async def delete_project_type(
    org_slug: str,
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
        org_slug: Organization slug from URL path.
        slug: Project type slug to delete.

    Raises:
        404: Project type not found

    """
    query: typing.LiteralString = """
    MATCH (pt:ProjectType {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    DETACH DELETE pt
    RETURN count(pt) AS deleted
    """
    records = await neo4j.query(
        query,
        slug=slug,
        org_slug=org_slug,
    )

    if not records or records[0].get('deleted', 0) == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Project type with slug {slug!r} not found'),
        )
