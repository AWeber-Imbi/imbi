"""Agent task endpoints (ADR 0020).

An agent task is the durable unit of work of one agent. Its state lives
in the ``tickets`` Postgres schema; the graph holds the agent,
the organization, and the project that a task refers to by id. People
are referred to by email, as everywhere in this API.

Every route needs the caller to be a member of the organization
(``MEMBER_OF``), because task content is sensitive and the
``ticket:*`` permissions are not scoped to an organization. A
caller that is not a member gets ``403 organization_forbidden``: see
:mod:`imbi.api.auth.organizations`. There is no admin bypass.

Nothing runs a task yet. A person can make a task, read it and its
events, and change its control value. When no harness session is open,
a control change also changes the status at once: see
:meth:`imbi.api.tickets.TicketStore.set_control`.
"""

import contextlib
import dataclasses
import datetime
import decimal
import logging
import re
import typing
import uuid
from collections import abc

import fastapi
import fastapi.routing
import orjson
import pydantic
from fastapi import utils as fastapi_utils

from imbi.api import tickets
from imbi.api.auth import autonomous, organizations, permissions
from imbi.api.endpoints import agents
from imbi.api.endpoints._pagination import (
    build_link_header,
    decode_cursor,
    encode_cursor,
)
from imbi.api.tickets.store import (
    ActorKind,
    AssigneeKind,
    Channel,
    Control,
    Group,
    PersonOutcome,
    Priority,
    ResolvedStatus,
    Status,
)
from imbi.common import graph, models
from imbi.common.auth import permissions as common_permissions

LOGGER = logging.getLogger(__name__)

#: The origin kind of a task that a person makes with this API.
HUMAN_ORIGIN = 'human'

#: The origin kind of the tasks that each of Imbi's own services makes
#: (see :mod:`imbi.api.auth.internal_services`). Only these service
#: accounts can make a task that a person did not start (CC9).
SERVICE_ORIGINS: dict[str, typing.Literal['schedule', 'webhook']] = {
    common_permissions.SCHEDULER_ACCOUNT: 'schedule',
    common_permissions.GATEWAY_ACCOUNT: 'webhook',
}


#: The key shape of the task of a workflow agent step,
#: ``<run_id>:<node_key>``. Only that step makes it.
_STEP_KEY = re.compile(
    r'^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}:[a-z][a-z0-9_]*$'
)


def _header(name: str) -> typing.Any:
    """Return an optional request header of at most 200 characters."""
    return fastapi.Header(alias=name, min_length=1, max_length=200)


#: The longest reply or answer, in characters.
MAX_TEXT_LENGTH = 64 * 1024

#: The largest inline event payload, in bytes of JSON.
MAX_PAYLOAD_BYTES = 64 * 1024

#: A constraint or a digest in a resolution.
_ShortText = typing.Annotated[
    str, pydantic.StringConstraints(min_length=1, max_length=1000)
]


# --- Schemas -----------------------------------------------------------


class TicketRequirement(pydantic.BaseModel):
    """A prerequisite of a new ticket."""

    short_id: str = pydantic.Field(min_length=1, max_length=50)
    gates: bool = pydantic.Field(
        default=False,
        description='Hold the ticket until the prerequisite closes with a '
        '``done_*`` outcome.',
    )


class AgentTaskCreate(pydantic.BaseModel):
    assignee_kind: AssigneeKind = 'agent'
    agent_slug: str | None = pydantic.Field(
        default=None,
        min_length=1,
        description='The agent of an agent ticket.',
    )
    assignee: pydantic.EmailStr | None = pydantic.Field(
        default=None,
        description='The email of the person of a person ticket. Must be '
        'in the org.',
    )
    title: str = pydantic.Field(min_length=1)
    description: str = pydantic.Field(
        min_length=1, description='What the assignee should do.'
    )
    requires: list[TicketRequirement] = pydantic.Field(
        default_factory=list,
        max_length=50,
        description='The prerequisites of the ticket, by short id. An open '
        'gating prerequisite makes the ticket start ``held``.',
    )
    project_ids: list[_ShortText] = pydantic.Field(
        default_factory=list,
        max_length=50,
        description='The projects of the task, by id or slug.',
    )
    budget: decimal.Decimal | None = pydantic.Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=6,
        description=(
            "USD. Defaults to the agent's task_budget. It cannot be more "
            'than that budget.'
        ),
    )
    idempotency_key: str | None = pydantic.Field(
        default=None,
        min_length=1,
        max_length=200,
        description='A repeat with the same key returns the first task.',
    )
    priority: Priority = 'normal'

    @pydantic.model_validator(mode='before')
    @classmethod
    def _legacy_project_id(cls, data: object) -> object:
        """Read the old ``project_id`` field as a list of one project.

        A client that is not updated yet still sends it. Without this,
        the task would have no project and no error would show.
        """
        if not isinstance(data, dict):
            return data
        fields = dict(typing.cast(dict[str, typing.Any], data))
        if 'project_id' in fields:
            legacy = fields.pop('project_id')
            if 'project_ids' in fields:
                raise ValueError('send project_ids or project_id, not both')
            fields['project_ids'] = [] if legacy is None else [legacy]
        return fields

    @pydantic.model_validator(mode='after')
    def _assignee(self) -> typing.Self:
        """An agent ticket names an agent; a person ticket names a
        person and has no budget."""
        if self.assignee_kind == 'agent':
            if self.agent_slug is None or self.assignee is not None:
                raise ValueError('an agent ticket needs agent_slug only')
        elif (
            self.assignee is None
            or self.agent_slug is not None
            or self.budget is not None
        ):
            raise ValueError(
                'a person ticket needs assignee, and no agent_slug or budget'
            )
        if len({r.short_id.upper() for r in self.requires}) < len(
            self.requires
        ):
            raise ValueError('requires names a ticket more than once')
        return self


class AgentTaskRetry(pydantic.BaseModel):
    note: str | None = pydantic.Field(
        default=None,
        min_length=1,
        max_length=MAX_TEXT_LENGTH,
        description='What the agent should do differently this time.',
    )
    idempotency_key: str | None = pydantic.Field(
        default=None,
        min_length=1,
        max_length=200,
        description='A repeat with the same key returns the first task.',
    )


class AgentTaskReassign(pydantic.BaseModel):
    owner: pydantic.EmailStr = pydantic.Field(
        description='The email of the new owner. Must be in the org.'
    )


class AgentTaskPriority(pydantic.BaseModel):
    priority: Priority


class AgentTaskOrigin(pydantic.BaseModel):
    """What started a task. It does not change.

    A ``schedule`` origin also has ``scheduled_task_id``. A ``webhook``
    origin also has ``webhook_id`` and ``delivery_id``. A
    ``task_completed`` origin is a workflow run that a closed task
    started; it also has ``task_id``.
    """

    model_config = pydantic.ConfigDict(extra='allow')

    #: ``ticket`` and ``ticket_closed`` are the ADR 0028 names of
    #: ``task`` and ``task_completed``. Release B writes the new names;
    #: rows of older releases have the old ones (see
    #: :data:`imbi.api.tickets.store.CHILD_ORIGIN_KINDS` and
    #: :mod:`imbi.api.workflows.ticket_trigger`).
    kind: typing.Literal[
        'human',
        'schedule',
        'webhook',
        'task',
        'ticket',
        'task_completed',
        'ticket_closed',
    ]
    #: The email of the person, for a ``human`` origin.
    user: str | None = None


class TaskProject(pydantic.BaseModel):
    project_id: str
    project_slug: str


class AgentTaskResponse(pydantic.BaseModel):
    id: uuid.UUID
    short_id: str
    #: ``agent``: the agent columns are set. ``person``: ``assignee`` is
    #: set and the agent columns are ``None`` (ADR 0028).
    assignee_kind: AssigneeKind = 'agent'
    assignee: str | None = None
    agent_id: str | None = None
    agent_version: int | None = None
    prompt_version: int | None = None
    #: The version of the organization's agent platform configuration
    #: when the task was made. ``None``: the defaults apply.
    platform_config_version: int | None = None
    service_account_id: str | None = None
    #: The projects of the task, oldest first. Each slug is the slug
    #: when the project was associated.
    projects: list[TaskProject]
    title: str
    description: str
    origin: AgentTaskOrigin
    idempotency_key: str | None = None
    owner: str
    budget: decimal.Decimal | None = None
    status: Status
    control: Control
    priority: Priority = 'normal'
    phase: str | None = None
    outcome: str | None = None
    outcome_reason: str | None = None
    cost_total: decimal.Decimal
    tokens_in: int
    tokens_out: int
    cache_read_tokens: int
    cache_write_tokens: int
    #: The ``seq`` of the newest event.
    last_seq: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    closed_at: datetime.datetime | None = None
    log_archived_at: datetime.datetime | None = None
    #: The id of the root task of the chain (ADR 0022).
    chain_id: uuid.UUID | None = None
    #: When a person marked the closed task as needing no more
    #: attention, and who.
    acknowledged_at: datetime.datetime | None = None
    acknowledged_by: str | None = None
    #: The JSON Schema of the structured output that the agent must
    #: return, and the output that it returned.
    output_schema: dict[str, typing.Any] | None = None
    structured_output: dict[str, typing.Any] | None = None


class HighlightPart(pydantic.BaseModel):
    text: str
    match: bool


class TaskHighlight(pydantic.BaseModel):
    """A field of a task that the text query matched."""

    field: typing.Literal['agent', 'project', 'short_id', 'title']
    #: The id of the agent or project, for those fields.
    id: str | None = None
    #: The whole value of the field, in order, split around each match.
    parts: list[HighlightPart]


