"""Harness-facing agent task endpoints (ADR 0020).

A harness is the process that runs an agent. It works a task through
these routes: it opens a session, heartbeats, writes events, reports
model usage, opens requests, and sets the terminal outcome.

Only the service account of the task's agent can call these routes.
Every other caller, people included, gets ``403``. The router is
mounted with the router dependencies of the agent task routes, which
include :func:`imbi.api.auth.organizations.member_org_id`, so the
service account must also be a member of the organization.

A closed task refuses every write with ``409 task_closed``. Errors that
a harness branches on have a ``detail.error`` code.

Imbi stores payloads as the harness sends them. The harness redacts
them before it sends them (CC8); Imbi does not redact again.

Not in this version: payloads larger than :data:`MAX_PAYLOAD_BYTES` are
refused rather than moved to object storage.
"""

import datetime
import decimal
import typing
import uuid

import fastapi
import pydantic

from imbi.api import agent_tasks
from imbi.api.agent_tasks import store as task_store
from imbi.api.auth import autonomous, organizations, permissions
from imbi.api.endpoints import agent_tasks as tasks_api
from imbi.common import graph, models

#: The largest inline event payload, in bytes of JSON.
MAX_PAYLOAD_BYTES = tasks_api.MAX_PAYLOAD_BYTES

#: The event types that a harness writes. Imbi writes all others.
HarnessEventType = typing.Literal[
    'turn', 'tool.called', 'phase.changed', 'todos.updated', 'check.reported'
]

#: An outcome reason: a lower-case slug.
_REASON_PATTERN = r'^[a-z0-9][a-z0-9_.-]*$'

#: The actor of the events that Imbi writes when it enforces a limit.
_SYSTEM = agent_tasks.Actor('system', 'imbi', 'harness')


# --- Schemas -----------------------------------------------------------


class SessionOpen(pydantic.BaseModel):
    session_key: str = pydantic.Field(
        min_length=1,
        max_length=200,
        description='A repeat with the same key returns the first session.',
    )
    harness_instance: str | None = pydantic.Field(default=None, max_length=200)


class SessionClose(pydantic.BaseModel):
    reason: str = pydantic.Field(min_length=1, max_length=200)


class HarnessEvent(pydantic.BaseModel):
    """One event in the envelope of ADR 0020."""

    event_id: uuid.UUID = pydantic.Field(
        description=(
            'Picked by the harness. An event that the task already has '
            'is a duplicate and is not written again.'
        )
    )
    type: HarnessEventType
    schema_version: int = pydantic.Field(default=1, ge=1)
    actor_kind: typing.Literal['agent', 'subagent'] = 'agent'
    actor_id: str | None = pydantic.Field(
        default=None,
        min_length=1,
        max_length=200,
        description='Defaults to the id of the agent.',
    )
    at: pydantic.AwareDatetime | None = pydantic.Field(
        default=None, description='When it happened. Defaults to now.'
    )
    payload: dict[str, typing.Any] = pydantic.Field(default_factory=dict)

    @pydantic.model_validator(mode='after')
    def _phase_has_name(self) -> typing.Self:
        phase = self.payload.get('phase')
        if self.type == 'phase.changed' and not (
            isinstance(phase, str) and phase
        ):
            raise ValueError('phase.changed needs a payload.phase string')
        return self


class EventBatch(pydantic.BaseModel):
    session_id: uuid.UUID | None = None
    events: list[HarnessEvent] = pydantic.Field(min_length=1, max_length=100)


class UsageReport(pydantic.BaseModel):
    """One model call. Imbi computes the cost from the AI model catalog."""

    model_config = pydantic.ConfigDict(protected_namespaces=())

    idempotency_key: str = pydantic.Field(
        min_length=1,
        max_length=200,
        description='A repeat with the same key returns the first report.',
    )
    model_id: str = pydantic.Field(
        min_length=1,
        max_length=200,
        description='The catalog slug or the model id sent to the provider.',
    )
    tokens_in: int | None = pydantic.Field(
        default=None,
        ge=0,
        description=(
            'Uncached input tokens only. Do not include the tokens in'
            ' cache_read_tokens or cache_write_tokens.'
        ),
    )
    tokens_out: int | None = pydantic.Field(
        default=None, ge=0, description='Output tokens.'
    )
    cache_read_tokens: int | None = pydantic.Field(
        default=None, ge=0, description='Input tokens read from the cache.'
    )
    cache_write_tokens: int | None = pydantic.Field(
        default=None, ge=0, description='Input tokens written to the cache.'
    )
    session_id: uuid.UUID | None = None


