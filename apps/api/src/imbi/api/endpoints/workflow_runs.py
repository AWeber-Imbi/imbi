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
The Slack route is the same for a running ``slack`` step: imbi-api
holds the bot token.

The two agent task routes are for the engine only too. They make,
read, and cancel the agent task of a running ``agent`` step (ADR 0021,
Agent tasks from workflows).

The side-effect routes let an operator (``workflow:recover``) find the
calls that started and did not finish, resolve each one, and retry its
step (ADR 0021, unknown-outcome reconciliation).

Every route needs the caller to be a member of the organization
(``MEMBER_OF``): see :mod:`imbi.api.auth.organizations`.
"""

import asyncio
import datetime
import logging
import re
import typing
import uuid

import aiohttp
import fastapi
import pydantic
from slack_sdk import errors as slack_errors
from slack_sdk.web import async_client as slack_client

from imbi.api import email, workflows
from imbi.api import settings as api_settings
from imbi.api import tickets as ticket_store
from imbi.api.auth import organizations, permissions
from imbi.api.email import client as email_client
from imbi.api.endpoints import project_deployments, tickets
from imbi.api.plugins.resolution import ResolvedCapability
from imbi.api.tickets import store as ticket_rows
from imbi.api.workflows import tickets as workflow_tickets
from imbi.common import graph, lifespan
from imbi.common.auth import permissions as common_permissions
from imbi.common.plugins.base import DeploymentRun
from imbi.common.workflows import graph as wf
from imbi.common.workflows import history, registry, validation, walk
from imbi.common.workflows.registry import agent as agent_step
from imbi.common.workflows.registry import assign_ticket as assign_step
from imbi.common.workflows.registry import email as email_step
from imbi.common.workflows.registry import slack as slack_step
from imbi.common.workflows.registry import ticket_state_changed

LOGGER = logging.getLogger(__name__)

OrgId = organizations.MemberOrgId

RunStatus = typing.Literal[
    'queued',
    'running',
    'succeeded',
    'failed',
    'cancelled',
    'timed_out',
    'skipped',
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
    project_id: str | None = pydantic.Field(
        default=None,
        description='The project that the gateway matched to the webhook '
        'delivery. Only a webhook run uses it.',
    )
    actor: str | None = pydantic.Field(
        default=None,
        description='The email of the Imbi user who caused the webhook '
        'delivery, as the gateway resolved it. Only a webhook run uses it.',
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
    dedupe_key: str | None = pydantic.Field(
        description="The workflow's dedupe key filled with the payload.",
    )
    duplicate_of: uuid.UUID | None = pydantic.Field(
        description='For a ``skipped`` run: the earlier run with the same '
        'dedupe key.',
    )


class RunDetail(Run):
    steps: list[StepRun]


class AttentionRun(Run):
    workflow_slug: str
    workflow_name: str
    reason: typing.Literal['failed', 'stuck']
    worker_id: str | None
    lease_expires_at: datetime.datetime | None


class RunFailure(pydantic.BaseModel):
    """The failed step of a run that finished last.

    ``task_id``, ``outcome``, ``reason``, and ``summary`` come from the
    agent task of an ``agent`` step. ``reason`` and ``summary`` are
    ``None`` for a caller who cannot read agent tasks, and ``error``
    has only its code.
    """

    node_key: str
    title: str
    node_type: str
    attempt: int
    error: str | None
    task_id: str | None = None
    outcome: str | None = None
    reason: str | None = None
    summary: str | None = None


class OrgRun(Run):
    workflow_slug: str
    workflow_name: str
    stuck: bool
    failure: RunFailure | None = pydantic.Field(
        description='``None`` when the run did not fail, when no step '
        'failed (a timeout), or when the archived step records are not '
        'available.'
    )


class StaleSideEffect(pydantic.BaseModel):
    """A side effect of a run that started and did not finish."""

    key: str
    action: str
    created_at: datetime.datetime
    run_id: uuid.UUID
    run_status: RunStatus
    run_error: str | None
    workflow_slug: str
    workflow_name: str
    #: The step that made the call. ``None`` for a failure notice.
    node_key: str | None
    #: The step's parameters (the project, environment, and version of a
    #: deployment). ``None`` when the step rows are archived.
    step_input: dict[str, typing.Any] | None
    #: The step can run again after the key is resolved.
    retryable: bool


class SideEffectResolve(pydantic.BaseModel):
    key: str
    resolution: typing.Literal['clear', 'mark_done'] = pydantic.Field(
        description='``clear`` deletes the key, so a repeat of the call '
        'acts again. ``mark_done`` records that the call acted, so a '
        'repeat does not act. A deployment marked done with no '
        '``deployment_run_id`` cannot be retried: Imbi does not know its '
        'deployment run.'
    )
    retry: bool = pydantic.Field(
        default=False,
        description='Open the run again and run the step again.',
    )
    deployment_run_id: str | None = pydantic.Field(
        default=None,
        description='With ``mark_done`` on a deployment: the run, from '
        '``GET side-effects/deployments``, that the operator confirmed. '
        'Imbi stores it as the result of the call, so a retried step '
        'follows that deployment.',
    )


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


class SlackResult(pydantic.BaseModel):
    channel: str
    #: The timestamp of the message. ``None`` when Slack refused it, or
    #: an operator marked an unknown send done.
    ts: str | None = None
    permalink: str | None = None
    #: The Slack error code when Slack refused the message, such as
    #: ``not_in_channel``. Nothing was posted.
    error: str | None = None


class StepAgentTask(agent_step.TicketAttributes):
    """The attributes of :class:`agent_step.TicketAttributes` are set
    when the task is closed."""

    #: The short id, ``T-<n>``.
    task_id: str
    status: str
    outcome: str | None
    reason: str | None
    #: The last message of the agent, when the task is closed.
    summary: str | None
    #: The structured output of the agent, when the task is closed.
    result: dict[str, typing.Any] | None = None


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
ENGINE_SERVICE_ACCOUNT = workflows.runs.ENGINE_PRINCIPAL

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
    'text': (str,),
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
    origin: tickets.TaskOrigin,
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


def _slack_token() -> str:
    return api_settings.get_slack_settings().bot_token.get_secret_value()


#: Errors of a call to Slack that may come after Slack posted.
_SLACK_TRANSPORT_ERRORS = (
    slack_errors.SlackClientError,
    aiohttp.ClientError,
    TimeoutError,
)

#: Slack errors that can come after part of the call succeeded, so
#: the message may be posted: treated as a transport error.
_SLACK_AMBIGUOUS = frozenset(
    {'fatal_error', 'internal_error', 'request_timeout', 'service_unavailable'}
)

# slack_sdk's AsyncWebClient is only loosely typed (``**kwargs`` and
# untyped responses), so it is Any here, as in imbi-slackbot.
SlackClient = typing.Any


#: Seconds that each call to Slack may take. The post and the
#: permalink together stay well under the engine's 60-second timeout.
_SLACK_TIMEOUT = 20
_SLACK_PERMALINK_TIMEOUT = 5.0
_HTTP_SERVER_ERROR = 500
_HTTP_TOO_MANY_REQUESTS = 429


def _slack_refusal(error: slack_errors.SlackApiError) -> str | None:
    """Return the code of a refusal that posted nothing, or ``None``.

    A ``429`` is ``ratelimited`` with or without a code. ``None`` when
    Slack may have posted: a 5xx (slack_sdk gives a 5xx
    with an HTML body no error code), a missing code, or a code in
    :data:`_SLACK_AMBIGUOUS`. On a body that is not JSON, slack_sdk
    passes the raw HTTP response, which has no ``get``.
    """
    response: SlackClient = error.response
    status = getattr(response, 'status_code', None)
    if status == _HTTP_TOO_MANY_REQUESTS:
        return 'ratelimited'
    if isinstance(status, int) and status >= _HTTP_SERVER_ERROR:
        return None
    get = getattr(response, 'get', None)
    code: typing.Any = get('error') if callable(get) else None
    if not code or code in _SLACK_AMBIGUOUS:
        return None
    return str(code)


async def _post_slack(token: str, channel: str, text: str) -> SlackResult:
    """Post ``text`` to ``channel``, then ask for its permalink.

    The client does not retry: a retry after a lost response could post
    the message two times. A refusal from Slack posted nothing, so it is
    a result with ``error``, except ``ratelimited``: a ``429`` releases
    the key, and the engine tries again. A transport error, or a Slack
    answer that may come after it posted (:func:`_slack_refusal`), is a
    ``502`` and the idempotency key stays.
    """
    client: SlackClient = slack_client.AsyncWebClient(
        token=token, timeout=_SLACK_TIMEOUT, retry_handlers=[]
    )
    try:
        posted = await client.chat_postMessage(
            channel=channel, text=text, unfurl_links=False
        )
    except slack_errors.SlackApiError as e:
        refusal = _slack_refusal(e)
        if refusal == 'ratelimited':
            raise fastapi.HTTPException(
                status_code=429, detail={'error': 'slack_ratelimited'}
            ) from None
        if refusal is not None:
            return SlackResult(channel=channel, error=refusal)
        raise fastapi.HTTPException(
            status_code=502, detail={'error': 'slack_unreachable'}
        ) from None
    except _SLACK_TRANSPORT_ERRORS:
        raise fastapi.HTTPException(
            status_code=502, detail={'error': 'slack_unreachable'}
        ) from None
    ts = str(posted['ts'])
    channel = str(posted.get('channel') or channel)
    return SlackResult(
        channel=channel,
        ts=ts,
        permalink=await _slack_permalink(client, channel, ts),
    )


async def _slack_permalink(
    client: SlackClient, channel: str, ts: str
) -> str | None:
    """Return the permalink of a message, or ``None``: the message is
    posted, so a failure here does not fail the step."""
    try:
        found = await asyncio.wait_for(
            client.chat_getPermalink(channel=channel, message_ts=ts),
            _SLACK_PERMALINK_TIMEOUT,
        )
    except _SLACK_TRANSPORT_ERRORS:
        return None
    permalink: typing.Any = found.get('permalink')
    return str(permalink) if permalink else None


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
) -> tuple[workflows.Row, workflows.Row, tickets.TaskOrigin, str]:
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
    origin = tickets.TaskOrigin(
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


async def _step_owner(
    db: graph.Graph, org_slug: str, run: workflows.Row
) -> str | None:
    """Return the owner of the task of an agent step, or ``None``.

    The person who activated the workflow is the authority for its
    runs: ``None`` when they can no longer make agent tasks in the org,
    so that removing their permission stops the workflow. The person of
    the run's origin (``origin['user']``) owns the tasks when they can
    also make agent tasks: the person who started a manual run, or the
    person who caused a webhook delivery, as the gateway resolved them.
    Otherwise the activator owns them.
    """
    activator: str = run['activated_by']
    if not await tickets.may_create(db, org_slug, activator):
        return None
    origin: dict[str, typing.Any] = run['origin'] or {}
    person: str | None = origin.get('user')
    if person and person != activator:
        if await tickets.may_create(db, org_slug, person):
            return person
    return activator


async def _pinned_agent_ids(
    store: workflows.WorkflowStore,
    org_id: str,
    slug: str,
    run: workflows.Row,
    step: workflows.Row,
) -> tuple[str, str | None]:
    """Return the agent id and project of the step in the run's version.

    The agent comes from the pinned version, so run input cannot choose
    it. A pinned :data:`agent_step.TRIGGER_PROJECT` is the project in
    the run's origin, which only the gateway sets. Any other pinned
    reference, such as the output of an earlier agent step, is the
    value that the engine rendered into the step input: a project id or
    slug, which :func:`tickets.make_task` checks is in the org.

    Raises:
        422: ``agent_params_not_literal``: the agent id is a template.
            ``trigger_project_missing``: the run's origin has no project.
            ``project_not_rendered``: the rendered project is empty, not
            a string, or still a template.

    """
    wf_graph, _ = await _version_graph(store, org_id, slug, run['version'])
    node_id = step['node_id']
    node = next((n for n in wf_graph.nodes if n.id == node_id), None)
    params = node.params if node is not None else {}
    agent_id, project_id = params.get('agent_id'), params.get('project_id')
    if not isinstance(agent_id, str) or _is_template(agent_id):
        raise fastapi.HTTPException(
            status_code=422, detail={'error': 'agent_params_not_literal'}
        )
    if project_id == agent_step.TRIGGER_PROJECT:
        project_id = run['origin'].get('project_id')
        if not project_id:
            raise fastapi.HTTPException(
                status_code=422, detail={'error': 'trigger_project_missing'}
            )
    elif isinstance(project_id, str) and _is_template(project_id):
        step_input: dict[str, typing.Any] = step['input'] or {}
        rendered = step_input.get('project_id')
        project_id = rendered.strip() if isinstance(rendered, str) else ''
        if not project_id or _is_template(project_id):
            raise fastapi.HTTPException(
                status_code=422, detail={'error': 'project_not_rendered'}
            )
    return agent_id, project_id


def _is_template(value: str) -> bool:
    return '{{' in value or '{%' in value


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


def _can_read_tasks(auth: permissions.AuthContext) -> bool:
    return auth.is_admin or common_permissions.holds(
        'ticket:read', auth.permissions
    )


def _without_ticket(output: dict[str, typing.Any]) -> dict[str, typing.Any]:
    return {
        k: v
        for k, v in output.items()
        if k not in agent_step.TicketAttributes.model_fields
    }


_ERROR_CODE = re.compile(r'[a-z][a-z0-9_]*')


def _error_code(error: str | None) -> str | None:
    """Return the code of ``error``: the text before the first ``:`` or
    whitespace. Return ``None`` when that text is not a snake_case code.
    """
    code = re.split(r'[:\s]', error or '', maxsplit=1)[0]
    return code if _ERROR_CODE.fullmatch(code) else None


def _run_for(
    auth: permissions.AuthContext,
    run: dict[str, typing.Any],
    steps: list[dict[str, typing.Any]] | None = None,
) -> dict[str, typing.Any]:
    """Return ``run`` without agent task content, for a caller who
    cannot read agent tasks.

    A run that a closed task started, or that has an agent step, can
    hold task content in any value that a template rendered. For such
    a run, set the dedupe and concurrency keys to ``None``, remove
    the ``input`` and ``output`` of each of ``steps``, and keep only
    the code of the run and step errors. Remove the ticket attributes
    from the payload of a run that a task started. The keys come only
    from the payload (:func:`validation.dedupe_key`), so a list
    without ``steps`` cannot show the content of an agent step. The
    run error can, and a list cannot see the agent steps, so a list
    keeps only the code of the run error of each run.
    """
    found = list(steps or [])
    from_task = run['origin_kind'] == ticket_state_changed.TYPE
    task_content = from_task or any(s['node_type'] == 'agent' for s in found)
    if _can_read_tasks(auth) or (steps is not None and not task_content):
        return run if steps is None else {**run, 'steps': found}
    hidden = {**run, 'error': _error_code(run['error'])}
    if not task_content:
        return hidden
    hidden |= {'dedupe_key': None, 'concurrency_key': None}
    if from_task:
        hidden['payload'] = _without_ticket(run['payload'])
    if steps is not None:
        hidden['steps'] = [
            {
                **s,
                'input': None,
                'output': None,
                'error': _error_code(s['error']),
            }
            for s in found
        ]
    return hidden


def _step_agent_task(
    task: dict[str, typing.Any], summary: str | None = None
) -> dict[str, typing.Any]:
    return {
        'task_id': task['short_id'],
        'status': task['status'],
        'outcome': task['outcome'],
        'reason': task['outcome_reason'],
        'summary': summary,
        'result': task['structured_output'],
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
#: The stored result of a deployment that an operator marked done. It
#: has the shape of the deploy response, so a repeat of the key parses.
_DEPLOYMENT_DONE: dict[str, typing.Any] = {
    'run': {'run_id': '', 'status': 'unknown'},
    'plugin_id': '',
    'plugin_slug': '',
    'warning': 'An operator marked this deployment done',
}

RecoverAuth = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('workflow:recover')),
]
EngineAuth = typing.Annotated[
    permissions.AuthContext, fastapi.Depends(_require_engine)
]
EmailClient = typing.Annotated[
    email_client.EmailClient, fastapi.Depends(_email_client)
]
SlackToken = typing.Annotated[str, fastapi.Depends(_slack_token)]


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
    headers (see :func:`tickets.task_origin`). The idempotency key
    is the ``Idempotency-Key`` header (the scheduler sends its run id),
    or the delivery id for a webhook. A repeat by the same origin
    returns the first run.

    A run that a service starts is written ``skipped``,
    with ``duplicate_of``, when its dedupe key matches a run of the
    workflow made within the dedupe window. For a webhook run of a
    project, only a run of the same project or a run with no project
    counts. A person's run always starts, and its key counts for later
    runs of every project.

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
    origin = tickets.task_origin(auth, scheduled_task, webhook, delivery)
    workflow = await _workflow(store, org_id, slug)
    if workflow['status'] != 'active' or workflow['active_version'] is None:
        raise fastapi.HTTPException(
            status_code=409, detail=f'Workflow {slug!r} is not active'
        )
    wf_graph, settings = await _version_graph(
        store, org_id, slug, workflow['active_version']
    )
    project_id: str | None = None
    if origin.kind == tickets.HUMAN_ORIGIN:
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
        if origin.kind == 'webhook' and data.project_id:
            # The gateway calls once for each project that the delivery
            # matches. Each project gets its own run.
            payload = {**payload, 'project': data.project_id}
            origin = origin._replace(
                record={**origin.record, 'project_id': data.project_id}
            )
            idempotency_key = f'{idempotency_key}:{data.project_id}'
            project_id = data.project_id
        if origin.kind == 'webhook' and data.actor:
            # The person who caused the delivery owns the tickets of the
            # run, as the person who starts a manual run does.
            origin = origin._replace(
                record={**origin.record, 'user': data.actor}
            )
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
            if origin.kind == tickets.HUMAN_ORIGIN
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
                dedupe_key=validation.dedupe_key(settings, payload),
                dedupe_window_seconds=settings.dedupe_window_seconds,
                skip_duplicate=origin.kind != tickets.HUMAN_ORIGIN,
                project_id=project_id,
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
    auth: ReadAuth,
    limit: typing.Annotated[int, fastapi.Query(ge=1, le=200)] = 50,
) -> list[workflows.Row]:
    """Return the runs of a workflow, newest first."""
    workflow = await _workflow(store, org_id, slug)
    return [
        _run_for(auth, r) for r in await runs.list_runs(workflow['id'], limit)
    ]


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

    A later step can render agent task content into its ``input`` and
    ``output``. For a run that a closed task started or that has an
    agent step, only a caller who can read agent tasks
    (``ticket:read``) gets the step ``input`` and ``output``, the
    dedupe key, and the ticket attributes of the payload.

    Raises:
        404: No such workflow or run.
        503: The run's log is archived and ClickHouse is not available.

    """
    workflow = await _workflow(store, org_id, slug)
    row = await _run(runs, workflow, run_id)
    steps = [] if row['log_archived_at'] else await runs.steps(run_id)
    if not steps and row['log_archived_at'] is None:
        # The archive can commit between the two reads and delete the
        # step rows. Read the run again to get its archive state. Keep
        # the first row when the run is not archived: the engine can
        # add a step and set the run error after the step read, and
        # that error must not go out with a step list that is empty.
        again = await _run(runs, workflow, run_id)
        if again['log_archived_at'] is not None:
            row = again
    if row['log_archived_at'] is not None:
        try:
            steps = await history.archived_steps(row)
        except Exception as e:
            raise fastapi.HTTPException(
                status_code=503, detail='The run history is not available'
            ) from e
    return _run_for(auth, row, steps)


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
    return _run_for(auth, await _run(runs, workflow, run_id))