class AgentTaskListItem(AgentTaskResponse):
    #: When the oldest open request opened, for a task that waits on a
    #: person; ``null`` when the task is closed or has none open.
    blocked_since: datetime.datetime | None = None
    #: What ``q`` matched; empty without ``q``.
    highlights: list[TaskHighlight] = pydantic.Field(default_factory=list)
    #: The icon of each project of the task that has one, by project id:
    #: the project's own icon, else the icon of its project type.
    project_icons: dict[str, str] = pydantic.Field(default_factory=dict)


class AgentTaskCounts(pydantic.BaseModel):
    """The number of tasks in each inbox group."""

    input: int = 0
    running: int = 0
    paused: int = 0
    queued: int = 0
    closed: int = 0


class AgentTaskPosition(pydantic.BaseModel):
    """Where a task is in the task list."""

    group: Group
    #: The index of the task in its group, from 0.
    index: int


class WaitingRequest(pydantic.BaseModel):
    """An open request on a ticket of the caller."""

    id: uuid.UUID
    kind: str
    title: str
    opened_at: datetime.datetime
    expires_at: datetime.datetime | None = None
    #: The ticket of the request.
    short_id: str
    ticket_title: str


class WaitingTicket(pydantic.BaseModel):
    """A ticket that waits on the caller."""

    short_id: str
    title: str
    status: Status
    priority: Priority = 'normal'
    assignee_kind: AssigneeKind = 'agent'
    assignee: str | None = None
    agent_id: str | None = None
    owner: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    #: For a held ticket: its gating prerequisites that closed with an
    #: outcome that does not release it.
    failed: list[str] = pydantic.Field(default_factory=list)


class AgentTaskWaiting(pydantic.BaseModel):
    """What waits on the caller (ADR 0028), for the navigation badge
    and the Waiting on me page."""

    #: The number of items in the three lists.
    count: int
    #: Open requests on the tickets that the caller owns.
    requests: list[WaitingRequest] = pydantic.Field(default_factory=list)
    #: Person tickets assigned to the caller that are not closed.
    assigned: list[WaitingTicket] = pydantic.Field(default_factory=list)
    #: Held tickets of the caller with a gating prerequisite that failed.
    held: list[WaitingTicket] = pydantic.Field(default_factory=list)


class AgentTaskEventResponse(pydantic.BaseModel):
    event_id: uuid.UUID
    seq: int
    type: str
    schema_version: int
    actor_kind: ActorKind
    actor_id: str | None = None
    channel: Channel
    session_id: uuid.UUID | None = None
    at: datetime.datetime
    payload: dict[str, typing.Any]


