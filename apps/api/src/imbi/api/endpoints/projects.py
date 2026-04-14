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
import psycopg
import pydantic
from imbi_common import blueprints, graph, models

from imbi_api.auth import permissions
from imbi_api.relationships import relationship_link

LOGGER = logging.getLogger(__name__)

projects_router = fastapi.APIRouter(tags=['Projects'])


# -- Request / Response models ------------------------------------------


class EnvironmentRef(models.Environment):
    """Environment with dynamic edge properties from DEPLOYED_IN.

    Edge properties are defined by relationship blueprints and
    accepted via ``extra='allow'`` so they flow through to the
    response without hard-coding field names.
    """

    model_config = pydantic.ConfigDict(extra='allow')


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
    environments: dict[str, dict[str, typing.Any]] = pydantic.Field(
        default_factory=dict,
        description=(
            'Map of environment slug to edge properties. '
            'Example: {"production": {"url": "https://..."}, '
            '"staging": {}}'
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

    environments: dict[str, dict[str, typing.Any]] | None = pydantic.Field(
        default=None,
        description=(
            'Map of environment slug to edge properties. '
            'Replaces all environment assignments when provided.'
        ),
    )
    links: dict[str, pydantic.AnyUrl] | None = None
    identifiers: dict[str, int | str] | None = None


class ProjectRelationships(pydantic.BaseModel):
    """Typed relationship links and counts for a project."""

    team: models.RelationshipLink
    environments: models.RelationshipLink
    href: str
    outbound_count: int = 0
    inbound_count: int = 0


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
    relationships: ProjectRelationships | None = None

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
        """Graph stores dicts as JSON strings."""
        if isinstance(value, str):
            return json.loads(value)
        return value


# -- Helpers ------------------------------------------------------------


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

    Returns ``SET p.`name` = {name}, p.`slug` = {slug}``.

    """
    if not props:
        return ''
    assignments = ', '.join(
        f'{alias}.{_escape_prop(k)} = {{{k}}}' for k in props
    )
    return f'SET {assignments}'


def _env_entries_template(
    entries: list[dict[str, typing.Any]],
) -> tuple[str, dict[str, typing.Any]]:
    """Build an inline Cypher list of maps for env entries.

    Each entry is a dict with ``slug`` plus arbitrary edge
    properties.  Returns ``(template_fragment, params_dict)``
    where the template uses indexed placeholders and the params
    dict maps those keys to scalar values.

    """
    if not entries:
        return '[]', {}
    maps: list[str] = []
    params: dict[str, typing.Any] = {}
    for i, entry in enumerate(entries):
        pairs: list[str] = []
        for key, value in entry.items():
            param = f'env_{i}_{key}'
            pairs.append(f'{_escape_prop(key)}: {{{param}}}')
            params[param] = value
        maps.append('{{' + ', '.join(pairs) + '}}')
    return '[' + ', '.join(maps) + ']', params


def _edge_create_props(
    entries: list[dict[str, typing.Any]],
) -> str:
    """Build a Cypher property map for DEPLOYED_IN edge creation.

    Returns a string like ``{{`url`: entry.`url`}}`` derived from
    the union of all entries' keys (excluding ``slug``).  Returns
    an empty string when there are no edge properties.

    """
    if not entries:
        return ''
    all_keys: dict[str, None] = {}
    for entry in entries:
        for k in entry:
            if k != 'slug':
                all_keys[k] = None
    prop_keys = list(all_keys)
    if not prop_keys:
        return ''
    pairs = [f'{_escape_prop(k)}: entry.{_escape_prop(k)}' for k in prop_keys]
    return ' {{' + ', '.join(pairs) + '}}'


async def _validate_env_slugs(
    db: graph.Pool,
    org_slug: str,
    env_slugs: list[str],
) -> None:
    """Validate that all environment slugs exist in the org.

    Raises HTTPException 422 if any are missing.
    """
    env_check: typing.LiteralString = """
    MATCH (o:Organization {{slug: {org_slug}}})
    UNWIND {env_slugs} AS env_slug
    OPTIONAL MATCH (e:Environment {{slug: env_slug}})
             -[:BELONGS_TO]->(o)
    RETURN env_slug, e IS NOT NULL AS found
    """
    records = await db.execute(
        env_check,
        {
            'org_slug': org_slug,
            'env_slugs': json.dumps(env_slugs),
        },
        ['env_slug', 'found'],
    )
    missing = [
        graph.parse_agtype(r['env_slug'])
        for r in records
        if not graph.parse_agtype(r['found'])
    ]
    if missing:
        raise fastapi.HTTPException(
            status_code=422,
            detail=(f'Environment slug(s) not found: {sorted(missing)!r}'),
        )


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


_PROTECTED_ENV_KEYS = frozenset(
    {
        'id',
        'name',
        'slug',
        'sort_order',
        'organization',
        'created_at',
        'updated_at',
        'label_color',
        'description',
        'icon',
    }
)


def _flatten_edge_props(
    project: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Merge ``_edge`` sub-dicts into each environment entry.

    The Cypher return fragment stores relationship properties
    under a nested ``_edge`` key.  This flattens them into the
    top-level environment dict so they appear as peer fields.
    Protected environment keys are excluded to prevent
    accidental overwrites.
    """
    envs: list[dict[str, typing.Any]] = project.get('environments') or []
    for env in envs:
        raw_edge = env.pop('_edge', None)
        if raw_edge:
            edge: dict[str, typing.Any] = (
                json.loads(raw_edge) if isinstance(raw_edge, str) else raw_edge
            )
            env.update(
                {k: v for k, v in edge.items() if k not in _PROTECTED_ENV_KEYS}
            )
    return project


def _add_relationships(
    project: dict[str, typing.Any],
    org_slug: str,
    outbound_count: int = 0,
    inbound_count: int = 0,
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
        'href': f'{base}/relationships',
        'outbound_count': outbound_count,
        'inbound_count': inbound_count,
    }
    return project


# -- Return fragment used by all read queries ---------------------------

_RETURN_FRAGMENT: typing.LiteralString = """
    MATCH (p)-[:OWNED_BY]->(t:Team)-[:BELONGS_TO]->(o)
    WITH p, o, t
    OPTIONAL MATCH (p)-[:TYPE]->(pt:ProjectType)
          -[:BELONGS_TO]->(o)
    WITH p, o, t, collect(pt{{.*, organization: o{{.*}}}}) AS pts
    OPTIONAL MATCH (p)-[d:DEPLOYED_IN]->(env:Environment)
          -[:BELONGS_TO]->(o)
    WITH p, o, t, pts,
         collect(env{{.*,
                     sort_order: coalesce(env.sort_order, 0),
                     _edge: properties(d),
                     organization: o{{.*}}}}) AS envs
    OPTIONAL MATCH (p)-[:DEPENDS_ON]->(out:Project)
    WITH p, o, t, pts, envs, count(out) AS outbound_count
    OPTIONAL MATCH (p)<-[:DEPENDS_ON]-(in_:Project)
    WITH p, o, t, pts, envs, outbound_count,
         count(in_) AS inbound_count
    RETURN p{{.*,
        team: t{{.*, organization: o{{.*}}}},
        project_types: pts,
        environments: envs
    }} AS project,
    outbound_count,
    inbound_count
"""


# -- Endpoints ----------------------------------------------------------


@projects_router.post('/', status_code=201)
async def create_project(
    org_slug: str,
    data: ProjectCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:create'),
        ),
    ],
) -> ProjectResponse:
    """Create a new project in an organization."""
    dynamic_model = await blueprints.get_model(
        db,
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
            **{
                k: v
                for k, v in typing.cast(
                    dict[str, typing.Any],
                    {
                        'identifiers': data.identifiers,
                        **(data.model_extra or {}),
                    },
                ).items()
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
        mode='json',
        exclude={
            'team',
            'project_types',
            'environments',
        },
    )
    # Serialize dict/list fields to JSON strings for graph storage
    for key in ('links', 'identifiers'):
        if key in props and not isinstance(props[key], str):
            props[key] = json.dumps(props[key])

    # Pre-validate that all project type slugs exist before creating
    # anything, to avoid orphaned Project nodes when slugs are invalid.
    validate_query: typing.LiteralString = """
    MATCH (o:Organization {{slug: {org_slug}}})
    UNWIND {pt_slugs} AS pt_slug
    OPTIONAL MATCH (pt:ProjectType {{slug: pt_slug}})
             -[:BELONGS_TO]->(o)
    RETURN pt_slug, pt IS NOT NULL AS found
    """
    validation = await db.execute(
        validate_query,
        {
            'org_slug': org_slug,
            'pt_slugs': json.dumps(data.project_type_slugs),
        },
        ['pt_slug', 'found'],
    )
    missing = [
        graph.parse_agtype(r['pt_slug'])
        for r in validation
        if not graph.parse_agtype(r['found'])
    ]
    if missing:
        raise fastapi.HTTPException(
            status_code=422,
            detail=(f'Project type slug(s) not found: {sorted(missing)!r}'),
        )

    # Pre-validate that all environment slugs exist
    if data.environments:
        await _validate_env_slugs(
            db,
            org_slug,
            list(data.environments.keys()),
        )

    create_tpl = _props_template(props)
    env_entries = [{'slug': s, **ep} for s, ep in data.environments.items()]
    env_tpl, env_params = _env_entries_template(env_entries)
    edge_props_tpl = _edge_create_props(env_entries)

    query: str = (
        """
    MATCH (o:Organization {{slug: {org_slug}}})
    MATCH (t:Team {{slug: {team_slug}}})
          -[:BELONGS_TO]->(o)
    CREATE (p:Project """
        + create_tpl
        + """)
    CREATE (p)-[:OWNED_BY]->(t)
    WITH p, t, o
    UNWIND {pt_slugs} AS pt_slug
    OPTIONAL MATCH (pt:ProjectType {{slug: pt_slug}})
          -[:BELONGS_TO]->(o)
    FOREACH (_ IN CASE WHEN pt IS NOT NULL
                       THEN [1] ELSE [] END |
        CREATE (p)-[:TYPE]->(pt)
    )
    WITH DISTINCT p, t, o
    UNWIND
        CASE WHEN size("""
        + env_tpl
        + """) = 0
             THEN [null]
             ELSE """
        + env_tpl
        + """ END AS entry
    OPTIONAL MATCH (e:Environment {{slug: entry.slug}})
             -[:BELONGS_TO]->(o)
    FOREACH (_ IN CASE WHEN e IS NOT NULL
                       THEN [1] ELSE [] END |
        CREATE (p)-[:DEPLOYED_IN"""
        + edge_props_tpl
        + """]->(e)
    )
    WITH DISTINCT p, t, o
    """
        + _RETURN_FRAGMENT
    )
    try:
        records = await db.execute(
            query,
            {
                'org_slug': org_slug,
                'team_slug': data.team_slug,
                'pt_slugs': json.dumps(
                    data.project_type_slugs,
                ),
                **props,
                **env_params,
            },
            ['project', 'outbound_count', 'inbound_count'],
        )
    except psycopg.errors.UniqueViolation as e:
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

    project_data = graph.parse_agtype(records[0]['project'])
    _flatten_edge_props(project_data)
    result = _add_relationships(
        project_data,
        org_slug,
        graph.parse_agtype(records[0]['outbound_count']),
        graph.parse_agtype(records[0]['inbound_count']),
    )
    return ProjectResponse.model_validate(result)


@projects_router.get('/')
async def list_projects(
    org_slug: str,
    db: graph.Pool,
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
        'MATCH (p)-[:TYPE]->(filter_pt:ProjectType {{slug: {project_type}}})'
        if project_type
        else ''
    )
    query: typing.LiteralString = (
        """
    MATCH (p:Project)-[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    WITH DISTINCT p, o
    """
        + type_filter
        + _RETURN_FRAGMENT
        + """
    ORDER BY p.name
    """
    )
    results: list[ProjectResponse] = []
    records = await db.execute(
        query,
        {
            'org_slug': org_slug,
            'project_type': project_type,
        },
        ['project', 'outbound_count', 'inbound_count'],
    )
    for record in records:
        project_data = graph.parse_agtype(record['project'])
        _flatten_edge_props(project_data)
        proj = _add_relationships(
            project_data,
            org_slug,
            graph.parse_agtype(record['outbound_count']),
            graph.parse_agtype(record['inbound_count']),
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
    x_ui: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
        alias='x-ui',
        serialization_alias='x-ui',
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
    db: graph.Pool,
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
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (p)-[:TYPE]->(pt:ProjectType)
          -[:BELONGS_TO]->(o)
    WITH p, o, collect(pt.slug) AS type_slugs
    OPTIONAL MATCH (p)-[:DEPLOYED_IN]->(env:Environment)
          -[:BELONGS_TO]->(o)
    WITH type_slugs, collect(env.slug) AS env_slugs
    RETURN type_slugs, env_slugs
    """
    records = await db.execute(
        lookup,
        {
            'project_id': project_id,
            'org_slug': org_slug,
        },
        ['type_slugs', 'env_slugs'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )

    type_slugs: set[str] = set(
        graph.parse_agtype(records[0]['type_slugs']) or []
    )
    env_slugs: set[str] = set(
        graph.parse_agtype(records[0]['env_slugs']) or []
    )

    # Fetch all enabled node blueprints for Project
    all_blueprints = await db.match(
        models.Blueprint,
        {'type': 'Project', 'enabled': True},
        order_by='priority',
    )

    # Match blueprints whose filters intersect the project's own
    # types/envs. A blueprint with no filter matches everything.
    # A blueprint with a project_type filter matches if any of
    # the project's types appear in that list (same for environment).
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
            raw_x_ui = (
                prop_schema.model_extra.get('x-ui')
                if prop_schema.model_extra
                else None
            )
            x_ui = dict(raw_x_ui or {})
            if x_ui.get('editable') is None:
                x_ui['editable'] = True
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
    db: graph.Pool,
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
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    WITH DISTINCT p, o
    """
        + _RETURN_FRAGMENT
    )
    records = await db.execute(
        query,
        {
            'project_id': project_id,
            'org_slug': org_slug,
        },
        ['project', 'outbound_count', 'inbound_count'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )
    project_data = graph.parse_agtype(records[0]['project'])
    _flatten_edge_props(project_data)
    result = _add_relationships(
        project_data,
        org_slug,
        graph.parse_agtype(records[0]['outbound_count']),
        graph.parse_agtype(records[0]['inbound_count']),
    )
    return ProjectResponse.model_validate(result)


class ProjectRelationshipSummary(pydantic.BaseModel):
    """Summary of the project on the other end of an edge."""

    id: str
    name: str
    slug: str
    namespace: str | None = None
    project_type: str | None = None
    project_type_icon: str | None = None


class ProjectRelationship(pydantic.BaseModel):
    """A single DEPENDS_ON edge touching the project."""

    direction: typing.Literal['inbound', 'outbound']
    type: typing.Literal['depends_on'] = 'depends_on'
    project: ProjectRelationshipSummary


class ProjectRelationshipsResponse(pydantic.BaseModel):
    """Wrapped list of relationships."""

    relationships: list[ProjectRelationship]


class ProjectRelationshipsUpdate(pydantic.BaseModel):
    """Request body for replacing outbound DEPENDS_ON edges."""

    depends_on: list[str] = pydantic.Field(
        description='Project IDs that this project depends on.',
    )


_RELATIONSHIPS_QUERY: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    WITH p
    OPTIONAL MATCH (p)-[r:DEPENDS_ON]-(other:Project)
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(otherOrg:Organization)
    OPTIONAL MATCH (other)-[:TYPE]->(pt:ProjectType)
    WITH p, r, other, otherOrg, pt
    ORDER BY pt.slug
    WITH p, r, other, otherOrg,
         collect(pt.slug)[0] AS pt_slug,
         collect(pt.icon)[0] AS pt_icon,
         CASE WHEN r IS NULL THEN null
              WHEN startNode(r) = p THEN 'outbound'
              ELSE 'inbound'
         END AS direction
    RETURN direction,
           CASE WHEN other IS NULL THEN null
                ELSE other{{.id, .name, .slug,
                           namespace: otherOrg.slug,
                           project_type: pt_slug,
                           project_type_icon: pt_icon}}
           END AS other
    ORDER BY CASE direction WHEN 'inbound' THEN 0
                            WHEN 'outbound' THEN 1
                            ELSE 2 END,
             other.name,
             other.id
"""


async def _fetch_relationships(
    db: graph.Pool,
    project_id: str,
    org_slug: str,
) -> list[ProjectRelationship]:
    """Fetch all DEPENDS_ON edges for a project, sorted inbound-first."""
    records = await db.execute(
        _RELATIONSHIPS_QUERY,
        {'project_id': project_id, 'org_slug': org_slug},
        ['direction', 'other'],
    )
    relationships: list[ProjectRelationship] = []
    for record in records:
        direction = graph.parse_agtype(record['direction'])
        other = graph.parse_agtype(record['other'])
        if not direction or not other:
            continue
        relationships.append(
            ProjectRelationship(
                direction=direction,
                project=ProjectRelationshipSummary.model_validate(other),
            ),
        )
    return relationships


_PROJECT_EXISTS_QUERY: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    RETURN p.id AS id
"""


@projects_router.get('/{project_id}/relationships')
async def list_project_relationships(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> ProjectRelationshipsResponse:
    """List every DEPENDS_ON edge touching the project.

    Returns both inbound and outbound edges in a flat list with a
    ``direction`` field. Rows are sorted inbound first, then by
    the related project's name.
    """
    exists = await db.execute(
        _PROJECT_EXISTS_QUERY,
        {'project_id': project_id, 'org_slug': org_slug},
        ['id'],
    )
    if not exists:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )
    return ProjectRelationshipsResponse(
        relationships=await _fetch_relationships(db, project_id, org_slug),
    )


@projects_router.put('/{project_id}/relationships')
async def set_project_relationships(
    org_slug: str,
    project_id: str,
    data: ProjectRelationshipsUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> ProjectRelationshipsResponse:
    """Replace the outbound DEPENDS_ON edges for a project.

    Deletes all existing outbound DEPENDS_ON edges and creates new
    ones for each project ID in ``depends_on``.  Self-references
    are silently ignored.
    """
    target_ids = list(
        dict.fromkeys(tid for tid in data.depends_on if tid != project_id)
    )

    exists = await db.execute(
        _PROJECT_EXISTS_QUERY,
        {'project_id': project_id, 'org_slug': org_slug},
        ['id'],
    )
    if not exists:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )

    if target_ids:
        validate_query: typing.LiteralString = """
        UNWIND {target_ids} AS tid
        OPTIONAL MATCH (t:Project {{id: tid}})
        RETURN tid, t IS NOT NULL AS found
        """
        records = await db.execute(
            validate_query,
            {'target_ids': target_ids},
            ['tid', 'found'],
        )
        missing = [
            graph.parse_agtype(r['tid'])
            for r in records
            if not graph.parse_agtype(r['found'])
        ]
        if missing:
            raise fastapi.HTTPException(
                status_code=422,
                detail=(f'Project ID(s) not found: {sorted(missing)!r}'),
            )

    if target_ids:
        mutate_query: typing.LiteralString = """
        MATCH (p:Project {{id: {project_id}}})
        OPTIONAL MATCH (p)-[old:DEPENDS_ON]->(:Project)
        DELETE old
        WITH DISTINCT p
        UNWIND {target_ids} AS tid
        MATCH (target:Project {{id: tid}})
        CREATE (p)-[:DEPENDS_ON]->(target)
        """
        await db.execute(
            mutate_query,
            {
                'project_id': project_id,
                'target_ids': target_ids,
            },
        )
    else:
        delete_query: typing.LiteralString = """
        MATCH (p:Project {{id: {project_id}}})
        OPTIONAL MATCH (p)-[old:DEPENDS_ON]->(:Project)
        DELETE old
        """
        await db.execute(
            delete_query,
            {'project_id': project_id},
        )

    return ProjectRelationshipsResponse(
        relationships=await _fetch_relationships(db, project_id, org_slug),
    )


@projects_router.put('/{project_id}')
async def update_project(
    org_slug: str,
    project_id: str,
    data: ProjectUpdate,
    db: graph.Pool,
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
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    WITH DISTINCT p, o
    MATCH (p)-[:OWNED_BY]->(t:Team)-[:BELONGS_TO]->(o)
    WITH p, o, t.slug AS team_slug
    OPTIONAL MATCH (p)-[:TYPE]->(pt:ProjectType)
          -[:BELONGS_TO]->(o)
    WITH p, team_slug, collect(pt.slug) AS type_slugs
    RETURN p{{.*}} AS project,
           team_slug AS current_team_slug,
           type_slugs AS current_type_slugs
    """
    records = await db.execute(
        fetch_query,
        {
            'project_id': project_id,
            'org_slug': org_slug,
        },
        ['project', 'current_team_slug', 'current_type_slugs'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )

    existing = graph.parse_agtype(records[0]['project'])
    current_team = graph.parse_agtype(records[0]['current_team_slug'])
    current_types = graph.parse_agtype(records[0]['current_type_slugs'])

    effective_team = data.team_slug or current_team
    effective_types = data.project_type_slugs or current_types

    dynamic_model = await blueprints.get_model(
        db,
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

    raw_created = existing.get('created_at')
    project.created_at = (
        datetime.datetime.fromisoformat(raw_created)
        if raw_created
        else datetime.datetime.now(datetime.UTC)
    )
    project.updated_at = datetime.datetime.now(datetime.UTC)
    props = project.model_dump(
        mode='json',
        exclude={
            'team',
            'project_types',
            'environments',
        },
    )
    # Serialize dict/list fields to JSON strings for graph storage
    for key in ('links', 'identifiers'):
        if key in props and not isinstance(props[key], str):
            props[key] = json.dumps(props[key])

    # Pre-validate team slug exists before executing the update to
    # prevent partial writes (SET p = $props commits even when a
    # subsequent strict MATCH on the team returns 0 rows).
    if data.team_slug:
        team_check: typing.LiteralString = """
        MATCH (t:Team {{slug: {team_slug}}})
              -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
        RETURN t.slug AS slug
        """
        team_records = await db.execute(
            team_check,
            {
                'team_slug': data.team_slug,
                'org_slug': org_slug,
            },
            ['slug'],
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
        MATCH (o:Organization {{slug: {org_slug}}})
        UNWIND {pt_slugs} AS pt_slug
        OPTIONAL MATCH (pt:ProjectType {{slug: pt_slug}})
                 -[:BELONGS_TO]->(o)
        RETURN pt_slug, pt IS NOT NULL AS found
        """
        pt_records = await db.execute(
            pt_check,
            {
                'org_slug': org_slug,
                'pt_slugs': json.dumps(
                    data.project_type_slugs,
                ),
            },
            ['pt_slug', 'found'],
        )
        missing = [
            graph.parse_agtype(r['pt_slug'])
            for r in pt_records
            if not graph.parse_agtype(r['found'])
        ]
        if missing:
            raise fastapi.HTTPException(
                status_code=422,
                detail=(
                    f'Project type slug(s) not found: {sorted(missing)!r}'
                ),
            )

    # Pre-validate that all environment slugs exist to avoid
    # dropping valid DEPLOYED_IN edges for unknown slugs.
    if data.environments is not None and data.environments:
        await _validate_env_slugs(
            db,
            org_slug,
            list(data.environments.keys()),
        )

    # Build update query with optional relationship changes
    rel_clauses: str = ''
    if data.team_slug:
        rel_clauses += """
    WITH p, o
    MATCH (new_t:Team {{slug: {new_team_slug}}})
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
    UNWIND {new_type_slugs} AS new_pt_slug
    MATCH (new_pt:ProjectType {{slug: new_pt_slug}})
          -[:BELONGS_TO]->(o)
    CREATE (p)-[:TYPE]->(new_pt)
    """
    new_env_entries = [
        {'slug': s, **ep} for s, ep in (data.environments or {}).items()
    ]
    new_env_tpl, new_env_params = _env_entries_template(
        new_env_entries,
    )
    new_edge_props_tpl = _edge_create_props(new_env_entries)

    if data.environments is not None:
        rel_clauses += (
            ' WITH DISTINCT p, o'
            ' OPTIONAL MATCH'
            ' (p)-[old_env:DEPLOYED_IN]->(:Environment)'
            ' DELETE old_env'
            ' WITH DISTINCT p, o'
            f' UNWIND CASE WHEN size({new_env_tpl}) = 0'
            f' THEN [null] ELSE {new_env_tpl}'
            ' END AS entry'
            ' OPTIONAL MATCH (e:Environment'
            ' {{slug: entry.slug}})-[:BELONGS_TO]->(o)'
            ' FOREACH (_ IN CASE WHEN e IS NOT NULL'
            ' THEN [1] ELSE [] END |'
            ' CREATE (p)-[:DEPLOYED_IN' + new_edge_props_tpl + ']->(e))'
        )

    set_clause = _set_clause('p', props)

    update_query: str = (
        """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    WITH DISTINCT p, o
    """
        + set_clause
        + rel_clauses
        + """
    WITH DISTINCT p, o
    """
        + _RETURN_FRAGMENT
    )

    try:
        updated = await db.execute(
            update_query,
            {
                'project_id': project_id,
                'org_slug': org_slug,
                **props,
                'new_team_slug': data.team_slug or '',
                'new_type_slugs': json.dumps(
                    data.project_type_slugs or [],
                ),
                **new_env_params,
            },
            ['project', 'outbound_count', 'inbound_count'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=str(e),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )

    project_data = graph.parse_agtype(updated[0]['project'])
    _flatten_edge_props(project_data)
    result = _add_relationships(
        project_data,
        org_slug,
        graph.parse_agtype(updated[0]['outbound_count']),
        graph.parse_agtype(updated[0]['inbound_count']),
    )
    return ProjectResponse.model_validate(result)


@projects_router.delete('/{project_id}', status_code=204)
async def delete_project(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:delete'),
        ),
    ],
) -> None:
    """Delete a project."""
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    DETACH DELETE p
    RETURN p
    """
    records = await db.execute(
        query,
        {
            'project_id': project_id,
            'org_slug': org_slug,
        },
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )
