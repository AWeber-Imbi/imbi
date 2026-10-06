"""Agent definition endpoints.

Agents are scoped to an organization and owned by a team. Only the
definition is stored; nothing runs an agent yet. The prompt CMS owns
the model and the model parameters: an agent names its prompt with
``prompt_ref`` (``namespace/slug@label``).

Each write that changes the configuration (create, PUT, PATCH,
restore) writes one immutable :class:`~imbi.common.models.AgentVersion`
and sets ``Agent.version`` to its number. A write that changes only
``enabled``, or that changes nothing, does not write a version.
"""

import datetime
import json
import logging
import typing

import fastapi
import nanoid
import pydantic

from imbi.api.auth import permissions
from imbi.api.endpoints._helpers import conflict_on_unique_violation
from imbi.api.graph_sql import props_template, set_clause
from imbi.common import graph, models
from imbi.common.graph import cypher as graph_cypher
from imbi.common import patch as json_patch
from imbi.common.prompts import resolve as prompt_resolve

LOGGER = logging.getLogger(__name__)

agents_router = fastapi.APIRouter(tags=['Agents'])

_READONLY_PATHS: frozenset[str] = frozenset(
    [
        '/id',
        '/organization',
        '/version',
        '/created_at',
        '/updated_at',
        '/updated_by',
        '/last_version_at',
    ]
)


def _check_prompt_ref(value: str | None) -> str | None:
    """Make sure that ``value`` parses as a prompt CMS reference.

    The prompt does not have to exist.
    """
    if value is not None:
        try:
            prompt_resolve.parse_ref(value)
        except prompt_resolve.InvalidRef as e:
            raise ValueError(str(e)) from e
    return value


PromptRef = typing.Annotated[
    str | None, pydantic.AfterValidator(_check_prompt_ref)
]


# --- Schemas -----------------------------------------------------------


class TeamRef(pydantic.BaseModel):
    name: str
    slug: str


class TagRef(pydantic.BaseModel):
    name: str
    slug: str
    color: str | None = None


class OrganizationRef(pydantic.BaseModel):
    name: str
    slug: str


class AgentSnapshot(pydantic.BaseModel):
    """The editable configuration of an agent, as a version stores it.

    ``team`` is a team slug and ``tags`` are tag slugs in sort order,
    so two snapshots of the same configuration compare equal.
    """

    model_config = pydantic.ConfigDict(extra='ignore')

    name: str
    slug: str
    description: str | None = None
    icon: str | None = None
    team: str
    tags: list[str] = []
    slack_channel: str | None = None
    prompt_ref: str | None = None
    settings: models.AgentSettings = pydantic.Field(
        default_factory=models.AgentSettings
    )


class AgentWrite(pydantic.BaseModel):
    """The full agent document that a create or a JSON Patch gives."""

    name: str = pydantic.Field(min_length=1)
    slug: str = pydantic.Field(min_length=1)
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    team: str = pydantic.Field(
        min_length=1, description='Slug of the owner team in the org.'
    )
    tags: list[str] = pydantic.Field(
        default=[],
        description='Tag slugs to attach. Must already exist in the org.',
    )
    enabled: bool = True
    slack_channel: str | None = None
    prompt_ref: PromptRef = pydantic.Field(
        default=None,
        description='Prompt CMS reference: namespace/slug@label.',
    )
    settings: models.AgentSettings = pydantic.Field(
        default_factory=models.AgentSettings
    )
    version_summary: str | None = pydantic.Field(
        default=None,
        description='Note for the version that this write creates.',
    )


class AgentCreate(AgentWrite):
    pass


class AgentUpdate(pydantic.BaseModel):
    """A whole-or-partial replace. Fields that are not set stay."""

    name: str | None = pydantic.Field(default=None, min_length=1)
    slug: str | None = pydantic.Field(default=None, min_length=1)
    description: str | None = None
    icon: pydantic.HttpUrl | str | None = None
    team: str | None = pydantic.Field(default=None, min_length=1)
    tags: list[str] | None = None
    enabled: bool | None = None
    slack_channel: str | None = None
    prompt_ref: PromptRef = None
    settings: models.AgentSettings | None = None
    version_summary: str | None = None