class AppendEventsResponse(pydantic.BaseModel):
    #: The events written, with their seqs.
    written: list[tasks_api.AgentTaskEventResponse]
    #: The ids of the events that the task already had.
    duplicates: list[uuid.UUID]


class RequestCreate(pydantic.BaseModel):
    kind: typing.Literal['feedback', 'approval']
    title: str = pydantic.Field(min_length=1, max_length=500)
    why: str | None = None
    options: list[typing.Any] | None = None
    artifacts: list[typing.Any] | None = None
    artifact_digests: list[str] | None = pydantic.Field(
        default=None,
        description='Required for an approval: what the approval binds to.',
    )
    expires_at: pydantic.AwareDatetime | None = None
    session_id: uuid.UUID | None = None
    request_key: str | None = pydantic.Field(
        default=None,
        min_length=1,
        max_length=200,
        description=(
            'A repeat with the same key returns the first request of the task.'
        ),
    )

    @pydantic.model_validator(mode='after')
    def _check(self) -> typing.Self:
        if self.kind == 'approval' and not self.artifact_digests:
            raise ValueError('an approval needs artifact_digests')
        if self.expires_at is not None and self.expires_at <= (
            datetime.datetime.now(datetime.UTC)
        ):
            raise ValueError('expires_at must be in the future')
        return self


class OutcomeSet(pydantic.BaseModel):
    outcome: task_store.Outcome
    reason: str | None = pydantic.Field(
        default=None,
        max_length=100,
        pattern=_REASON_PATTERN,
        description='A slug. Required for every outcome but done_acted.',
    )

    @pydantic.model_validator(mode='after')
    def _reason_required(self) -> typing.Self:
        if self.outcome != 'done_acted' and not self.reason:
            raise ValueError(f'outcome {self.outcome} needs a reason')
        return self


class TaskState(pydantic.BaseModel):
    """What a harness reads at each turn boundary."""

    short_id: str
    status: task_store.Status
    control: task_store.Control
    phase: str | None = None
    outcome: str | None = None
    outcome_reason: str | None = None
    #: The ``seq`` of the newest event.
    last_seq: int
    budget: decimal.Decimal | None = None
    cost_total: decimal.Decimal
    #: ``budget`` less ``cost_total``. ``None`` when there is no budget.
    budget_remaining: decimal.Decimal | None = None


class SessionResponse(pydantic.BaseModel):
    id: uuid.UUID
    session_key: str | None = None
    harness_instance: str | None = None
    opened_at: datetime.datetime
    heartbeat_at: datetime.datetime | None = None
    closed_at: datetime.datetime | None = None
    close_reason: str | None = None


class SessionOpenResponse(pydantic.BaseModel):
    session: SessionResponse
    task: TaskState


class UsageResponse(pydantic.BaseModel):
    """The budget ledger row of a report, and the task after it.

    A ``None`` token count was not measured. A ``None`` cost is unknown:
    the model or a price it needs is not in the catalog.
    """

    model_config = pydantic.ConfigDict(protected_namespaces=())

    id: uuid.UUID
    idempotency_key: str
    model_id: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    input_cost_per_million: decimal.Decimal | None = None
    output_cost_per_million: decimal.Decimal | None = None
    cache_read_cost_per_million: decimal.Decimal | None = None
    cache_write_cost_per_million: decimal.Decimal | None = None
    cost: decimal.Decimal | None = None
    recorded_at: datetime.datetime
    task: TaskState


class RequestOpenResponse(pydantic.BaseModel):
    request: tasks_api.RequestResponse
    task: TaskState