class RequestResponse(pydantic.BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID | None = None
    kind: str
    status: str
    title: str
    why: str | None = None
    options: list[typing.Any] | None = None
    artifacts: list[typing.Any] | None = None
    artifact_digests: list[str] | None = None
    expires_at: datetime.datetime | None = None
    opened_at: datetime.datetime
    request_key: str | None = None
    #: The email of the person who resolved the request.
    resolved_by: str | None = None
    resolved_at: datetime.datetime | None = None
    #: The answer, constraints, approved digests, and channel (I9).
    resolution: dict[str, typing.Any] | None = None


class AgentTaskRequestResolve(pydantic.BaseModel):
    """How a person resolves a request (I9)."""

    status: ResolvedStatus = pydantic.Field(
        description='``answered`` for feedback; ``approved`` or '
        '``rejected`` for an approval.'
    )
    answer: str | None = pydantic.Field(
        default=None,
        min_length=1,
        max_length=MAX_TEXT_LENGTH,
        description='The decision. Required for ``answered``.',
    )
    constraints: list[_ShortText] | None = pydantic.Field(
        default=None,
        max_length=50,
        description='Conditions that the person sets on the resolution.',
    )
    artifact_digests: list[_ShortText] | None = pydantic.Field(
        default=None,
        max_length=100,
        description=(
            'For ``approved``: the digests that the person reviewed. They '
            'must be the digests of the request (I3).'
        ),
    )

    @pydantic.model_validator(mode='after')
    def _check(self) -> typing.Self:
        if self.status == 'answered' and not self.answer:
            raise ValueError('an answer needs answer text')
        if self.status == 'approved' and not self.artifact_digests:
            raise ValueError('an approval needs artifact_digests')
        return self


class AgentTaskRequestResolveResponse(pydantic.BaseModel):
    request: RequestResponse
    task: AgentTaskResponse


class AgentTaskReply(pydantic.BaseModel):
    body: str = pydantic.Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    hold: bool = pydantic.Field(
        default=False,
        description='Also pause the task (Reply and hold).',
    )


class RelatedTask(pydantic.BaseModel):
    """The task at the other end of a relation."""

    short_id: str
    title: str
    assignee_kind: AssigneeKind = 'agent'
    assignee: str | None = None
    agent_id: str | None = None
    status: Status
    outcome: str | None = None
    created_at: datetime.datetime
    #: Who linked the tasks, and when. ``null`` for delegation.
    linked_by_kind: ActorKind | None = None
    linked_by: str | None = None
    linked_at: datetime.datetime | None = None
    #: Whether the prerequisite holds the dependent until it closes with
    #: a ``done_*`` outcome (ADR 0028). ``null`` for a parent or child.
    gates: bool | None = None


class TicketTree(pydantic.BaseModel):
    """The tree of a ticket, computed on read (ADR 0028)."""

    root_short_id: str
    root_title: str
    #: The number of tickets in the tree, the root included.
    tickets: int
    #: The number of tickets in the tree that are not closed.
    open: int


class AgentTaskRelations(pydantic.BaseModel):
    """The tasks related to a task.

    ``requires`` are the prerequisites of this task; ``required_by`` are
    the tasks that have this task as a prerequisite. A prerequisite is a
    link only, unless it ``gates``: a gating prerequisite holds the task
    (status ``held``, never claimed) until it closes with a ``done_*``
    outcome. ``parent`` and ``children`` come from the parent of each
    ticket. ``tree`` is the state of the tree of the ticket.
    """

    requires: list[RelatedTask]
    required_by: list[RelatedTask]
    parent: RelatedTask | None = None
    children: list[RelatedTask]
    tree: TicketTree


class TicketDependencySet(pydantic.BaseModel):
    """The kind of a dependency."""

    gates: bool = pydantic.Field(
        default=False,
        description='Hold the ticket until the prerequisite closes with a '
        '``done_*`` outcome. Only a ticket that has not started (``queued`` '
        'or ``held``) can get a gating prerequisite.',
    )


class TicketStatusSet(pydantic.BaseModel):
    """A status change of a person ticket (ADR 0028)."""

    status: typing.Literal['open', 'in_progress', 'blocked', 'closed']
    outcome: PersonOutcome | None = pydantic.Field(
        default=None, description='Required to close, else not allowed.'
    )
    reason: str | None = pydantic.Field(
        default=None,
        min_length=1,
        max_length=MAX_TEXT_LENGTH,
        description='Why. Required to block.',
    )

    @pydantic.model_validator(mode='after')
    def _fields(self) -> typing.Self:
        if (self.status == 'closed') != (self.outcome is not None):
            raise ValueError('send outcome to close, and only to close')
        if self.status == 'blocked' and self.reason is None:
            raise ValueError('send a reason to block')
        return self


class TicketHandOff(pydantic.BaseModel):
    """The new assignee of a ticket (ADR 0028)."""

    assignee_kind: AssigneeKind
    agent_slug: str | None = pydantic.Field(
        default=None, min_length=1, description='The agent, for an agent.'
    )
    assignee: pydantic.EmailStr | None = pydantic.Field(
        default=None,
        description='The email of the person, for a person. Must be in the '
        'org.',
    )
    note: str | None = pydantic.Field(
        default=None,
        min_length=1,
        max_length=MAX_TEXT_LENGTH,
        description='Why, for the new assignee.',
    )

    @pydantic.model_validator(mode='after')
    def _assignee(self) -> typing.Self:
        person = self.assignee_kind == 'person'
        if person != (self.assignee is not None) or person == (
            self.agent_slug is not None
        ):
            raise ValueError(
                'send agent_slug for an agent, or assignee for a person'
            )
        return self


class TicketParentSet(pydantic.BaseModel):
    """The new parent of a ticket."""

    parent: str | None = pydantic.Field(
        description='The short id of the new parent. ``null`` makes the '
        'ticket a root.'
    )


class AssociatedProject(pydantic.BaseModel):
    """A project that a task touches (F13)."""

    project_id: str
    #: The slug now, or the slug when the project was associated if the
    #: project is not available.
    project_slug: str
    name: str | None = None
    #: ``false`` when the project is no longer in the organization.
    available: bool
    added_by_kind: ActorKind | None = None
    added_by: str | None = None
    added_at: datetime.datetime | None = None


# --- Queries -----------------------------------------------------------

#: The agents and projects that the text query of the task list
#: matches by agent name and project slug (O3).
_TEXT_QUERY: typing.LiteralString = """
MATCH (o:Organization {{slug: {org_slug}}})
OPTIONAL MATCH (a:Agent)-[:BELONGS_TO]->(o)
WHERE toLower(a.name) CONTAINS {text}
WITH o, collect(a.id) AS agent_ids, collect(a.name) AS agent_names
OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(:Team)-[:BELONGS_TO]->(o)
WHERE toLower(p.slug) CONTAINS {text}
RETURN agent_ids, agent_names, collect(p.id) AS project_ids,
       collect(p.slug) AS project_slugs
"""

_AGENT_QUERY: typing.LiteralString = """
MATCH (a:Agent {{slug: {slug}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN a
"""

_AGENT_SLUG_QUERY: typing.LiteralString = """
MATCH (a:Agent {{id: {id}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN a.slug AS slug
"""

_PROJECTS_QUERY: typing.LiteralString = """
MATCH (p:Project)
      -[:OWNED_BY]->(:Team)
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
WHERE p.id IN {ids} OR p.slug IN {ids}
RETURN p.id AS id, p.slug AS slug, p.name AS name
"""

_ICONS_QUERY: typing.LiteralString = """
MATCH (p:Project)
      -[:OWNED_BY]->(:Team)
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
WHERE p.id IN {ids}
OPTIONAL MATCH (p)-[:TYPE]->(pt:ProjectType)
WITH p, pt
ORDER BY pt.slug
WITH p, collect(pt.icon) AS type_icons
RETURN p.id AS id, p.icon AS icon, type_icons[0] AS type_icon
"""

_WEBHOOK_QUERY: typing.LiteralString = """
MATCH (w:Webhook {{id: {id}}})-[:BELONGS_TO]->(o:Organization)
RETURN o.slug AS org, w.created_by AS created_by
"""

_OWNER_QUERY: typing.LiteralString = """
MATCH (u:User {{email: {email}}})
      -[:MEMBER_OF]->(:Organization {{slug: {org_slug}}})
RETURN u.is_admin AS is_admin, u.is_active AS is_active
"""

_MEMBER_QUERY: typing.LiteralString = """
MATCH (u:User {{email: {email}}})
      -[:MEMBER_OF]->(:Organization {{slug: {org_slug}}})
RETURN u.email AS email
"""


# --- Helpers -----------------------------------------------------------


def _unprocessable(detail: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(status_code=422, detail=detail)


def check_payload_size(
    what: str, payload: typing.Any, limit: int = MAX_PAYLOAD_BYTES
) -> int:
    """Raise 413 when ``payload`` as JSON is larger than ``limit``.

    Return the size in bytes.

    Raises:
        413: ``payload_too_large``.

    """
    size = len(orjson.dumps(payload))
    if size > limit:
        raise fastapi.HTTPException(
            status_code=413,
            detail={
                'error': 'payload_too_large',
                'message': f'{what} is {size} bytes; the limit is {limit}',
            },
        )
    return size


def _person_ticket(short_id: str) -> fastapi.HTTPException:
    """409 for a change that applies only to an agent ticket."""
    return _conflict(
        'person_ticket',
        f'Task {short_id!r} is a person ticket; this applies only to an '
        'agent ticket',
    )


def _conflict(
    error: str, message: str, **extra: typing.Any
) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=409,
        detail={'error': error, 'message': message, **extra},
    )


#: The id of the organization in the path. The router also depends on
#: it, so no route can skip the membership check.
OrgId = organizations.MemberOrgId


async def _fetch_agent(
    db: graph.Graph, org_slug: str, slug: str
) -> dict[str, typing.Any]:
    """Return the properties of an agent in the org, or raise 422."""
    records = await db.execute(
        _AGENT_QUERY, {'slug': slug, 'org_slug': org_slug}, ['a']
    )
    props: typing.Any = (
        graph.parse_agtype(records[0]['a']) if records else None
    )
    if not isinstance(props, dict):
        raise _unprocessable(f'Agent {slug!r} not found')
    return typing.cast('dict[str, typing.Any]', props)


def _ids(value: typing.Any) -> list[str]:
    """Return the ids in an agtype list."""
    items = typing.cast('list[typing.Any]', graph.parse_agtype(value) or [])
    return [str(item) for item in items]


def _pairs(ids: typing.Any, values: typing.Any) -> dict[str, str]:
    """Pair two agtype lists that one ``collect`` pass built."""
    keys, names = _ids(ids), _ids(values)
    if len(keys) != len(names):
        return dict.fromkeys(keys, '')
    return dict(zip(keys, names, strict=True))


def _parts(value: str, text: str) -> list[dict[str, typing.Any]]:
    """Split ``value`` around each case-blind match of ``text``."""
    parts: list[dict[str, typing.Any]] = []
    end = 0
    for found in re.finditer(re.escape(text), value, re.IGNORECASE):
        if found.start() > end:
            parts.append({'text': value[end : found.start()], 'match': False})
        parts.append({'text': found.group(), 'match': True})
        end = found.end()
    if parts and end < len(value):
        parts.append({'text': value[end:], 'match': False})
    return parts


def _highlights(
    row: dict[str, typing.Any],
    text: str,
    agents: dict[str, str],
    projects: dict[str, str],
) -> list[dict[str, typing.Any]]:
    """Return each field of the task that ``text`` matched.

    The agent and project values are the current name and slug from
    the graph, which the search matched, not the slug the task stored.
    """
    found: list[dict[str, typing.Any]] = []
    for field in ('short_id', 'title'):
        if parts := _parts(row[field], text):
            found.append({'field': field, 'parts': parts})
    if parts := _parts(agents.get(row['agent_id'], ''), text):
        found.append({'field': 'agent', 'id': row['agent_id'], 'parts': parts})
    for project in _projects_of(row):
        project_id = project['project_id']
        if parts := _parts(projects.get(project_id, ''), text):
            found.append(
                {'field': 'project', 'id': project_id, 'parts': parts}
            )
    return found


def _projects_of(row: dict[str, typing.Any]) -> list[dict[str, str]]:
    return typing.cast('list[dict[str, str]]', row['projects'] or [])


async def _project_icons(
    db: graph.Graph, org_slug: str, rows: list[dict[str, typing.Any]]
) -> dict[str, str]:
    """Return the icon of each project of ``rows`` that has one."""
    ids = sorted(
        {
            project['project_id']
            for row in rows
            for project in _projects_of(row)
        }
    )
    if not ids:
        return {}
    records = await db.execute(
        _ICONS_QUERY,
        {'org_slug': org_slug, 'ids': ids},
        ['id', 'icon', 'type_icon'],
    )
    icons: dict[str, str] = {}
    for record in records:
        icon: typing.Any = graph.parse_agtype(
            record['icon']
        ) or graph.parse_agtype(record['type_icon'])
        if icon:
            icons[str(graph.parse_agtype(record['id']))] = str(icon)
    return icons


def task_budget(
    settings: models.AgentSettings, requested: decimal.Decimal | None
) -> decimal.Decimal | None:
    """Return the budget of a new task, or raise 422.

    The agent's ``task_budget`` is the default. A caller can only make
    the budget lower.
    """
    limit = settings.task_budget
    if requested is None:
        return limit
    if limit is not None and requested > limit:
        raise _unprocessable(
            f'budget {requested} is more than the task budget {limit} of '
            'the agent'
        )
    return requested


class TaskOrigin(typing.NamedTuple):
    """The origin of a new task: its kind, its id, and the record."""

    kind: str
    #: The user id, the scheduler task id, or the webhook id. The
    #: idempotency key is unique per kind and id.
    id: str
    record: dict[str, typing.Any]
    #: For a ``schedule`` origin, the person accountable for the
    #: scheduler task and its org, as the scheduler sends them.
    creator: str | None = None
    org: str | None = None


def task_origin(
    auth: permissions.AuthContext,
    scheduled_task: str | None = None,
    webhook: str | None = None,
    delivery: str | None = None,
    scheduled_by: str | None = None,
    scheduled_org: str | None = None,
) -> TaskOrigin:
    """Return the origin of a new task, from the caller (CC9).

    A person starts a ``human`` task. Only the service account of the
    scheduler makes a ``schedule`` task, and only the service account
    of the gateway makes a ``webhook`` task (:data:`SERVICE_ORIGINS`).
    Each service names its origin in request headers. The scheduler
    also sends the person accountable for its task (who last changed
    it) and its org, which the author of the task cannot change. A
    person cannot name an origin, so a person cannot forge one.

    Raises:
        403: A person names an origin, or the caller is a service
            account that is not in :data:`SERVICE_ORIGINS`.
        422: A service does not name its origin.

    """
    if auth.user is not None:
        named = (
            scheduled_task,
            webhook,
            delivery,
            scheduled_by,
            scheduled_org,
        )
        if any(named):
            raise autonomous.forbidden(
                'origin_forbidden',
                "Only Imbi's own services can name the origin of a task.",
            )
        return TaskOrigin(
            HUMAN_ORIGIN,
            auth.user.id,
            {'kind': HUMAN_ORIGIN, 'user': auth.user.email},
        )
    slug = auth.service_account.slug if auth.service_account else ''
    kind = SERVICE_ORIGINS.get(slug)
    if kind == 'schedule':
        if scheduled_task is None:
            raise _unprocessable('X-Imbi-Scheduled-Task is required')
        return TaskOrigin(
            kind,
            scheduled_task,
            {'kind': kind, 'scheduled_task_id': scheduled_task},
            scheduled_by,
            scheduled_org,
        )
    if kind == 'webhook':
        if webhook is None or delivery is None:
            raise _unprocessable(
                'X-Imbi-Webhook and X-Imbi-Delivery are required'
            )
        return TaskOrigin(
            kind,
            webhook,
            {'kind': kind, 'webhook_id': webhook, 'delivery_id': delivery},
        )
    raise fastapi.HTTPException(
        403, 'This endpoint requires user authentication'
    )


def _actor(auth: permissions.AuthContext) -> tickets.Actor:
    """Return the actor of a request, for the events that it writes.

    A browser session authenticates with a JWT; other callers use an API
    key or client credentials. imbi-slackbot mints its JWTs with a
    ``slack`` channel claim.
    """
    channel: Channel = auth.channel or (
        'web' if auth.auth_method == 'jwt' else 'api'
    )
    if auth.user is not None:
        return tickets.Actor('human', auth.user.email, channel)
    return tickets.Actor('system', auth.principal_name, channel)


async def _get_task(
    store: tickets.TicketStore, org_id: str, short_id: str
) -> dict[str, typing.Any]:
    task = await store.get(org_id, short_id.upper())
    if task is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Task {short_id!r} not found'
        )
    return task


