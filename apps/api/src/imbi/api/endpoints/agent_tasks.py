"""Agent task endpoints (ADR 0020).

An agent task is the durable unit of work of one agent. Its state lives
in the ``agent_runtime`` Postgres schema; the graph holds the agent,
the organization, and the project that a task refers to by id. People
are referred to by email, as everywhere in this API.

Every route needs the caller to be a member of the organization
(``MEMBER_OF``), because task content is sensitive and the
``agent_task:*`` permissions are not scoped to an organization. A
caller that is not a member gets ``403 organization_forbidden``, as in
:mod:`imbi.api.auth.autonomous`. There is no admin bypass.

Nothing runs a task yet. A person can make a task, read it and its
events, and change its control value. When no harness session is open,
a control change also changes the status at once: see
:meth:`imbi.api.agent_tasks.TaskStore.set_control`.
"""

import datetime
import decimal
import typing
import uuid

import fastapi
import pydantic

from imbi.api import agent_tasks
from imbi.api.agent_tasks.store import ActorKind, Channel, Control, Status
from imbi.api.auth import autonomous, permissions
from imbi.api.endpoints import agents
from imbi.api.endpoints._pagination import (
    build_link_header,
    decode_cursor,
    encode_cursor,
)
from imbi.common import graph, models

#: The origin kind of a task that a person makes with this API.
HUMAN_ORIGIN = 'human'


# --- Schemas -----------------------------------------------------------