# --- Helpers -----------------------------------------------------------

_AGENT_SETTINGS_QUERY: typing.LiteralString = """
MATCH (a:Agent {{id: {id}}})
RETURN a.settings AS settings
"""

#: A model by catalog slug or by provider model id. The AI model catalog
#: is global, so the organization does not narrow the match.
_MODEL_PRICES_QUERY: typing.LiteralString = """
MATCH (m:AIModel)
WHERE m.slug = {model} OR m.model_id = {model}
RETURN m.slug AS slug,
       m.input_cost_per_million AS input_cost_per_million,
       m.output_cost_per_million AS output_cost_per_million,
       m.cache_read_cost_per_million AS cache_read_cost_per_million,
       m.cache_write_cost_per_million AS cache_write_cost_per_million
"""

_PRICE_COLUMNS = (
    'input_cost_per_million',
    'output_cost_per_million',
    'cache_read_cost_per_million',
    'cache_write_cost_per_million',
)


async def _harness_task(
    org_id: organizations.MemberOrgId,
    short_id: str,
    store: agent_tasks.Store,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> dict[str, typing.Any]:
    """Return the task when the caller is the service account of its agent.

    Raises:
        403: The caller is not the service account of the task's agent.
        404: No such task.

    """
    task = await store.get(org_id, short_id.upper())
    if task is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Task {short_id!r} not found'
        )
    account = auth.service_account
    if account is None or account.id != task['service_account_id']:
        raise autonomous.forbidden(
            'agent_task_forbidden',
            (
                f'Principal {auth.principal_name!r} is not the service '
                f'account of the agent of task {task["short_id"]}.'
            ),
        )
    return task


#: The task in the path, after the caller is checked.
HarnessTask = typing.Annotated[
    dict[str, typing.Any], fastapi.Depends(_harness_task)
]


def _agent_actor(task: dict[str, typing.Any]) -> agent_tasks.Actor:
    return agent_tasks.Actor('agent', task['agent_id'], 'harness')


async def _agent_settings(
    db: graph.Graph, agent_id: str
) -> models.AgentSettings:
    """Return the settings of the agent; defaults when it is gone."""
    records = await db.execute(
        _AGENT_SETTINGS_QUERY, {'id': agent_id}, ['settings']
    )
    raw: typing.Any = (
        graph.parse_agtype(records[0]['settings']) if records else None
    )
    if isinstance(raw, str):
        return models.AgentSettings.model_validate_json(raw)
    return models.AgentSettings.model_validate(raw or {})


async def _model_prices(
    db: graph.Graph, model: str
) -> dict[str, decimal.Decimal | None] | None:
    """Return the catalog prices of a model; ``None`` when it is unknown.

    A slug match wins. When only provider model ids match, the model
    with the first slug is used.
    """
    records = await db.execute(
        _MODEL_PRICES_QUERY, {'model': model}, ['slug', *_PRICE_COLUMNS]
    )
    rows = [
        {key: graph.parse_agtype(value) for key, value in record.items()}
        for record in records
    ]
    if not rows:
        return None
    row = next(
        (r for r in rows if r['slug'] == model),
        min(rows, key=lambda r: str(r['slug'])),
    )
    return {
        column: None
        if row[column] is None
        else decimal.Decimal(str(row[column]))
        for column in _PRICE_COLUMNS
    }


def task_state(task: dict[str, typing.Any]) -> TaskState:
    """Return the harness view of a task row."""
    budget: decimal.Decimal | None = task['budget']
    return TaskState(
        short_id=task['short_id'],
        status=task['status'],
        control=task['control'],
        phase=task['phase'],
        outcome=task['outcome'],
        outcome_reason=task['outcome_reason'],
        last_seq=task['last_seq'],
        budget=budget,
        cost_total=task['cost_total'],
        budget_remaining=(
            None if budget is None else budget - task['cost_total']
        ),
    )


def _conflict(error: str, message: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=409, detail={'error': error, 'message': message}
    )