_require_read = permissions.require_permission('ticket:read')


async def _readable_task(
    org_id: OrgId,
    short_id: str,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> dict[str, typing.Any]:
    """Return the task when the caller can read it.

    The caller needs ``ticket:read``. The service account of the
    task's agent can also read its own task and events without it, so
    its harness can poll the log for human input.

    Raises:
        403: The caller cannot read the task.
        404: No such task.

    """
    if auth.service_account is None:
        await _require_read(auth)
        return await _get_task(store, org_id, short_id)
    task = await _get_task(store, org_id, short_id)
    if auth.service_account.id != task['service_account_id']:
        await _require_read(auth)
    return task


#: The task in the path, after the read check.
ReadableTask = typing.Annotated[
    dict[str, typing.Any], fastapi.Depends(_readable_task)
]


async def _set_control(
    store: tickets.TicketStore,
    org_id: str,
    short_id: str,
    control: Control,
    auth: permissions.AuthContext,
) -> dict[str, typing.Any]:
    try:
        with write_errors(short_id):
            return await store.set_control(
                org_id, short_id.upper(), control, _actor(auth)
            )
    except tickets.WrongAssigneeKind as e:
        raise _person_ticket(short_id) from e


@contextlib.contextmanager
def write_errors(short_id: str) -> abc.Generator[None]:
    """Map the errors of a change to an agent ticket to HTTP errors."""
    try:
        yield
    except tickets.TaskNotFound as e:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Task {short_id!r} not found'
        ) from e
    except tickets.TaskClosed as e:
        raise fastapi.HTTPException(
            status_code=409, detail=f'Task {short_id!r} is closed'
        ) from e
    except tickets.CancelPending as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Task {short_id!r} has a cancel that is not done yet',
        ) from e


async def may_create(db: graph.Graph, org_slug: str, email: str) -> bool:
    """Return whether the person can make agent tasks in the org.

    The person must be an active member of the org, and an admin or a
    holder of ``ticket:create``, as for a create of their own.
    """
    records = await db.execute(
        _OWNER_QUERY,
        {'email': email, 'org_slug': org_slug},
        ['is_admin', 'is_active'],
    )
    if not records or graph.parse_agtype(records[0]['is_active']) is False:
        return False
    if graph.parse_agtype(records[0]['is_admin']):
        return True
    return common_permissions.holds(
        'ticket:create',
        await common_permissions.load_principal_permissions(
            db, 'User', 'email', email, org_slug=org_slug
        ),
    )


async def _owner(
    db: graph.Graph,
    org_slug: str,
    auth: permissions.AuthContext,
    origin: TaskOrigin,
) -> str:
    """Return the owner of a new task (F9).

    A person owns the tasks that they make. A ``schedule`` task is owned
    by the person who last changed the scheduler task, and a ``webhook``
    task by the person who last set the rules of the webhook. The
    scheduler task or the webhook must be in the org, and its person
    must be able to make agent tasks in the org. So a person who can
    configure a service cannot use it to make tasks that they could not
    make.

    Raises:
        403: ``origin_forbidden``: the scheduler task or the webhook is
            not in the org. ``owner_forbidden``: no person is recorded,
            or the person cannot make agent tasks in the org.
        422: No such webhook.

    """
    if auth.user is not None:
        return auth.user.email
    if origin.kind == 'schedule':
        org, creator = origin.org, origin.creator
    else:
        records = await db.execute(
            _WEBHOOK_QUERY, {'id': origin.id}, ['org', 'created_by']
        )
        if not records:
            raise _unprocessable(f'Webhook {origin.id!r} not found')
        org = graph.parse_agtype(records[0]['org'])
        creator = graph.parse_agtype(records[0]['created_by'])
    if org != org_slug:
        raise autonomous.forbidden(
            'origin_forbidden',
            f'The {origin.kind} {origin.id!r} is not in organization '
            f'{org_slug!r}.',
        )
    if not creator:
        LOGGER.warning(
            'Refusing a %s task from %r: it records no person who set it',
            origin.kind,
            origin.id,
        )
        raise autonomous.forbidden(
            'owner_forbidden',
            f'The {origin.kind} {origin.id!r} records no person who set it; '
            'edit it to make agent tasks from it.',
        )
    if not await may_create(db, org_slug, str(creator)):
        raise autonomous.forbidden(
            'owner_forbidden',
            f'{creator!r} cannot make agent tasks in organization '
            f'{org_slug!r}.',
        )
    return str(creator)


async def project_slugs(
    db: graph.Graph, org_slug: str, projects: list[str]
) -> list[tuple[str, str]]:
    """Return the ``(id, slug)`` of each project in the org, in the
    order of ``projects`` with no repeats, or raise 422.

    Each entry is a project id or slug. An id wins over a slug, and a
    slug that more than one project in the org has is refused.
    """
    refs = list(dict.fromkeys(projects))
    if not refs:
        return []
    records = await db.execute(
        _PROJECTS_QUERY,
        {'org_slug': org_slug, 'ids': refs},
        ['id', 'slug', 'name'],
    )
    rows = [
        (str(graph.parse_agtype(r['id'])), str(graph.parse_agtype(r['slug'])))
        for r in records
    ]
    found: list[tuple[str, str]] = []
    for ref in refs:
        matches = [row for row in rows if row[0] == ref] or [
            row for row in rows if row[1] == ref
        ]
        if len(matches) > 1:
            raise _unprocessable(f'Project slug {ref!r} is not unique')
        if not matches:
            raise _unprocessable(f'Project {ref!r} not found')
        found.append(matches[0])
    return list(dict.fromkeys(found))


@contextlib.contextmanager
def relation_errors() -> abc.Generator[None]:
    """Map the errors of a relation change to HTTP errors."""
    try:
        yield
    except tickets.TaskNotFound as e:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Task {str(e)!r} not found'
        ) from e
    except tickets.TaskArchived as e:
        raise _conflict(
            'task_archived', f'The log of {e} is archived; it cannot change'
        ) from e
    except tickets.SelfDependency as e:
        raise _unprocessable(f'Task {str(e)!r} cannot require itself') from e
    except tickets.ParentCycle as e:
        raise _conflict(
            'parent_cycle', f'Task {str(e)!r} cannot be its own ancestor'
        ) from e
    except tickets.TicketStarted as e:
        raise _conflict(
            'ticket_started',
            f'Task {str(e)!r} has started; a gating prerequisite cannot'
            ' hold it',
        ) from e


#: A caller with ``ticket:read``, with no exception for the service
#: account of the task's agent (see :func:`_readable_task`).
TaskReader = typing.Annotated[
    permissions.AuthContext, fastapi.Depends(_require_read)
]

_require_manage = permissions.require_permission('ticket:manage')
_require_create = permissions.require_permission('ticket:create')

#: A person with ``ticket:manage``. Agents cannot change relations.
ManagingPerson = typing.Annotated[
    permissions.AuthContext, fastapi.Depends(_require_manage)
]


def ticket_operation_id(route: fastapi.routing.APIRoute) -> str:
    """Return the operation id of a route at ``/tickets``: the default
    id, with ``ticket`` for ``agent_task`` in the function name (ADR
    0028).
    """
    name = route.name.replace('agent_task', 'ticket')
    return name + fastapi_utils.generate_unique_id(route)[len(route.name) :]


# --- Endpoints ---------------------------------------------------------

tickets_router = fastapi.APIRouter(
    tags=['Agent Tasks'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)


@tickets_router.post(
    '/',
    status_code=201,
    response_model=AgentTaskResponse,
    responses={
        200: {
            'model': AgentTaskResponse,
            'description': (
                'A task with this idempotency key exists; it is returned '
                'unchanged.'
            ),
        },
    },
)
async def create_agent_task(
    org_slug: str,
    org_id: OrgId,
    data: AgentTaskCreate,
    response: fastapi.Response,
    db: graph.Pool,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ticket:create')),
    ],
    scheduled_task: typing.Annotated[
        str | None, _header('X-Imbi-Scheduled-Task')
    ] = None,
    webhook: typing.Annotated[str | None, _header('X-Imbi-Webhook')] = None,
    delivery: typing.Annotated[str | None, _header('X-Imbi-Delivery')] = None,
    scheduled_by: typing.Annotated[
        str | None, _header('X-Imbi-Scheduled-Task-Accountable')
    ] = None,
    scheduled_org: typing.Annotated[
        str | None, _header('X-Imbi-Scheduled-Task-Org')
    ] = None,
    idempotency_key: typing.Annotated[
        str | None, _header('Idempotency-Key')
    ] = None,
) -> dict[str, typing.Any]:
    """Make a ticket for an agent or, with ``assignee_kind`` ``person``,
    for a person (ADR 0028).

    An agent ticket starts ``queued`` and a person ticket ``open``; an
    open gating prerequisite in ``requires`` makes it start ``held``.
    A person owns the tasks that they make. The scheduler and the
    gateway also make tasks, with a ``schedule`` or a ``webhook``
    origin that they name in headers (see :func:`task_origin`). The
    person who last set the scheduler task or the webhook owns such a task
    (see :func:`_owner`). The task records the agent version and the
    prompt version that the agent has now. A repeat with the same
    idempotency key (``idempotency_key``, else the ``Idempotency-Key``
    header) and the same origin returns the first task with status 200.

    Raises:
        403: The caller is not a person or one of Imbi's own services,
            a person names an origin, the caller is not a member of the
            org, or the origin or its person is not allowed (see
            :func:`_owner`).
        404: No such organization.
        409: The agent is disabled.
        422: The agent, the assignee, or the project is not in the org,
            the budget is more than the agent's task budget, a service
            does not name its origin, the webhook does not exist, a
            prerequisite is not found, or the key has the shape of a
            workflow step key (``<uuid>:<node_key>``).

    """
    origin = task_origin(
        auth, scheduled_task, webhook, delivery, scheduled_by, scheduled_org
    )
    return await _create_task(
        db,
        store,
        org_slug,
        org_id,
        data,
        origin,
        data.idempotency_key or idempotency_key,
        response,
        auth,
    )


