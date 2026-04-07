"""Project management endpoints.

Projects are identified by a Nano-ID (``id`` field) and may
belong to multiple project types.  See ADR-0006 for rationale.
"""

import datetime
import json
import logging
import typing

import fastapi
import nanoid
import pydantic
from imbi_common import blueprints, models, neo4j
from neo4j import exceptions

from imbi_api.auth import permissions
from imbi_api.relationships import relationship_link

LOGGER = logging.getLogger(__name__)

projects_router = fastapi.APIRouter(tags=['Projects'])


# -- Request / Response models ------------------------------------------


class EnvironmentRef(models.Environment):
    """Environment with deployment URL from the DEPLOYED_IN edge."""

    url: pydantic.AnyUrl | str | None = None


class ProjectCreate(pydantic.BaseModel):
    """Request body for creating a project.

    Blueprint-defined fields are accepted as extra properties.
    """

    model_config = pydantic.ConfigDict(extra='allow')

    name: str
    slug: str
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    team_slug: str
    project_type_slugs: list[str] = pydantic.Field(min_length=1)
    environments: dict[str, str | None] = pydantic.Field(
        default_factory=dict,
        description=(
            'Map of environment slug to URL (or null for no URL). '
            'Example: {"production": "https://...", "staging": null}'
        ),
    )
    links: dict[str, pydantic.AnyUrl] = {}
    identifiers: dict[str, int | str] = {}

    @pydantic.field_validator('project_type_slugs')
    @classmethod
    def _deduplicate_type_slugs(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


class ProjectUpdate(pydantic.BaseModel):
    """Request body for updating a project.

    Blueprint-defined fields are accepted as extra properties.
    """

    model_config = pydantic.ConfigDict(extra='allow')

    name: str | None = None
    slug: str | None = None
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    team_slug: str | None = None
    project_type_slugs: list[str] | None = pydantic.Field(
        default=None, min_length=1
    )

    @pydantic.field_validator('project_type_slugs')
    @classmethod
    def _deduplicate_type_slugs(
        cls,
        v: list[str] | None,
    ) -> list[str] | None:
        if v is not None:
            return list(dict.fromkeys(v))
        return v

    environments: dict[str, str | None] | None = pydantic.Field(
        default=None,
        description=(
            'Map of environment slug to URL (or null). '
            'Replaces all environment assignments when provided.'
        ),
    )
    links: dict[str, pydantic.AnyUrl] | None = None
    identifiers: dict[str, int | str] | None = None


class ProjectResponse(pydantic.BaseModel):
    """Response body for a project."""

    model_config = pydantic.ConfigDict(extra='allow')

    id: str | None = None
    name: str
    slug: str
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    team: models.Team
    project_types: list[models.ProjectType] = []
    environments: list[EnvironmentRef] = []
    links: dict[str, pydantic.AnyUrl] = {}
    identifiers: dict[str, int | str] = {}
    relationships: dict[str, models.RelationshipLink] | None = None
    dependency_uris: list[str] = []

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

_RESERVED_FIELDS = frozenset(
    {
        'id',
        'team',
        'project_types',
        'environments',
        'created_at',
        'updated_at',
    }
)


def _add_relationships(
    project: dict[str, typing.Any],
    org_slug: str,
    dependency_count: int = 0,
) -> dict[str, typing.Any]:
    """Attach relationships sub-object to a project dict."""
    project_id = project.get('id') or ''
    team = project.get('team', {})
    team_slug = team.get('slug', '') if team else ''
    base = f'/api/organizations/{org_slug}/projects/{project_id}'
    project['relationships'] = {
        'team': relationship_link(
            f'/api/organizations/{org_slug}/teams/{team_slug}',
            1 if team_slug else 0,
        ),
        'environments': relationship_link(
            f'{base}/environments',
            len(project.get('environments') or []),
        ),
        'dependencies': relationship_link(
            f'{base}/dependencies',
            dependency_count,
        ),
    }
    return project


# -- Return fragment used by all read queries ---------------------------

_RETURN_FRAGMENT: typing.LiteralString = """
    CALL {
        WITH p, o
        MATCH (p)-[:OWNED_BY]->(t:Team)
        RETURN t{.*, organization: o{.*}} AS team
        LIMIT 1
    }
    CALL {
        WITH p, o
        MATCH (p)-[:TYPE]->(pt:ProjectType)
        RETURN collect(pt{.*, organization: o{.*}}) AS pts
    }
    CALL {
        WITH p, o
        OPTIONAL MATCH (p)-[d:DEPLOYED_IN]->(env:Environment)
        RETURN collect(env{.*,
                           sort_order: coalesce(env.sort_order, 0),
                           url: d.url,
                           organization: o{.*}}) AS envs
    }
    CALL {
        WITH p
        OPTIONAL MATCH (p)-[:DEPENDS_ON]->(dep:Project)
              -[:OWNED_BY]->(:Team)
              -[:BELONGS_TO]->(depOrg:Organization)
        RETURN count(dep) AS dependency_count,
               [x IN collect(DISTINCT
                   CASE WHEN dep IS NOT NULL
                             AND depOrg IS NOT NULL
                             AND dep.id IS NOT NULL
                        THEN '/organizations/' + depOrg.slug
                             + '/projects/'
                             + dep.id
                   END
               ) WHERE x IS NOT NULL] AS dependency_uris
    }
    RETURN p{.*,
        team: team,
        project_types: pts,
        environments: envs,
        dependency_uris: dependency_uris
    } AS project,
    dependency_count
"""


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
    dynamic_model = await blueprints.get_model(
        models.Project,
        context={'project_type': data.project_type_slugs},
    )

    project_id = nanoid.generate()

    try:
        project = dynamic_model(
            id=project_id,
            team=models.Team(
                name='',
                slug=data.team_slug,
                organization=models.Organization(
                    name='',
                    slug=org_slug,
                ),
            ),
            project_types=[],
            environments=[],
            name=data.name,
            slug=data.slug,
            description=data.description,
            icon=data.icon,
            links=data.links,
            identifiers=data.identifiers,
            **{
                k: v
                for k, v in (data.model_extra or {}).items()
                if k not in _RESERVED_FIELDS
            },
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
        exclude={
            'team',
            'project_types',
            'environments',
        },
    )

    # Pre-validate that all project type slugs exist before creating
    # anything, to avoid orphaned Project nodes when slugs are invalid.
    validate_query: typing.LiteralString = """
    MATCH (o:Organization {slug: $org_slug})
    UNWIND $pt_slugs AS pt_slug
    OPTIONAL MATCH (pt:ProjectType {slug: pt_slug})
             -[:BELONGS_TO]->(o)
    RETURN pt_slug, pt IS NOT NULL AS found
    """
    validation = await neo4j.query(
        validate_query,
        org_slug=org_slug,
        pt_slugs=data.project_type_slugs,
    )
    missing = [r['pt_slug'] for r in validation if not r['found']]
    if missing:
        raise fastapi.HTTPException(
            status_code=422,
            detail=(f'Project type slug(s) not found: {sorted(missing)!r}'),
        )

    query: typing.LiteralString = (
        """
    MATCH (o:Organization {slug: $org_slug})
    MATCH (t:Team {slug: $team_slug})
          -[:BELONGS_TO]->(o)
    CREATE (p:Project $props)
    CREATE (p)-[:OWNED_BY]->(t)
    WITH p, t, o
    UNWIND $pt_slugs AS pt_slug
    OPTIONAL MATCH (pt:ProjectType {slug: pt_slug})
          -[:BELONGS_TO]->(o)
    FOREACH (_ IN CASE WHEN pt IS NOT NULL
                       THEN [1] ELSE [] END |
        CREATE (p)-[:TYPE]->(pt)
    )
    WITH DISTINCT p, t, o
    UNWIND
        CASE WHEN size($env_entries) = 0
             THEN [null]
             ELSE $env_entries
        END AS entry
    OPTIONAL MATCH (e:Environment {slug: entry.slug})
             -[:BELONGS_TO]->(o)
    FOREACH (_ IN CASE WHEN e IS NOT NULL
                       THEN [1] ELSE [] END |
        CREATE (p)-[:DEPLOYED_IN {url: entry.url}]->(e)
    )
    WITH DISTINCT p, t, o
    """
        + _RETURN_FRAGMENT
    )
    env_entries = [
        {'slug': slug, 'url': url} for slug, url in data.environments.items()
    ]
    try:
        records = await neo4j.query(
            query,
            org_slug=org_slug,
            team_slug=data.team_slug,
            pt_slugs=data.project_type_slugs,
            props=props,
            env_entries=env_entries,
        )
    except exceptions.ConstraintError as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(f'Project with id {project_id!r} already exists'),
        ) from e

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Organization {org_slug!r}, team'
                f' {data.team_slug!r}, or project type(s)'
                f' {data.project_type_slugs!r} not found'
            ),
        )

    project = records[0]['project']
    result = _add_relationships(project, org_slug)
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
    project_type: str | None = None,
) -> list[ProjectResponse]:
    """List all projects, optionally filtered by type."""
    type_filter: typing.LiteralString = (
        'MATCH (p)-[:TYPE]->(filter_pt:ProjectType {slug: $project_type})'
        if project_type
        else ''
    )
    query: typing.LiteralString = (
        """
    MATCH (p:Project)-[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    WITH DISTINCT p, o
    """
        + type_filter
        + _RETURN_FRAGMENT
        + """
    ORDER BY p.name
    """
    )
    results: list[ProjectResponse] = []
    records = await neo4j.query(
        query,
        org_slug=org_slug,
        project_type=project_type,
    )
    for record in records:
        proj = _add_relationships(
            record['project'],
            org_slug,
            record['dependency_count'],
        )
        results.append(
            ProjectResponse.model_validate(proj),
        )
    return results