class AgentTaskCreate(pydantic.BaseModel):
    agent_slug: str = pydantic.Field(min_length=1)
    title: str = pydantic.Field(min_length=1)
    description: str = pydantic.Field(
        min_length=1, description='The instruction for the agent.'
    )
    project_id: str | None = pydantic.Field(
        default=None, description='The primary project of the task.'
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


class AgentTaskReassign(pydantic.BaseModel):
    owner: pydantic.EmailStr = pydantic.Field(
        description='The email of the new owner. Must be in the org.'
    )


class AgentTaskOrigin(pydantic.BaseModel):
    """What started a task. It does not change."""

    model_config = pydantic.ConfigDict(extra='allow')

    kind: typing.Literal['human', 'schedule', 'webhook', 'task']
    #: The email of the person, for a ``human`` origin.
    user: str | None = None


class AgentTaskResponse(pydantic.BaseModel):
    id: uuid.UUID
    short_id: str
    agent_id: str
    agent_version: int
    prompt_version: int | None = None
    service_account_id: str
    project_id: str | None = None
    title: str
    description: str
    origin: AgentTaskOrigin
    idempotency_key: str | None = None
    owner: str
    budget: decimal.Decimal | None = None
    status: Status
    control: Control
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


# --- Queries -----------------------------------------------------------

#: The org id, and whether the user with ``email`` is a member of it.
_ORG_MEMBER_QUERY: typing.LiteralString = """
MATCH (o:Organization {{slug: {org_slug}}})
OPTIONAL MATCH (u:User {{email: {email}}})-[:MEMBER_OF]->(o)
RETURN o.id AS id, u IS NOT NULL AS member
"""

#: The agents and projects that the text query of the task list
#: matches by agent name and project slug (O3).
_TEXT_QUERY: typing.LiteralString = """
MATCH (o:Organization {{slug: {org_slug}}})
OPTIONAL MATCH (a:Agent)-[:BELONGS_TO]->(o)
WHERE toLower(a.name) CONTAINS {text}
WITH o, collect(a.id) AS agent_ids
OPTIONAL MATCH (p:Project)-[:OWNED_BY]->(:Team)-[:BELONGS_TO]->(o)
WHERE toLower(p.slug) CONTAINS {text}
RETURN agent_ids, collect(p.id) AS project_ids
"""

_AGENT_QUERY: typing.LiteralString = """
MATCH (a:Agent {{slug: {slug}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN a
"""

_PROJECT_QUERY: typing.LiteralString = """
MATCH (p:Project {{id: {project_id}}})
      -[:OWNED_BY]->(:Team)
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN p.id AS id
"""

_MEMBER_QUERY: typing.LiteralString = """
MATCH (u:User {{email: {email}}})
      -[:MEMBER_OF]->(:Organization {{slug: {org_slug}}})
RETURN u.email AS email
"""


# --- Helpers -----------------------------------------------------------


def _org_not_found(org_slug: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=404,
        detail=f'Organization with slug {org_slug!r} not found',
    )


def _unprocessable(detail: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(status_code=422, detail=detail)


async def _member_org_id(
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> str:
    """Return the id of the organization when the caller is a member.

    Raises:
        403: The caller is not a member of the organization.
        404: No such organization.

    """
    records = await db.execute(
        _ORG_MEMBER_QUERY,
        {
            'org_slug': org_slug,
            'email': auth.user.email if auth.user else None,
        },
        ['id', 'member'],
    )
    if not records:
        raise _org_not_found(org_slug)
    if auth.user is None:
        await autonomous.require_organization_membership(
            db, auth, org_slug=org_slug
        )
    elif not graph.parse_agtype(records[0]['member']):
        raise autonomous.forbidden(
            'organization_forbidden',
            (
                f'Principal {auth.principal_name!r} is not a member of '
                f'organization {org_slug!r}.'
            ),
            org_slug=org_slug,
        )
    return str(graph.parse_agtype(records[0]['id']))


#: The id of the organization in the path. The router also depends on
#: it, so no route can skip the membership check.
OrgId = typing.Annotated[str, fastapi.Depends(_member_org_id)]


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


def _task_budget(
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


def _actor(auth: permissions.AuthContext) -> agent_tasks.Actor:
    """Return the actor of a request, for the events that it writes.

    A browser session authenticates with a JWT; other callers use an API
    key or client credentials.
    """
    channel: Channel = 'web' if auth.auth_method == 'jwt' else 'api'
    if auth.user is not None:
        return agent_tasks.Actor('human', auth.user.email, channel)
    return agent_tasks.Actor('system', auth.principal_name, channel)


async def _get_task(
    store: agent_tasks.TaskStore, org_id: str, short_id: str
) -> dict[str, typing.Any]:
    task = await store.get(org_id, short_id.upper())
    if task is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Task {short_id!r} not found'
        )
    return task


async def _set_control(
    store: agent_tasks.TaskStore,
    org_id: str,
    short_id: str,
    control: Control,
    auth: permissions.AuthContext,
) -> dict[str, typing.Any]:
    try:
        return await store.set_control(
            org_id, short_id.upper(), control, _actor(auth)
        )
    except agent_tasks.TaskNotFound as e:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Task {short_id!r} not found'
        ) from e
    except agent_tasks.TaskClosed as e:
        raise fastapi.HTTPException(
            status_code=409, detail=f'Task {short_id!r} is closed'
        ) from e
    except agent_tasks.CancelPending as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Task {short_id!r} has a cancel that is not done yet',
        ) from e


# --- Endpoints ---------------------------------------------------------

agent_tasks_router = fastapi.APIRouter(
    tags=['Agent Tasks'], dependencies=[fastapi.Depends(_member_org_id)]
)


@agent_tasks_router.post(
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
    store: agent_tasks.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent_task:create')),
    ],
) -> dict[str, typing.Any]:
    """Make a task for an agent, owned by the caller.

    The task records the agent version and the prompt version that the
    agent has now. A repeat with the same ``idempotency_key`` returns
    the first task with status 200.

    Raises:
        403: The caller is not a person, or not a member of the org.
        404: No such organization.
        409: The agent is disabled.
        422: The agent or the project is not in the org, or the budget
            is more than the agent's task budget.

    """
    user = auth.require_user
    if data.idempotency_key is not None:
        existing = await store.find_by_idempotency_key(
            org_id, HUMAN_ORIGIN, user.id, data.idempotency_key
        )
        if existing is not None:
            response.status_code = 200
            return existing
    agent = await _fetch_agent(db, org_slug, data.agent_slug)
    if not agent.get('enabled', True):
        raise fastapi.HTTPException(
            status_code=409, detail=f'Agent {data.agent_slug!r} is disabled'
        )
    raw_settings: typing.Any = agent.get('settings') or {}
    settings = (
        models.AgentSettings.model_validate_json(raw_settings)
        if isinstance(raw_settings, str)
        else models.AgentSettings.model_validate(raw_settings)
    )
    budget = _task_budget(settings, data.budget)
    if data.project_id is not None and not await db.execute(
        _PROJECT_QUERY,
        {'project_id': data.project_id, 'org_slug': org_slug},
        ['id'],
    ):
        raise _unprocessable(f'Project {data.project_id!r} not found')
    agent_id = str(agent['id'])
    service_account_id = await agents.ensure_service_account(
        db, agent_id, str(agent.get('name', data.agent_slug))
    )
    origin = {'kind': HUMAN_ORIGIN, 'user': user.email}
    agent_version = int(agent.get('version') or 1)
    prompt_version = agent.get('prompt_version')
    task, created = await store.create(
        agent_tasks.NewTask(
            organization_id=org_id,
            agent_id=agent_id,
            agent_version=agent_version,
            prompt_version=prompt_version,
            service_account_id=service_account_id,
            project_id=data.project_id,
            title=data.title,
            description=data.description,
            origin_kind=HUMAN_ORIGIN,
            origin_id=user.id,
            origin=origin,
            idempotency_key=data.idempotency_key,
            owner=user.email,
            budget=budget,
        ),
        _actor(auth),
        {
            'title': data.title,
            'description': data.description,
            'origin': origin,
            'budget': None if budget is None else str(budget),
            'agent_version': agent_version,
            'prompt_version': prompt_version,
        },
    )
    if not created:
        response.status_code = 200
    return task


