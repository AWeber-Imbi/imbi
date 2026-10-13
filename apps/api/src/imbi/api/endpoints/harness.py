"""Runner pool, runner, and agent token routes (ADR 0022).

- **Pools** (``/harness/pools``): only platform administrators
  (``is_admin``) manage them. This is not a permission, because an
  organization administrator can grant a permission to a role. A holder
  of ``harness_pool:read`` sees the pools that serve an organization
  that they are a member of, and only the runners and chains of that
  organization.
- **Runners** (``/harness/runners``): a runner registers with its pool
  credential (the client credential of the pool's service account),
  then heartbeats, claims, and finishes with its runner credential.
- **Tasks** (``/harness/tasks``): the routes that a runner calls with
  an agent token for a task of its chain: read events, make a child
  task, and check a tool rate limit.
"""

import asyncio
import datetime
import decimal
import json
import typing
import uuid

import fastapi
import pydantic

from imbi.api import agent_tasks, harness
from imbi.api.auth import autonomous, organizations, permissions
from imbi.api.endpoints import agent_tasks as tasks_api
from imbi.api.endpoints import agents as agents_api
from imbi.api.harness import auth as harness_auth
from imbi.api.harness import store as harness_store
from imbi.api.harness import tokens
from imbi.common import graph, models

#: The longest wait of a claim long poll, in seconds.
MAX_CLAIM_WAIT_SECONDS = 20
#: How often a long poll looks for a task again.
CLAIM_POLL_SECONDS = 1.0

_POOL_NAME_PATTERN = r'^[a-z0-9][a-z0-9-]*$'


# --- Schemas -----------------------------------------------------------


class PoolCreate(pydantic.BaseModel):
    name: str = pydantic.Field(
        min_length=1,
        max_length=63,
        pattern=_POOL_NAME_PATTERN,
        description='The name of the Kubernetes Deployment of the pool.',
    )
    description: str | None = None
    labels: list[models.RunnerLabel] = []
    organizations: list[str] = pydantic.Field(
        default=[],
        description='Organization slugs. Empty means all organizations.',
    )
    service_account: str = pydantic.Field(
        min_length=1,
        description=(
            'The slug of the service account whose client credential '
            'registers runners of the pool.'
        ),
    )


class PoolUpdate(pydantic.BaseModel):
    description: str | None = None
    labels: list[models.RunnerLabel] | None = None
    organizations: list[str] | None = None
    service_account: str | None = pydantic.Field(default=None, min_length=1)


class RunnerChain(pydantic.BaseModel):
    """The chain that a runner holds."""

    root_task_id: uuid.UUID
    short_id: str | None = None
    organization_slug: str | None = None
    attempt: int
    state: harness_store.ChainState
    #: Why the fencers failed, for a ``stuck`` chain.
    fence_error: str | None = None


class RunnerResponse(pydantic.BaseModel):
    id: uuid.UUID
    instance: str | None = None
    labels: list[str]
    state: harness_store.RunnerState
    image_version: str | None = None
    registered_at: datetime.datetime
    last_heartbeat: datetime.datetime
    lease_expires_at: datetime.datetime
    #: ``None`` when the runner holds no chain, or a chain of an
    #: organization that the caller cannot see.
    chain: RunnerChain | None = None


class PoolResponse(pydantic.BaseModel):
    name: str
    description: str | None = None
    labels: list[str]
    #: The slugs of the allowlist. Empty means all organizations. A
    #: caller who is not a platform administrator sees only the
    #: organization that they asked for.
    organizations: list[str]
    #: Shown only to platform administrators.
    service_account: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    #: The runners that are not offline.
    runners: list[RunnerResponse] = []


class RunnerRegister(pydantic.BaseModel):
    pool: str = pydantic.Field(min_length=1)
    instance: str | None = pydantic.Field(
        default=None, max_length=253, description='The pod name.'
    )
    image_version: str | None = pydantic.Field(default=None, max_length=200)


class RunnerRegistered(pydantic.BaseModel):
    runner_id: uuid.UUID
    #: Heartbeat, claim, and finish. Shown only here.
    runner_token: str
    #: For the executor's secret routes only. Shown only here.
    executor_token: str
    labels: list[str]
    lease_seconds: int
    lease_expires_at: datetime.datetime