workflow_attention_router = fastapi.APIRouter(
    tags=['Workflows'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)


@workflow_attention_router.get('/attention', response_model=list[AttentionRun])
async def list_attention_runs(
    org_id: OrgId,
    runs: workflows.Runs,
    auth: ReadAuth,
) -> list[workflows.Row]:
    """Return the failed runs of the last 7 days and the stuck runs.

    A stuck run is open and no engine works on it: see
    :meth:`imbi.api.workflows.RunStore.attention`.
    """
    return [_run_for(auth, r) for r in await runs.attention(org_id)]


@workflow_attention_router.get('/', response_model=list[OrgRun])
async def list_org_runs(
    org_id: OrgId,
    runs: workflows.Runs,
    auth: ReadAuth,
    days: typing.Annotated[int, fastapi.Query(ge=1, le=90)] = 7,
    limit: typing.Annotated[int, fastapi.Query(ge=1, le=1000)] = 500,
) -> list[dict[str, typing.Any]]:
    """Return the runs of every workflow made in the last ``days``
    days, and the stuck runs, newest first.

    A failed or timed-out run has the failed step that finished last.
    Its step records come from Postgres, or from ClickHouse when the
    run's log is archived. When ClickHouse is not available, an archived
    run has no ``failure``.
    """
    found = await runs.org_runs(org_id, days, limit)
    failed = [r for r in found if r['status'] in ('failed', 'timed_out')]
    live = [r['id'] for r in failed if r['log_archived_at'] is None]
    archived = [str(r['id']) for r in failed if r['log_archived_at']]
    steps, from_archive = await asyncio.gather(
        runs.failed_steps(live) if live else _no_steps(),
        history.archived_failed_steps(org_id, archived)
        if archived
        else _no_steps(),
        return_exceptions=True,
    )
    if isinstance(steps, BaseException):
        raise steps
    if isinstance(from_archive, BaseException):
        LOGGER.error(
            'Could not read archived failed steps', exc_info=from_archive
        )
    else:
        steps |= from_archive
    task_content = _can_read_tasks(auth)
    return [
        {
            **_run_for(auth, r),
            'failure': _failure(steps.get(str(r['id'])), task_content),
        }
        for r in found
    ]


async def _no_steps() -> dict[str, dict[str, typing.Any]]:
    return {}


def _failure(
    step: dict[str, typing.Any] | None, task_content: bool
) -> dict[str, typing.Any] | None:
    if step is None:
        return None
    output: dict[str, typing.Any] = (
        step['output']
        if step['node_type'] == 'agent' and step['output']
        else {}
    )
    return {
        'node_key': step['node_key'],
        'title': step['title'],
        'node_type': step['node_type'],
        'attempt': step['attempt'],
        'error': step['error'] if task_content else _error_code(step['error']),
        'task_id': output.get('task_id'),
        'outcome': output.get('outcome'),
        'reason': output.get('reason') if task_content else None,
        'summary': output.get('summary') if task_content else None,
    }


@workflow_attention_router.get(
    '/side-effects', response_model=list[StaleSideEffect]
)
async def list_stale_side_effects(
    org_id: OrgId, runs: workflows.Runs, _: RecoverAuth
) -> list[workflows.Row]:
    """Return the side effects of runs that started and did not finish.

    A repeat of such a key gets ``409 outcome_unknown``, so its step
    fails. Only an operator resolves one; keys never expire (ADR 0021,
    unknown-outcome reconciliation).
    """
    return await runs.stale_side_effects(org_id)


async def _stale_side_effect(
    runs: workflows.RunStore, org_id: str, key: str
) -> workflows.Row:
    found = await runs.stale_side_effects(org_id, key)
    if not found:
        raise fastapi.HTTPException(
            status_code=404, detail='No stale side effect with this key'
        )
    return found[0]


async def _deployment_candidates(
    db: graph.Graph,
    org_slug: str,
    effect: workflows.Row,
    auth: permissions.AuthContext,
) -> tuple[ResolvedCapability, list[DeploymentRun]]:
    """Ask the deployment plugin for the deployments that the call of a
    stale ``deployment`` key can have made.

    The project, environment, and version come from the step's stored
    input. A rollback to ``last_healthy`` or ``previous`` finds its
    version when it runs, so its input has none. The window starts one
    minute before the key, for clock skew between Imbi and the provider.

    Raises:
        409: The key is not a deployment, or its step input does not
            name a project, an environment, and a version.

    """
    params: dict[str, typing.Any] = effect['step_input'] or {}
    project_id, environment, version = (
        params.get(name) for name in ('project_id', 'environment', 'version')
    )
    if effect['node_type'] == 'rollback' and params.get('target') != 'version':
        version = None
    if effect['action'] != 'deployment' or not (
        isinstance(project_id, str)
        and isinstance(environment, str)
        and isinstance(version, str)
    ):
        raise fastapi.HTTPException(
            status_code=409,
            detail='The step input of this key does not name a project, '
            'an environment, and a version',
        )
    return await project_deployments.find_deployments(
        db,
        org_slug,
        project_id,
        auth,
        environment=environment,
        ref=version,
        since=effect['created_at'] - datetime.timedelta(minutes=1),
    )


@workflow_attention_router.get(
    '/side-effects/deployments', response_model=list[DeploymentRun]
)
async def find_side_effect_deployments(
    org_slug: str,
    org_id: OrgId,
    key: str,
    db: graph.Pool,
    runs: workflows.Runs,
    auth: RecoverAuth,
) -> list[DeploymentRun]:
    """Return the deployments that a stale ``deployment`` key can have
    made, from the project's deployment plugin.

    Another deploy of the same version and environment at the same time
    also matches, so the operator confirms one (``mark_done`` with
    ``deployment_run_id``) before Imbi stores it. An empty list: the
    plugin found none.

    Raises:
        400: The plugin cannot find deployments.
        404: No stale side effect with the key in the organization.
        409: The key is not a deployment, or its step input is gone.

    """
    effect = await _stale_side_effect(runs, org_id, key)
    _, found = await _deployment_candidates(db, org_slug, effect, auth)
    return found


@workflow_attention_router.post('/side-effects/resolve', status_code=204)
async def resolve_side_effect(
    org_slug: str,
    org_id: OrgId,
    body: SideEffectResolve,
    db: graph.Pool,
    runs: workflows.Runs,
    auth: RecoverAuth,
) -> None:
    """Clear a stale side effect, or mark it done, and retry its step.

    A deployment marked done with a ``deployment_run_id`` stores that
    run as the result of the call, if the plugin still finds it.

    Raises:
        404: No stale side effect with the key in the organization.
        409: The resolution or the retry does not apply to it, or it
            changed.

    """
    effect = await _stale_side_effect(runs, org_id, body.key)
    done = body.resolution == 'mark_done'
    deployment = effect['action'] == 'deployment'
    if body.deployment_run_id is not None and not (done and deployment):
        raise fastapi.HTTPException(
            status_code=409,
            detail='Only a deployment marked done takes a deployment run',
        )
    if body.retry and (
        not effect['retryable']
        or (done and deployment and body.deployment_run_id is None)
    ):
        raise fastapi.HTTPException(
            status_code=409, detail='The step of this key cannot run again'
        )
    response = None
    if body.deployment_run_id is not None:
        resolved, found = await _deployment_candidates(
            db, org_slug, effect, auth
        )
        run = next(
            (r for r in found if r.run_id == body.deployment_run_id), None
        )
        if run is None:
            raise fastapi.HTTPException(
                status_code=409,
                detail='The plugin does not find this deployment run '
                'for the key',
            )
        response = project_deployments.DeploymentTriggerResponse(
            run=run,
            plugin_id=resolved.integration_id,
            plugin_slug=resolved.plugin_slug,
        ).model_dump(mode='json')
    elif done:
        response = _done_response(effect)
    retry = (effect['run_id'], effect['node_id']) if body.retry else None
    if not await runs.resolve_side_effect(body.key, response, retry):
        raise fastapi.HTTPException(
            status_code=409, detail='The side effect or its run changed'
        )


def _done_response(effect: workflows.Row) -> dict[str, typing.Any]:
    """Return the result to store for a call that an operator marked
    done with no deployment run."""
    match effect['action']:
        case 'deployment':
            return _DEPLOYMENT_DONE
        case 'step-slack':
            step_input: dict[str, typing.Any] = effect['step_input'] or {}
            return SlackResult(
                channel=str(step_input.get('channel') or '')
            ).model_dump()
        case _:
            return EmailResult(recipients=[]).model_dump()


async def _running_step(
    store: workflows.WorkflowStore,
    runs: workflows.RunStore,
    org_id: str,
    slug: str,
    run_id: uuid.UUID,
    node_id: str,
) -> workflows.Row:
    """Return the step of a run, if it is running.

    Raises:
        404: No such workflow, run, or step.
        409: The step is not running.

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
    if step['status'] != 'running':
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Step {node_id!r} is not a running '
            f'{step["node_type"]} step',
        )
    return step


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
    step = await _running_step(store, runs, org_id, slug, run_id, node_id)
    if step['node_type'] != 'email':
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
    '/{slug}/runs/{run_id}/steps/{node_id}/slack', response_model=SlackResult
)
async def send_step_slack(
    org_slug: str,
    org_id: OrgId,
    slug: str,
    run_id: uuid.UUID,
    node_id: str,
    store: workflows.Store,
    runs: workflows.Runs,
    tasks: ticket_store.Store,
    token: SlackToken,
    auth: EngineAuth,
    idempotency_key: IdempotencyKey,
) -> dict[str, typing.Any]:
    """Post the message of a running slack step. Engine only.

    Raises:
        404: No such workflow, run, or step.
        409: The step is not a running slack step, or
            ``outcome_unknown``: a call with the key did not finish.
        422: ``invalid_channel``: the channel is not a Slack channel id,
            or ``ticket_not_found``: the ticket is not a task of the
            organization.
        502: ``slack_unreachable``: the call to Slack failed, and Slack
            may have posted the message.
        503: ``slack_not_configured``: imbi-api has no bot token.

    A refusal from Slack is not an error here: the response has its
    code in ``error``, and the engine fails the step.

    A step with a ``ticket`` shows the task below the message (see
    :func:`workflow_tickets.with_ticket_block`).

    """
    step = await _running_step(store, runs, org_id, slug, run_id, node_id)
    if step['node_type'] != 'slack':
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Step {node_id!r} is not a running slack step',
        )
    # Checked before the key is taken: a 5xx inside ``once`` keeps the
    # key, and this one posted nothing.
    if not token:
        raise fastapi.HTTPException(
            status_code=503, detail={'error': 'slack_not_configured'}
        )
    params = slack_step.Params.model_validate(step['input'])
    if not slack_step.CHANNEL_ID.match(params.channel):
        raise fastapi.HTTPException(
            status_code=422, detail={'error': 'invalid_channel'}
        )
    # Read before the key is taken too: a failed read posted nothing.
    text = params.text
    if params.ticket:
        task = await tasks.get(org_id, params.ticket)
        if task is None:
            raise fastapi.HTTPException(
                status_code=422, detail={'error': 'ticket_not_found'}
            )
        text = workflow_tickets.with_ticket_block(text, task, org_slug)

    async def call() -> dict[str, typing.Any]:
        posted = await _post_slack(token, params.channel, text)
        return posted.model_dump()

    return await runs.once(
        auth.principal_name, 'step-slack', idempotency_key, call
    )


@workflow_runs_router.post(
    '/{slug}/runs/{run_id}/steps/{node_id}/assign-ticket',
    response_model=assign_step.Output,
)
async def assign_step_ticket(
    org_slug: str,
    org_id: OrgId,
    slug: str,
    run_id: uuid.UUID,
    node_id: str,
    db: graph.Pool,
    store: workflows.Store,
    runs: workflows.Runs,
    tasks: ticket_store.Store,
    auth: EngineAuth,
    idempotency_key: IdempotencyKey,
) -> dict[str, typing.Any]:
    """Hand the ticket of a running assign_ticket step to the person in
    its role. Engine only.

    A role with nobody in it changes nothing and returns ``assignee``
    ``None``. A ticket that the person has already is not changed. A
    repeat with the same ``Idempotency-Key`` returns the first result
    and changes nothing, so it cannot undo a later hand-off.

    Raises:
        404: No such workflow, run, or step.
        409: The step is not a running assign_ticket step, or the
            ticket cannot change now (``ticket_closed``,
            ``session_open``, ``chain_pinned``, ``cancel_pending``), or
            the role changed before the hand-off (``roles_changed``), or
            a call with this key started and did not finish
            (``outcome_unknown``).
        422: ``ticket_not_found``: the ticket is not a ticket of the
            organization, or ``assignee_not_member``: the person in the
            role is not in the organization.

    """
    step = await _running_step(store, runs, org_id, slug, run_id, node_id)
    if step['node_type'] != assign_step.STEP.type:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Step {node_id!r} is not a running assign_ticket step',
        )
    params = assign_step.Params.model_validate(step['input'])

    async def call() -> dict[str, typing.Any]:
        task = await tasks.get(org_id, params.ticket.upper())
        if task is None:
            raise fastapi.HTTPException(
                status_code=422, detail={'error': 'ticket_not_found'}
            )
        role = ticket_rows.normalize_label(params.role)
        roles: dict[str, str] = task['roles'] or {}
        email = roles.get(role)
        result: dict[str, typing.Any] = {
            'task_id': task['short_id'],
            'role': role,
            'assignee': email,
        }
        if email is None:
            return result
        try:
            to = await tickets.person_assignee(db, org_slug, email)
        except fastapi.HTTPException as e:
            raise fastapi.HTTPException(
                status_code=422, detail={'error': 'assignee_not_member'}
            ) from e
        # A ticket that closed after the person got it succeeds too.
        if task['assignee_kind'] == 'person' and task['assignee'] == email:
            return result
        errors: dict[type[Exception], str] = {
            ticket_store.TaskClosed: 'ticket_closed',
            ticket_store.SessionOpen: 'session_open',
            ticket_store.ChainPinned: 'chain_pinned',
            ticket_store.CancelPending: 'cancel_pending',
            ticket_store.RolesChanged: 'roles_changed',
        }
        try:
            # The roles are read again under the lock, so a person who
            # left the role does not get the ticket.
            await tasks.hand_off(
                org_id,
                task['short_id'],
                to,
                ticket_store.Actor('system', auth.principal_name, 'api'),
                roles_read=roles,
            )
        except tuple(errors) as e:
            raise fastapi.HTTPException(
                status_code=409, detail={'error': errors[type(e)]}
            ) from e
        return result

    return await runs.once(
        auth.principal_name, 'step-assign-ticket', idempotency_key, call
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
    tasks: ticket_store.Store,
    auth: EngineAuth,
) -> dict[str, typing.Any]:
    """Make the task of a running agent step, or return it. Engine only.

    A repeat, after a crash or for a retry of the step, returns the
    first task: the key is the same. The owner of the task (see
    :func:`_step_owner`) must still be able to make agent tasks in the
    org. The engine polls this route until the task is closed.

    The agent comes from the pinned version, and the project from the
    pinned version or the step input (see :func:`_pinned_agent_ids`).
    A task with the key that this step did not make, or that has
    another agent, is refused.

    Raises:
        403: ``owner_forbidden``: the owner cannot make agent tasks.
        404: No such workflow, run, or step.
        409: The step is not a running agent step, the agent is
            disabled, or ``task_key_conflict``.
        422: ``agent_not_found``, ``agent_params_not_literal``,
            ``trigger_project_missing``, ``project_not_rendered``, the
            project or the budget is not valid, or
            ``custom_fields_invalid`` (see :func:`tickets.make_task`).

    """
    workflow = await _workflow(store, org_id, slug)
    run, step, origin, key = await _agent_step(runs, workflow, run_id, node_id)
    agent_id, project_id = await _pinned_agent_ids(
        store, org_id, slug, run, step
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
        owner = await _step_owner(db, org_slug, run)
        if owner is None:
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
            data = tickets.AgentTaskCreate(
                agent_slug=str(graph.parse_agtype(records[0]['slug'])),
                title=params.task_title
                or f'{workflow["name"]}: {step["title"]}',
                description=params.instruction,
                project_ids=[project_id] if project_id else [],
                budget=params.budget,
                custom_fields=params.custom_fields,
            )
        except pydantic.ValidationError as e:
            raise fastapi.HTTPException(
                status_code=422, detail={'error': 'invalid_params'}
            ) from e
        task, _ = await tickets.make_task(
            db,
            tasks,
            org_slug,
            org_id,
            data,
            origin,
            key,
            owner,
            ticket_store.Actor('system', auth.principal_name, 'api'),
            agent_step.output_schema(params.output_fields),
        )
    if (
        not _made_by_step(task, run_id, step['node_key'])
        or task['agent_id'] != agent_id
    ):
        raise _task_key_conflict()
    if task['status'] != 'closed':
        return _step_agent_task(task)
    summary, attributes = await asyncio.gather(
        tasks.last_agent_turn(task), workflow_tickets.attributes(db, task)
    )
    return {**_step_agent_task(task, summary), **attributes}


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
    tasks: ticket_store.Store,
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
            ticket_store.Actor('system', auth.principal_name, 'api'),
        )
    except (ticket_store.TaskClosed, ticket_store.CancelPending):
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
        names = step.ports_for(node.params)
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