class AgentResponse(pydantic.BaseModel):
    id: str
    name: str
    slug: str
    description: str | None = None
    icon: str | None = None
    team: TeamRef | None = None
    tags: list[TagRef] = []
    enabled: bool = True
    slack_channel: str | None = None
    prompt_ref: str | None = None
    settings: models.AgentSettings = pydantic.Field(
        default_factory=models.AgentSettings
    )
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime | None = None
    #: The principal that wrote the newest version.
    updated_by: str | None = None
    #: When the newest version was written.
    last_version_at: datetime.datetime | None = None
    organization: OrganizationRef


class AgentVersionResponse(pydantic.BaseModel):
    n: int
    summary: str | None = None
    snapshot: AgentSnapshot
    created_by: str
    created_at: datetime.datetime


# --- Queries -----------------------------------------------------------

#: Every agent query ends with this tail. The newest version is found
#: with ``max()`` and then matched back, because Apache AGE loses an
#: ``ORDER BY`` in a ``WITH`` before an aggregation.
_AGENT_TAIL: typing.LiteralString = """
    OPTIONAL MATCH (v:AgentVersion)-[:VERSION_OF]->(a)
    WITH a, o, max(v.n) AS latest
    OPTIONAL MATCH (lv:AgentVersion)-[:VERSION_OF]->(a)
    WHERE lv.n = latest
    OPTIONAL MATCH (a)-[:OWNED_BY]->(t:Team)
    OPTIONAL MATCH (a)-[:TAGGED_WITH]->(tag:Tag)
    WITH a, o, t, lv, latest,
         collect(CASE WHEN tag IS NOT NULL
                      THEN tag{{.name, .slug, .color}}
                      END) AS raw_tags
    RETURN a, o, t, raw_tags AS tags, latest,
           lv.created_by AS updated_by,
           lv.created_at AS last_version_at
"""

_COLUMNS = [
    'a',
    'o',
    't',
    'tags',
    'latest',
    'updated_by',
    'last_version_at',
]

_GET_QUERY: typing.LiteralString = (
    """
    MATCH (a:Agent {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    """
    + _AGENT_TAIL
)

_LIST_QUERY: typing.LiteralString = (
    """
    MATCH (a:Agent)-[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    """
    + _AGENT_TAIL
)

_SLUG_TAKEN_QUERY: typing.LiteralString = """
MATCH (a:Agent {{slug: {slug}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN a.id AS id
"""

_TEAM_QUERY: typing.LiteralString = """
MATCH (o:Organization {{slug: {org_slug}}})
OPTIONAL MATCH (t:Team {{slug: {team_slug}}})-[:BELONGS_TO]->(o)
RETURN t.id AS team_id
"""

_DETACH_TEAM_QUERY: typing.LiteralString = """
MATCH (a:Agent {{id: {id}}})-[r:OWNED_BY]->(:Team)
DELETE r
RETURN count(r) AS removed
"""

_ATTACH_TEAM_QUERY: typing.LiteralString = """
MATCH (a:Agent {{id: {id}}}), (t:Team {{id: {team_id}}})
CREATE (a)-[:OWNED_BY]->(t)
RETURN t.id AS team_id
"""

_TAGS_FOUND_QUERY: typing.LiteralString = """
MATCH (o:Organization {{slug: {org_slug}}})
UNWIND {slugs} AS tag_slug
OPTIONAL MATCH (t:Tag {{slug: tag_slug}})-[:BELONGS_TO]->(o)
RETURN tag_slug, t IS NOT NULL AS found
"""

_DETACH_TAGS_QUERY: typing.LiteralString = """
MATCH (a:Agent {{id: {id}}})-[r:TAGGED_WITH]->(:Tag)
DELETE r
RETURN count(r) AS removed
"""