class RunnerLease(pydantic.BaseModel):
    state: harness_store.RunnerState
    chain_id: uuid.UUID | None = None
    lease_seconds: int
    lease_expires_at: datetime.datetime


class IdentityBundle(pydantic.BaseModel):
    """The pinned identity of a task's agent. Holds no secret."""

    agent_id: str
    agent_slug: str | None = None
    agent_version: int
    #: The pinned agent version snapshot (see ``AgentVersion``).
    snapshot: dict[str, typing.Any]
    prompt_ref: str | None = None
    prompt_version: int | None = None


class Claim(pydantic.BaseModel):
    chain_id: uuid.UUID
    attempt: int
    organization_slug: str
    task: tasks_api.AgentTaskResponse
    bundle: IdentityBundle
    #: For the harness routes of the tasks of this chain only.
    agent_token: str
    agent_token_expires_at: datetime.datetime


class RunnerFinished(pydantic.BaseModel):
    #: The state of the chain after the finish: ``done``, or
    #: ``fencing`` when a task of it is still open.
    chain_state: harness_store.ChainState | None = None


class ChildTaskCreate(pydantic.BaseModel):
    agent_slug: str = pydantic.Field(min_length=1)
    title: str = pydantic.Field(min_length=1)
    description: str = pydantic.Field(
        min_length=1, description='The instruction for the agent.'
    )
    budget: decimal.Decimal | None = pydantic.Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=6,
        description="USD. At most the child agent's task_budget.",
    )
    idempotency_key: str | None = pydantic.Field(
        default=None, min_length=1, max_length=200
    )


class ToolCallCheck(pydantic.BaseModel):
    tool_key: models.AgentToolKey


class ToolCallVerdict(pydantic.BaseModel):
    allowed: bool
    #: ``tool_not_configured`` or ``rate_limited`` when not allowed.
    reason: str | None = None
    count: int | None = None
    limit: int | None = None
    per: typing.Literal['minute', 'hour', 'day'] | None = None
    window_start: datetime.datetime | None = None


# --- Graph queries -----------------------------------------------------

_AGENTS_QUERY: typing.LiteralString = """
MATCH (a:Agent)
RETURN a.id AS id, a.enabled AS enabled, a.settings AS settings
"""

_AGENT_QUERY: typing.LiteralString = """
MATCH (a:Agent {{slug: {slug}}})
      -[:BELONGS_TO]->(:Organization {{id: {org_id}}})
RETURN a
"""

_AGENT_SLUG_QUERY: typing.LiteralString = """
MATCH (a:Agent {{id: {id}}})
RETURN a.slug AS slug
"""

_VERSION_QUERY: typing.LiteralString = """
MATCH (v:AgentVersion {{agent_id: {id}, n: {n}}})
RETURN v.snapshot AS snapshot
"""

_ORGS_BY_ID_QUERY: typing.LiteralString = """
MATCH (o:Organization) WHERE o.id IN {ids}
RETURN o.id AS id, o.slug AS slug
"""

_ORGS_BY_SLUG_QUERY: typing.LiteralString = """
MATCH (o:Organization) WHERE o.slug IN {slugs}
RETURN o.id AS id, o.slug AS slug
"""


def _settings(raw: typing.Any) -> models.AgentSettings:
    if isinstance(raw, str):
        return models.AgentSettings.model_validate_json(raw)
    return models.AgentSettings.model_validate(raw or {})