_STORE_ERRORS = (
    agent_tasks.TaskNotFound,
    agent_tasks.SessionNotFound,
    agent_tasks.TaskClosed,
    agent_tasks.CancelPending,
    agent_tasks.SessionClosed,
    agent_tasks.ConcurrencyLimit,
    agent_tasks.EventIdConflict,
    agent_tasks.RequestKeyConflict,
)


def _translate(err: Exception, short_id: str) -> fastapi.HTTPException:
    """Return the HTTP error of a store error in :data:`_STORE_ERRORS`."""
    if isinstance(err, agent_tasks.TaskNotFound):
        return fastapi.HTTPException(
            status_code=404, detail=f'Task {short_id!r} not found'
        )
    if isinstance(err, agent_tasks.SessionNotFound):
        return fastapi.HTTPException(
            status_code=404, detail=f'Session {err} not found'
        )
    if isinstance(err, agent_tasks.TaskClosed):
        return _conflict('task_closed', f'Task {short_id} is closed')
    if isinstance(err, agent_tasks.CancelPending):
        return _conflict(
            'task_cancelled', f'Task {short_id} has control cancel'
        )
    if isinstance(err, agent_tasks.SessionClosed):
        return _conflict('session_closed', f'Session {err} is closed')
    if isinstance(err, agent_tasks.EventIdConflict):
        return _conflict(
            'event_id_conflict', 'Another task has an event with this id'
        )
    if isinstance(err, agent_tasks.RequestKeyConflict):
        return _conflict(
            'request_key_conflict',
            f'Request {err} has other artifact_digests; use a new key',
        )
    return _conflict(
        'concurrency_limit',
        'The agent has its maximum number of open sessions',
    )


# --- Endpoints ---------------------------------------------------------

agent_task_harness_router = fastapi.APIRouter(tags=['Agent Task Harness'])


@agent_task_harness_router.post(
    '/{short_id}/sessions',
    status_code=201,
    response_model=SessionOpenResponse,
    responses={
        200: {
            'model': SessionOpenResponse,
            'description': (
                'A session with this session key exists; it is returned.'
            ),
        },
    },
)
async def open_agent_task_session(
    org_id: organizations.MemberOrgId,
    task: HarnessTask,
    data: SessionOpen,
    response: fastapi.Response,
    db: graph.Pool,
    store: agent_tasks.Store,
) -> SessionOpenResponse:
    """Open a harness session on a task.

    A repeat with the same ``session_key`` returns the first session
    with status 200. A new session moves a ``queued`` task to
    ``running``, as it does a ``blocked`` task with no open request.

    Raises:
        403: The caller is not the service account of the task's agent.
        404: No such task.
        409: ``task_closed``, ``task_cancelled`` (control is cancel), or
            ``concurrency_limit`` (``settings.max_concurrent_tasks``
            other tasks of the agent have an open session).

    """
    settings = await _agent_settings(db, task['agent_id'])
    try:
        row, session, created = await store.open_session(
            org_id,
            task['short_id'],
            key=data.session_key,
            harness_instance=data.harness_instance,
            max_concurrent=settings.max_concurrent_tasks,
            actor=_agent_actor(task),
        )
    except _STORE_ERRORS as err:
        raise _translate(err, task['short_id']) from err
    if not created:
        response.status_code = 200
    return SessionOpenResponse(
        session=SessionResponse.model_validate(session),
        task=task_state(row),
    )


@agent_task_harness_router.post(
    '/{short_id}/sessions/{session_id}/heartbeat', response_model=TaskState
)
async def heartbeat_agent_task_session(
    org_id: organizations.MemberOrgId,
    task: HarnessTask,
    session_id: uuid.UUID,
    db: graph.Pool,
    store: agent_tasks.Store,
) -> TaskState:
    """Record a heartbeat; return the control value, seq, and budget.

    When the task has run longer than the agent's
    ``settings.task_timeout_seconds`` since its first session opened,
    the task closes with ``exceeded_ceiling`` (reason ``task_timeout``)
    and the response has the closed status.

    Raises:
        403: The caller is not the service account of the task's agent.
        404: No such task or session.
        409: ``task_closed`` or ``session_closed``.

    """
    settings = await _agent_settings(db, task['agent_id'])
    try:
        row = await store.heartbeat(
            org_id,
            task['short_id'],
            session_id,
            timeout_seconds=settings.task_timeout_seconds,
            system=_SYSTEM,
        )
    except _STORE_ERRORS as err:
        raise _translate(err, task['short_id']) from err
    return task_state(row)