_ATTACH_TAGS_QUERY: typing.LiteralString = """
MATCH (a:Agent {{id: {id}}})-[:BELONGS_TO]->(o:Organization),
      (t:Tag)-[:BELONGS_TO]->(o)
WHERE t.slug IN {tag_slugs}
MERGE (a)-[:TAGGED_WITH]->(t)
RETURN count(t) AS attached
"""

_VERSIONS_QUERY: typing.LiteralString = """
MATCH (v:AgentVersion)-[:VERSION_OF]->(:Agent {{id: {id}}})
RETURN v
"""

_VERSION_QUERY: typing.LiteralString = """
MATCH (v:AgentVersion {{agent_id: {id}, n: {n}}})
      -[:VERSION_OF]->(:Agent {{id: {id}}})
RETURN v
"""

_DELETE_VERSIONS_QUERY: typing.LiteralString = """
MATCH (v:AgentVersion)-[:VERSION_OF]->(:Agent {{id: {id}}})
DETACH DELETE v
"""

_DELETE_AGENT_QUERY: typing.LiteralString = """
MATCH (a:Agent {{id: {id}}})
DETACH DELETE a
RETURN 1 AS deleted
"""

_DELETE_VERSION_QUERY: typing.LiteralString = """
MATCH (v:AgentVersion {{agent_id: {id}, n: {n}}})
DETACH DELETE v
"""


# --- Helpers -----------------------------------------------------------


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _props(raw: typing.Any) -> dict[str, typing.Any] | None:
    """Return an agtype vertex's properties, or ``None`` for a null."""
    parsed: typing.Any = graph.parse_agtype(raw)
    if not isinstance(parsed, dict):
        return None
    return typing.cast('dict[str, typing.Any]', parsed)


def _not_found(slug: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=404, detail=f'Agent with slug {slug!r} not found'
    )