async def _keyed_task(
    store: tickets.TicketStore,
    org_id: str,
    origin: TaskOrigin,
    key: str | None,
    response: fastapi.Response,
) -> dict[str, typing.Any] | None:
    """Return the task that has ``key``, and set status 200, if it exists."""
    if key is None:
        return None
    if _STEP_KEY.match(key):
        raise _unprocessable(
            'The idempotency key has the shape of a workflow step key'
        )
    existing = await store.find_by_idempotency_key(
        org_id, origin.kind, origin.id, key
    )
    if existing is not None:
        response.status_code = 200
    return existing


async def _create_task(
    db: graph.Graph,
    store: tickets.TicketStore,
    org_slug: str,
    org_id: str,
    data: AgentTaskCreate,
    origin: TaskOrigin,
    key: str | None,
    response: fastapi.Response,
    auth: permissions.AuthContext,
) -> dict[str, typing.Any]:
    """Make a task, or return the task that has ``key`` with status 200."""
    existing = await _keyed_task(store, org_id, origin, key, response)
    if existing is not None:
        return existing
    owner = await _owner(db, org_slug, auth, origin)
    task, created = await make_task(
        db, store, org_slug, org_id, data, origin, key, owner, _actor(auth)
    )
    if not created:
        response.status_code = 200
    return task


async def person_assignee(
    db: graph.Graph, org_slug: str, email: str | None
) -> tickets.HandOff:
    """Return a person as an assignee, or raise 422.

    Raises:
        422: The person is not a member of the org.

    """
    if not await db.execute(
        _MEMBER_QUERY, {'email': email, 'org_slug': org_slug}, ['email']
    ):
        raise _unprocessable(f'User {email!r} is not in the org')
    return tickets.HandOff('person', assignee=email)


async def agent_assignee(
    db: graph.Graph,
    org_slug: str,
    slug: str,
    budget: decimal.Decimal | None = None,
) -> tickets.HandOff:
    """Return an agent as an assignee: its service account, the agent
    and prompt versions that it has now, and the budget (see
    :func:`task_budget`).

    Raises:
        409: The agent is disabled.
        422: The agent is not in the org, or the budget is more than the
            agent's task budget.

    """
    agent = await _fetch_agent(db, org_slug, slug)
    if not agent.get('enabled', True):
        raise fastapi.HTTPException(
            status_code=409, detail=f'Agent {slug!r} is disabled'
        )
    raw_settings: typing.Any = agent.get('settings') or {}
    settings = (
        models.AgentSettings.model_validate_json(raw_settings)
        if isinstance(raw_settings, str)
        else models.AgentSettings.model_validate(raw_settings)
    )
    budget = task_budget(settings, budget)
    agent_id = str(agent['id'])
    return tickets.HandOff(
        'agent',
        agent_id=agent_id,
        agent_version=int(agent.get('version') or 1),
        prompt_version=agent.get('prompt_version'),
        service_account_id=await agents.ensure_service_account(
            db, agent_id, str(agent.get('name', slug))
        ),
        budget=budget,
    )


async def make_task(
    db: graph.Graph,
    store: tickets.TicketStore,
    org_slug: str,
    org_id: str,
    data: AgentTaskCreate,
    origin: TaskOrigin,
    key: str | None,
    owner: str,
    actor: tickets.Actor,
    output_schema: dict[str, typing.Any] | None = None,
) -> tuple[dict[str, typing.Any], bool]:
    """Make a ticket. An agent ticket gets the agent and prompt
    versions that the agent has now.

    Return the task, and ``False`` when a task with the key exists.
    ``output_schema`` is the JSON Schema of the structured output that
    the agent must return.

    Raises:
        409: The agent is disabled.
        422: The agent, the assignee, or the project is not in the org,
            the budget is more than the agent's task budget, or a
            prerequisite is not found.

    """
    projects = await project_slugs(db, org_slug, data.project_ids)
    if data.assignee_kind == 'person':
        assignee = await person_assignee(db, org_slug, data.assignee)
    else:
        assignee = await agent_assignee(
            db, org_slug, data.agent_slug or '', data.budget
        )
    budget = assignee.budget
    agent_version = assignee.agent_version
    prompt_version = assignee.prompt_version
    try:
        return await store.create(
            tickets.NewTask(
                organization_id=org_id,
                agent_id=assignee.agent_id,
                agent_version=agent_version,
                prompt_version=prompt_version,
                service_account_id=assignee.service_account_id,
                projects=projects,
                title=data.title,
                description=data.description,
                origin_kind=origin.kind,
                origin_id=origin.id,
                origin=origin.record,
                idempotency_key=key,
                owner=owner,
                budget=budget,
                output_schema=output_schema,
                priority=data.priority,
                assignee_kind=data.assignee_kind,
                assignee=data.assignee,
                requires=[
                    (r.short_id.upper(), r.gates) for r in data.requires
                ],
            ),
            actor,
            {
                'title': data.title,
                'description': data.description,
                'origin': origin.record,
                'budget': None if budget is None else str(budget),
                'agent_version': agent_version,
                'prompt_version': prompt_version,
                'priority': data.priority,
                'assignee_kind': data.assignee_kind,
                'assignee': data.assignee,
            },
        )
    except tickets.TaskNotFound as e:
        raise _unprocessable(f'Prerequisite {str(e)!r} not found') from e


@tickets_router.get('/', response_model=list[AgentTaskListItem])
async def list_agent_tasks(
    org_slug: str,
    org_id: OrgId,
    request: fastapi.Request,
    response: fastapi.Response,
    db: graph.Pool,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ticket:read')),
    ],
    status: typing.Annotated[list[Status] | None, fastapi.Query()] = None,
    agent_id: typing.Annotated[list[str] | None, fastapi.Query()] = None,
    owner: typing.Annotated[list[str] | None, fastapi.Query()] = None,
    mine: bool = False,
    q: str | None = None,
    limit: typing.Annotated[int, fastapi.Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
    group: Group | None = None,
    offset: typing.Annotated[int, fastapi.Query(ge=0)] = 0,
) -> list[dict[str, typing.Any]]:
    """List the tasks in an organization, newest first.

    ``q`` matches the title, the short id, the agent name, or the
    project slug, and ``highlights`` says where. ``agent_id`` and
    ``owner`` repeat to match any of their values, and ``mine`` adds
    the caller to the owners. The ``Link`` header has the URL of the
    next page. Each task has ``project_icons``, and ``blocked_since``
    when it waits on a person, so a client can sort that queue oldest
    block first (O2). ``status=blocked`` also matches every task that
    waits on a person. ``group`` lists one inbox group in the order of
    the inbox: oldest block first for ``input``, newest close first for
    ``closed``, else newest first; it pages with ``offset``, so a client
    can read any part of it.

    Raises:
        400: The cursor is not valid or comes with ``group``, or
            ``offset`` comes without ``group``.
        403: The caller is not a member of the org.
        404: No such organization.

    """
    text = (q or '').strip().lower()
    agents, projects = await _text_matches(db, org_slug, text)
    before: tuple[datetime.datetime, uuid.UUID] | None = None
    if cursor is not None and group is not None:
        raise fastapi.HTTPException(
            status_code=400, detail='A group pages with offset, not cursor'
        )
    if offset and group is None:
        raise fastapi.HTTPException(
            status_code=400, detail='Only a group pages with offset'
        )
    if cursor is not None:
        decoded = decode_cursor(cursor)
        try:
            before = (decoded[0], uuid.UUID(decoded[1])) if decoded else None
        except ValueError:
            before = None
        if before is None:
            raise fastapi.HTTPException(
                status_code=400, detail='Invalid cursor'
            )
    owners = [*(owner or []), *([auth.principal_name] if mine else [])]
    rows = await store.search(
        org_id,
        statuses=status,
        agent_ids=agent_id,
        owners=owners,
        text=text or None,
        text_agent_ids=list(agents),
        text_project_ids=list(projects),
        group=group,
        before=before,
        offset=offset,
        limit=limit + 1,
    )
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        if group is None:
            next_cursor = encode_cursor(
                rows[-1]['created_at'], str(rows[-1]['id'])
            )
    response.headers['Link'] = build_link_header(request, next_cursor)
    icons = await _project_icons(db, org_slug, rows)
    return [
        {
            **row,
            'highlights': (
                _highlights(row, text, agents, projects) if text else []
            ),
            'project_icons': {
                project['project_id']: icons[project['project_id']]
                for project in _projects_of(row)
                if project['project_id'] in icons
            },
        }
        for row in rows
    ]


@tickets_router.get('/counts', response_model=AgentTaskCounts)
async def count_agent_tasks(
    org_slug: str,
    org_id: OrgId,
    db: graph.Pool,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ticket:read')),
    ],
    status: typing.Annotated[list[Status] | None, fastapi.Query()] = None,
    agent_id: typing.Annotated[list[str] | None, fastapi.Query()] = None,
    owner: typing.Annotated[list[str] | None, fastapi.Query()] = None,
    mine: bool = False,
    q: str | None = None,
) -> dict[str, int]:
    """Count the tasks in each inbox group that the task list with the
    same filters finds, so a client can size the whole list before it
    reads the tasks.

    Raises:
        403: The caller is not a member of the org.
        404: No such organization.

    """
    text = (q or '').strip().lower()
    agents, projects = await _text_matches(db, org_slug, text)
    owners = [*(owner or []), *([auth.principal_name] if mine else [])]
    return await store.count_groups(
        org_id,
        statuses=status,
        agent_ids=agent_id,
        owners=owners,
        text=text or None,
        text_agent_ids=list(agents),
        text_project_ids=list(projects),
    )