@agent_task_harness_router.post(
    '/{short_id}/sessions/{session_id}/close', response_model=TaskState
)
async def close_agent_task_session(
    org_id: organizations.MemberOrgId,
    task: HarnessTask,
    session_id: uuid.UUID,
    data: SessionClose,
    store: agent_tasks.Store,
) -> TaskState:
    """Close a session. Closing a closed session changes nothing.

    When no session remains open, the status follows the control value:
    ``pause`` makes the task ``paused``, ``run`` puts a ``running`` task
    back to ``queued``, and ``cancel`` closes it.

    Raises:
        403: The caller is not the service account of the task's agent.
        404: No such task or session.
        409: ``task_closed``.

    """
    try:
        row = await store.close_session(
            org_id,
            task['short_id'],
            session_id,
            data.reason,
            _agent_actor(task),
        )
    except _STORE_ERRORS as err:
        raise _translate(err, task['short_id']) from err
    return task_state(row)


@agent_task_harness_router.post(
    '/{short_id}/events',
    status_code=201,
    response_model=AppendEventsResponse,
    responses={
        200: {
            'model': AppendEventsResponse,
            'description': 'All events in the batch are duplicates.',
        },
    },
)
async def append_agent_task_events(
    org_id: organizations.MemberOrgId,
    task: HarnessTask,
    data: EventBatch,
    response: fastapi.Response,
    store: agent_tasks.Store,
) -> AppendEventsResponse:
    """Write a batch of harness events, in order.

    The harness writes only ``turn``, ``tool.called``,
    ``phase.changed``, ``todos.updated``, and ``check.reported``. A
    ``phase.changed`` event also sets the phase of the task.

    Each event has an ``event_id`` that the harness picks. An event that
    the task already has is not written again and takes no seq; its id
    is in ``duplicates``. The status is 200 when nothing was written.

    Raises:
        403: The caller is not the service account of the task's agent.
        404: No such task or session.
        409: ``task_closed``, ``session_closed``, or
            ``event_id_conflict`` (another task has the event id).
        413: A payload is larger than :data:`MAX_PAYLOAD_BYTES`.
        422: An event type that Imbi writes, or a bad envelope.

    """
    for index, event in enumerate(data.events):
        tasks_api.check_payload_size(
            f'The payload of event {index}', event.payload
        )
    try:
        _row, written, duplicates = await store.append_events(
            org_id,
            task['short_id'],
            [
                agent_tasks.NewEvent(
                    event_id=event.event_id,
                    type=event.type,
                    payload=event.payload,
                    actor=agent_tasks.Actor(
                        event.actor_kind,
                        event.actor_id or task['agent_id'],
                        'harness',
                    ),
                    schema_version=event.schema_version,
                    at=event.at,
                )
                for event in data.events
            ],
            data.session_id,
        )
    except _STORE_ERRORS as err:
        raise _translate(err, task['short_id']) from err
    if not written:
        response.status_code = 200
    return AppendEventsResponse.model_validate(
        {'written': written, 'duplicates': duplicates}
    )


