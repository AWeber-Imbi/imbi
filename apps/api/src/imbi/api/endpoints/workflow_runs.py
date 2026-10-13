"""Workflow run endpoints (ADR 0021).

A manual run is written ``queued`` in ``workflow_runtime``; imbi-workflows
claims and executes it. Cancel only asks: the engine stops the run
before its next step. A test run walks the graph with the sample output
of each step type and writes nothing.

Run detail reads the step records from Postgres until the archive sweep
moves the run's log to ClickHouse, and from ClickHouse after that
(ADR 0021, Run history).

The two email routes are for the engine only. imbi-api holds the email
client, so the engine asks it to send what a run recorded: the input of
a running email step, or the failure notice of a failed run. Both take
an ``Idempotency-Key``, so a repeat after a crash sends nothing twice.

The two agent task routes are for the engine only too. They make,
read, and cancel the agent task of a running ``agent`` step (ADR 0021,
Agent tasks from workflows).

Every route needs the caller to be a member of the organization
(``MEMBER_OF``): see :mod:`imbi.api.auth.organizations`.
"""

import datetime
import typing
import uuid

import fastapi
import pydantic

from imbi.api import agent_tasks as agent_runtime
from imbi.api import email, workflows
from imbi.api.auth import organizations, permissions
from imbi.api.email import client as email_client
from imbi.api.endpoints import agent_tasks
from imbi.common import graph, lifespan
from imbi.common.workflows import graph as wf
from imbi.common.workflows import history, registry, validation, walk
from imbi.common.workflows.registry import agent as agent_step
from imbi.common.workflows.registry import email as email_step

OrgId = organizations.MemberOrgId

RunStatus = typing.Literal[
    'queued', 'running', 'succeeded', 'failed', 'cancelled', 'timed_out'
]


# --- Schemas -----------------------------------------------------------


class RunCreate(pydantic.BaseModel):
    inputs: dict[str, str | int | float | bool] = {}
    trigger: str | None = pydantic.Field(
        default=None,
        description='The id of the trigger node. Defaults to the only '
        'manual trigger.',
    )
    payload: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict,
        description='The trigger payload that the scheduler or the '
        'gateway sends. A person sends inputs.',
    )
    binding: str | None = pydantic.Field(
        default=None,
        description='The trigger binding of the gateway rule that '
        'started a webhook run.',
    )


class StepRun(pydantic.BaseModel):
    node_id: str
    node_key: str
    node_type: str
    title: str
    status: walk.Status
    attempt: int
    input: dict[str, typing.Any] | None
    output: dict[str, typing.Any] | None
    error: str | None
    port: int | None
    started_at: datetime.datetime | None
    finished_at: datetime.datetime | None


class Run(pydantic.BaseModel):
    id: uuid.UUID
    version: int
    trigger_node_id: str
    origin_kind: str
    origin_id: str
    origin: dict[str, typing.Any] = pydantic.Field(
        description='The scheduler task id, the webhook id and delivery '
        'id, or the person.'
    )
    payload: dict[str, typing.Any]
    status: RunStatus
    error: str | None
    cancel_requested: bool
    created_at: datetime.datetime
    started_at: datetime.datetime | None
    closed_at: datetime.datetime | None
    log_archived_at: datetime.datetime | None


class RunDetail(Run):
    steps: list[StepRun]


class AttentionRun(Run):
    workflow_slug: str
    workflow_name: str
    reason: typing.Literal['failed', 'stuck']
    worker_id: str | None
    lease_expires_at: datetime.datetime | None


class TestRunCreate(pydantic.BaseModel):
    version: int | None = pydantic.Field(
        default=None, gt=0, description='Defaults to the latest version.'
    )
    trigger: str | None = pydantic.Field(
        default=None, description='A trigger node id. Defaults to the first.'
    )
    ports: dict[str, int] = pydantic.Field(
        default_factory=dict,
        description='The port that a branching node takes, by node id. '
        'Defaults to its first port.',
    )


class TestRunStep(pydantic.BaseModel):
    node_id: str
    key: str
    type: str
    title: str
    output: dict[str, typing.Any]
    port: int
    port_name: str


class TestRunResult(pydantic.BaseModel):
    steps: list[TestRunStep]
    skipped: list[str]


class EmailResult(pydantic.BaseModel):
    #: The addresses that got the message.
    recipients: list[str]
    #: The addresses that a send failed for, after the client's retries.
    failed: list[str] = []