async def eligible_agents(
    db: graph.Graph,
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Return the enabled agents with their required labels, and the
    ``max_concurrent_tasks`` of those that have one.

    The claim compares the labels with the labels of the runner's pool
    in its transaction.
    """
    # ponytail: reads every agent per claim; filter by the pool's
    # organizations in the query when the agent count grows.
    agents: dict[str, list[str]] = {}
    limits: dict[str, int] = {}
    for record in await db.execute(
        _AGENTS_QUERY, {}, ['id', 'enabled', 'settings']
    ):
        if graph.parse_agtype(record['enabled']) is False:
            continue
        settings = _settings(graph.parse_agtype(record['settings']))
        agent_id = str(graph.parse_agtype(record['id']))
        agents[agent_id] = settings.required_labels
        if settings.max_concurrent_tasks is not None:
            limits[agent_id] = settings.max_concurrent_tasks
    return agents, limits


async def _org_slugs(db: graph.Graph, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    records = await db.execute(_ORGS_BY_ID_QUERY, {'ids': ids}, ['id', 'slug'])
    return {
        str(graph.parse_agtype(r['id'])): str(graph.parse_agtype(r['slug']))
        for r in records
    }


async def _org_ids(db: graph.Graph, slugs: list[str]) -> list[str]:
    """Return the ids of organization slugs, or raise 422."""
    if not slugs:
        return []
    records = await db.execute(
        _ORGS_BY_SLUG_QUERY, {'slugs': slugs}, ['id', 'slug']
    )
    found = {
        str(graph.parse_agtype(r['slug'])): str(graph.parse_agtype(r['id']))
        for r in records
    }
    missing = sorted(set(slugs) - set(found))
    if missing:
        raise _unprocessable(f'Unknown organizations: {", ".join(missing)}')
    return sorted({found[slug] for slug in slugs})


async def _service_account_id(db: graph.Graph, slug: str) -> str:
    """Return the immutable id of a service account, or raise 422."""
    accounts = await db.match(models.ServiceAccount, {'slug': slug})
    if not accounts:
        raise _unprocessable(f'Service account {slug!r} not found')
    return accounts[0].id


async def _bundle(
    db: graph.Graph, task: dict[str, typing.Any]
) -> IdentityBundle:
    """Return the identity bundle of the pinned agent version of a task."""
    records = await db.execute(
        _VERSION_QUERY,
        {'id': task['agent_id'], 'n': task['agent_version']},
        ['snapshot'],
    )
    raw: typing.Any = (
        graph.parse_agtype(records[0]['snapshot']) if records else None
    )
    snapshot: dict[str, typing.Any] = (
        json.loads(raw) if isinstance(raw, str) else raw or {}
    )
    slug = snapshot.get('slug')
    if slug is None:
        records = await db.execute(
            _AGENT_SLUG_QUERY, {'id': task['agent_id']}, ['slug']
        )
        slug = graph.parse_agtype(records[0]['slug']) if records else None
    return IdentityBundle(
        agent_id=task['agent_id'],
        agent_slug=slug,
        agent_version=task['agent_version'],
        snapshot=snapshot,
        prompt_ref=snapshot.get('prompt_ref'),
        prompt_version=task['prompt_version'],
    )


class _NoServiceAccount(LookupError):
    """The service account of a claimed task is gone."""


#: The actor of the outcome of a task that cannot run.
_SYSTEM = agent_tasks.Actor('system', 'imbi', 'harness')


async def _deliver(
    db: graph.Graph,
    store: harness.HarnessStore,
    tasks: agent_tasks.TaskStore,
    runner: dict[str, typing.Any],
    claimed: tuple[dict[str, typing.Any], dict[str, typing.Any]],
    *,
    pinned: bool,
) -> Claim | None:
    """Return the claim response, or undo the claim when it fails.

    A task whose service account is gone can never run, so it closes
    with ``unhandled_no_actor`` and ``None`` is returned: the caller
    claims again. Any other error undoes the claim and is raised again,
    so the runner is not left busy with a chain that it does not know.
    """
    task, chain = claimed
    try:
        return await _claim(db, runner, task, chain)
    except _NoServiceAccount:
        await tasks.set_outcome(
            task['organization_id'],
            task['short_id'],
            'unhandled_no_actor',
            'service_account_missing',
            _SYSTEM,
        )
        await store.release_claim(runner['id'], task, chain, pinned=pinned)
        return None
    except BaseException:
        await store.release_claim(runner['id'], task, chain, pinned=pinned)
        raise


async def _claim(
    db: graph.Graph,
    runner: dict[str, typing.Any],
    task: dict[str, typing.Any],
    chain: dict[str, typing.Any],
) -> Claim:
    """Return the claim response of a task: its bundle and agent token."""
    accounts = await db.match(
        models.ServiceAccount, {'id': task['service_account_id']}
    )
    if not accounts:
        raise _NoServiceAccount(task['short_id'])
    org_slugs = await _org_slugs(db, [task['organization_id']])
    grant = tokens.AgentGrant(
        chain_id=chain['root_task_id'],
        attempt=chain['attempt'],
        runner_id=runner['id'],
        organization_id=task['organization_id'],
    )
    token, expires = tokens.mint_agent_token(accounts[0].slug, grant)
    return Claim(
        chain_id=chain['root_task_id'],
        attempt=chain['attempt'],
        organization_slug=org_slugs.get(task['organization_id'], ''),
        task=tasks_api.AgentTaskResponse.model_validate(task),
        bundle=await _bundle(db, task),
        agent_token=token,
        agent_token_expires_at=expires,
    )


def _unprocessable(detail: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(status_code=422, detail=detail)


def _conflict(error: str, message: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=409, detail={'error': error, 'message': message}
    )


def _pool_response(
    pool: dict[str, typing.Any],
    org_slugs: dict[str, str],
    runners: list[dict[str, typing.Any]],
    visible_org: str | None,
) -> PoolResponse:
    """Return a pool and its runners.

    With ``visible_org`` (a caller who is not a platform administrator),
    the allowlist shows only that organization, the service account is
    hidden, and a runner with a chain of another organization shows
    only its state: no chain, instance, or image version.
    """
    items: list[RunnerResponse] = []
    for runner in runners:
        chain: RunnerChain | None = None
        foreign = (
            visible_org is not None
            and runner['chain_id'] is not None
            and runner['chain_organization_id'] != visible_org
        )
        if foreign:
            runner = {**runner, 'instance': None, 'image_version': None}
        elif runner['chain_id'] is not None:
            chain = RunnerChain(
                root_task_id=runner['chain_id'],
                short_id=runner['chain_short_id'],
                organization_slug=org_slugs.get(
                    runner['chain_organization_id'] or ''
                ),
                attempt=runner['attempt'],
                state=runner['chain_state'],
                fence_error=runner['fence_error'],
            )
        items.append(RunnerResponse.model_validate({**runner, 'chain': chain}))
    org_ids = [str(org_id) for org_id in pool['organization_ids']]
    if visible_org is not None:
        org_ids = [org_id for org_id in org_ids if org_id == visible_org]
    return PoolResponse.model_validate(
        {
            **pool,
            'organizations': sorted(
                org_slugs.get(org_id, org_id) for org_id in org_ids
            ),
            'service_account': (
                pool['service_account'] if visible_org is None else None
            ),
            'runners': items,
        }
    )


async def _chain_task(
    caller: harness_auth.HarnessCaller,
    short_id: str,
    db: graph.Graph,
    store: agent_tasks.TaskStore,
) -> dict[str, typing.Any]:
    """Return a task of the agent token's chain, of the token's agent.

    The service account must still be a member of the organization of
    the token, as on the ADR 0020 harness routes.

    Raises:
        403: Not a member of the organization, another chain, or
            another agent.
        404: No such task in the organization of the token.

    """
    grant = caller.grant
    if grant is None:  # pragma: no cover - AgentCaller has a grant
        raise RuntimeError('an agent caller has no grant')
    org_slug = (await _org_slugs(db, [grant.organization_id])).get(
        grant.organization_id
    )
    if org_slug is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Task {short_id!r} not found'
        )
    await autonomous.require_organization_membership(
        db, caller.auth, org_slug=org_slug
    )
    task = await store.get(grant.organization_id, short_id.upper())
    if task is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Task {short_id!r} not found'
        )
    account = caller.auth.service_account
    if (task['chain_id'] or task['id']) != grant.chain_id:
        raise autonomous.forbidden(
            'chain_forbidden',
            f'Task {task["short_id"]} is not in the chain of the token.',
        )
    if account is None or account.id != task['service_account_id']:
        raise autonomous.forbidden(
            'agent_task_forbidden',
            f'The token is not for the agent of task {task["short_id"]}.',
        )
    return task


# --- Endpoints ---------------------------------------------------------

harness_router = fastapi.APIRouter(prefix='/harness', tags=['Agent Harness'])


async def _require_platform_admin(
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> permissions.AuthContext:
    """Return the caller when it is a platform administrator.

    Raises:
        403: The caller is not a platform administrator.

    """
    if not auth.is_admin:
        raise fastapi.HTTPException(
            status_code=403,
            detail='Only platform administrators can change runner pools',
        )
    return auth


_require_write = _require_platform_admin


@harness_router.get('/pools', response_model=list[PoolResponse])
async def list_harness_pools(
    db: graph.Pool,
    store: harness.Store,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
    organization: typing.Annotated[
        str | None,
        fastapi.Query(description='The slug of the organization to see.'),
    ] = None,
) -> list[PoolResponse]:
    """List runner pools and their runners that are not offline.

    A platform administrator sees every pool and chain; with
    ``organization``, only the pools that serve it. Every other caller
    needs ``harness_pool:read`` and ``organization``, must be a member
    of it, and sees only the pools that serve it and its own chains.

    Raises:
        403: No ``harness_pool:read``, or not a member.
        422: ``organization`` is missing.

    """
    org_id: str | None = None
    if organization is not None and auth.is_admin:
        # A platform administrator needs no membership.
        records = await db.execute(
            _ORGS_BY_SLUG_QUERY, {'slugs': [organization]}, ['id', 'slug']
        )
        if not records:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'Organization with slug {organization!r} not found',
            )
        org_id = str(graph.parse_agtype(records[0]['id']))
    elif organization is not None:
        org_id = await organizations.check_member(organization, db, auth)
    if not auth.is_admin:
        if 'harness_pool:read' not in auth.permissions:
            raise fastapi.HTTPException(
                status_code=403,
                detail='Permission denied: harness_pool:read required',
            )
        if org_id is None:
            raise _unprocessable('organization is required')
    pools = [
        pool
        for pool in await store.pools()
        if org_id is None
        or not pool['organization_ids']
        or org_id in pool['organization_ids']
    ]
    runners = await store.runners([pool['name'] for pool in pools])
    ids = {org for pool in pools for org in pool['organization_ids']}
    ids |= {r['chain_organization_id'] for r in runners} - {None}
    org_slugs = await _org_slugs(db, sorted(ids))
    return [
        _pool_response(
            pool,
            org_slugs,
            [r for r in runners if r['pool'] == pool['name']],
            None if auth.is_admin else org_id,
        )
        for pool in pools
    ]


@harness_router.post('/pools', status_code=201, response_model=PoolResponse)
async def create_harness_pool(
    data: PoolCreate,
    db: graph.Pool,
    store: harness.Store,
    _auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(_require_write)
    ],
) -> PoolResponse:
    """Create a runner pool.

    Raises:
        403: Not a platform administrator.
        409: A pool has this name.
        422: An unknown organization or service account.

    """
    org_ids = await _org_ids(db, data.organizations)
    account_id = await _service_account_id(db, data.service_account)
    try:
        pool = await store.create_pool(
            data.name,
            description=data.description,
            labels=sorted(set(data.labels)),
            organization_ids=org_ids,
            service_account=data.service_account,
            service_account_id=account_id,
        )
    except harness.PoolExists as err:
        raise _conflict('pool_exists', f'Pool {data.name!r} exists') from err
    return _pool_response(pool, await _org_slugs(db, org_ids), [], None)


@harness_router.patch('/pools/{name}', response_model=PoolResponse)
async def update_harness_pool(
    name: str,
    data: PoolUpdate,
    db: graph.Pool,
    store: harness.Store,
    _auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(_require_write)
    ],
) -> PoolResponse:
    """Change a runner pool. The next claim of each runner of the pool
    uses the new labels and allowlist.

    Raises:
        403: Not a platform administrator.
        404: No such pool.
        422: An unknown organization or service account.

    """
    changes: dict[str, typing.Any] = {}
    fields = data.model_fields_set
    if 'description' in fields:
        changes['description'] = data.description
    if data.labels is not None:
        changes['labels'] = sorted(set(data.labels))
    if data.organizations is not None:
        changes['organization_ids'] = await _org_ids(db, data.organizations)
    if data.service_account is not None:
        changes['service_account_id'] = await _service_account_id(
            db, data.service_account
        )
        changes['service_account'] = data.service_account
    pool = await store.update_pool(name, changes)
    if pool is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Pool {name!r} not found'
        )
    runners = await store.runners([name])
    return _pool_response(
        pool, await _org_slugs(db, pool['organization_ids']), runners, None
    )


@harness_router.delete('/pools/{name}', status_code=204)
async def delete_harness_pool(
    name: str,
    store: harness.Store,
    _auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(_require_write)
    ],
) -> None:
    """Delete a runner pool with no live runner.

    Raises:
        403: Not a platform administrator.
        404: No such pool.
        409: ``pool_in_use``: a runner of the pool is not offline.

    """
    try:
        deleted = await store.delete_pool(name)
    except harness.PoolInUse as err:
        raise _conflict(
            'pool_in_use', f'Pool {name!r} has runners that are not offline'
        ) from err
    if not deleted:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Pool {name!r} not found'
        )


@harness_router.post(
    '/runners', status_code=201, response_model=RunnerRegistered
)
async def register_harness_runner(
    data: RunnerRegister,
    store: harness.Store,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> RunnerRegistered:
    """Register a runner with the pool credential.

    The caller is the service account of the pool. The runner gets the
    labels and the organization allowlist of the pool. Keep the
    returned credentials: they are not shown again.

    Raises:
        403: ``pool_forbidden``: the caller is not the service account
            of the pool, or there is no such pool.

    """
    pool = await store.pool(data.pool)
    account = auth.service_account
    if (
        pool is None
        or account is None
        # The id, not the slug: a new service account can take the
        # slug of a deleted one.
        or account.id != pool['service_account_id']
    ):
        raise autonomous.forbidden(
            'pool_forbidden',
            f'Principal {auth.principal_name!r} cannot register runners of '
            f'pool {data.pool!r}.',
        )
    runner, runner_token, executor_token = await store.register(
        pool, instance=data.instance, image_version=data.image_version
    )
    return RunnerRegistered(
        runner_id=runner['id'],
        runner_token=runner_token,
        executor_token=executor_token,
        labels=pool['labels'],
        lease_seconds=harness_store.LEASE_SECONDS,
        lease_expires_at=runner['lease_expires_at'],
    )


@harness_router.post(
    '/runners/{runner_id}/heartbeat', response_model=RunnerLease
)
async def heartbeat_harness_runner(
    runner: harness_auth.Runner, store: harness.Store
) -> RunnerLease:
    """Renew the lease of the runner.

    Raises:
        401: ``invalid_runner_credential``: the runner is lost. It
            stops every SDK instance and exits.

    """
    row = await store.heartbeat(runner['id'])
    if row is None:  # pragma: no cover - lost between the two reads
        raise fastapi.HTTPException(
            status_code=401,
            detail={
                'error': 'invalid_runner_credential',
                'message': 'The runner is not live',
            },
        )
    return RunnerLease(
        state=row['state'],
        chain_id=row['chain_id'],
        lease_seconds=harness_store.LEASE_SECONDS,
        lease_expires_at=row['lease_expires_at'],
    )


@harness_router.post(
    '/runners/{runner_id}/claim',
    response_model=Claim,
    responses={204: {'description': 'No task waits for this runner.'}},
)
async def claim_harness_task(
    runner: harness_auth.Runner,
    db: graph.Pool,
    store: harness.Store,
    tasks: agent_tasks.Store,
    wait: typing.Annotated[
        int,
        fastapi.Query(
            ge=0,
            le=MAX_CLAIM_WAIT_SECONDS,
            description='Seconds to wait for a task (long poll).',
        ),
    ] = 0,
) -> Claim | fastapi.Response:
    """Claim the oldest task that the runner may run; pin its chain.

    The task is ``queued``, its agent is enabled and under
    ``max_concurrent_tasks``, the runner has every label that the
    agent requires, and the pool serves its organization. Return the
    task, the identity bundle, and an agent token for the chain, or
    ``204`` when no task comes in ``wait`` seconds.

    Raises:
        401: ``invalid_runner_credential``.
        409: ``runner_busy``: the runner holds a chain.

    """
    if runner['state'] != 'idle':
        raise _conflict('runner_busy', 'The runner holds a chain')
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait
    while True:
        # Read the agents again on each attempt, so an agent disabled or
        # changed during the long poll is not dispatched. They are in the
        # graph, not in the claim transaction; the gap is one query.
        agents, limits = await eligible_agents(db)
        try:
            claimed = await store.claim(runner, agents, limits)
        except harness.RunnerBusy as err:
            raise _conflict('runner_busy', 'The runner holds a chain') from err
        if claimed is not None:
            delivered = await _deliver(
                db, store, tasks, runner, claimed, pinned=True
            )
            if delivered is not None:
                return delivered
            continue
        remaining = deadline - loop.time()
        if remaining <= 0:
            return fastapi.Response(status_code=204)
        await asyncio.sleep(min(CLAIM_POLL_SECONDS, remaining))


@harness_router.post(
    '/runners/{runner_id}/chain/claim',
    response_model=Claim,
    responses={204: {'description': 'No child task waits.'}},
)
async def claim_harness_child_task(
    runner: harness_auth.Runner,
    db: graph.Pool,
    store: harness.Store,
    tasks: agent_tasks.Store,
) -> Claim | fastapi.Response:
    """Claim the oldest queued child task of the runner's chain.

    Only the runner that holds a chain can claim its child tasks.

    Raises:
        401: ``invalid_runner_credential``.

    """
    while (claimed := await store.claim_child(runner)) is not None:
        delivered = await _deliver(
            db, store, tasks, runner, claimed, pinned=False
        )
        if delivered is not None:
            return delivered
    return fastapi.Response(status_code=204)


@harness_router.post(
    '/runners/{runner_id}/finish', response_model=RunnerFinished
)
async def finish_harness_runner(
    runner: harness_auth.Runner, store: harness.Store
) -> RunnerFinished:
    """End the runner. Its credentials and agent tokens stop working.

    When every task of its chain is closed, the chain is ``done``.
    Otherwise the chain is fenced as for a lost runner, and goes back
    to the queue after the fencers succeed and the grace period passes.

    Raises:
        401: ``invalid_runner_credential``.

    """
    chain = await store.finish(runner)
    return RunnerFinished(chain_state=chain['state'] if chain else None)


@harness_router.get(
    '/tasks/{short_id}/events',
    response_model=list[tasks_api.AgentTaskEventResponse],
)
async def list_harness_task_events(
    short_id: str,
    caller: harness_auth.AgentCaller,
    db: graph.Pool,
    store: agent_tasks.Store,
    after_seq: typing.Annotated[int, fastapi.Query(ge=0)] = 0,
    limit: typing.Annotated[int, fastapi.Query(ge=1, le=1000)] = 100,
) -> list[dict[str, typing.Any]]:
    """List the events of a task of the chain after ``after_seq``.

    The harness reads human input here at each turn boundary.

    Raises:
        401: Not a current agent token.
        403: Another chain or another agent.
        404: No such task.

    """
    task = await _chain_task(caller, short_id, db, store)
    if task['log_archived_at'] is not None:
        return await agent_tasks.log.archived_events(task, after_seq, limit)
    return await store.events(task['id'], after_seq, limit)


@harness_router.post(
    '/tasks/{short_id}/children',
    status_code=201,
    response_model=tasks_api.AgentTaskResponse,
    responses={
        200: {
            'model': tasks_api.AgentTaskResponse,
            'description': 'A child with this idempotency key exists.',
        },
    },
)
async def create_harness_child_task(
    short_id: str,
    data: ChildTaskCreate,
    response: fastapi.Response,
    caller: harness_auth.AgentCaller,
    db: graph.Pool,
    store: agent_tasks.Store,
    runners: harness.Store,
) -> dict[str, typing.Any]:
    """Make a child task (origin ``task``) in the chain of a task.

    The child agent must be a subagent of the parent's pinned agent
    version.

    The child has the owner and the project of its parent. Only the
    runner of the chain can claim it, so its agent must not need a
    label that the runner does not have.

    Raises:
        401: Not a current agent token.
        403: Another chain or another agent, ``subagent_forbidden`` (the
            child agent is not in the ``subagents`` of the parent's
            pinned agent version), or ``owner_forbidden`` (the owner of
            the parent can no longer make agent tasks in the
            organization).
        404: No such task.
        409: The parent is closed, the child agent is disabled, or the
            runner of the chain does not have a label that the child
            agent needs (``runner_label_missing``).
        422: No such agent, or a budget over its task budget.

    """
    parent = await _chain_task(caller, short_id, db, store)
    if parent['status'] == 'closed':
        raise _conflict('task_closed', f'Task {parent["short_id"]} is closed')
    org_slugs = await _org_slugs(db, [parent['organization_id']])
    if not await tasks_api.may_create(
        db, org_slugs.get(parent['organization_id'], ''), parent['owner']
    ):
        raise autonomous.forbidden(
            'owner_forbidden',
            f'{parent["owner"]!r} can no longer make agent tasks in the '
            'organization.',
        )
    origin_id = str(parent['id'])
    if data.idempotency_key is not None:
        existing = await store.find_by_idempotency_key(
            parent['organization_id'], 'task', origin_id, data.idempotency_key
        )
        if existing is not None:
            response.status_code = 200
            return existing
    records = await db.execute(
        _AGENT_QUERY,
        {'slug': data.agent_slug, 'org_id': parent['organization_id']},
        ['a'],
    )
    agent: typing.Any = (
        graph.parse_agtype(records[0]['a']) if records else None
    )
    if not isinstance(agent, dict):
        raise _unprocessable(f'Agent {data.agent_slug!r} not found')
    agent = typing.cast('dict[str, typing.Any]', agent)
    subagents: list[dict[str, typing.Any]] = (
        await _bundle(db, parent)
    ).snapshot.get('subagents') or []
    if str(agent['id']) not in {str(s.get('agent_id')) for s in subagents}:
        raise autonomous.forbidden(
            'subagent_forbidden',
            f'Agent {data.agent_slug!r} is not a subagent of the pinned '
            f'version of the agent of task {parent["short_id"]}.',
        )
    if not agent.get('enabled', True):
        raise _conflict(
            'agent_disabled', f'Agent {data.agent_slug!r} is disabled'
        )
    settings = _settings(agent.get('settings'))
    chain_id = parent['chain_id'] or parent['id']
    labels = await runners.runner_labels(chain_id) or []
    missing = sorted(set(settings.required_labels) - set(labels))
    if missing:
        raise _conflict(
            'runner_label_missing',
            f'The runner of the chain does not have the labels '
            f'{", ".join(missing)} that agent {data.agent_slug!r} needs',
        )
    budget = tasks_api.task_budget(settings, data.budget)
    agent_id = str(agent['id'])
    service_account_id = await agents_api.ensure_service_account(
        db, agent_id, str(agent.get('name', data.agent_slug))
    )
    agent_version = int(agent.get('version') or 1)
    prompt_version = agent.get('prompt_version')
    origin = {
        'kind': 'task',
        'task_id': origin_id,
        'short_id': parent['short_id'],
        'agent_id': parent['agent_id'],
    }
    task, created = await store.create(
        agent_tasks.NewTask(
            organization_id=parent['organization_id'],
            agent_id=agent_id,
            agent_version=agent_version,
            prompt_version=prompt_version,
            service_account_id=service_account_id,
            project_id=parent['project_id'],
            project_slug=parent['project_slug'],
            title=data.title,
            description=data.description,
            origin_kind='task',
            origin_id=origin_id,
            origin=origin,
            idempotency_key=data.idempotency_key,
            owner=parent['owner'],
            budget=budget,
            chain_id=chain_id,
        ),
        agent_tasks.Actor('agent', parent['agent_id'], 'harness'),
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


@harness_router.post(
    '/tasks/{short_id}/tool-calls/check', response_model=ToolCallVerdict
)
async def check_harness_tool_call(
    short_id: str,
    data: ToolCallCheck,
    caller: harness_auth.AgentCaller,
    db: graph.Pool,
    store: agent_tasks.Store,
    runners: harness.Store,
) -> ToolCallVerdict:
    """Count a call of a tool against its rate limit, across runners.

    The limit is ``rate_limit`` of the tool in the pinned agent
    version. A tool with no limit is allowed and not counted. A tool
    that is not configured is not allowed. A refused call is not
    counted.

    Raises:
        401: Not a current agent token.
        403: Another chain or another agent.
        404: No such task.

    """
    task = await _chain_task(caller, short_id, db, store)
    tools: dict[str, typing.Any] = (await _bundle(db, task)).snapshot.get(
        'tools'
    ) or {}
    if data.tool_key not in tools:
        return ToolCallVerdict(allowed=False, reason='tool_not_configured')
    config = models.AgentToolConfig.model_validate(tools[data.tool_key])
    if config.rate_limit is None:
        return ToolCallVerdict(allowed=True)
    limit = config.rate_limit
    allowed, count, window_start = await runners.count_tool_call(
        task['agent_id'], data.tool_key, limit.per, limit.count
    )
    return ToolCallVerdict(
        allowed=allowed,
        reason=None if allowed else 'rate_limited',
        count=count,
        limit=limit.count,
        per=limit.per,
        window_start=window_start,
    )