def _unprocessable(detail: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(status_code=422, detail=detail)


def _settings_json(settings: models.AgentSettings) -> str:
    """Store settings as a JSON string, as Apache AGE needs."""
    return json.dumps(settings.model_dump(mode='json'))


def _parse_row(record: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Build an :class:`AgentResponse` payload from one graph row."""
    agent = _props(record['a']) or {}
    org = _props(record['o']) or {}
    team = _props(record['t'])
    raw_tags: list[typing.Any] = graph.parse_agtype(record['tags']) or []
    tags: list[dict[str, typing.Any]] = []
    for raw in raw_tags:
        if not isinstance(raw, dict):
            continue
        entry = typing.cast('dict[str, typing.Any]', raw)
        if not entry.get('slug'):
            continue
        tags.append(
            {
                'name': str(entry.get('name', '')),
                'slug': str(entry['slug']),
                'color': entry.get('color'),
            }
        )
    tags.sort(key=lambda t: str(t['slug']))
    settings: typing.Any = agent.get('settings')
    if isinstance(settings, str):
        settings = json.loads(settings)
    latest = graph.parse_agtype(record['latest'])
    return {
        **agent,
        'icon': None if agent.get('icon') is None else str(agent['icon']),
        'team': (
            None
            if team is None
            else {
                'name': str(team.get('name', '')),
                'slug': str(team.get('slug', '')),
            }
        ),
        'tags': tags,
        'settings': settings or {},
        'version': agent.get('version') or latest or 1,
        'updated_by': graph.parse_agtype(record['updated_by']),
        'last_version_at': graph.parse_agtype(record['last_version_at']),
        'organization': {
            'name': str(org.get('name', '')),
            'slug': str(org.get('slug', '')),
        },
        # Kept for the version writer; not part of the response model.
        '_latest': int(latest) if latest else 0,
    }


async def _fetch_agent(
    db: graph.Pool, org_slug: str, slug: str
) -> dict[str, typing.Any]:
    """Read one agent, or raise 404."""
    records = await db.execute(
        _GET_QUERY, {'slug': slug, 'org_slug': org_slug}, _COLUMNS
    )
    if not records:
        raise _not_found(slug)
    return _parse_row(records[0])


def _snapshot_of(agent: dict[str, typing.Any]) -> AgentSnapshot:
    """Build the snapshot of the configuration that is stored now."""
    team = typing.cast('dict[str, typing.Any] | None', agent.get('team'))
    tags = typing.cast('list[dict[str, typing.Any]]', agent.get('tags', []))
    return AgentSnapshot(
        name=agent['name'],
        slug=agent['slug'],
        description=agent.get('description'),
        icon=agent.get('icon'),
        team=str(team['slug']) if team else '',
        tags=sorted(str(t['slug']) for t in tags),
        slack_channel=agent.get('slack_channel'),
        prompt_ref=agent.get('prompt_ref'),
        settings=models.AgentSettings.model_validate(
            agent.get('settings') or {}
        ),
    )


def _snapshot_from(data: AgentWrite) -> AgentSnapshot:
    """Build a snapshot from a validated request document."""
    return AgentSnapshot(
        name=data.name,
        slug=data.slug,
        description=data.description,
        icon=None if data.icon is None else str(data.icon),
        team=data.team,
        tags=sorted(dict.fromkeys(data.tags)),
        slack_channel=data.slack_channel,
        prompt_ref=data.prompt_ref,
        settings=data.settings,
    )


def _current_document(agent: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Return the agent as an :class:`AgentWrite` document."""
    snapshot = _snapshot_of(agent)
    return {
        **snapshot.model_dump(mode='json'),
        'enabled': bool(agent.get('enabled', True)),
        'version_summary': None,
    }


def _slug_taken_detail(slug: str) -> str:
    return f'Agent with slug {slug!r} already exists'


async def _assert_slug_free(db: graph.Pool, org_slug: str, slug: str) -> None:
    """Raise 409 when the org has an agent with ``slug``.

    This check gives a fast, clear error. It is not sufficient by
    itself, because two concurrent requests can both pass it. The
    ``(org_id, slug)`` unique index stops the second write.
    """
    records = await db.execute(
        _SLUG_TAKEN_QUERY, {'slug': slug, 'org_slug': org_slug}, ['id']
    )
    if records:
        raise fastapi.HTTPException(
            status_code=409, detail=_slug_taken_detail(slug)
        )


async def _team_id(db: graph.Pool, org_slug: str, team_slug: str) -> str:
    """Return the id of a team in the org, or raise 404 or 422."""
    records = await db.execute(
        _TEAM_QUERY,
        {'org_slug': org_slug, 'team_slug': team_slug},
        ['team_id'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization with slug {org_slug!r} not found',
        )
    team_id = graph.parse_agtype(records[0]['team_id'])
    if not team_id:
        raise _unprocessable(f'Team {team_slug!r} not found')
    return str(team_id)


async def _validate_tag_slugs(
    db: graph.Pool, org_slug: str, tag_slugs: list[str]
) -> None:
    """Raise 422 when a tag slug is not in the org."""
    if not tag_slugs:
        return
    records = await db.execute(
        _TAGS_FOUND_QUERY,
        {'org_slug': org_slug, 'slugs': tag_slugs},
        ['tag_slug', 'found'],
    )
    missing = [
        graph.parse_agtype(r['tag_slug'])
        for r in records
        if not graph.parse_agtype(r['found'])
    ]
    if missing:
        raise _unprocessable(f'Tag slug(s) not found: {sorted(missing)!r}')


async def _replace_tags(
    db: graph.Pool, agent_id: str, tag_slugs: list[str]
) -> None:
    await db.execute(_DETACH_TAGS_QUERY, {'id': agent_id}, ['removed'])
    if tag_slugs:
        await db.execute(
            _ATTACH_TAGS_QUERY,
            {'id': agent_id, 'tag_slugs': tag_slugs},
            ['attached'],
        )


async def _write_version(
    db: graph.Pool,
    agent_id: str,
    n: int,
    snapshot: AgentSnapshot,
    summary: str | None,
    created_by: str,
) -> None:
    """Write version ``n``, or raise 409 when it exists already."""
    props: dict[str, typing.Any] = {
        'id': nanoid.generate(),
        'agent_id': agent_id,
        'n': n,
        'summary': summary,
        'snapshot': json.dumps(snapshot.model_dump(mode='json')),
        'created_by': created_by,
        'created_at': _now(),
    }
    query = (
        'MATCH (a:Agent {{id: {agent_id}}})'
        f' CREATE (v:AgentVersion {props_template(props)})'
        ' CREATE (v)-[:VERSION_OF]->(a)'
        ' RETURN v.n AS n'
    )
    with conflict_on_unique_violation(
        f'Version {n} of this agent was saved by another request; '
        'reload the agent and try again'
    ):
        await db.execute(query, props, ['n'])


async def _apply(
    db: graph.Pool,
    org_slug: str,
    existing: dict[str, typing.Any],
    target: AgentSnapshot,
    enabled: bool,
    summary: str | None,
    principal: str,
) -> dict[str, typing.Any]:
    """Write ``target`` and ``enabled`` over the stored agent.

    A new version is written only when the snapshot changes.
    """
    current = _snapshot_of(existing)
    config_changed = target != current
    enabled_changed = enabled != bool(existing.get('enabled', True))
    if not config_changed and not enabled_changed:
        return existing

    agent_id = str(existing['id'])
    props: dict[str, typing.Any] = {'enabled': enabled, 'updated_at': _now()}
    team_id: str | None = None
    n: int | None = None
    if config_changed:
        if target.slug != current.slug:
            await _assert_slug_free(db, org_slug, target.slug)
        if target.team != current.team:
            team_id = await _team_id(db, org_slug, target.team)
        if target.tags != current.tags:
            await _validate_tag_slugs(db, org_slug, target.tags)
        n = int(existing['_latest']) + 1
        # The version is written first. Its unique index stops a
        # concurrent save before that save changes the agent.
        await _write_version(db, agent_id, n, target, summary, principal)
        props.update(
            {
                'name': target.name,
                'slug': target.slug,
                'description': target.description,
                'icon': target.icon,
                'slack_channel': target.slack_channel,
                'prompt_ref': target.prompt_ref,
                'settings': _settings_json(target.settings),
                'version': n,
            }
        )

    # The properties are set before the edges change. If the write
    # fails for any reason (for example, the ``(org_id, slug)`` unique
    # index), only the new version must be removed.
    query = (
        'MATCH (a:Agent {{id: {agent_id}}})'
        f' {set_clause("a", props)}'
        ' RETURN a.slug AS slug'
    )
    try:
        with conflict_on_unique_violation(_slug_taken_detail(target.slug)):
            records = await db.execute(
                query, {**props, 'agent_id': agent_id}, ['slug']
            )
    except Exception:
        if n is not None:
            await db.execute(
                _DELETE_VERSION_QUERY, {'id': agent_id, 'n': n}, []
            )
        raise
    if not records:
        raise _not_found(str(existing['slug']))

    if team_id is not None:
        await db.execute(_DETACH_TEAM_QUERY, {'id': agent_id}, ['removed'])
        await db.execute(
            _ATTACH_TEAM_QUERY,
            {'id': agent_id, 'team_id': team_id},
            ['team_id'],
        )
    if config_changed and target.tags != current.tags:
        await _replace_tags(db, agent_id, target.tags)
    return await _fetch_agent(db, org_slug, target.slug)


# --- Agent endpoints ---------------------------------------------------


@agents_router.post('/', status_code=201, response_model=AgentResponse)
async def create_agent(
    org_slug: str,
    data: AgentCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent:create')),
    ],
) -> dict[str, typing.Any]:
    """Create an agent in ``org_slug`` and write its version 1.

    Raises:
        404: No such organization.
        409: The org has an agent with this slug.
        422: The team or a tag is not in the org, or ``prompt_ref``
            does not parse.

    """
    snapshot = _snapshot_from(data)
    team_id = await _team_id(db, org_slug, data.team)
    await _validate_tag_slugs(db, org_slug, snapshot.tags)
    await _assert_slug_free(db, org_slug, data.slug)

    now = _now()
    agent_id = nanoid.generate()
    props: dict[str, typing.Any] = {
        'id': agent_id,
        'name': snapshot.name,
        'slug': snapshot.slug,
        'description': snapshot.description,
        'icon': snapshot.icon,
        'enabled': data.enabled,
        'slack_channel': snapshot.slack_channel,
        'prompt_ref': snapshot.prompt_ref,
        'settings': _settings_json(snapshot.settings),
        'version': 1,
        'created_at': now,
        'updated_at': now,
    }
    # ``org_id`` is copied from the organization so that the
    # ``(org_id, slug)`` unique index stops a concurrent create.
    query = (
        'MATCH (o:Organization {{slug: {org_slug}}}),'
        ' (t:Team {{id: {team_id}}})'
        f' CREATE (a:Agent {props_template(props)})'
        ' SET a.org_id = o.id'
        ' CREATE (a)-[:BELONGS_TO]->(o)'
        ' CREATE (a)-[:OWNED_BY]->(t)'
        ' RETURN a.id AS id'
    )
    with conflict_on_unique_violation(_slug_taken_detail(snapshot.slug)):
        records = await db.execute(
            query,
            {**props, 'org_slug': org_slug, 'team_id': team_id},
            ['id'],
        )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization with slug {org_slug!r} not found',
        )
    # The graph has no transaction across these writes. If a write
    # fails, remove the agent, so that no agent exists without its
    # version 1.
    try:
        if snapshot.tags:
            await db.execute(
                _ATTACH_TAGS_QUERY,
                {'id': agent_id, 'tag_slugs': snapshot.tags},
                ['attached'],
            )
        await _write_version(
            db,
            agent_id,
            1,
            snapshot,
            data.version_summary,
            auth.principal_name,
        )
    except Exception:
        LOGGER.warning('Removing agent %s after a failed create', agent_id)
        await db.execute(_DELETE_VERSIONS_QUERY, {'id': agent_id}, [])
        await db.execute(_DELETE_AGENT_QUERY, {'id': agent_id}, ['deleted'])
        raise
    return await _fetch_agent(db, org_slug, snapshot.slug)


@agents_router.get('/', response_model=list[AgentResponse])
async def list_agents(
    org_slug: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent:read')),
    ],
) -> list[dict[str, typing.Any]]:
    """List the agents in an organization, by name."""
    records = await db.execute(_LIST_QUERY, {'org_slug': org_slug}, _COLUMNS)
    agents = [_parse_row(record) for record in records]
    agents.sort(key=lambda a: str(a.get('name', '')).lower())
    return agents


@agents_router.get('/{slug}', response_model=AgentResponse)
async def get_agent(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent:read')),
    ],
) -> dict[str, typing.Any]:
    """Get an agent by slug."""
    return await _fetch_agent(db, org_slug, slug)


@agents_router.put('/{slug}', response_model=AgentResponse)
async def update_agent(
    org_slug: str,
    slug: str,
    data: AgentUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent:write')),
    ],
) -> dict[str, typing.Any]:
    """Update an agent (whole-or-partial replace).

    Fields that are not in the body keep their values.
    """
    existing = await _fetch_agent(db, org_slug, slug)
    document = _current_document(existing)
    document.update(data.model_dump(exclude_unset=True))
    try:
        merged = AgentWrite.model_validate(document)
    except pydantic.ValidationError as e:
        raise _unprocessable(f'Validation error: {e.errors()}') from e
    return await _apply(
        db,
        org_slug,
        existing,
        _snapshot_from(merged),
        merged.enabled,
        merged.version_summary,
        auth.principal_name,
    )


@agents_router.patch('/{slug}', response_model=AgentResponse)
async def patch_agent(
    org_slug: str,
    slug: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent:write')),
    ],
) -> dict[str, typing.Any]:
    """Partially update an agent with JSON Patch (RFC 6902).

    ``/team`` is a team slug and ``/tags`` a list of tag slugs. Add
    ``/version_summary`` to put a note on the version.
    """
    existing = await _fetch_agent(db, org_slug, slug)
    patched = json_patch.apply_patch(
        _current_document(existing), operations, _READONLY_PATHS
    )
    # apply_patch does not know the types, so validate again.
    try:
        merged = AgentWrite.model_validate(patched)
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=400, detail=f'Validation error: {e.errors()}'
        ) from e
    return await _apply(
        db,
        org_slug,
        existing,
        _snapshot_from(merged),
        merged.enabled,
        merged.version_summary,
        auth.principal_name,
    )