@agent_task_harness_router.post(
    '/{short_id}/usage',
    status_code=201,
    response_model=UsageResponse,
    responses={
        200: {
            'model': UsageResponse,
            'description': (
                'A report with this idempotency key exists; it is returned.'
            ),
        },
    },
)
async def report_agent_task_usage(
    org_id: organizations.MemberOrgId,
    task: HarnessTask,
    data: UsageReport,
    response: fastapi.Response,
    db: graph.Pool,
    store: agent_tasks.Store,
) -> UsageResponse:
    """Report the tokens of one model call; return the remaining budget.

    Imbi prices the report from the AI model catalog and records the
    prices it used. A report with no token counts is unmeasured, and an
    unknown model has no cost; both are still recorded. When the cost
    total passes the budget, the task closes with ``exceeded_ceiling``
    (reason ``budget``). A repeat with the same ``idempotency_key``
    returns the first report with status 200.

    Raises:
        403: The caller is not the service account of the task's agent.
        404: No such task or session.
        409: ``task_closed`` or ``session_closed``.

    """
    prices = await _model_prices(db, data.model_id)
    try:
        row, ledger, created = await store.report_usage(
            org_id,
            task['short_id'],
            agent_tasks.Usage(
                idempotency_key=data.idempotency_key,
                model_id=data.model_id,
                tokens_in=data.tokens_in,
                tokens_out=data.tokens_out,
                cache_read_tokens=data.cache_read_tokens,
                cache_write_tokens=data.cache_write_tokens,
                session_id=data.session_id,
            ),
            prices,
            actor=_agent_actor(task),
            system=_SYSTEM,
        )
    except _STORE_ERRORS as err:
        raise _translate(err, task['short_id']) from err
    if not created:
        response.status_code = 200
    return UsageResponse.model_validate({**ledger, 'task': task_state(row)})


@agent_task_harness_router.post(
    '/{short_id}/requests',
    status_code=201,
    response_model=RequestOpenResponse,
    responses={
        200: {
            'model': RequestOpenResponse,
            'description': (
                'A request with this request key exists; it is returned.'
            ),
        },
    },
)
async def open_agent_task_request(
    org_id: organizations.MemberOrgId,
    task: HarnessTask,
    data: RequestCreate,
    response: fastapi.Response,
    store: agent_tasks.Store,
) -> RequestOpenResponse:
    """Ask a person for feedback or an approval; block the task.

    A repeat with the same ``request_key`` returns the first request
    with status 200, resolved or not. Changed ``artifact_digests`` need a
    new key (I3).

    Raises:
        403: The caller is not the service account of the task's agent.
        404: No such task or session.
        409: ``task_closed``, ``session_closed``, or
            ``request_key_conflict`` (the request with the key has other
            ``artifact_digests``).
        413: The request content is larger than
            :data:`MAX_PAYLOAD_BYTES`.
        422: An approval with no ``artifact_digests``, or an
            ``expires_at`` that is not in the future.

    """
    tasks_api.check_payload_size('The request', data.model_dump(mode='json'))
    try:
        row, request, created = await store.open_request(
            org_id,
            task['short_id'],
            agent_tasks.NewRequest(
                kind=data.kind,
                title=data.title,
                why=data.why,
                options=data.options,
                artifacts=data.artifacts,
                artifact_digests=data.artifact_digests,
                expires_at=data.expires_at,
                session_id=data.session_id,
                request_key=data.request_key,
            ),
            _agent_actor(task),
        )
    except _STORE_ERRORS as err:
        raise _translate(err, task['short_id']) from err
    if not created:
        response.status_code = 200
    return RequestOpenResponse(
        request=tasks_api.RequestResponse.model_validate(request),
        task=task_state(row),
    )


@agent_task_harness_router.post(
    '/{short_id}/outcome', response_model=TaskState
)
async def set_agent_task_outcome(
    org_id: organizations.MemberOrgId,
    task: HarnessTask,
    data: OutcomeSet,
    store: agent_tasks.Store,
) -> TaskState:
    """Close the task with a terminal outcome (F5).

    Every open session closes. Every outcome but ``done_acted`` needs a
    slug ``reason``. Per-outcome reason lists (F6) are not checked yet.

    Raises:
        403: The caller is not the service account of the task's agent.
        404: No such task.
        409: ``task_closed``.
        422: Not an F5 outcome, or no reason.

    """
    try:
        row = await store.set_outcome(
            org_id,
            task['short_id'],
            data.outcome,
            data.reason,
            _agent_actor(task),
        )
    except _STORE_ERRORS as err:
        raise _translate(err, task['short_id']) from err
    return task_state(row)
