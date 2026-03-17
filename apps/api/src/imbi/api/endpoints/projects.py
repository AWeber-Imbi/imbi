"""Project management endpoints."""

import datetime
import json
import logging
import typing

import fastapi
import pydantic
from imbi_common import blueprints, models, neo4j
from neo4j import exceptions

from imbi_api.auth import permissions
from imbi_api.relationships import relationship_link

LOGGER = logging.getLogger(__name__)

projects_router = fastapi.APIRouter(tags=['Projects'])


# -- Request / Response models ------------------------------------------


class OrganizationRef(pydantic.BaseModel):
    name: str
    slug: str


class TeamRef(pydantic.BaseModel):
    name: str
    slug: str
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    organization: OrganizationRef


class ProjectTypeRef(pydantic.BaseModel):
    name: str
    slug: str
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    organization: OrganizationRef


class EnvironmentRef(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='ignore')

    name: str
    slug: str
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    label_color: str | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    organization: OrganizationRef | None = None


class ProjectCreate(pydantic.BaseModel):
    """Request body for creating a project."""

    name: str
    slug: str
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    team_slug: str
    project_type_slug: str
    environment_slugs: list[str] = []
    links: dict[str, pydantic.HttpUrl] = {}
    identifiers: dict[str, int | str] = {}


class ProjectUpdate(pydantic.BaseModel):
    """Request body for updating a project."""

    name: str | None = None
    slug: str | None = None
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    team_slug: str | None = None
    project_type_slug: str | None = None
    environment_slugs: list[str] | None = None
    links: dict[str, pydantic.HttpUrl] | None = None
    identifiers: dict[str, int | str] | None = None


class ProjectResponse(pydantic.BaseModel):
    """Response body for a project."""

    model_config = pydantic.ConfigDict(extra='allow')

    name: str
    slug: str
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    team: TeamRef
    project_type: ProjectTypeRef
    environments: list[EnvironmentRef] = []
    links: dict[str, pydantic.HttpUrl] = {}
    identifiers: dict[str, int | str] = {}
    relationships: dict[str, models.RelationshipLink] | None = None

    @pydantic.field_validator(
        'links',
        'identifiers',
        mode='before',
    )
    @classmethod
    def _parse_json_strings(
        cls,
        value: typing.Any,
    ) -> typing.Any:
        """Neo4j stores dicts as JSON strings."""
        if isinstance(value, str):
            return json.loads(value)
        return value


# -- Helpers ------------------------------------------------------------


def _add_relationships(
    project: dict[str, typing.Any],
    org_slug: str,
    dependency_count: int = 0,
) -> dict[str, typing.Any]:
    """Attach relationships sub-object to a project dict."""
    slug = project['slug']
    team = project.get('team', {})
    team_slug = team.get('slug', '') if team else ''
    project['relationships'] = {
        'team': relationship_link(
            f'/api/organizations/{org_slug}/teams/{team_slug}',
            1 if team_slug else 0,
        ),
        'environments': relationship_link(
            f'/api/organizations/{org_slug}/projects/{slug}/environments',
            len(project.get('environments') or []),
        ),
        'dependencies': relationship_link(
            f'/api/organizations/{org_slug}/projects/{slug}/dependencies',
            dependency_count,
        ),
    }
    return project


# -- Endpoints ----------------------------------------------------------


@projects_router.post('/', status_code=201)
async def create_project(
    org_slug: str,
    data: ProjectCreate,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:create'),
        ),
    ],
) -> ProjectResponse:
    """Create a new project in an organization."""
    dynamic_model = await blueprints.get_model(models.Project)

    try:
        project = dynamic_model(
            team=models.Team(
                name='',
                slug=data.team_slug,
                organization=models.Organization(
                    name='',
                    slug=org_slug,
                ),
            ),
            project_type=models.ProjectType(
                name='',
                slug=data.project_type_slug,
                organization=models.Organization(
                    name='',
                    slug=org_slug,
                ),
            ),
            environments=[],
            name=data.name,
            slug=data.slug,
            description=data.description,
            icon=data.icon,
            links=data.links,
            identifiers=data.identifiers,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning(
            'Validation error creating project: %s',
            e,
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    now = datetime.datetime.now(datetime.UTC)
    project.created_at = now
    project.updated_at = now
    props = project.model_dump(
        exclude={'team', 'project_type', 'environments'},
    )
    props['project_type_slug'] = data.project_type_slug

    env_clause: typing.LiteralString = ''
    if data.environment_slugs:
        env_clause = """
    WITH p, t, pt, o
    UNWIND $env_slugs AS env_slug
    MATCH (e:Environment {slug: env_slug})
          -[:BELONGS_TO]->(o)
    CREATE (p)-[:DEPLOYED_IN]->(e)
    """

    query: typing.LiteralString = (
        """
    MATCH (o:Organization {slug: $org_slug})
    MATCH (t:Team {slug: $team_slug})
          -[:BELONGS_TO]->(o)
    MATCH (pt:ProjectType {slug: $pt_slug})
          -[:BELONGS_TO]->(o)
    CREATE (p:Project $props)
    CREATE (p)-[:OWNED_BY]->(t)
    CREATE (p)-[:TYPE]->(pt)
    """
        + env_clause
        + """
    WITH p, t, pt, o
    OPTIONAL MATCH (p)-[:DEPLOYED_IN]->(env:Environment)
    WITH p, t, pt, o, collect(env{.*, organization: o{.*}}) AS envs
    RETURN p{.*,
        team: t{.*,
            organization: o{.*}
        },
        project_type: pt{.*,
            organization: o{.*}
        },
        environments: envs
    } AS project
    """
    )
    try:
        records = await neo4j.query(
            query,
            org_slug=org_slug,
            team_slug=data.team_slug,
            pt_slug=data.project_type_slug,
            props=props,
            env_slugs=data.environment_slugs,
        )
    except exceptions.ConstraintError as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Project with slug {data.slug!r}'
                ' already exists for this project type'
            ),
        ) from e

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Organization {org_slug!r}, team'
                f' {data.team_slug!r}, or project type'
                f' {data.project_type_slug!r} not found'
            ),
        )

    result = _add_relationships(
        records[0]['project'],
        org_slug,
    )
    return ProjectResponse.model_validate(result)