class BlueprintSectionProperty(pydantic.BaseModel):
    """A single property from a blueprint's JSON Schema."""

    model_config = pydantic.ConfigDict(
        populate_by_name=True, serialize_by_alias=True
    )

    type: str | None = None
    format: str | None = None
    title: str | None = None
    description: str | None = None
    enum: list[str] | None = None
    default: typing.Any = None
    minimum: float | None = None
    maximum: float | None = None
    x_ui: dict[str, typing.Any] | None = pydantic.Field(
        None, alias='x-ui', serialization_alias='x-ui'
    )


class BlueprintSection(pydantic.BaseModel):
    """One blueprint's contribution to the project schema."""

    name: str
    slug: str
    description: str | None = None
    properties: dict[str, BlueprintSectionProperty]


class ProjectSchemaResponse(pydantic.BaseModel):
    """Fully resolved, blueprint-grouped schema for a project."""

    sections: list[BlueprintSection]


@projects_router.get('/{project_id}/schema')
async def get_project_schema(
    org_slug: str,
    project_id: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> ProjectSchemaResponse:
    """Return the merged blueprint schema for a specific project.

    Resolves the project's own types and environments, matches every
    applicable blueprint, and returns the properties grouped by
    blueprint so the UI can render labelled sections.
    """
    # Fetch the project's type slugs and environment slugs
    lookup: typing.LiteralString = """
    MATCH (p:Project {id: $project_id})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    CALL {
        WITH p
        MATCH (p)-[:TYPE]->(pt:ProjectType)
        RETURN collect(pt.slug) AS type_slugs
    }
    CALL {
        WITH p
        OPTIONAL MATCH (p)-[:DEPLOYED_IN]->(env:Environment)
        RETURN collect(env.slug) AS env_slugs
    }
    RETURN type_slugs, env_slugs
    """
    records = await neo4j.query(
        lookup,
        project_id=project_id,
        org_slug=org_slug,
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )

    type_slugs: set[str] = set(records[0]['type_slugs'] or [])
    env_slugs: set[str] = set(records[0]['env_slugs'] or [])

    # Fetch all enabled Project blueprints ordered by priority
    all_blueprints: list[models.Blueprint] = []
    async for bp in neo4j.fetch_nodes(
        models.Blueprint,
        {'type': 'Project', 'enabled': True},
        order_by='priority',
    ):
        all_blueprints.append(bp)

    # Match blueprints whose filters intersect the project's own types/envs.
    # A blueprint with no filter matches everything.
    # A blueprint with a project_type filter matches if any of the project's
    # types appear in that list (same for environment).
    sections: list[BlueprintSection] = []
    for bp in all_blueprints:
        f = bp.filter
        if f is not None:
            if f.project_type and not type_slugs.intersection(f.project_type):
                continue
            if f.environment and not env_slugs.intersection(f.environment):
                continue

        schema = bp.json_schema
        if not schema.properties:
            continue

        props: dict[str, BlueprintSectionProperty] = {}
        for prop_name, prop_schema in schema.properties.items():
            x_ui = (
                prop_schema.model_extra.get('x-ui')
                if prop_schema.model_extra
                else None
            )
            props[prop_name] = BlueprintSectionProperty(
                type=getattr(prop_schema, 'type', None),
                format=getattr(prop_schema, 'format', None),
                title=getattr(prop_schema, 'title', None),
                description=getattr(prop_schema, 'description', None),
                enum=getattr(prop_schema, 'enum', None),
                default=getattr(prop_schema, 'default', None),
                minimum=getattr(prop_schema, 'minimum', None),
                maximum=getattr(prop_schema, 'maximum', None),
                **{'x-ui': x_ui},
            )

        sections.append(
            BlueprintSection(
                name=bp.name,
                slug=bp.slug or '',
                description=bp.description,
                properties=props,
            )
        )

    return ProjectSchemaResponse(sections=sections)


@projects_router.get('/{project_id}')
async def get_project(
    org_slug: str,
    project_id: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> ProjectResponse:
    """Get a project by ID."""
    query: typing.LiteralString = (
        """
    MATCH (p:Project {id: $project_id})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    WITH DISTINCT p, o
    """
        + _RETURN_FRAGMENT
    )
    records = await neo4j.query(
        query,
        project_id=project_id,
        org_slug=org_slug,
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )
    result = _add_relationships(
        records[0]['project'],
        org_slug,
        records[0]['dependency_count'],
    )
    return ProjectResponse.model_validate(result)


@projects_router.put('/{project_id}')
async def update_project(
    org_slug: str,
    project_id: str,
    data: ProjectUpdate,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> ProjectResponse:
    """Update a project."""
    # Fetch existing project to determine current types
    fetch_query: typing.LiteralString = """
    MATCH (p:Project {id: $project_id})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    WITH DISTINCT p
    CALL {
        WITH p
        MATCH (p)-[:OWNED_BY]->(t:Team)
        RETURN t.slug AS team_slug
        LIMIT 1
    }
    CALL {
        WITH p
        MATCH (p)-[:TYPE]->(pt:ProjectType)
        RETURN collect(pt.slug) AS type_slugs
    }
    RETURN p{.*} AS project,
           team_slug AS current_team_slug,
           type_slugs AS current_type_slugs
    """
    records = await neo4j.query(
        fetch_query,
        project_id=project_id,
        org_slug=org_slug,
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )

    existing = records[0]['project']
    current_team = records[0]['current_team_slug']
    current_types = records[0]['current_type_slugs']

    effective_team = data.team_slug or current_team
    effective_types = data.project_type_slugs or current_types

    dynamic_model = await blueprints.get_model(
        models.Project,
        context={'project_type': effective_types},
    )

    # Merge provided fields with existing values
    merged = {
        'name': data.name or existing.get('name', ''),
        'slug': data.slug or existing.get('slug', ''),
        'description': (
            data.description
            if data.description is not None
            else existing.get('description')
        ),
        'icon': (data.icon if data.icon is not None else existing.get('icon')),
        'links': (
            data.links if data.links is not None else existing.get('links', {})
        ),
        'identifiers': (
            data.identifiers
            if data.identifiers is not None
            else existing.get('identifiers', {})
        ),
    }

    # Merge blueprint extra fields
    base_fields = set(ProjectUpdate.model_fields)
    skip = {
        'id',
        'team',
        'project_types',
        'environments',
        'created_at',
        'updated_at',
    }
    extra_fields = {
        k: v
        for k, v in existing.items()
        if k not in base_fields and k not in skip
    }
    extra_fields.update(
        {
            k: v
            for k, v in (data.model_extra or {}).items()
            if k not in _RESERVED_FIELDS
        }
    )

    try:
        project = dynamic_model(
            id=project_id,
            team=models.Team(
                name='',
                slug=effective_team,
                organization=models.Organization(
                    name='',
                    slug=org_slug,
                ),
            ),
            project_types=[],
            environments=[],
            **merged,  # type: ignore[arg-type]
            **extra_fields,
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
        exclude={
            'team',
            'project_types',
            'environments',
        },
    )

    # Pre-validate team slug exists before executing the update to
    # prevent partial writes (SET p = $props commits even when a
    # subsequent strict MATCH on the team returns 0 rows).
    if data.team_slug:
        team_check: typing.LiteralString = """
        MATCH (t:Team {slug: $team_slug})
              -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
        RETURN t.slug AS slug
        """
        team_records = await neo4j.query(
            team_check,
            team_slug=data.team_slug,
            org_slug=org_slug,
        )
        if not team_records:
            raise fastapi.HTTPException(
                status_code=422,
                detail=(
                    f'Team {data.team_slug!r} not found in'
                    f' organization {org_slug!r}'
                ),
            )

    # Pre-validate that all project type slugs exist to avoid
    # silently deleting existing TYPE edges with no replacements.
    if data.project_type_slugs is not None:
        pt_check: typing.LiteralString = """
        MATCH (o:Organization {slug: $org_slug})
        UNWIND $pt_slugs AS pt_slug
        OPTIONAL MATCH (pt:ProjectType {slug: pt_slug})
                 -[:BELONGS_TO]->(o)
        RETURN pt_slug, pt IS NOT NULL AS found
        """
        pt_records = await neo4j.query(
            pt_check,
            org_slug=org_slug,
            pt_slugs=data.project_type_slugs,
        )
        missing = [r['pt_slug'] for r in pt_records if not r['found']]
        if missing:
            raise fastapi.HTTPException(
                status_code=422,
                detail=(
                    f'Project type slug(s) not found: {sorted(missing)!r}'
                ),
            )

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
    if data.project_type_slugs is not None:
        rel_clauses += """
    WITH DISTINCT p, o
    OPTIONAL MATCH (p)-[old_type:TYPE]->(:ProjectType)
    DELETE old_type
    WITH DISTINCT p, o
    UNWIND $new_type_slugs AS new_pt_slug
    MATCH (new_pt:ProjectType {slug: new_pt_slug})
          -[:BELONGS_TO]->(o)
    CREATE (p)-[:TYPE]->(new_pt)
    """
    if data.environments is not None:
        rel_clauses += """
    WITH DISTINCT p, o
    OPTIONAL MATCH (p)-[old_env:DEPLOYED_IN]->(:Environment)
    DELETE old_env
    WITH DISTINCT p, o
    UNWIND
        CASE WHEN size($new_env_entries) = 0
             THEN [null]
             ELSE $new_env_entries
        END AS entry
    OPTIONAL MATCH (e:Environment {slug: entry.slug})
             -[:BELONGS_TO]->(o)
    FOREACH (_ IN CASE WHEN e IS NOT NULL
                       THEN [1] ELSE [] END |
        CREATE (p)-[:DEPLOYED_IN {url: entry.url}]->(e)
    )
    """

    update_query: typing.LiteralString = (
        """
    MATCH (p:Project {id: $project_id})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    WITH DISTINCT p, o
    SET p = $props
    """
        + rel_clauses
        + """
    WITH DISTINCT p, o
    """
        + _RETURN_FRAGMENT
    )

    try:
        updated = await neo4j.query(
            update_query,
            project_id=project_id,
            org_slug=org_slug,
            props=props,
            new_team_slug=data.team_slug or '',
            new_type_slugs=data.project_type_slugs or [],
            new_env_entries=[
                {'slug': s, 'url': u}
                for s, u in (data.environments or {}).items()
            ],
        )
    except exceptions.ConstraintError as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=str(e),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )

    result = _add_relationships(
        updated[0]['project'],
        org_slug,
        updated[0]['dependency_count'],
    )
    return ProjectResponse.model_validate(result)


@projects_router.delete('/{project_id}', status_code=204)
async def delete_project(
    org_slug: str,
    project_id: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:delete'),
        ),
    ],
) -> None:
    """Delete a project."""
    query: typing.LiteralString = """
    MATCH (p:Project {id: $project_id})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {slug: $org_slug})
    DETACH DELETE p
    RETURN count(p) AS deleted
    """
    records = await neo4j.query(
        query,
        project_id=project_id,
        org_slug=org_slug,
    )

    if not records or records[0].get('deleted', 0) == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )
