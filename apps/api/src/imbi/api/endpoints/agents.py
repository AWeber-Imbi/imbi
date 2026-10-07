"""Agent definition endpoints.

Agents are scoped to an organization and owned by a team. Only the
definition is stored; nothing runs an agent yet. The prompt CMS owns
the model and the model parameters: an agent names its prompt with
``prompt_ref`` (``namespace/slug@label``) and records the prompt
version that its configuration uses in ``prompt_version``.

Each write that changes the configuration (create, PUT, PATCH,
restore) writes one immutable :class:`~imbi.common.models.AgentVersion`
and sets ``Agent.version`` to its number. A write that changes only
``enabled``, or that changes nothing, does not write a version. A
restore also moves the prompt label back to the recorded prompt
version, so the system prompt and the model come back too.

Each agent is its own service principal (ADR 0020): a
``ServiceAccount`` that is ``MEMBER_OF`` the organization, with an
``ACTS_AS`` edge from the agent. It is made with the agent and deleted
with it. It has no role, so it has no permissions.
"""

import datetime
import json
import logging
import typing

import fastapi
import nanoid
import psycopg.errors
import pydantic

from imbi.api import agent_tools
from imbi.api.auth import permissions
from imbi.api.endpoints import prompts
from imbi.api.endpoints._helpers import conflict_on_unique_violation
from imbi.api.graph_sql import props_template, set_clause
from imbi.api.scoring import OptionalValkeyClient
from imbi.common import graph, models
from imbi.common import patch as json_patch
from imbi.common.graph import cypher as graph_cypher
from imbi.common.prompts import resolve as prompt_resolve

LOGGER = logging.getLogger(__name__)

agents_router = fastapi.APIRouter(tags=['Agents'])

#: The prompt CMS namespace that holds the prompts the UI makes for
#: agents (``agents/<slug>``). Restore moves labels only in it.
AGENT_PROMPT_NAMESPACE = 'agents'

#: The tool configuration of an agent, by tool key.
AgentTools = dict[models.AgentToolKey, models.AgentToolConfig]


def _check_subagents(
    value: list[models.AgentSubagent],
) -> list[models.AgentSubagent]:
    """Make sure that no target agent is in the list two times."""
    seen: set[str] = set()
    duplicates_found: set[str] = set()
    for item in value:
        if item.agent_id in seen:
            duplicates_found.add(item.agent_id)
        seen.add(item.agent_id)
    duplicates = sorted(duplicates_found)
    if duplicates:
        raise ValueError(f'Duplicate subagent id(s): {duplicates!r}')
    return value


#: The agents that an agent can delegate to, in order.
AgentSubagents = typing.Annotated[
    list[models.AgentSubagent], pydantic.AfterValidator(_check_subagents)
]

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


# The ``Agent`` prefix keeps these schema names unique in the OpenAPI
# document. Other endpoints have a different ``TeamRef`` and ``TagRef``.
class AgentTeamRef(pydantic.BaseModel):
    name: str
    slug: str