@tickets_router.get('/{short_id}/position', response_model=AgentTaskPosition)
async def get_agent_task_position(
    org_slug: str,
    org_id: OrgId,
    short_id: str,
    db: graph.Pool,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ticket:read')),
    ],
    status: typing.Annotated[list[Status] | None, fastapi.Query()] = None,
    agent_id: typing.Annotated[list[str] | None, fastapi.Query()] = None,
    owner: typing.Annotated[list[str] | None, fastapi.Query()] = None,
    mine: bool = False,
    q: str | None = None,
) -> dict[str, typing.Any]:
    """Find where a task is in the task list with the same filters: its
    inbox group and its index in that group, so a client can scroll to
    it before it reads that part of the list.

    Raises:
        403: The caller is not a member of the org.
        404: No such organization, or the filters do not find the task.

    """
    text = (q or '').strip().lower()
    agents, projects = await _text_matches(db, org_slug, text)
    owners = [*(owner or []), *([auth.principal_name] if mine else [])]
    found = await store.position(
        org_id,
        short_id,
        statuses=status,
        agent_ids=agent_id,
        owners=owners,
        text=text or None,
        text_agent_ids=list(agents),
        text_project_ids=list(projects),
    )
    if found is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'{short_id} is not in the list'
        )
    return {'group': found[0], 'index': found[1]}


async def _text_matches(
    db: graph.Graph, org_slug: str, text: str
) -> tuple[dict[str, str], dict[str, str]]:
    """The agents (id to name) and projects (id to slug) of the org that
    ``text`` matches by agent name and project slug.
    """
    if not text:
        return {}, {}
    records = await db.execute(
        _TEXT_QUERY,
        {'org_slug': org_slug, 'text': text},
        ['agent_ids', 'agent_names', 'project_ids', 'project_slugs'],
    )
    if not records:
        return {}, {}
    record = records[0]
    return (
        _pairs(record['agent_ids'], record['agent_names']),
        _pairs(record['project_ids'], record['project_slugs']),
    )


@tickets_router.get('/waiting', response_model=AgentTaskWaiting)
async def count_waiting_agent_tasks(
    org_id: OrgId,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ticket:read')),
    ],
    lists: bool = False,
) -> dict[str, typing.Any]:
    """Count, and with ``lists`` list, what waits on the caller (ADR
    0028).

    ``requests`` are the open requests that have not expired on the
    tickets that the caller owns and that are not closed, whatever
    their status: a ticket that is paused with an open request (Reply
    and hold) still waits. ``assigned`` are the person tickets assigned
    to the caller that are not closed. ``held`` are the held tickets
    that the caller owns with a gating prerequisite that closed with an
    outcome that does not release them. ``count`` is the number of
    items. Without ``lists`` (the navigation badge, which polls), only
    ``count`` is sent and the lists are empty. A caller that is not a
    person has none.

    Raises:
        403: The caller is not a member of the org.
        404: No such organization.

    """
    if auth.user is None:
        return {'count': 0}
    return await store.waiting(org_id, auth.user.email, lists=lists)


@tickets_router.get('/{short_id}', response_model=AgentTaskResponse)
async def get_agent_task(task: ReadableTask) -> dict[str, typing.Any]:
    """Get a task by its short id (``T-<n>``).

    The service account of the task's agent can read its own task.
    """
    return task


@tickets_router.get(
    '/{short_id}/events', response_model=list[AgentTaskEventResponse]
)
async def list_agent_task_events(
    task: ReadableTask,
    store: tickets.Store,
    after_seq: typing.Annotated[int, fastapi.Query(ge=0)] = 0,
    limit: typing.Annotated[int, fastapi.Query(ge=1, le=1000)] = 100,
) -> list[dict[str, typing.Any]]:
    """List the events of a task with ``seq`` after ``after_seq``.

    To read new events, give the ``seq`` of the last event that you
    have as ``after_seq``. The events of an archived task come from
    ClickHouse, in the same shape. The service account of the task's
    agent can read the events of its own task.
    """
    if task['log_archived_at'] is not None:
        return await tickets.log.archived_events(task, after_seq, limit)
    return await store.events(task['id'], after_seq, limit)


@tickets_router.post('/{short_id}/pause', response_model=AgentTaskResponse)
async def pause_agent_task(
    org_id: OrgId,
    short_id: str,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ticket:manage')),
    ],
) -> dict[str, typing.Any]:
    """Set the control value of a task to ``pause``.

    Raises:
        403: The caller is not a member of the org.
        404: No such task.
        409: The task is closed, or a cancel is not done yet.

    """
    return await _set_control(store, org_id, short_id, 'pause', auth)


@tickets_router.post('/{short_id}/resume', response_model=AgentTaskResponse)
async def resume_agent_task(
    org_id: OrgId,
    short_id: str,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ticket:manage')),
    ],
) -> dict[str, typing.Any]:
    """Set the control value of a task to ``run``.

    Raises:
        403: The caller is not a member of the org.
        404: No such task.
        409: The task is closed, or a cancel is not done yet.

    """
    return await _set_control(store, org_id, short_id, 'run', auth)


@tickets_router.post('/{short_id}/cancel', response_model=AgentTaskResponse)
async def cancel_agent_task(
    org_id: OrgId,
    short_id: str,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ticket:manage')),
    ],
) -> dict[str, typing.Any]:
    """Set the control value of a task to ``cancel``.

    Raises:
        403: The caller is not a member of the org.
        404: No such task.
        409: The task is closed.

    """
    return await _set_control(store, org_id, short_id, 'cancel', auth)


@tickets_router.delete('/{short_id}', status_code=204)
async def delete_agent_task(
    org_id: OrgId,
    short_id: str,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ticket:delete')),
    ],
) -> None:
    """Delete a closed task, with its events and relations.

    The secret audit and the usage records of the task stay.

    Raises:
        403: The caller has no ``ticket:delete``, or is not a member
            of the org.
        404: No such task.
        409: The task, or a task in its chain, is not closed.

    """
    try:
        task = await store.delete(org_id, short_id.upper(), _actor(auth))
    except tickets.TaskNotFound as e:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Task {short_id!r} not found'
        ) from e
    except tickets.TaskOpen as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Task {short_id!r} or a task in its chain is not closed,'
                ' or its log is not archived yet'
            ),
        ) from e
    LOGGER.info(
        'Agent task %s (%s) deleted by %s',
        task['short_id'],
        task['id'],
        _actor(auth).id,
    )


@tickets_router.post(
    '/{short_id}/acknowledge', response_model=AgentTaskResponse
)
async def acknowledge_agent_task(
    org_id: OrgId,
    short_id: str,
    store: tickets.Store,
    auth: ManagingPerson,
) -> dict[str, typing.Any]:
    """Mark a closed task as needing no more attention.

    The first acknowledgement stays; a repeat returns the task.

    Raises:
        403: The caller is not a person, or not a member of the org.
        404: No such task.
        409: The task is not closed.

    """
    user = auth.require_user
    try:
        return await store.acknowledge(org_id, short_id.upper(), user.email)
    except tickets.TaskNotFound as e:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Task {short_id!r} not found'
        ) from e
    except tickets.TaskOpen as e:
        raise fastapi.HTTPException(
            status_code=409, detail=f'Task {short_id!r} is not closed'
        ) from e


#: The most text of the last agent turn that a retry copies.
RETRY_TURN_LIMIT = 16_000


def retry_description(
    task: dict[str, typing.Any],
    last_turn: str | None,
    note: str | None,
    person: str,
) -> str:
    """Return the description of a retry of ``task``.

    It is the description of the task, then what happened to it: the
    outcome and the last agent turn. Then the note of the person.
    """
    outcome = f'`{task["outcome"]}`'
    if task['outcome_reason']:
        outcome += f': {task["outcome_reason"]}'
    parts = [
        task['description'],
        '---',
        '## Previous attempt',
        f'This task retries {task["short_id"]}, which closed as {outcome}.',
    ]
    if last_turn:
        if len(last_turn) > RETRY_TURN_LIMIT:
            last_turn = last_turn[:RETRY_TURN_LIMIT] + ' …'
        quoted = '\n'.join(f'> {line}' for line in last_turn.splitlines())
        parts += ['The last message from the agent:', quoted]
    if note:
        parts += [f'## Note from {person}', note]
    return '\n\n'.join(parts)