class StepAgentTask(pydantic.BaseModel):
    #: The short id, ``T-<n>``.
    task_id: str
    status: str
    outcome: str | None
    reason: str | None
    #: The last message of the agent, when the task is closed.
    summary: str | None


# --- Helpers -----------------------------------------------------------

_AGENT_SLUG_QUERY: typing.LiteralString = """
MATCH (a:Agent {{id: {id}}})-[:BELONGS_TO]->(:Organization {{id: {org}}})
RETURN a.slug AS slug
"""

_TEAM_MEMBER_QUERY: typing.LiteralString = """
MATCH (u:User {{email: {email}}})-[:MEMBER_OF]->(t:Team {{id: {team}}})
RETURN u.email AS email
"""

#: The service account of the engine (``auth/internal_services.py``).
ENGINE_SERVICE_ACCOUNT = 'imbi-workflows'

_USER_EMAIL_QUERY: typing.LiteralString = """
MATCH (u:User)-[:MEMBER_OF]->(:Organization {{id: {org}}})
WHERE (u.id = {id} OR u.email = {id}) AND u.is_active
RETURN u.email AS email
"""

_TEAM_EMAILS_QUERY: typing.LiteralString = """
MATCH (u:User)-[:MEMBER_OF]->(t:Team)-[:BELONGS_TO]->
      (:Organization {{id: {org}}})
WHERE t.id = {id} AND u.is_active
RETURN u.email AS email
"""

_INPUT_TYPES: dict[str, tuple[type, ...]] = {
    'string': (str,),
    'number': (int, float),
    'boolean': (bool,),
}


def _not_found(slug: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=404, detail=f'Workflow {slug!r} not found'
    )


async def _workflow(
    store: workflows.WorkflowStore, org_id: str, slug: str
) -> workflows.Row:
    row = await store.get(org_id, slug)
    if row is None:
        raise _not_found(slug)
    return row


async def _version_graph(
    store: workflows.WorkflowStore, org_id: str, slug: str, version: int
) -> tuple[wf.Graph, wf.Settings]:
    row = await store.version(org_id, slug, version)
    if row is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Workflow {slug!r} has no version {version}',
        )
    return (
        wf.Graph.model_validate(row['graph']),
        wf.Settings.model_validate(row['settings']),
    )


def _manual_trigger(wf_graph: wf.Graph, node_id: str | None) -> wf.Node:
    manual = [n for n in wf_graph.nodes if n.type == 'manual']
    if node_id is not None:
        manual = [n for n in manual if n.id == node_id]
    if len(manual) != 1:
        raise fastapi.HTTPException(
            status_code=422,
            detail='Name the manual trigger to start'
            if manual
            else 'The active version has no such manual trigger',
        )
    return manual[0]


async def _check_who(
    db: graph.Graph,
    trigger: wf.Node,
    workflow: workflows.Row,
    auth: permissions.AuthContext,
    action: str = 'start',
) -> None:
    """Apply the ``who`` parameter of the trigger.

    A trigger without ``who`` (schedule, webhook) allows the owner team.
    """
    who = trigger.params.get('who', 'owner_team')
    if auth.is_admin or who == 'anyone':
        return
    if who == 'owner_team' and await db.execute(
        _TEAM_MEMBER_QUERY,
        {'email': auth.principal_name, 'team': workflow['owner_team_id']},
        ['email'],
    ):
        return
    raise fastapi.HTTPException(
        status_code=403,
        detail=f'Only {who.replace("_", " ")} can {action} this workflow',
    )


def _check_inputs(
    trigger: wf.Node, inputs: dict[str, str | int | float | bool]
) -> None:
    """Every declared input is required and typed. Others are refused."""
    declared = {
        str(i['name']): str(i.get('type', 'string'))
        for i in trigger.params.get('inputs', [])
    }
    errors = [f'Unknown input {n!r}' for n in sorted(inputs.keys() - declared)]
    for name, kind in declared.items():
        if name not in inputs:
            errors.append(f'Input {name!r} is required')
            continue
        value = inputs[name]
        if not isinstance(value, _INPUT_TYPES[kind]) or (
            kind == 'number' and isinstance(value, bool)
        ):
            errors.append(f'Input {name!r} must be a {kind}')
    if errors:
        raise fastapi.HTTPException(status_code=422, detail=errors)