@agents_router.delete('/{slug}', status_code=204)
async def delete_agent(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent:delete')),
    ],
) -> None:
    """Delete an agent and every version of it."""
    records = await db.execute(
        _SLUG_TAKEN_QUERY, {'slug': slug, 'org_slug': org_slug}, ['id']
    )
    if not records:
        raise _not_found(slug)
    params = {'id': str(graph.parse_agtype(records[0]['id']))}
    # One transaction: the versions and the agent go together, or
    # neither goes. ``_execute_batch`` is the transactional primitive
    # that other endpoints also use.
    await db._execute_batch(  # pyright: ignore[reportPrivateUsage]
        [
            graph_cypher.Statement(_DELETE_VERSIONS_QUERY, params),
            graph_cypher.Statement(_DELETE_AGENT_QUERY, params),
        ]
    )


# --- Version endpoints -------------------------------------------------


def _version_response(props: dict[str, typing.Any]) -> AgentVersionResponse:
    snapshot: typing.Any = props.get('snapshot') or {}
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    return AgentVersionResponse(
        n=int(props['n']),
        summary=props.get('summary'),
        snapshot=AgentSnapshot.model_validate(snapshot),
        created_by=str(props.get('created_by', '')),
        created_at=props['created_at'],
    )


async def _fetch_version(
    db: graph.Pool, agent_id: str, n: int
) -> AgentVersionResponse:
    """Read version ``n`` of an agent, or raise 404."""
    records = await db.execute(_VERSION_QUERY, {'id': agent_id, 'n': n}, ['v'])
    props = _props(records[0]['v']) if records else None
    if props is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Version {n} not found'
        )
    return _version_response(props)