@tickets_router.post(
    '/{short_id}/retry',
    status_code=201,
    response_model=AgentTaskResponse,
    responses={
        200: {
            'model': AgentTaskResponse,
            'description': (
                'A task with this idempotency key exists; it is returned '
                'unchanged.'
            ),
        },
    },
)
async def retry_agent_task(
    org_slug: str,
    org_id: OrgId,
    short_id: str,
    data: AgentTaskRetry,
    response: fastapi.Response,
    db: graph.Pool,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ticket:create')),
    ],
) -> dict[str, typing.Any]:
    """Make a new task that does a closed task again.

    The new task has the agent, title, and projects of the closed task.
    Its description adds what happened to the closed task, and the note
    of the person. The closed task does not change. The caller also
    needs ``ticket:read``, because the new description shows the
    log of the closed task.

    Raises:
        403: The caller is not a person, not a member of the org, or
            cannot read tasks.
        404: No such task.
        409: The task is not closed, or its agent is disabled.
        422: The agent or a project is no longer in the org.

    """
    user = auth.require_user
    await _require_read(auth)
    task = await _get_task(store, org_id, short_id)
    if task['assignee_kind'] == 'person':
        raise _person_ticket(short_id)
    if task['status'] != 'closed':
        raise fastapi.HTTPException(
            status_code=409, detail=f'Task {short_id!r} is not closed'
        )
    # A repeat returns the first retry before the agent and log reads,
    # which can fail after the first retry succeeded.
    origin = task_origin(auth)
    existing = await _keyed_task(
        store, org_id, origin, data.idempotency_key, response
    )
    if existing is not None:
        return existing
    records = await db.execute(
        _AGENT_SLUG_QUERY,
        {'id': task['agent_id'], 'org_slug': org_slug},
        ['slug'],
    )
    if not records:
        raise _unprocessable('The agent of the task is not in the org')
    last_turn = await store.last_agent_turn(task)
    # Not validated: the projects are stored associations, and a task can
    # have more of them than the 50 that a create request allows.
    create = AgentTaskCreate.model_construct(
        agent_slug=str(graph.parse_agtype(records[0]['slug'])),
        title=task['title'],
        description=retry_description(task, last_turn, data.note, user.email),
        project_ids=[p['project_id'] for p in task['projects']],
        priority=task['priority'],
    )
    return await _create_task(
        db,
        store,
        org_slug,
        org_id,
        create,
        origin,
        data.idempotency_key,
        response,
        auth,
    )


@tickets_router.post('/{short_id}/reassign', response_model=AgentTaskResponse)
async def reassign_agent_task(
    org_slug: str,
    org_id: OrgId,
    short_id: str,
    data: AgentTaskReassign,
    db: graph.Pool,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ticket:manage')),
    ],
) -> dict[str, typing.Any]:
    """Give a task a new owner.

    Raises:
        403: The caller is not a member of the org.
        404: No such task.
        409: The task is closed.
        422: The new owner is not a member of the org.

    """
    if not await db.execute(
        _MEMBER_QUERY, {'email': data.owner, 'org_slug': org_slug}, ['email']
    ):
        raise _unprocessable(f'User {data.owner!r} is not in the org')
    try:
        return await store.set_owner(
            org_id, short_id.upper(), data.owner, _actor(auth)
        )
    except tickets.TaskNotFound as e:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Task {short_id!r} not found'
        ) from e
    except tickets.TaskClosed as e:
        raise fastapi.HTTPException(
            status_code=409, detail=f'Task {short_id!r} is closed'
        ) from e


@tickets_router.post('/{short_id}/status', response_model=AgentTaskResponse)
async def set_ticket_status(
    org_id: OrgId,
    short_id: str,
    data: TicketStatusSet,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> dict[str, typing.Any]:
    """Move a person ticket to a status, or close it (ADR 0028).

    ``open`` -> ``in_progress``; ``open`` or ``in_progress`` ->
    ``blocked`` (with a ``reason``) and back; ``closed`` with an
    ``outcome`` from every status. A ``held`` ticket opens when its
    gating prerequisites are done. The assignee makes these changes;
    other people need ``ticket:manage``.

    Raises:
        403: The caller is not a person, or is not the assignee and has
            no ``ticket:manage``.
        404: No such task.
        409: The task is closed (``Task ... is closed``), is an agent
            ticket (``agent_ticket``), or cannot move from its status
            (``transition_invalid``).

    """
    user = auth.require_user
    task = await _get_task(store, org_id, short_id)
    if (task['assignee'] or '').lower() != user.email.lower():
        await _require_manage(auth)
    try:
        return await store.set_person_status(
            org_id,
            task['short_id'],
            data.status,
            _actor(auth),
            outcome=data.outcome,
            reason=data.reason,
        )
    except tickets.TaskClosed as e:
        raise fastapi.HTTPException(
            status_code=409, detail=f'Task {short_id!r} is closed'
        ) from e
    except tickets.WrongAssigneeKind as e:
        raise _conflict(
            'agent_ticket',
            f'Task {short_id!r} is an agent ticket; its status follows its '
            'sessions',
        ) from e
    except tickets.TransitionInvalid as e:
        raise _conflict('transition_invalid', str(e)) from e


@tickets_router.post('/{short_id}/hand-off', response_model=AgentTaskResponse)
async def hand_off_ticket(
    org_slug: str,
    org_id: OrgId,
    short_id: str,
    data: TicketHandOff,
    db: graph.Pool,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> dict[str, typing.Any]:
    """Hand a ticket to an agent or to a person (ADR 0028).

    The ticket keeps its id, log, owner, parent, dependencies, and cost.
    Its status changes in the same write: ``held`` stays ``held``;
    otherwise a person gets it ``open`` and an agent ``queued``. Open
    requests close as ``withdrawn``. An agent gets the ticket at the
    agent version that it has now. A person ticket to another person
    changes only the assignee. The owner and the assignee make this
    change; other callers need ``ticket:manage``. To an agent, the
    caller also needs ``ticket:create``, and the owner must be able to
    make tickets (see :func:`may_create`), as for a create: the agent
    works for the owner. An agent hands off its own ticket, to a person
    only, with the harness tool ``hand_off``.

    Raises:
        403: The caller is not the owner or the assignee and has no
            ``ticket:manage``; or, to an agent, the caller has no
            ``ticket:create`` or the owner cannot make tickets
            (``owner_forbidden``).
        404: No such task.
        409: The task is closed, is an agent ticket and goes to an agent
            (``agent_ticket``), has an open session (``session_open``),
            has a pinned chain (``chain_pinned``), or a cancel is not
            done yet. The agent is disabled.
        422: The agent or the person is not in the org.

    """
    task = await _get_task(store, org_id, short_id)
    people = {task['owner'].lower(), (task['assignee'] or '').lower()}
    if auth.user is None or auth.user.email.lower() not in people:
        await _require_manage(auth)
    if data.assignee_kind == 'agent' == task['assignee_kind']:
        raise _agent_ticket(short_id)
    if data.assignee_kind == 'person':
        to = await person_assignee(db, org_slug, data.assignee)
    else:
        # An agent works for the owner: as for a create, the caller needs
        # ticket:create, and the owner must be able to make tickets.
        await _require_create(auth)
        if not await may_create(db, org_slug, task['owner']):
            raise autonomous.forbidden(
                'owner_forbidden',
                f'{task["owner"]!r} cannot make agent tickets in '
                f'organization {org_slug!r}.',
            )
        to = await agent_assignee(db, org_slug, data.agent_slug or '')
    try:
        with write_errors(short_id):
            return await store.hand_off(
                org_id,
                task['short_id'],
                dataclasses.replace(to, note=data.note),
                _actor(auth),
            )
    except tickets.WrongAssigneeKind as e:
        raise _agent_ticket(short_id) from e
    except tickets.SessionOpen as e:
        raise _conflict(
            'session_open',
            f'Task {short_id!r} has an open session; pause it and hand it '
            'off when the session closes',
        ) from e
    except tickets.ChainPinned as e:
        raise _conflict(
            'chain_pinned',
            f'A runner holds the chain of task {short_id!r}; hand it off '
            'when the runner lets it go',
        ) from e


def _agent_ticket(short_id: str) -> fastapi.HTTPException:
    """409 for a handoff of an agent ticket to an agent."""
    return _conflict(
        'agent_ticket',
        f'Task {short_id!r} is an agent ticket; hand it off to a person',
    )


@tickets_router.post('/{short_id}/priority', response_model=AgentTaskResponse)
async def set_agent_task_priority(
    org_id: OrgId,
    short_id: str,
    data: AgentTaskPriority,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ticket:manage')),
    ],
) -> dict[str, typing.Any]:
    """Set the priority of a task.

    Raises:
        403: The caller is not a member of the org.
        404: No such task.
        409: The task is closed.

    """
    try:
        return await store.set_priority(
            org_id, short_id.upper(), data.priority, _actor(auth)
        )
    except tickets.TaskNotFound as e:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Task {short_id!r} not found'
        ) from e
    except tickets.TaskClosed as e:
        raise fastapi.HTTPException(
            status_code=409, detail=f'Task {short_id!r} is closed'
        ) from e


