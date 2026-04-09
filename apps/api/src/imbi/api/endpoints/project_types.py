"""Project type management endpoints."""

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

project_types_router = fastapi.APIRouter(tags=['Project Types'])


def _escape_prop(name: str) -> str:
    """Escape a Cypher property name with backticks."""
    return '`' + name.replace('`', '``') + '`'


def _props_template(props: dict[str, typing.Any]) -> str:
    """Build a Cypher property-map template with double-escaped braces.

    Each key becomes ```key`: {key}`` inside doubled braces so that
    ``psycopg.sql.SQL.format()`` resolves them correctly::

        >>> _props_template({'name': 'x', 'slug': 'y'})
        '{{`name`: {name}, `slug`: {slug}}}'

    """
    if not props:
        return ''
    pairs = [f'{_escape_prop(k)}: {{{k}}}' for k in props]
    return '{{' + ', '.join(pairs) + '}}'


def _set_clause(
    alias: str,
    props: dict[str, typing.Any],
) -> str:
    """Build a Cypher SET clause from a property dict.

    Returns ``SET pt.`name` = {name}, pt.`slug` = {slug}``.

    """
    if not props:
        return ''
    assignments = ', '.join(
        f'{alias}.{_escape_prop(k)} = {{{k}}}' for k in props
    )
    return f'SET {assignments}'


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
        exclude={'organization'},
    )

    create_tpl = _props_template(props)
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

    pt_props = graph.parse_agtype(records[0]['pt'])
    org_props = graph.parse_agtype(records[0]['o'])
    pt_props['organization'] = org_props
    return _add_relationships(pt_props)


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
        _add_relationships(pt, pc or 0)
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

    pt = graph.parse_agtype(records[0]['pt'])
    org = graph.parse_agtype(records[0]['o'])
    pt['organization'] = org
    pc = graph.parse_agtype(records[0]['project_count'])
    return _add_relationships(pt, pc or 0)


@project_types_router.put('/{slug}')
async def update_project_type(
    org_slug: str,
    slug: str,
    data: dict[str, typing.Any],
    db: graph.Pool,
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
    existing['organization'] = existing_org

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

    set_stmt = _set_clause('pt', props)
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
    params = {**props, 'slug': slug, 'org_slug': org_slug}
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
                f'Project type with slug {payload["slug"]!r} already exists'
            ),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Project type with slug {slug!r} not found'),
        )

    pt = graph.parse_agtype(updated[0]['pt'])
    org = graph.parse_agtype(updated[0]['o'])
    pt['organization'] = org
    pc = graph.parse_agtype(updated[0]['project_count'])
    return _add_relationships(pt, pc or 0)


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