async def _service_trigger(
    store: workflows.WorkflowStore,
    workflow: workflows.Row,
    wf_graph: wf.Graph,
    data: RunCreate,
    origin: agent_tasks.TaskOrigin,
) -> wf.Node:
    """Return the schedule or webhook trigger that the service names.

    A schedule run must come from the scheduler task that the trigger's
    enabled and synced binding records, so a scheduler task that a
    person made cannot start the workflow. A webhook run must name, from
    its gateway rule, the enabled and synced binding of the trigger on
    that webhook, so a ``start_workflow`` rule that a person made cannot
    start it.

    Raises:
        403: The scheduler task or the rule is not the binding's.
        409: The active version has no such trigger: the binding is out
            of date (ADR 0021, Triggers).

    """
    node = next(
        (
            n
            for n in wf_graph.nodes
            if n.id == data.trigger
            and n.type == origin.kind
            and (
                origin.kind != 'webhook'
                or n.params.get('webhook_id') == origin.id
            )
        ),
        None,
    )
    if node is None:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'The active version has no such {origin.kind} trigger',
        )
    allowed = any(
        b['node_id'] == node.id
        and b['type'] == origin.kind
        and b['enabled']
        and b['sync_state'] == 'synced'
        and b['target_id'] == origin.id
        and (origin.kind == 'schedule' or str(b['id']) == data.binding)
        for b in await store.bindings(workflow['id'])
    )
    if not allowed:
        raise fastapi.HTTPException(
            status_code=403,
            detail={
                'error': 'origin_forbidden',
                'message': f'The {origin.kind} {origin.id!r} is not the '
                'binding of this trigger',
            },
        )
    return node


async def _run(
    runs: workflows.RunStore, workflow: workflows.Row, run_id: uuid.UUID
) -> workflows.Row:
    row = await runs.get(workflow['id'], run_id)
    if row is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Run {run_id} not found'
        )
    return row


async def _recipients(
    db: graph.Graph, org_id: str, to: list[email_step.Recipient]
) -> list[str]:
    """Return the emails of org users and team members, in order.

    Only Imbi users and teams of the organization: never an address
    that a workflow names itself (ADR 0021).
    """
    found: list[str] = []
    for recipient in to:
        query = (
            _USER_EMAIL_QUERY
            if recipient.kind == 'user'
            else _TEAM_EMAILS_QUERY
        )
        for record in await db.execute(
            query, {'org': org_id, 'id': recipient.id}, ['email']
        ):
            address = str(graph.parse_agtype(record['email']))
            if address not in found:
                found.append(address)
    return found


def _email_client(
    context: lifespan.InjectLifespan,
) -> email_client.EmailClient:
    # Imported here: imbi.api.email imports the lifespans, which import
    # the endpoints, so a module-level import is circular.
    from imbi.api import lifespans

    client, _ = context.get_state(lifespans.email_hook)
    return client


async def _send(
    client: email_client.EmailClient, to: list[str], subject: str, body: str
) -> dict[str, typing.Any]:
    """Send to every address, and report which sends failed.

    A failure does not stop the others, and the result is stored with
    the idempotency key: a repeat returns it and sends nothing again.
    """
    sent: list[str] = []
    failed: list[str] = []
    for address in to:
        audit = await email.send_workflow_email(
            client, to_email=address, subject=subject, body=body
        )
        (failed if audit.status == 'failed' else sent).append(address)
    return {'recipients': sent, 'failed': failed}


async def _require_engine(
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> permissions.AuthContext:
    if (
        auth.service_account is None
        or auth.service_account.slug != ENGINE_SERVICE_ACCOUNT
    ):
        raise fastapi.HTTPException(
            status_code=403, detail='Only imbi-workflows can call this'
        )
    return auth


async def _agent_step(
    runs: workflows.RunStore,
    workflow: workflows.Row,
    run_id: uuid.UUID,
    node_id: str,
) -> tuple[workflows.Row, workflows.Row, agent_tasks.TaskOrigin, str]:
    """Return the run, its agent step, and the origin and key of its task.

    The task has the root origin of the run, and its origin record
    names the run and the node (ADR 0021). The key is
    ``<run_id>:<node_key>``, as for every side effect of a step.

    Raises:
        404: No such run or step.
        409: The step is not an agent step.

    """
    run = await _run(runs, workflow, run_id)
    step = next(
        (s for s in await runs.steps(run_id) if s['node_id'] == node_id),
        None,
    )
    if step is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Run {run_id} has no step {node_id!r}'
        )
    if step['node_type'] != 'agent':
        raise fastapi.HTTPException(
            status_code=409, detail=f'Step {node_id!r} is not an agent step'
        )
    origin = agent_tasks.TaskOrigin(
        run['origin_kind'],
        run['origin_id'],
        {
            **run['origin'],
            'kind': run['origin_kind'],
            'workflow_run_id': str(run_id),
            'node_key': step['node_key'],
        },
    )
    return run, step, origin, f'{run_id}:{step["node_key"]}'