@tickets_router.post(
    '/{short_id}/requests/{request_id}/resolve',
    status_code=201,
    response_model=AgentTaskRequestResolveResponse,
    responses={
        200: {
            'model': AgentTaskRequestResolveResponse,
            'description': (
                'The caller already resolved the request this way; it is '
                'returned unchanged.'
            ),
        },
    },
)
async def resolve_agent_task_request(
    org_id: OrgId,
    short_id: str,
    request_id: uuid.UUID,
    data: AgentTaskRequestResolve,
    response: fastapi.Response,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ticket:resolve')),
    ],
) -> dict[str, typing.Any]:
    """Answer a feedback request, or approve or reject an approval.

    Only a person can resolve a request, so an agent can never resolve
    its own request or one of its subagent (I6). An approval names the
    digests that the person reviewed; they must be the digests of the
    request (I3). The resolution records the person, the time, the
    channel, the constraints, and the approved digests (I9).

    The status is 201 when this call resolves the request. When the
    same person sends the same resolution again, the status is 200 and
    nothing changes. A request that someone else resolved is a
    ``409 request_resolved`` that names who resolved it (I4).

    Raises:
        403: The caller is not a person, has no ``ticket:resolve``,
            or is not a member of the org.
        404: No such task or request.
        409: ``task_closed``, ``request_resolved``, ``request_expired``,
            or ``digest_mismatch``.
        413: The resolution is larger than :data:`MAX_PAYLOAD_BYTES`.
        422: The status does not fit the kind of the request.

    """
    _ = auth.require_user  # raises 403 for a caller that is not a person
    check_payload_size('The resolution', data.model_dump(mode='json'))
    try:
        task, request, created = await store.resolve_request(
            org_id,
            short_id.upper(),
            request_id,
            tickets.Resolution(
                status=data.status,
                answer=data.answer,
                constraints=data.constraints,
                artifact_digests=data.artifact_digests,
            ),
            _actor(auth),
        )
    except tickets.TaskNotFound as e:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Task {short_id!r} not found'
        ) from e
    except tickets.RequestNotFound as e:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Request {request_id} not found'
        ) from e
    except tickets.TaskClosed as e:
        raise _conflict('task_closed', f'Task {short_id!r} is closed') from e
    except tickets.RequestNotOpen as e:
        if e.request['status'] == 'open':
            raise _conflict(
                'request_expired', f'Request {request_id} expired'
            ) from e
        raise _conflict(
            'request_resolved',
            f'Request {request_id} is {e.request["status"]} by '
            f'{e.request["resolved_by"]}',
            status=e.request['status'],
            resolved_by=e.request['resolved_by'],
            resolved_at=e.request['resolved_at'].isoformat(),
        ) from e
    except tickets.DigestMismatch as e:
        raise _conflict(
            'digest_mismatch',
            'The artifacts changed; the approval is void. Review the '
            'request again.',
        ) from e
    except tickets.ResolutionInvalid as e:
        raise _unprocessable(str(e)) from e
    if not created:
        response.status_code = 200
    return {'request': request, 'task': task}


@tickets_router.post('/{short_id}/reply', response_model=AgentTaskResponse)
async def reply_agent_task(
    org_id: OrgId,
    short_id: str,
    data: AgentTaskReply,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ticket:manage')),
    ],
) -> dict[str, typing.Any]:
    """Write a reply from a person to the agent (H3).

    The reply is a ``turn`` event with the person and the channel. The
    harness reads it by seq at its next turn boundary (H7). With
    ``hold``, the control value also changes to ``pause``, in the same
    transaction (Reply and hold).

    Raises:
        403: The caller is not a person, has no ``ticket:manage``,
            or is not a member of the org.
        404: No such task.
        409: The task is closed, or ``hold`` and a cancel is not done
            yet.
        413: The reply is larger than :data:`MAX_PAYLOAD_BYTES`.

    """
    _ = auth.require_user  # raises 403 for a caller that is not a person
    check_payload_size('The reply', data.model_dump(mode='json'))
    try:
        return await store.reply(
            org_id, short_id.upper(), data.body, _actor(auth), hold=data.hold
        )
    except tickets.TaskNotFound as e:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Task {short_id!r} not found'
        ) from e
    except tickets.TaskClosed as e:
        raise fastapi.HTTPException(
            status_code=409, detail=f'Task {short_id!r} is closed'
        ) from e
    except tickets.CancelPending as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Task {short_id!r} has a cancel that is not done yet',
        ) from e
    except tickets.WrongAssigneeKind as e:
        raise _person_ticket(short_id) from e


@tickets_router.get('/{short_id}/relations', response_model=AgentTaskRelations)
async def get_agent_task_relations(
    task: ReadableTask, store: tickets.Store, _auth: TaskReader
) -> dict[str, typing.Any]:
    """List the tasks related to a task: the tasks it requires, the
    tasks that require it, and its parent and children (delegation).

    The caller needs ``ticket:read``, also the service account of the
    task's agent: the relations show other tasks.
    """
    return await store.relations(task)


@tickets_router.put('/{short_id}/requires/{prerequisite}', status_code=204)
async def add_agent_task_dependency(
    org_id: OrgId,
    short_id: str,
    prerequisite: str,
    store: tickets.Store,
    auth: ManagingPerson,
    data: TicketDependencySet = TicketDependencySet(),  # noqa: B008
) -> None:
    """Make the task require the ``prerequisite`` task, in the same org.

    A dependency is information only, unless it ``gates`` (ADR 0028): a
    ``queued`` task then becomes ``held`` until the prerequisite closes
    with a ``done_*`` outcome. Each task gets a ``dependency.added``
    event; an archived task gets none. When the dependency exists with
    the same ``gates`` value, nothing changes; with another value, the
    value changes.

    Raises:
        403: The caller is not a person, has no ``ticket:manage``,
            or is not a member of the org.
        404: No such task.
        409: ``task_archived``: both tasks are archived.
            ``ticket_started``: ``gates``, the task is not ``queued``
            or ``held``, and the dependency does not gate already.
        422: The two tasks are the same.

    """
    _ = auth.require_user  # raises 403 for a caller that is not a person
    with relation_errors():
        await store.add_dependency(
            org_id,
            short_id.upper(),
            prerequisite.upper(),
            _actor(auth),
            gates=data.gates,
        )


@tickets_router.delete('/{short_id}/requires/{prerequisite}', status_code=204)
async def remove_agent_task_dependency(
    org_id: OrgId,
    short_id: str,
    prerequisite: str,
    store: tickets.Store,
    auth: ManagingPerson,
) -> None:
    """Remove the dependency of the task on the ``prerequisite`` task.

    Each task gets a ``dependency.removed`` event with the removed row;
    an archived task gets none. A ``held`` task that no other gate holds
    is released. When there is no such dependency, nothing changes.

    Raises:
        403: The caller is not a person, has no ``ticket:manage``,
            or is not a member of the org.
        404: No such task.
        409: ``task_archived``: both tasks are archived.

    """
    _ = auth.require_user  # raises 403 for a caller that is not a person
    with relation_errors():
        await store.remove_dependency(
            org_id, short_id.upper(), prerequisite.upper(), _actor(auth)
        )


@tickets_router.put('/{short_id}/parent', status_code=204)
async def set_agent_task_parent(
    org_id: OrgId,
    short_id: str,
    data: TicketParentSet,
    store: tickets.Store,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> None:
    """Move the task, with its descendants, under another task in the
    org, or make it a root (ADR 0028).

    The owner of the task and holders of ``ticket:manage`` can move
    it. A move changes no status, assignee, dependency, or chain. The
    task gets a ``parent.changed`` event with the old and new parent.
    When the parent does not change, nothing changes.

    Raises:
        403: The caller is not a person, or is not the owner and has no
            ``ticket:manage``.
        404: No such task.
        409: ``task_archived``: the log of the task is archived.
            ``parent_cycle``: the task is the new parent or one of its
            ancestors.

    """
    user = auth.require_user  # raises 403 for a caller that is not a person
    task = await _get_task(store, org_id, short_id)
    if task['owner'] != user.email:
        await _require_manage(auth)
    with relation_errors():
        await store.set_parent(
            org_id,
            task['short_id'],
            data.parent and data.parent.upper(),
            _actor(auth),
        )


@tickets_router.get(
    '/{short_id}/projects', response_model=list[AssociatedProject]
)
async def list_agent_task_projects(
    org_slug: str,
    task: ReadableTask,
    db: graph.Pool,
    store: tickets.Store,
    _auth: TaskReader,
) -> list[dict[str, typing.Any]]:
    """List the projects of a task, oldest first.

    The caller needs ``ticket:read``, also the service account of the
    task's agent: the rows show who associated each project.

    A project that is no longer in the org is not ``available``; its
    slug is the slug when it was associated.
    """
    rows = await store.projects(task)
    records = await db.execute(
        _PROJECTS_QUERY,
        {'org_slug': org_slug, 'ids': [row['project_id'] for row in rows]},
        ['id', 'slug', 'name'],
    )
    found = {
        str(graph.parse_agtype(r['id'])): (
            str(graph.parse_agtype(r['slug'])),
            graph.parse_agtype(r['name']),
        )
        for r in records
    }
    for row in rows:
        current = found.get(row['project_id'])
        row['available'] = current is not None
        if current is not None:
            row['project_slug'], row['name'] = current
    return rows


@tickets_router.put('/{short_id}/projects/{project_id}', status_code=204)
async def associate_agent_task_project(
    org_slug: str,
    org_id: OrgId,
    short_id: str,
    project_id: str,
    db: graph.Pool,
    store: tickets.Store,
    auth: ManagingPerson,
) -> None:
    """Associate a project of the org with the task (F13).

    The task gets a ``project.associated`` event. When the project is
    associated, nothing changes.

    Raises:
        403: The caller is not a person, has no ``ticket:manage``,
            or is not a member of the org.
        404: No such task.
        409: ``task_archived``.
        422: The project is not in the org.

    """
    _ = auth.require_user  # raises 403 for a caller that is not a person
    [(project_id, slug)] = await project_slugs(db, org_slug, [project_id])
    with relation_errors():
        await store.associate_project(
            org_id, short_id.upper(), project_id, slug, _actor(auth)
        )


@tickets_router.delete('/{short_id}/projects/{project_id}', status_code=204)
async def dissociate_agent_task_project(
    org_id: OrgId,
    short_id: str,
    project_id: str,
    store: tickets.Store,
    auth: ManagingPerson,
) -> None:
    """Remove a project association from the task.

    The task gets a ``project.dissociated`` event with the removed row.
    A project that is no longer in the org can also be removed. When the
    project is not associated, nothing changes.

    Raises:
        403: The caller is not a person, has no ``ticket:manage``,
            or is not a member of the org.
        404: No such task.
        409: ``task_archived``.

    """
    _ = auth.require_user  # raises 403 for a caller that is not a person
    with relation_errors():
        await store.dissociate_project(
            org_id, short_id.upper(), project_id, _actor(auth)
        )