@agent_tasks_router.get('/', response_model=list[AgentTaskResponse])
async def list_agent_tasks(
    org_slug: str,
    org_id: OrgId,
    request: fastapi.Request,
    response: fastapi.Response,
    db: graph.Pool,
    store: agent_tasks.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent_task:read')),
    ],
    status: typing.Annotated[list[Status] | None, fastapi.Query()] = None,
    agent_id: str | None = None,
    owner: str | None = None,
    mine: bool = False,
    q: str | None = None,
    limit: typing.Annotated[int, fastapi.Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> list[dict[str, typing.Any]]:
    """List the tasks in an organization, newest first.

    ``q`` matches the title, the short id, the agent name, or the
    project slug. ``mine`` keeps the tasks that the caller owns. The
    ``Link`` header has the URL of the next page.

    Raises:
        400: The cursor is not valid.
        403: The caller is not a member of the org.
        404: No such organization.

    """
    text = (q or '').strip().lower()
    agent_ids: list[str] = []
    project_ids: list[str] = []
    if text:
        records = await db.execute(
            _TEXT_QUERY,
            {'org_slug': org_slug, 'text': text},
            ['agent_ids', 'project_ids'],
        )
        if records:
            agent_ids = _ids(records[0]['agent_ids'])
            project_ids = _ids(records[0]['project_ids'])
    before: tuple[datetime.datetime, uuid.UUID] | None = None
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
    rows = await store.search(
        org_id,
        statuses=status,
        agent_id=agent_id,
        owner=auth.principal_name if mine else owner,
        text=text or None,
        text_agent_ids=agent_ids,
        text_project_ids=project_ids,
        before=before,
        limit=limit + 1,
    )
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(
            rows[-1]['created_at'], str(rows[-1]['id'])
        )
    response.headers['Link'] = build_link_header(request, next_cursor)
    return rows


@agent_tasks_router.get('/{short_id}', response_model=AgentTaskResponse)
async def get_agent_task(
    org_id: OrgId,
    short_id: str,
    store: agent_tasks.Store,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent_task:read')),
    ],
) -> dict[str, typing.Any]:
    """Get a task by its short id (``T-<n>``)."""
    return await _get_task(store, org_id, short_id)


@agent_tasks_router.get(
    '/{short_id}/events', response_model=list[AgentTaskEventResponse]
)
async def list_agent_task_events(
    org_id: OrgId,
    short_id: str,
    store: agent_tasks.Store,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent_task:read')),
    ],
    after_seq: typing.Annotated[int, fastapi.Query(ge=0)] = 0,
    limit: typing.Annotated[int, fastapi.Query(ge=1, le=1000)] = 100,
) -> list[dict[str, typing.Any]]:
    """List the events of a task with ``seq`` after ``after_seq``.

    To read new events, give the ``seq`` of the last event that you
    have as ``after_seq``.
    """
    task = await _get_task(store, org_id, short_id)
    return await store.events(task['id'], after_seq, limit)


@agent_tasks_router.post('/{short_id}/pause', response_model=AgentTaskResponse)
async def pause_agent_task(
    org_id: OrgId,
    short_id: str,
    store: agent_tasks.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent_task:manage')),
    ],
) -> dict[str, typing.Any]:
    """Set the control value of a task to ``pause``.

    Raises:
        403: The caller is not a member of the org.
        404: No such task.
        409: The task is closed, or a cancel is not done yet.

    """
    return await _set_control(store, org_id, short_id, 'pause', auth)


@agent_tasks_router.post(
    '/{short_id}/resume', response_model=AgentTaskResponse
)
async def resume_agent_task(
    org_id: OrgId,
    short_id: str,
    store: agent_tasks.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent_task:manage')),
    ],
) -> dict[str, typing.Any]:
    """Set the control value of a task to ``run``.

    Raises:
        403: The caller is not a member of the org.
        404: No such task.
        409: The task is closed, or a cancel is not done yet.

    """
    return await _set_control(store, org_id, short_id, 'run', auth)


@agent_tasks_router.post(
    '/{short_id}/cancel', response_model=AgentTaskResponse
)
async def cancel_agent_task(
    org_id: OrgId,
    short_id: str,
    store: agent_tasks.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent_task:manage')),
    ],
) -> dict[str, typing.Any]:
    """Set the control value of a task to ``cancel``.

    Raises:
        403: The caller is not a member of the org.
        404: No such task.
        409: The task is closed.

    """
    return await _set_control(store, org_id, short_id, 'cancel', auth)


@agent_tasks_router.post(
    '/{short_id}/reassign', response_model=AgentTaskResponse
)
async def reassign_agent_task(
    org_slug: str,
    org_id: OrgId,
    short_id: str,
    data: AgentTaskReassign,
    db: graph.Pool,
    store: agent_tasks.Store,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent_task:manage')),
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
    except agent_tasks.TaskNotFound as e:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Task {short_id!r} not found'
        ) from e
    except agent_tasks.TaskClosed as e:
        raise fastapi.HTTPException(
            status_code=409, detail=f'Task {short_id!r} is closed'
        ) from e