@projects_router.get('/')
async def list_projects(
    org_slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> list[ProjectResponse]:
    """List all projects in an organization."""
    query: typing.LiteralString = """
    MATCH (p:Project)-[:OWNED_BY]->(t:Team)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    MATCH (p)-[:TYPE]->(pt:ProjectType)
    OPTIONAL MATCH (p)-[:DEPLOYED_IN]->(env:Environment)
    OPTIONAL MATCH (p)-[:DEPENDS_ON]->(dep:Project)
    WITH p, t, pt, o,
         collect(DISTINCT env{.*, organization: o{.*}}) AS envs,
         count(DISTINCT dep) AS dependency_count
    RETURN p{.*,
        team: t{.*,
            organization: o{.*}
        },
        project_type: pt{.*,
            organization: o{.*}
        },
        environments: envs
    } AS project,
    dependency_count
    ORDER BY p.name
    """
    results: list[ProjectResponse] = []
    records = await neo4j.query(query, org_slug=org_slug)
    for record in records:
        proj = _add_relationships(
            record['project'],
            org_slug,
            record['dependency_count'],
        )
        results.append(ProjectResponse.model_validate(proj))
    return results


@projects_router.get('/{slug}')
async def get_project(
    org_slug: str,
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> ProjectResponse:
    """Get a project by slug."""
    query: typing.LiteralString = """
    MATCH (p:Project {slug: $slug})
          -[:OWNED_BY]->(t:Team)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    MATCH (p)-[:TYPE]->(pt:ProjectType)
    OPTIONAL MATCH (p)-[:DEPLOYED_IN]->(env:Environment)
    OPTIONAL MATCH (p)-[:DEPENDS_ON]->(dep:Project)
    WITH p, t, pt, o,
         collect(DISTINCT env{.*, organization: o{.*}}) AS envs,
         count(DISTINCT dep) AS dependency_count
    RETURN p{.*,
        team: t{.*,
            organization: o{.*}
        },
        project_type: pt{.*,
            organization: o{.*}
        },
        environments: envs
    } AS project,
    dependency_count
    """
    records = await neo4j.query(
        query,
        slug=slug,
        org_slug=org_slug,
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project with slug {slug!r} not found',
        )
    result = _add_relationships(
        records[0]['project'],
        org_slug,
        records[0]['dependency_count'],
    )
    return ProjectResponse.model_validate(result)


@projects_router.put('/{slug}')
async def update_project(
    org_slug: str,
    slug: str,
    data: ProjectUpdate,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> ProjectResponse:
    """Update a project."""
    dynamic_model = await blueprints.get_model(models.Project)

    # Fetch existing project
    fetch_query: typing.LiteralString = """
    MATCH (p:Project {slug: $slug})
          -[:OWNED_BY]->(t:Team)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    MATCH (p)-[:TYPE]->(pt:ProjectType)
    RETURN p{.*,
        team: t{.*,
            organization: o{.*}
        },
        project_type: pt{.*,
            organization: o{.*}
        }
    } AS project,
    t.slug AS current_team_slug,
    pt.slug AS current_pt_slug
    """
    records = await neo4j.query(
        fetch_query,
        slug=slug,
        org_slug=org_slug,
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project with slug {slug!r} not found',
        )

    existing = records[0]['project']
    effective_team_slug = data.team_slug or records[0]['current_team_slug']
    effective_pt_slug = data.project_type_slug or records[0]['current_pt_slug']

    # Merge provided fields with existing values
    merged_name = data.name or existing.get('name', '')
    merged_slug = data.slug or slug
    merged_desc = (
        data.description
        if data.description is not None
        else existing.get('description')
    )
    merged_icon = data.icon if data.icon is not None else existing.get('icon')
    merged_links = (
        data.links if data.links is not None else existing.get('links', {})
    )
    merged_ids = (
        data.identifiers
        if data.identifiers is not None
        else existing.get('identifiers', {})
    )

    try:
        project = dynamic_model(
            team=models.Team(
                name='',
                slug=effective_team_slug,
                organization=models.Organization(
                    name='',
                    slug=org_slug,
                ),
            ),
            project_type=models.ProjectType(
                name='',
                slug=effective_pt_slug,
                organization=models.Organization(
                    name='',
                    slug=org_slug,
                ),
            ),
            environments=[],
            name=merged_name,
            slug=merged_slug,
            description=merged_desc,
            icon=merged_icon,
            links=merged_links,
            identifiers=merged_ids,
        )
    except pydantic.ValidationError as e:
        LOGGER.warning(
            'Validation error updating project: %s',
            e,
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    project.created_at = existing.get('created_at')
    project.updated_at = datetime.datetime.now(datetime.UTC)
    props = project.model_dump(
        exclude={'team', 'project_type', 'environments'},
    )
    props['project_type_slug'] = effective_pt_slug

    # Build update query with optional relationship changes
    rel_clauses: typing.LiteralString = ''
    if data.team_slug:
        rel_clauses += """
    WITH p, o
    MATCH (new_t:Team {slug: $new_team_slug})
          -[:BELONGS_TO]->(o)
    OPTIONAL MATCH (p)-[old_own:OWNED_BY]->(:Team)
    DELETE old_own
    CREATE (p)-[:OWNED_BY]->(new_t)
    """
    if data.project_type_slug:
        rel_clauses += """
    WITH p, o
    MATCH (new_pt:ProjectType {slug: $new_pt_slug})
          -[:BELONGS_TO]->(o)
    OPTIONAL MATCH (p)-[old_type:TYPE]->(:ProjectType)
    DELETE old_type
    CREATE (p)-[:TYPE]->(new_pt)
    """
    if data.environment_slugs is not None:
        rel_clauses += """
    WITH p, o
    OPTIONAL MATCH (p)-[old_env:DEPLOYED_IN]->(:Environment)
    DELETE old_env
    WITH p, o
    UNWIND
        CASE WHEN size($new_env_slugs) = 0
             THEN [null]
             ELSE $new_env_slugs
        END AS env_slug
    OPTIONAL MATCH (e:Environment {slug: env_slug})
             -[:BELONGS_TO]->(o)
    FOREACH (_ IN CASE WHEN e IS NOT NULL
                       THEN [1] ELSE [] END |
        CREATE (p)-[:DEPLOYED_IN]->(e)
    )
    """

    update_query: typing.LiteralString = (
        """
    MATCH (p:Project {slug: $slug})
          -[:OWNED_BY]->(t:Team)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    SET p = $props
    """
        + rel_clauses
        + """
    WITH p, o
    MATCH (p)-[:OWNED_BY]->(t2:Team)
    MATCH (p)-[:TYPE]->(pt2:ProjectType)
    OPTIONAL MATCH (p)-[:DEPLOYED_IN]->(env:Environment)
    OPTIONAL MATCH (p)-[:DEPENDS_ON]->(dep:Project)
    WITH p, t2, pt2, o,
         collect(DISTINCT env{.*, organization: o{.*}}) AS envs,
         count(DISTINCT dep) AS dependency_count
    RETURN p{.*,
        team: t2{.*,
            organization: o{.*}
        },
        project_type: pt2{.*,
            organization: o{.*}
        },
        environments: envs
    } AS project,
    dependency_count
    """
    )

    try:
        updated = await neo4j.query(
            update_query,
            slug=slug,
            org_slug=org_slug,
            props=props,
            new_team_slug=data.team_slug or '',
            new_pt_slug=data.project_type_slug or '',
            new_env_slugs=data.environment_slugs or [],
        )
    except exceptions.ConstraintError as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Project with slug {merged_slug!r}'
                ' already exists for this project type'
            ),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project with slug {slug!r} not found',
        )

    result = _add_relationships(
        updated[0]['project'],
        org_slug,
        updated[0]['dependency_count'],
    )
    return ProjectResponse.model_validate(result)


@projects_router.delete('/{slug}', status_code=204)
async def delete_project(
    org_slug: str,
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:delete'),
        ),
    ],
) -> None:
    """Delete a project."""
    query: typing.LiteralString = """
    MATCH (p:Project {slug: $slug})
          -[:OWNED_BY]->(t:Team)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    DETACH DELETE p
    RETURN count(p) AS deleted
    """
    records = await neo4j.query(
        query,
        slug=slug,
        org_slug=org_slug,
    )

    if not records or records[0].get('deleted', 0) == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project with slug {slug!r} not found',
        )