@agents_router.get(
    '/{slug}/versions', response_model=list[AgentVersionResponse]
)
async def list_agent_versions(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent:read')),
    ],
) -> list[AgentVersionResponse]:
    """List every version of an agent, newest first."""
    agent = await _fetch_agent(db, org_slug, slug)
    records = await db.execute(_VERSIONS_QUERY, {'id': agent['id']}, ['v'])
    versions = [
        _version_response(props)
        for record in records
        if (props := _props(record['v'])) is not None
    ]
    versions.sort(key=lambda v: v.n, reverse=True)
    return versions


@agents_router.get('/{slug}/versions/{n}', response_model=AgentVersionResponse)
async def get_agent_version(
    org_slug: str,
    slug: str,
    n: int,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent:read')),
    ],
) -> AgentVersionResponse:
    """Get one version of an agent."""
    agent = await _fetch_agent(db, org_slug, slug)
    return await _fetch_version(db, str(agent['id']), n)


@agents_router.post(
    '/{slug}/versions/{n}/restore', response_model=AgentResponse
)
async def restore_agent_version(
    org_slug: str,
    slug: str,
    n: int,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent:write')),
    ],
) -> dict[str, typing.Any]:
    """Apply the snapshot of version ``n`` and write a new version.

    The new version has the summary ``Restored v{n}``. When the
    snapshot is the same as the configuration now, nothing is written.
    ``enabled`` does not change.

    Raises:
        404: No such agent or version.
        409: The snapshot slug is taken by another agent.
        422: The snapshot team or a snapshot tag no longer exists.

    """
    existing = await _fetch_agent(db, org_slug, slug)
    version = await _fetch_version(db, str(existing['id']), n)
    return await _apply(
        db,
        org_slug,
        existing,
        version.snapshot,
        bool(existing.get('enabled', True)),
        f'Restored v{n}',
        auth.principal_name,
    )