class AgentTagRef(pydantic.BaseModel):
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
    prompt_version: int | None = pydantic.Field(default=None, gt=0)
    settings: models.AgentSettings = pydantic.Field(
        default_factory=models.AgentSettings
    )
    tools: AgentTools = {}
    subagents: list[models.AgentSubagent] = []


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
    prompt_version: int | None = pydantic.Field(
        default=None,
        gt=0,
        description='The prompt CMS version that the agent uses.',
    )
    settings: models.AgentSettings = pydantic.Field(
        default_factory=models.AgentSettings
    )
    tools: AgentTools = pydantic.Field(
        default={},
        description=(
            'The tools that the agent can use, by tool key '
            '(<server slug>.<tool name>). A tool that is not in the map '
            'is off. Environment slugs must exist in the org.'
        ),
    )
    subagents: AgentSubagents = pydantic.Field(
        default=[],
        description=(
            'The agents that this agent can delegate to, in order, by '
            'agent id. Each must be another agent in the org.'
        ),
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
    prompt_version: int | None = pydantic.Field(default=None, gt=0)
    settings: models.AgentSettings | None = None
    tools: AgentTools | None = None
    subagents: AgentSubagents | None = None
    version_summary: str | None = None


class AgentSubagentRef(pydantic.BaseModel):
    """A subagent of an agent, with the target agent's details."""

    agent_id: str
    slug: str
    name: str
    icon: str | None = None
    version: int
    tool_count: int
    instructions: str = ''


class AgentResponse(pydantic.BaseModel):
    id: str
    name: str
    slug: str
    description: str | None = None
    icon: str | None = None
    team: AgentTeamRef | None = None
    tags: list[AgentTagRef] = []
    enabled: bool = True
    slack_channel: str | None = None
    prompt_ref: str | None = None
    prompt_version: int | None = None
    settings: models.AgentSettings = pydantic.Field(
        default_factory=models.AgentSettings
    )
    tools: AgentTools = {}
    #: A target agent that no longer exists is not in the list.
    subagents: list[AgentSubagentRef] = []
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

_ENVIRONMENTS_FOUND_QUERY: typing.LiteralString = """
MATCH (o:Organization {{slug: {org_slug}}})
UNWIND {slugs} AS env_slug
OPTIONAL MATCH (e:Environment {{slug: env_slug}})-[:BELONGS_TO]->(o)
RETURN env_slug, e IS NOT NULL AS found
"""

_SUBAGENTS_FOUND_QUERY: typing.LiteralString = """
MATCH (o:Organization {{slug: {org_slug}}})
UNWIND {ids} AS agent_id
OPTIONAL MATCH (s:Agent {{id: agent_id}})-[:BELONGS_TO]->(o)
RETURN agent_id, s
"""

_DELEGATORS_QUERY: typing.LiteralString = """
MATCH (a:Agent)-[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
WHERE a.id <> {id}
RETURN a.name AS name, a.slug AS slug, a.subagents AS subagents
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

#: Deletes the agent, its service account, and the credentials of
#: the service account.
_DELETE_AGENT_QUERY: typing.LiteralString = """
MATCH (a:Agent {{id: {id}}})
OPTIONAL MATCH (a)-[:ACTS_AS]->(s:ServiceAccount)
OPTIONAL MATCH (s)<-[:OWNED_BY]-(c)
DETACH DELETE c, s, a
RETURN 1 AS deleted
"""

#: Makes the service account of agent ``a`` in organization ``o``.
_CREATE_SERVICE_ACCOUNT: typing.LiteralString = """
CREATE (s:ServiceAccount {{id: {sa_id}, slug: {sa_slug},
                          display_name: {sa_display_name},
                          description: {sa_description},
                          is_active: true, created_at: {sa_created_at}}})
CREATE (s)-[:MEMBER_OF]->(o)
CREATE (a)-[:ACTS_AS]->(s)
"""

_SERVICE_ACCOUNT_QUERY: typing.LiteralString = """
MATCH (:Agent {{id: {id}}})-[:ACTS_AS]->(s:ServiceAccount)
RETURN s.id AS id
"""

_ENSURE_SERVICE_ACCOUNT_QUERY: typing.LiteralString = (
    """
    MATCH (a:Agent {{id: {id}}})-[:BELONGS_TO]->(o:Organization)
    """
    + _CREATE_SERVICE_ACCOUNT
    + """
    RETURN s.id AS id
    """
)


# --- Helpers -----------------------------------------------------------


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _props(raw: typing.Any) -> dict[str, typing.Any] | None:
    """Return an agtype vertex's properties, or ``None`` for a null."""
    parsed: typing.Any = graph.parse_agtype(raw)
    if not isinstance(parsed, dict):
        return None
    return typing.cast('dict[str, typing.Any]', parsed)


def _service_account_params(agent_id: str, name: str) -> dict[str, typing.Any]:
    """Return the parameters of :data:`_CREATE_SERVICE_ACCOUNT`.

    The slug comes from the agent id, which does not change, so two
    requests that make the same service account collide on the unique
    slug index.
    """
    return {
        'sa_id': nanoid.generate(),
        'sa_slug': f'agent-{agent_id}',
        'sa_display_name': name,
        'sa_description': f'Service principal of the agent {name!r}',
        'sa_created_at': _now(),
    }


async def ensure_service_account(
    db: graph.Graph, agent_id: str, name: str
) -> str:
    """Return the id of the agent's service account.

    Make the service account when the agent has none. Agents made before
    service accounts existed get one here, so no backfill is necessary.
    """
    records = await db.execute(
        _SERVICE_ACCOUNT_QUERY, {'id': agent_id}, ['id']
    )
    if not records:
        try:
            records = await db.execute(
                _ENSURE_SERVICE_ACCOUNT_QUERY,
                {'id': agent_id, **_service_account_params(agent_id, name)},
                ['id'],
            )
        except psycopg.errors.UniqueViolation:
            # A concurrent request made it first.
            records = await db.execute(
                _SERVICE_ACCOUNT_QUERY, {'id': agent_id}, ['id']
            )
    if not records:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Agent {name!r} not found'
        )
    return str(graph.parse_agtype(records[0]['id']))