async def _pinned_agent_ids(
    store: workflows.WorkflowStore,
    org_id: str,
    slug: str,
    run: workflows.Row,
    node_id: str,
) -> tuple[str, str | None]:
    """Return the agent id and project id of the node in the run's version.

    They come from the pinned version, not from the rendered step
    input, so run input cannot choose the agent or the project.

    Raises:
        422: ``agent_params_not_literal``: an id is a template.

    """
    wf_graph, _ = await _version_graph(store, org_id, slug, run['version'])
    node = next((n for n in wf_graph.nodes if n.id == node_id), None)
    params = node.params if node is not None else {}
    agent_id, project_id = params.get('agent_id'), params.get('project_id')
    if not isinstance(agent_id, str) or any(
        isinstance(value, str) and ('{{' in value or '{%' in value)
        for value in (agent_id, project_id)
    ):
        raise fastapi.HTTPException(
            status_code=422, detail={'error': 'agent_params_not_literal'}
        )
    return agent_id, project_id


def _made_by_step(
    task: dict[str, typing.Any], run_id: uuid.UUID, node_key: str
) -> bool:
    """Return whether the agent step of ``run_id`` made ``task``.

    A person can make a task with the same origin and key first. Only
    this route writes ``workflow_run_id`` in an origin record.
    """
    origin: dict[str, typing.Any] = task['origin'] or {}
    return (
        origin.get('workflow_run_id') == str(run_id)
        and origin.get('node_key') == node_key
    )


def _task_key_conflict() -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=409, detail={'error': 'task_key_conflict'}
    )


