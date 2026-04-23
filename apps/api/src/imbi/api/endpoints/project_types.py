"""Project type management endpoints."""

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

project_types_router = fastapi.APIRouter(tags=['Project Types'])


@project_types_router.post('/', status_code=201)
async def create_project_type(
    org_slug: str,
    data: dict[str, typing.Any],
    db: graph.Pool,
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
        db,
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
        mode='json',
        exclude={'organization'},
    )

    create_tpl = props_template(props)
    query = (
        f'MATCH (o:Organization {{{{slug: {{org_slug}}}}}})'
        f' CREATE (pt:ProjectType {create_tpl})'
        f' CREATE (pt)-[:BELONGS_TO]->(o)'
        f' RETURN pt, o'
    )
    params = {**props, 'org_slug': org_slug}
    try:
        records = await db.execute(
            query,
            params,
            columns=['pt', 'o'],
        )
    except psycopg.errors.UniqueViolation as e:
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

    pt_props: dict[str, typing.Any] = graph.parse_agtype(records[0]['pt'])
    org_props = graph.parse_agtype(records[0]['o'])
    pt_props['organization'] = org_props
    pt_props['relationships'] = build_relationships(
        '',
        {
            'projects': (
                f'/api/projects?project-type={pt_props["slug"]}',
                0,
            ),
        },
    )
    return pt_props


@project_types_router.get('/')
async def list_project_types(
    org_slug: str,
    db: graph.Pool,
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
    query = """
    MATCH (pt:ProjectType)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (p:Project)-[:TYPE]->(pt)
    WITH pt, o, count(DISTINCT p) AS project_count
    RETURN pt, o, project_count
    ORDER BY pt.name
    """
    project_types: list[dict[str, typing.Any]] = []
    records = await db.execute(
        query,
        {'org_slug': org_slug},
        columns=['pt', 'o', 'project_count'],
    )
    for record in records:
        pt = graph.parse_agtype(record['pt'])
        org = graph.parse_agtype(record['o'])
        pt['organization'] = org
        pc = graph.parse_agtype(record['project_count'])
        pt['relationships'] = build_relationships(
            '',
            {
                'projects': (
                    f'/api/projects?project-type={pt["slug"]}',
                    pc or 0,
                ),
            },
        )
        project_types.append(pt)
    return project_types


@project_types_router.get('/{slug}')
async def get_project_type(
    org_slug: str,
    slug: str,
    db: graph.Pool,
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
    query = """
    MATCH (pt:ProjectType {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (p:Project)-[:TYPE]->(pt)
    WITH pt, o, count(DISTINCT p) AS project_count
    RETURN pt, o, project_count
    """
    records = await db.execute(
        query,
        {'slug': slug, 'org_slug': org_slug},
        columns=['pt', 'o', 'project_count'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Project type with slug {slug!r} not found'),
        )

    pt: dict[str, typing.Any] = graph.parse_agtype(records[0]['pt'])
    org = graph.parse_agtype(records[0]['o'])
    pt['organization'] = org
    pc = graph.parse_agtype(records[0]['project_count'])
    pt['relationships'] = build_relationships(
        '',
        {
            'projects': (
                f'/api/projects?project-type={pt["slug"]}',
                pc or 0,
            ),
        },
    )
    return pt


async def _persist_project_type(
    original_slug: str,
    org_slug: str,
    pt_model: type,
    existing_org: dict[str, typing.Any],
    payload: dict[str, typing.Any],
    existing_created_at: str | None,
    db: graph.Pool,
) -> dict[str, typing.Any]:
    """Validate, stamp timestamps, and persist a project type to the graph.

    Parameters:
        original_slug: Current slug to match on in Cypher.
        org_slug: Organization slug for the BELONGS_TO edge.
        pt_model: Dynamic Pydantic model (from blueprints.get_model).
        existing_org: Parsed org dict from the graph (for organization
            field).
        payload: New field values (slug, name, description, etc.).
        existing_created_at: ISO string from existing node or None.
        db: Graph database connection.

    Returns:
        Updated project type dict with organization and relationships.

    Raises:
        HTTPException 400: Validation error.
        HTTPException 404: Project type not found.
        HTTPException 409: Slug conflict.

    """
    try:
        project_type = pt_model(
            organization=existing_org,
            **payload,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning(
            'Validation error persisting project type: %s',
            e,
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    project_type.created_at = (
        datetime.datetime.fromisoformat(existing_created_at)
        if existing_created_at
        else datetime.datetime.now(datetime.UTC)
    )
    project_type.updated_at = datetime.datetime.now(datetime.UTC)
    props = project_type.model_dump(
        mode='json',
        exclude={'organization'},
    )

    set_stmt = set_clause('pt', props)
    update_query = (
        f'MATCH (pt:ProjectType {{{{slug: {{slug}}}}}})'
        f' -[:BELONGS_TO]->(o:Organization'
        f' {{{{slug: {{org_slug}}}}}})'
        f' {set_stmt}'
        f' WITH pt, o'
        f' OPTIONAL MATCH (p:Project)-[:TYPE]->(pt)'
        f' WITH pt, o, count(DISTINCT p) AS project_count'
        f' RETURN pt, o, project_count'
    )
    params = {**props, 'slug': original_slug, 'org_slug': org_slug}
    try:
        updated = await db.execute(
            update_query,
            params,
            columns=['pt', 'o', 'project_count'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Project type with slug'
                f' {payload.get("slug", original_slug)!r}'
                f' already exists'
            ),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Project type with slug {original_slug!r} not found'),
        )

    pt: dict[str, typing.Any] = graph.parse_agtype(updated[0]['pt'])
    org = graph.parse_agtype(updated[0]['o'])
    pt['organization'] = org
    pc = graph.parse_agtype(updated[0]['project_count'])
    pt['relationships'] = build_relationships(
        '',
        {
            'projects': (
                f'/api/projects?project-type={pt["slug"]}',
                pc or 0,
            ),
        },
    )
    return pt


@project_types_router.patch('/{slug}')
async def patch_project_type(
    org_slug: str,
    slug: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project_type:update'),
        ),
    ],
) -> dict[str, typing.Any]:
    """Partially update a project type using JSON Patch (RFC 6902).

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Project type slug from URL.
        operations: JSON Patch operations.

    Returns:
        The updated project type.

    Raises:
        400: Invalid patch, read-only path, or validation error.
        404: Project type not found.
        409: Slug conflict.
        422: Patch test operation failed.

    """
    dynamic_model = await blueprints.get_model(
        db,
        models.ProjectType,
    )

    fetch_query = """
    MATCH (pt:ProjectType {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN pt, o
    """
    records = await db.execute(
        fetch_query,
        {'slug': slug, 'org_slug': org_slug},
        columns=['pt', 'o'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Project type with slug {slug!r} not found'),
        )
    existing = graph.parse_agtype(records[0]['pt'])
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

    return await _persist_project_type(
        slug,
        org_slug,
        dynamic_model,
        existing_org,
        patched,
        existing.get('created_at'),
        db,
    )


@project_types_router.delete('/{slug}', status_code=204)
async def delete_project_type(
    org_slug: str,
    slug: str,
    db: graph.Pool,
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
    query = """
    MATCH (pt:ProjectType {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    DETACH DELETE pt
    RETURN pt
    """
    records = await db.execute(
        query,
        {'slug': slug, 'org_slug': org_slug},
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Project type with slug {slug!r} not found'),
        )