def _not_found(slug: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=404, detail=f'Agent with slug {slug!r} not found'
    )


def _unprocessable(detail: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(status_code=422, detail=detail)


def _settings_json(settings: models.AgentSettings) -> str:
    """Store settings as a JSON string, as Apache AGE needs."""
    return json.dumps(settings.model_dump(mode='json'))


def _tools_json(tools: AgentTools) -> str:
    """Store the tools as a JSON string, as Apache AGE needs."""
    return json.dumps(
        {
            key: config.model_dump(mode='json')
            for key, config in sorted(tools.items())
        }
    )


def _subagents_json(subagents: list[models.AgentSubagent]) -> str:
    """Store the subagents as a JSON string, as Apache AGE needs."""
    return json.dumps([item.model_dump(mode='json') for item in subagents])


def _json_value(value: typing.Any) -> typing.Any:
    return json.loads(value) if isinstance(value, str) else value


def _stored_subagents(value: typing.Any) -> list[models.AgentSubagent]:
    """Parse the stored subagents of an agent."""
    return pydantic.TypeAdapter(list[models.AgentSubagent]).validate_python(
        _json_value(value) or []
    )


def _subagent_ref(
    item: models.AgentSubagent, target: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    """Build an :class:`AgentSubagentRef` payload."""
    tools: dict[str, typing.Any] = _json_value(target.get('tools')) or {}
    return {
        'agent_id': item.agent_id,
        'slug': str(target.get('slug', '')),
        'name': str(target.get('name', '')),
        'icon': None if target.get('icon') is None else str(target['icon']),
        'version': int(target.get('version') or 1),
        'tool_count': len(tools),
        'instructions': item.instructions,
    }


def _resolve_subagents(
    agent: dict[str, typing.Any], targets: dict[str, dict[str, typing.Any]]
) -> None:
    """Set ``subagents`` in a response payload from ``targets``.

    ``targets`` holds agent properties by id. A target that is not in
    it no longer exists and is not in the response.
    """
    agent['subagents'] = [
        _subagent_ref(item, targets[item.agent_id])
        for item in agent['_subagents']
        if item.agent_id in targets
    ]


async def _find_subagents(
    db: graph.Pool, org_slug: str, ids: list[str]
) -> dict[str, dict[str, typing.Any]]:
    """Return the agents of the org that have one of ``ids``, by id."""
    if not ids:
        return {}
    records = await db.execute(
        _SUBAGENTS_FOUND_QUERY,
        {'org_slug': org_slug, 'ids': sorted(set(ids))},
        ['agent_id', 's'],
    )
    found: dict[str, dict[str, typing.Any]] = {}
    for record in records:
        props = _props(record['s'])
        if props is not None:
            found[str(graph.parse_agtype(record['agent_id']))] = props
    return found


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
        'settings': _json_value(agent.get('settings')) or {},
        'tools': _json_value(agent.get('tools')) or {},
        # The caller sets the response list from these.
        'subagents': [],
        '_subagents': _stored_subagents(agent.get('subagents')),
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
    agent = _parse_row(records[0])
    stored: list[models.AgentSubagent] = agent['_subagents']
    _resolve_subagents(
        agent,
        await _find_subagents(db, org_slug, [s.agent_id for s in stored]),
    )
    return agent


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
        prompt_version=agent.get('prompt_version'),
        settings=models.AgentSettings.model_validate(
            agent.get('settings') or {}
        ),
        tools=pydantic.TypeAdapter(AgentTools).validate_python(
            agent.get('tools') or {}
        ),
        subagents=agent.get('_subagents') or [],
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
        prompt_version=data.prompt_version,
        settings=data.settings,
        tools=data.tools,
        subagents=data.subagents,
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


async def _validate_tool_environments(
    db: graph.Pool, org_slug: str, tools: AgentTools
) -> None:
    """Raise 422 when a tool names an environment that is not in the org.

    The tool keys are not checked, because a tool server can be
    offline when the agent is saved.
    """
    slugs = sorted(
        {
            slug
            for config in tools.values()
            for slug in config.environments or []
        }
    )
    if not slugs:
        return
    records = await db.execute(
        _ENVIRONMENTS_FOUND_QUERY,
        {'org_slug': org_slug, 'slugs': slugs},
        ['env_slug', 'found'],
    )
    missing = [
        graph.parse_agtype(r['env_slug'])
        for r in records
        if not graph.parse_agtype(r['found'])
    ]
    if missing:
        raise _unprocessable(
            f'Environment slug(s) not found: {sorted(missing)!r}'
        )


async def _validate_subagents(
    db: graph.Pool,
    org_slug: str,
    agent_id: str | None,
    subagents: list[models.AgentSubagent],
) -> None:
    """Raise 422 when a subagent is the agent itself or not in the org.

    Cycles are allowed: the runtime caps the delegation depth.
    """
    ids = [item.agent_id for item in subagents]
    if agent_id is not None and agent_id in ids:
        raise _unprocessable('An agent cannot be its own subagent')
    found = await _find_subagents(db, org_slug, ids)
    missing = sorted(set(ids) - set(found))
    if missing:
        raise _unprocessable(f'Subagent id(s) not found: {missing!r}')


def _version_conflict_detail(n: int) -> str:
    return (
        f'Version {n} of this agent was saved by another request; '
        'reload the agent and try again'
    )


def _version_statement(
    agent_id: str,
    n: int,
    snapshot: AgentSnapshot,
    summary: str | None,
    created_by: str,
) -> graph_cypher.Statement:
    """Return the statement that writes version ``n`` of an agent."""
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
    return graph_cypher.Statement(query, props)


async def _write_version(
    db: graph.Pool,
    agent_id: str,
    n: int,
    snapshot: AgentSnapshot,
    summary: str | None,
    created_by: str,
) -> None:
    """Write version ``n``, or raise 409 when it exists already."""
    stmt = _version_statement(agent_id, n, snapshot, summary, created_by)
    with conflict_on_unique_violation(_version_conflict_detail(n)):
        await db.execute(stmt.cypher, stmt.params, ['n'])


async def _apply(
    db: graph.Pool,
    org_slug: str,
    existing: dict[str, typing.Any],
    target: AgentSnapshot,
    enabled: bool,
    summary: str | None,
    principal: str,
    label_move: graph_cypher.Statement | None = None,
) -> dict[str, typing.Any]:
    """Write ``target`` and ``enabled`` over the stored agent.

    A new version is written only when the snapshot changes. All the
    writes, and ``label_move`` when it is given, run in one
    transaction.
    """
    current = _snapshot_of(existing)
    config_changed = target != current
    enabled_changed = enabled != bool(existing.get('enabled', True))
    if not config_changed and not enabled_changed:
        if label_move is not None:
            await _execute(db, [label_move], None, target, current)
        return existing

    agent_id = str(existing['id'])
    ids = {'id': agent_id}
    props: dict[str, typing.Any] = {'enabled': enabled, 'updated_at': _now()}
    statements: list[graph_cypher.Statement] = []
    if label_move is not None:
        statements.append(label_move)
    n: int | None = None
    if config_changed:
        if target.slug != current.slug:
            await _assert_slug_free(db, org_slug, target.slug)
        team_id: str | None = None
        if target.team != current.team:
            team_id = await _team_id(db, org_slug, target.team)
        if target.tags != current.tags:
            await _validate_tag_slugs(db, org_slug, target.tags)
        if target.tools != current.tools:
            await _validate_tool_environments(db, org_slug, target.tools)
        if target.subagents != current.subagents:
            await _validate_subagents(db, org_slug, agent_id, target.subagents)
        n = int(existing['_latest']) + 1
        # The version is written first. Its unique index stops a
        # concurrent save before that save changes the agent.
        statements.append(
            _version_statement(agent_id, n, target, summary, principal)
        )
        if team_id is not None:
            statements += [
                graph_cypher.Statement(_DETACH_TEAM_QUERY, ids),
                graph_cypher.Statement(
                    _ATTACH_TEAM_QUERY, {**ids, 'team_id': team_id}
                ),
            ]
        if target.tags != current.tags:
            statements.append(graph_cypher.Statement(_DETACH_TAGS_QUERY, ids))
            if target.tags:
                statements.append(
                    graph_cypher.Statement(
                        _ATTACH_TAGS_QUERY, {**ids, 'tag_slugs': target.tags}
                    )
                )
        props.update(
            {
                'name': target.name,
                'slug': target.slug,
                'description': target.description,
                'icon': target.icon,
                'slack_channel': target.slack_channel,
                'prompt_ref': target.prompt_ref,
                'prompt_version': target.prompt_version,
                'settings': _settings_json(target.settings),
                'tools': _tools_json(target.tools),
                'subagents': _subagents_json(target.subagents),
                'version': n,
            }
        )

    statements.append(
        graph_cypher.Statement(
            'MATCH (a:Agent {{id: {agent_id}}})'
            f' {set_clause("a", props)}'
            ' RETURN a.slug AS slug',
            {**props, 'agent_id': agent_id},
        )
    )
    await _execute(db, statements, n, target, current)
    return await _fetch_agent(db, org_slug, target.slug)


async def _execute(
    db: graph.Pool,
    statements: list[graph_cypher.Statement],
    n: int | None,
    target: AgentSnapshot,
    current: AgentSnapshot,
) -> None:
    """Run the statements of :func:`_apply` in one transaction.

    The version, the properties, the edges, and a label move are all
    written, or none is. If the agent was deleted, every agent MATCH
    finds nothing, nothing is written, and the next read gives 404.
    """
    try:
        await db._execute_batch(statements)  # pyright: ignore[reportPrivateUsage]
    except graph.StatementMatchedNothing as exc:
        # Only the label move expects rows.
        raise fastapi.HTTPException(
            status_code=409, detail=prompts.PROMPT_CHANGED_DETAIL
        ) from exc
    except psycopg.errors.UniqueViolation as exc:
        if n is not None and (
            target.slug == current.slug
            or exc.diag.table_name == 'AgentVersion'
        ):
            detail = _version_conflict_detail(n)
        else:
            detail = _slug_taken_detail(target.slug)
        raise fastapi.HTTPException(status_code=409, detail=detail) from exc


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
        422: The team, a tag, a tool environment, or a subagent is not
            in the org, a subagent is given two times, or
            ``prompt_ref`` does not parse.

    """
    snapshot = _snapshot_from(data)
    team_id = await _team_id(db, org_slug, data.team)
    await _validate_tag_slugs(db, org_slug, snapshot.tags)
    await _validate_tool_environments(db, org_slug, snapshot.tools)
    await _validate_subagents(db, org_slug, None, snapshot.subagents)
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
        'prompt_version': snapshot.prompt_version,
        'settings': _settings_json(snapshot.settings),
        'tools': _tools_json(snapshot.tools),
        'subagents': _subagents_json(snapshot.subagents),
        'version': 1,
        'created_at': now,
        'updated_at': now,
    }
    # ``org_id`` is copied from the organization so that the
    # ``(org_id, slug)`` unique index stops a concurrent create. The
    # service account is made in the same statement. A duplicate gets
    # its own service account, because it is a new agent.
    query = (
        'MATCH (o:Organization {{slug: {org_slug}}}),'
        ' (t:Team {{id: {team_id}}})'
        f' CREATE (a:Agent {props_template(props)})'
        ' SET a.org_id = o.id'
        ' CREATE (a)-[:BELONGS_TO]->(o)'
        ' CREATE (a)-[:OWNED_BY]->(t)'
        + _CREATE_SERVICE_ACCOUNT
        + ' RETURN a.id AS id'
    )
    with conflict_on_unique_violation(_slug_taken_detail(snapshot.slug)):
        records = await db.execute(
            query,
            {
                **props,
                **_service_account_params(agent_id, snapshot.name),
                'org_slug': org_slug,
                'team_id': team_id,
            },
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
    # The org's agents are all here, so no other query is necessary.
    targets = {str(a['id']): a for a in agents}
    for agent in agents:
        _resolve_subagents(agent, targets)
    agents.sort(key=lambda a: str(a.get('name', '')).lower())
    return agents


@agents_router.get(
    '/tool-catalog', response_model=agent_tools.AgentToolCatalog
)
async def get_agent_tool_catalog(
    org_slug: str,
    request: fastapi.Request,
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent:read')),
    ],
    refresh: bool = False,
) -> agent_tools.AgentToolCatalog:
    """List the tools that an agent can use, in groups by server.

    The groups are the Imbi tools and the tools of each enabled MCP
    server. A server that fails gives its group with an error code in
    ``error`` and no tools. The error text goes only to the log. The
    catalog is kept for five minutes; ``refresh=true`` lists it again.
    A refresh connects to each MCP server, so it needs
    ``agent:write``. The catalog is the same in each organization,
    because MCP servers are global.

    Raises:
        403: ``refresh=true`` and the caller does not have
            ``agent:write``.

    """
    _ = org_slug
    if refresh and not (auth.is_admin or 'agent:write' in auth.permissions):
        raise fastapi.HTTPException(
            status_code=403,
            detail='Permission denied: refresh needs agent:write',
        )
    return await agent_tools.get_catalog(
        db, valkey_client, request.app.openapi, refresh=refresh
    )


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
    """Delete an agent, every version of it, and its service account.

    Raises:
        404: No such agent.
        409: Other agents delegate to this agent.

    """
    records = await db.execute(
        _SLUG_TAKEN_QUERY, {'slug': slug, 'org_slug': org_slug}, ['id']
    )
    if not records:
        raise _not_found(slug)
    params = {'id': str(graph.parse_agtype(records[0]['id']))}
    await _assert_not_delegated_to(db, org_slug, slug, params['id'])
    # One transaction: the versions and the agent go together, or
    # neither goes. ``_execute_batch`` is the transactional primitive
    # that other endpoints also use.
    await db._execute_batch(  # pyright: ignore[reportPrivateUsage]
        [
            graph_cypher.Statement(_DELETE_VERSIONS_QUERY, params),
            graph_cypher.Statement(_DELETE_AGENT_QUERY, params),
        ]
    )


async def _assert_not_delegated_to(
    db: graph.Pool, org_slug: str, slug: str, agent_id: str
) -> None:
    """Raise 409 when other agents in the org delegate to the agent.

    The subagents are stored as JSON, so the match is done here and not
    in the graph.
    """
    records = await db.execute(
        _DELEGATORS_QUERY,
        {'org_slug': org_slug, 'id': agent_id},
        ['name', 'slug', 'subagents'],
    )
    delegators = sorted(
        (
            str(graph.parse_agtype(r['name'])),
            str(graph.parse_agtype(r['slug'])),
        )
        for r in records
        if any(
            item.agent_id == agent_id
            for item in _stored_subagents(graph.parse_agtype(r['subagents']))
        )
    )
    if delegators:
        names = ', '.join(f'{name} ({s})' for name, s in delegators)
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Agent {slug!r} is a subagent of: {names}. Remove it '
                'from these agents first.'
            ),
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
    snapshot is the same as the configuration now, no version is
    written. ``enabled`` does not change. A subagent in the snapshot
    that no longer exists is dropped, and the summary tells so.

    When the snapshot has ``prompt_ref`` and ``prompt_version``, the
    label that the reference names (the default label when it names
    none) moves to that prompt version in the same transaction. This
    needs ``prompt:promote``, as a label move in the prompt CMS does.
    A reference that names a version number moves no label. A label
    moves only on the agent's own prompt: a prompt in the ``agents``
    namespace that the ``prompt_ref`` of the agent names now, with a
    slug that starts with ``<org_slug>.``.

    Raises:
        403: The label must move and the caller cannot promote.
        404: No such agent or version.
        409: The snapshot slug is taken by another agent, the label
            must move on a prompt that is not the agent's own
            ``agents/<org_slug>.`` prompt, the prompt or its version no
            longer exists, or the prompt changed while this request
            ran.
        422: The snapshot team or a snapshot tag no longer exists.

    """
    existing = await _fetch_agent(db, org_slug, slug)
    version = await _fetch_version(db, str(existing['id']), n)
    snapshot = version.snapshot
    found = await _find_subagents(
        db, org_slug, [s.agent_id for s in snapshot.subagents]
    )
    kept = [s for s in snapshot.subagents if s.agent_id in found]
    summary = f'Restored v{n}'
    dropped = len(snapshot.subagents) - len(kept)
    if dropped:
        snapshot = snapshot.model_copy(update={'subagents': kept})
        noun = 'subagent' if dropped == 1 else 'subagents'
        summary += f'; dropped {dropped} missing {noun}'
    label_move = await _restore_label_move(
        db, org_slug, snapshot, existing.get('prompt_ref'), auth
    )
    return await _apply(
        db,
        org_slug,
        existing,
        snapshot,
        bool(existing.get('enabled', True)),
        summary,
        auth.principal_name,
        label_move,
    )


async def _restore_label_move(
    db: graph.Pool,
    org_slug: str,
    snapshot: AgentSnapshot,
    current_ref: str | None,
    auth: permissions.AuthContext,
) -> graph_cypher.Statement | None:
    """Return the statement that moves the prompt label of a restore.

    Return ``None`` when no label must move.

    A restore moves a label only on a prompt in the ``agents``
    namespace that the agent uses now, and only when the prompt slug
    starts with ``<org_slug>.``. Any caller with ``agent:write`` can
    write any ``prompt_ref`` into a version. Without these checks, a
    later restore by a caller with ``prompt:promote`` could move the
    label of a prompt that other consumers use, or that an agent in
    another organization uses. When the label is already at the
    version, nothing moves and the checks do not apply.

    Raises:
        403: The caller cannot promote prompts.
        409: The label must move on a prompt that is not the agent's
            own org-scoped prompt, or the prompt or the prompt version
            no longer exists.

    """
    if snapshot.prompt_ref is None or snapshot.prompt_version is None:
        return None
    namespace, prompt_slug, selector = prompt_resolve.parse_ref(
        snapshot.prompt_ref
    )
    if selector is not None and selector.isascii() and selector.isdigit():
        return None
    try:
        prompt, _latest = await prompt_resolve.fetch_prompt(
            db, namespace, prompt_slug
        )
        await prompt_resolve.fetch_version(db, prompt, snapshot.prompt_version)
    except prompt_resolve.PromptNotFound as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Cannot restore the prompt: {e}',
        ) from e
    label = selector or prompt.default_label
    if any(
        item.name == label and item.version == snapshot.prompt_version
        for item in prompt.labels
    ):
        return None
    current = (
        prompt_resolve.parse_ref(current_ref)[:2] if current_ref else None
    )
    if namespace != AGENT_PROMPT_NAMESPACE or current != (
        namespace,
        prompt_slug,
    ):
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Restoring this version moves the {label!r} label of '
                f'{namespace}/{prompt_slug}, which is not the '
                f'{AGENT_PROMPT_NAMESPACE}/ prompt that this agent uses '
                'now. Move the label in the prompt CMS instead.'
            ),
        )
    if not prompt_slug.startswith(f'{org_slug}.'):
        if '.' not in prompt_slug:
            detail = (
                f'Restoring this version moves the {label!r} label of '
                f'{namespace}/{prompt_slug}, which is not scoped to this '
                'organization. Change and save the system prompt of the '
                f'agent once, so that it moves to {namespace}/'
                f'{org_slug}.{prompt_slug}. Then restore this version.'
            )
        else:
            detail = (
                f'Restoring this version moves the {label!r} label of '
                f'{namespace}/{prompt_slug}, which is not a prompt of the '
                f'{org_slug!r} organization. Move the label in the '
                'prompt CMS instead.'
            )
        raise fastapi.HTTPException(status_code=409, detail=detail)
    if not (auth.is_admin or 'prompt:promote' in auth.permissions):
        raise fastapi.HTTPException(
            status_code=403,
            detail=(
                f'Restoring this version moves the {label!r} label of '
                f'{namespace}/{prompt_slug}; that needs prompt:promote'
            ),
        )
    return prompts.labels_statement(
        prompt,
        prompts.moved_labels(
            prompt, label, snapshot.prompt_version, auth.principal_name
        ),
        prompt.default_label,
    )