def _without_task_content(
    step: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Remove the agent task content from the output of an agent step."""
    if step['node_type'] != 'agent' or not step['output']:
        return step
    output = {
        k: v
        for k, v in step['output'].items()
        if k not in ('reason', 'summary')
    }
    return {**step, 'output': output}


def _step_agent_task(
    task: dict[str, typing.Any], summary: str | None = None
) -> dict[str, typing.Any]:
    return {
        'task_id': task['short_id'],
        'status': task['status'],
        'outcome': task['outcome'],
        'reason': task['outcome_reason'],
        'summary': summary,
    }


# --- Endpoints ---------------------------------------------------------

workflow_runs_router = fastapi.APIRouter(
    tags=['Workflows'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)

ReadAuth = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('workflow:read')),
]
RunAuth = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('workflow:run')),
]
EngineAuth = typing.Annotated[
    permissions.AuthContext, fastapi.Depends(_require_engine)
]
EmailClient = typing.Annotated[
    email_client.EmailClient, fastapi.Depends(_email_client)
]


def _header(name: str) -> typing.Any:
    """Return an optional origin header of at most 200 characters."""
    return fastapi.Header(alias=name, min_length=1, max_length=200)


IdempotencyKey = typing.Annotated[
    str, fastapi.Header(alias='Idempotency-Key', max_length=256)
]


@workflow_runs_router.post('/{slug}/runs', status_code=202, response_model=Run)
async def start_run(
    org_id: OrgId,
    slug: str,
    data: RunCreate,
    db: graph.Pool,
    store: workflows.Store,
    runs: workflows.Runs,
    auth: RunAuth,
    idempotency_key: typing.Annotated[
        str | None, fastapi.Header(alias='Idempotency-Key', max_length=256)
    ] = None,
    scheduled_task: typing.Annotated[
        str | None, _header('X-Imbi-Scheduled-Task')
    ] = None,
    webhook: typing.Annotated[str | None, _header('X-Imbi-Webhook')] = None,
    delivery: typing.Annotated[str | None, _header('X-Imbi-Delivery')] = None,
) -> workflows.Row:
    """Start a run of the active version.

    A person starts a manual trigger. The scheduler starts a schedule
    trigger, and the gateway a webhook trigger, with the origin in
    headers (see :func:`agent_tasks.task_origin`). The idempotency key
    is the ``Idempotency-Key`` header (the scheduler sends its run id),
    or the delivery id for a webhook. A repeat by the same origin
    returns the first run.

    Raises:
        403: The trigger's ``who`` does not include the caller, a person
            names an origin, the caller is a service account other than
            the scheduler or the gateway, or the scheduler task is not
            the one that the trigger's binding records.
        404: No such workflow.
        409: The workflow is not active, or its active version has no
            such schedule or webhook trigger.
        422: No such manual trigger, the inputs do not match it,
            ``concurrency_key_missing``, or a schedule run without an
            ``Idempotency-Key``.

    """
    origin = agent_tasks.task_origin(auth, scheduled_task, webhook, delivery)
    workflow = await _workflow(store, org_id, slug)
    if workflow['status'] != 'active' or workflow['active_version'] is None:
        raise fastapi.HTTPException(
            status_code=409, detail=f'Workflow {slug!r} is not active'
        )
    wf_graph, settings = await _version_graph(
        store, org_id, slug, workflow['active_version']
    )
    if origin.kind == agent_tasks.HUMAN_ORIGIN:
        trigger = _manual_trigger(wf_graph, data.trigger)
        await _check_who(db, trigger, workflow, auth)
        _check_inputs(trigger, data.inputs)
        payload: dict[str, typing.Any] = dict(data.inputs)
        origin_id = auth.principal_name
    else:
        trigger = await _service_trigger(
            store, workflow, wf_graph, data, origin
        )
        payload, origin_id = data.payload, origin.id
        idempotency_key = delivery or idempotency_key
        if not idempotency_key:
            # The scheduler sends its run id, the same on every retry of
            # a firing; without it a retry would start a second run.
            raise fastapi.HTTPException(
                status_code=422, detail='Idempotency-Key is required'
            )
    try:
        key = validation.concurrency_key(
            settings, str(workflow['id']), payload
        )
    except ValueError as e:
        # Validation makes a one_per_key workflow declare its key input,
        # and every input is required, but a string input can be empty.
        # A webhook payload can lack the key: it is known only now.
        raise fastapi.HTTPException(
            status_code=422,
            detail=['The input that the concurrency key uses is empty']
            if origin.kind == agent_tasks.HUMAN_ORIGIN
            else {'error': str(e)},
        ) from e
    try:
        row, _created = await runs.create(
            workflows.NewRun(
                organization_id=org_id,
                workflow_id=workflow['id'],
                version=workflow['active_version'],
                trigger_node_id=trigger.id,
                origin_kind=origin.kind,
                origin_id=origin_id,
                origin=origin.record,
                idempotency_key=idempotency_key,
                payload=payload,
                concurrency_key=key,
                activated_by=workflow['activated_by'],
            )
        )
    except workflows.NotActive as e:
        raise fastapi.HTTPException(
            status_code=409, detail=f'Workflow {slug!r} is not active'
        ) from e
    return row


@workflow_runs_router.get('/{slug}/runs', response_model=list[Run])
async def list_runs(
    org_id: OrgId,
    slug: str,
    store: workflows.Store,
    runs: workflows.Runs,
    _: ReadAuth,
    limit: typing.Annotated[int, fastapi.Query(ge=1, le=200)] = 50,
) -> list[workflows.Row]:
    """Return the runs of a workflow, newest first."""
    workflow = await _workflow(store, org_id, slug)
    return await runs.list_runs(workflow['id'], limit)


@workflow_runs_router.get('/{slug}/runs/{run_id}', response_model=RunDetail)
async def get_run(
    org_id: OrgId,
    slug: str,
    run_id: uuid.UUID,
    store: workflows.Store,
    runs: workflows.Runs,
    auth: ReadAuth,
) -> dict[str, typing.Any]:
    """Return a run with its step records.

    The ``reason`` and ``summary`` of an agent step's output come from
    the agent task. Only a caller who can read agent tasks
    (``agent_task:read``) gets them.

    Raises:
        404: No such workflow or run.
        503: The run's log is archived and ClickHouse is not available.

    """
    workflow = await _workflow(store, org_id, slug)
    row = await _run(runs, workflow, run_id)
    if row['log_archived_at'] is None:
        steps = await runs.steps(run_id)
    else:
        try:
            steps = await history.archived_steps(row)
        except Exception as e:
            raise fastapi.HTTPException(
                status_code=503, detail='The run history is not available'
            ) from e
    if not (auth.is_admin or 'agent_task:read' in auth.permissions):
        steps = [_without_task_content(s) for s in steps]
    return {**row, 'steps': steps}


@workflow_runs_router.post(
    '/{slug}/runs/{run_id}/cancel', status_code=202, response_model=Run
)
async def cancel_run(
    org_id: OrgId,
    slug: str,
    run_id: uuid.UUID,
    db: graph.Pool,
    store: workflows.Store,
    runs: workflows.Runs,
    auth: RunAuth,
) -> workflows.Row:
    """Ask the engine to stop a run before its next step.

    The caller needs the same ``who`` as the trigger that started the
    run, in the run's pinned version.

    Raises:
        403: The trigger's ``who`` does not include the caller.
        404: No such workflow or run.
        409: The run is closed.

    """
    workflow = await _workflow(store, org_id, slug)
    run = await _run(runs, workflow, run_id)
    wf_graph, _ = await _version_graph(store, org_id, slug, run['version'])
    trigger = next(
        (n for n in wf_graph.nodes if n.id == run['trigger_node_id']), None
    )
    if trigger is not None:
        await _check_who(db, trigger, workflow, auth, 'cancel')
    elif not auth.is_admin:
        raise fastapi.HTTPException(
            status_code=403, detail='Only admins can cancel this run'
        )
    if not await runs.cancel(run_id):
        raise fastapi.HTTPException(
            status_code=409, detail=f'Run {run_id} is closed'
        )
    return await _run(runs, workflow, run_id)


workflow_attention_router = fastapi.APIRouter(
    tags=['Workflows'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)


@workflow_attention_router.get('/attention', response_model=list[AttentionRun])
async def list_attention_runs(
    org_id: OrgId,
    runs: workflows.Runs,
    _: ReadAuth,
) -> list[workflows.Row]:
    """Return the failed runs of the last 7 days and the stuck runs.

    A stuck run is open and no engine works on it: see
    :meth:`imbi.api.workflows.RunStore.attention`.
    """
    return await runs.attention(org_id)


@workflow_runs_router.post(
    '/{slug}/runs/{run_id}/steps/{node_id}/email', response_model=EmailResult
)
async def send_step_email(
    org_id: OrgId,
    slug: str,
    run_id: uuid.UUID,
    node_id: str,
    db: graph.Pool,
    store: workflows.Store,
    runs: workflows.Runs,
    client: EmailClient,
    auth: EngineAuth,
    idempotency_key: IdempotencyKey,
) -> dict[str, typing.Any]:
    """Send the message of a running email step. Engine only.

    Raises:
        404: No such workflow, run, or step.
        409: The step is not a running email step, or
            ``outcome_unknown``: a call with the key did not finish.
        422: No recipient is an active user of the organization.

    A failed send is not an error here: the response lists it in
    ``failed``, and the engine fails the step.

    """
    workflow = await _workflow(store, org_id, slug)
    await _run(runs, workflow, run_id)
    step = next(
        (s for s in await runs.steps(run_id) if s['node_id'] == node_id),
        None,
    )
    if step is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Run {run_id} has no step {node_id!r}'
        )
    if step['node_type'] != 'email' or step['status'] != 'running':
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Step {node_id!r} is not a running email step',
        )
    params = email_step.Params.model_validate(step['input'])

    async def call() -> dict[str, typing.Any]:
        to = await _recipients(db, org_id, params.to)
        if not to:
            raise fastapi.HTTPException(
                status_code=422, detail={'error': 'no_recipients'}
            )
        return await _send(client, to, params.subject, params.body)

    return await runs.once(
        auth.principal_name, 'step-email', idempotency_key, call
    )


@workflow_runs_router.post(
    '/{slug}/runs/{run_id}/failure-notice', response_model=EmailResult
)
async def send_failure_notice(
    org_id: OrgId,
    slug: str,
    run_id: uuid.UUID,
    db: graph.Pool,
    store: workflows.Store,
    runs: workflows.Runs,
    client: EmailClient,
    auth: EngineAuth,
    idempotency_key: IdempotencyKey,
) -> dict[str, typing.Any]:
    """Tell the owner team that a run failed. Engine only.

    The ``notify_owner_team`` failure policy (ADR 0021).

    Raises:
        404: No such workflow or run.
        409: The run did not fail, or its policy is not
            ``notify_owner_team``.

    """
    workflow = await _workflow(store, org_id, slug)
    run = await _run(runs, workflow, run_id)
    _, settings = await _version_graph(store, org_id, slug, run['version'])
    if run['status'] != 'failed' or settings.on_failure != 'notify_owner_team':
        raise fastapi.HTTPException(
            status_code=409, detail='No failure notice for this run'
        )

    async def call() -> dict[str, typing.Any]:
        to = await _recipients(
            db,
            org_id,
            [email_step.Recipient(kind='team', id=workflow['owner_team_id'])],
        )
        return await _send(
            client,
            to,
            f'Workflow {workflow["name"]} failed',
            f'Run {run_id} of workflow {workflow["name"]} failed: '
            f'{run["error"]}.',
        )

    return await runs.once(
        auth.principal_name, 'failure-notice', idempotency_key, call
    )


@workflow_runs_router.post(
    '/{slug}/runs/{run_id}/steps/{node_id}/agent-task',
    response_model=StepAgentTask,
)
async def step_agent_task(
    org_slug: str,
    org_id: OrgId,
    slug: str,
    run_id: uuid.UUID,
    node_id: str,
    db: graph.Pool,
    store: workflows.Store,
    runs: workflows.Runs,
    tasks: agent_runtime.Store,
    auth: EngineAuth,
) -> dict[str, typing.Any]:
    """Make the task of a running agent step, or return it. Engine only.

    A repeat, after a crash or for a retry of the step, returns the
    first task: the key is the same. The person who activated the
    workflow owns the task, and must still be able to make agent tasks
    in the org. The engine polls this route until the task is closed.

    The agent and the project come from the pinned version (see
    :func:`_pinned_agent_ids`). A task with the key that this step did
    not make, or that has another agent, is refused.

    Raises:
        403: ``owner_forbidden``: the activator cannot make agent tasks.
        404: No such workflow, run, or step.
        409: The step is not a running agent step, the agent is
            disabled, or ``task_key_conflict``.
        422: ``agent_not_found``, ``agent_params_not_literal``, or the
            project or the budget is not valid (see
            :func:`agent_tasks.make_task`).

    """
    workflow = await _workflow(store, org_id, slug)
    run, step, origin, key = await _agent_step(runs, workflow, run_id, node_id)
    agent_id, project_id = await _pinned_agent_ids(
        store, org_id, slug, run, node_id
    )
    task = await tasks.find_by_idempotency_key(
        org_id, origin.kind, origin.id, key
    )
    if task is None:
        if step['status'] != 'running':
            raise fastapi.HTTPException(
                status_code=409,
                detail=f'Step {node_id!r} is not a running agent step',
            )
        if not await agent_tasks.may_create(db, org_slug, run['activated_by']):
            raise fastapi.HTTPException(
                status_code=403, detail={'error': 'owner_forbidden'}
            )
        records = await db.execute(
            _AGENT_SLUG_QUERY, {'id': agent_id, 'org': org_id}, ['slug']
        )
        if not records:
            raise fastapi.HTTPException(
                status_code=422, detail={'error': 'agent_not_found'}
            )
        try:
            params = agent_step.Params.model_validate(step['input'] or {})
            data = agent_tasks.AgentTaskCreate(
                agent_slug=str(graph.parse_agtype(records[0]['slug'])),
                title=f'{workflow["name"]}: {step["title"]}',
                description=params.instruction,
                project_id=project_id,
                budget=params.budget,
            )
        except pydantic.ValidationError as e:
            raise fastapi.HTTPException(
                status_code=422, detail={'error': 'invalid_params'}
            ) from e
        task, _ = await agent_tasks.make_task(
            db,
            tasks,
            org_slug,
            org_id,
            data,
            origin,
            key,
            run['activated_by'],
            agent_runtime.Actor('system', auth.principal_name, 'api'),
        )
    if (
        not _made_by_step(task, run_id, step['node_key'])
        or task['agent_id'] != agent_id
    ):
        raise _task_key_conflict()
    summary = (
        await tasks.last_agent_turn(task['id'])
        if task['status'] == 'closed'
        else None
    )
    return _step_agent_task(task, summary)


@workflow_runs_router.post(
    '/{slug}/runs/{run_id}/steps/{node_id}/agent-task/cancel',
    status_code=204,
)
async def cancel_step_agent_task(
    org_id: OrgId,
    slug: str,
    run_id: uuid.UUID,
    node_id: str,
    store: workflows.Store,
    runs: workflows.Runs,
    tasks: agent_runtime.Store,
    auth: EngineAuth,
) -> None:
    """Cancel the task of an agent step, when it is open. Engine only.

    The engine calls this when it closes a run whose agent step is
    running. A step with no task, or with a closed task, is not an
    error.

    Raises:
        404: No such workflow, run, or step.
        409: The step is not an agent step.

    """
    workflow = await _workflow(store, org_id, slug)
    _, step, origin, key = await _agent_step(runs, workflow, run_id, node_id)
    task = await tasks.find_by_idempotency_key(
        org_id, origin.kind, origin.id, key
    )
    # A task that the step did not make is never cancelled here.
    if (
        task is None
        or task['status'] == 'closed'
        or not _made_by_step(task, run_id, step['node_key'])
    ):
        return
    try:
        await tasks.set_control(
            org_id,
            task['short_id'],
            'cancel',
            agent_runtime.Actor('system', auth.principal_name, 'api'),
        )
    except (agent_runtime.TaskClosed, agent_runtime.CancelPending):
        pass


@workflow_runs_router.post('/{slug}/test-runs', response_model=TestRunResult)
async def test_run(
    org_id: OrgId,
    slug: str,
    store: workflows.Store,
    _: RunAuth,
    data: TestRunCreate | None = None,
) -> TestRunResult:
    """Walk a version with the sample output of each step.

    Nothing is called, sent, or written.

    Raises:
        404: No such workflow, version, or trigger.
        422: The version has errors, or a port is out of range.

    """
    data = data or TestRunCreate()
    workflow = await _workflow(store, org_id, slug)
    wf_graph, settings = await _version_graph(
        store, org_id, slug, data.version or workflow['latest_version']
    )
    errors = [
        i
        for i in validation.validate(wf_graph, settings).issues
        if i.severity == 'error'
    ]
    if errors:
        raise fastapi.HTTPException(
            status_code=422,
            detail={
                'error': 'validation_failed',
                'issues': [i.model_dump() for i in errors],
            },
        )
    return simulate(wf_graph, data.trigger, data.ports)


def simulate(
    wf_graph: wf.Graph, trigger_id: str | None, picked: dict[str, int]
) -> TestRunResult:
    """Walk ``wf_graph`` from a trigger with sample outputs."""
    nodes = {n.id: n for n in wf_graph.nodes}
    triggers = [
        n.id for n in wf_graph.nodes if registry.STEP_TYPES[n.type].trigger
    ]
    if not triggers:
        raise fastapi.HTTPException(
            status_code=422, detail='The workflow has no trigger'
        )
    start = trigger_id or triggers[0]
    if start not in triggers:
        raise fastapi.HTTPException(
            status_code=404, detail=f'No trigger {start!r}'
        )
    status: dict[str, str] = dict.fromkeys(nodes, 'pending')
    status.update(dict.fromkeys(triggers, 'skipped'))
    ports: dict[str, int | None] = {}
    steps: list[TestRunStep] = []
    skipped: list[str] = []
    node_id: str | None = start
    while node_id is not None:
        node = nodes[node_id]
        step = registry.STEP_TYPES[node.type]
        names = step.ports_for(node.params) or ['']
        port = picked.get(node_id, 0)
        if not 0 <= port < len(names):
            raise fastapi.HTTPException(
                status_code=422,
                detail=f'{node.title} has no output {port}',
            )
        status[node_id], ports[node_id] = 'succeeded', port
        steps.append(
            TestRunStep(
                node_id=node_id,
                key=node.key,
                type=node.type,
                title=node.title,
                output=step.sample_output,
                port=port,
                port_name=names[port],
            )
        )
        ready, newly_skipped = walk.advance(wf_graph, status, ports)
        skipped += newly_skipped
        node_id = ready[0] if ready else None
    return TestRunResult(
        steps=steps,
        skipped=skipped + [t for t in triggers if t != start],
    )
