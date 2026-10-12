"""Workflow definition endpoints (ADR 0021).

Definitions live in the ``workflows`` Postgres schema. Each save writes
one immutable version and moves ``latest_version``. Activation sets
``active_version``, the only version that triggers run, so a save never
changes what runs.

Activation needs a version with no validation issues, and a caller who
holds every permission that the version's steps need, so a workflow
cannot do more than the person who activated it.

Every route needs the caller to be a member of the organization
(``MEMBER_OF``): see :mod:`imbi.api.auth.organizations`. Nothing runs a
workflow yet.
"""

import datetime
import re
import typing
from collections import abc

import fastapi
import pydantic
import slugify

from imbi.api import workflows
from imbi.api.auth import organizations, permissions
from imbi.api.endpoints._helpers import conflict_on_unique_violation
from imbi.common import graph
from imbi.common.workflows import graph as wf
from imbi.common.workflows import registry, validation

OrgId = organizations.MemberOrgId

Status = typing.Literal['draft', 'active', 'paused']


# --- Schemas -----------------------------------------------------------


class WorkflowVersion(pydantic.BaseModel):
    version: int
    graph: wf.Graph
    settings: wf.Settings
    validation: wf.ValidationResult
    created_by: str
    created_at: datetime.datetime


class WorkflowSummary(pydantic.BaseModel):
    slug: str
    name: str
    description: str
    owner_team_slug: str | None = pydantic.Field(
        description='None when the owner team was deleted.'
    )
    status: Status
    latest_version: int
    active_version: int | None
    trigger_types: list[str]
    #: The agents that the latest version dispatches to. Always empty
    #: until the agent step type ships.
    agent_ids: list[str] = []
    created_at: datetime.datetime
    updated_at: datetime.datetime


class Workflow(WorkflowSummary):
    activated_by: str | None
    activated_at: datetime.datetime | None
    #: The latest version.
    version: WorkflowVersion


class WorkflowSave(pydantic.BaseModel):
    name: str = pydantic.Field(min_length=1)
    description: str = ''
    owner_team_slug: str = pydantic.Field(min_length=1)
    graph: wf.Graph = pydantic.Field(default_factory=wf.Graph)
    settings: wf.Settings = pydantic.Field(default_factory=wf.Settings)


class WorkflowCreate(WorkflowSave):
    slug: str | None = pydantic.Field(
        default=None,
        pattern=r'^[a-z0-9]+(-[a-z0-9]+)*$',
        description='Defaults to a slug of the name.',
    )


class WorkflowValidate(pydantic.BaseModel):
    graph: wf.Graph
    settings: wf.Settings = pydantic.Field(default_factory=wf.Settings)


class WorkflowActivate(pydantic.BaseModel):
    version: int | None = pydantic.Field(
        default=None, gt=0, description='Defaults to the latest version.'
    )


class StepType(pydantic.BaseModel):
    type: str
    category: typing.Literal['trigger', 'logic', 'action', 'agent']
    label: str
    description: str
    trigger: bool
    ports: list[str] | None = pydantic.Field(
        description='None: one port per entry of params.branches.'
    )
    params_schema: dict[str, typing.Any]
    output_schema: dict[str, typing.Any]
    sample_output: dict[str, typing.Any]
    side_effect: bool
    idempotent: bool
    timeout_seconds: int | None
    retries: int


# --- Helpers -----------------------------------------------------------

_TEAM_ID_QUERY: typing.LiteralString = """
MATCH (t:Team {{slug: {team}}})-[:BELONGS_TO]->(:Organization {{id: {org}}})
RETURN t.id AS id
"""

_TEAM_SLUGS_QUERY: typing.LiteralString = """
MATCH (t:Team)-[:BELONGS_TO]->(:Organization {{id: {org}}})
WHERE t.id IN {ids}
RETURN t.id AS id, t.slug AS slug
"""


async def _team_id(db: graph.Graph, org_id: str, team_slug: str) -> str:
    records = await db.execute(
        _TEAM_ID_QUERY, {'team': team_slug, 'org': org_id}, ['id']
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=422,
            detail=f'Team {team_slug!r} is not in the organization',
        )
    return str(graph.parse_agtype(records[0]['id']))


async def _team_slugs(
    db: graph.Graph, org_id: str, rows: list[workflows.Row]
) -> dict[str, str]:
    ids = sorted({str(r['owner_team_id']) for r in rows})
    if not ids:
        return {}
    records = await db.execute(
        _TEAM_SLUGS_QUERY, {'org': org_id, 'ids': ids}, ['id', 'slug']
    )
    return {
        str(graph.parse_agtype(r['id'])): str(graph.parse_agtype(r['slug']))
        for r in records
    }


#: For each kind of resource that a step names by id: the ids in
#: ``ids`` that are in the organization.
_ORG_RESOURCE_QUERIES: dict[str, typing.LiteralString] = {
    'project': """
MATCH (r:Project)-[:OWNED_BY]->(:Team)-[:BELONGS_TO]->
      (:Organization {{id: {org}}})
WHERE r.id IN {ids}
RETURN DISTINCT r.id AS id
""",
    'webhook': """
MATCH (r:Webhook)-[:BELONGS_TO]->(:Organization {{id: {org}}})
WHERE r.id IN {ids}
RETURN r.id AS id
""",
    'team': """
MATCH (r:Team)-[:BELONGS_TO]->(:Organization {{id: {org}}})
WHERE r.id IN {ids}
RETURN r.id AS id
""",
    'user': """
MATCH (r:User)-[:MEMBER_OF]->(:Organization {{id: {org}}})
WHERE r.id IN {ids}
RETURN r.id AS id
""",
}

_TEAM_MEMBER_QUERY: typing.LiteralString = """
MATCH (u:User {{email: {email}}})-[:MEMBER_OF]->(t:Team {{id: {team}}})
RETURN t.id AS id
"""


#: A resource id param may be one plain reference to a run-time value:
#: ``trigger`` or a node key, then one or more attribute names. No
#: filters, calls, literals, or other text, so it cannot hide a literal
#: id from the organization check.
_PLAIN_REFERENCE = re.compile(
    r'\{\{\s*[a-z][a-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+\s*\}\}'
)

#: Jinja delimiters. A value with none of them renders to itself.
_TEMPLATE_MARKERS = ('{{', '{%', '{#')

#: Resource kinds that must be a literal id, because activation binds
#: them before any run.
_LITERAL_ONLY = frozenset({'webhook'})


def _resource_ids(
    wf_graph: wf.Graph,
) -> tuple[dict[str, list[tuple[str, str]]], list[tuple[str, str]]]:
    """Return the literal resource ids in step params, and bad templates.

    The ids are by kind, each entry (node id, resource id). A plain
    reference is left out: the engine checks its value when the step
    runs. Any other template is returned as (node id, kind), because
    it could render to an id from another organization.
    """
    found: dict[str, list[tuple[str, str]]] = {}
    invalid: list[tuple[str, str]] = []

    def add(kind: str, node_id: str, value: typing.Any) -> None:
        if not isinstance(value, str) or not value:
            return
        if not any(m in value for m in _TEMPLATE_MARKERS):
            found.setdefault(kind, []).append((node_id, value))
        elif kind in _LITERAL_ONLY or not _PLAIN_REFERENCE.fullmatch(value):
            invalid.append((node_id, kind))

    for node in wf_graph.nodes:
        params = node.params
        if node.type in ('deploy', 'rollback'):
            add('project', node.id, params.get('project_id'))
        elif node.type == 'webhook':
            add('webhook', node.id, params.get('webhook_id'))
        elif node.type == 'email':
            raw: typing.Any = params.get('to')
            if not isinstance(raw, list):
                continue
            for recipient in typing.cast(abc.Iterable[typing.Any], raw):
                if isinstance(recipient, dict):
                    item = typing.cast(dict[str, typing.Any], recipient)
                    if item.get('kind') in ('user', 'team'):
                        add(str(item['kind']), node.id, item.get('id'))
    return found, invalid


async def _validate(
    db: graph.Graph,
    org_id: str,
    wf_graph: wf.Graph,
    settings: wf.Settings,
) -> wf.ValidationResult:
    """Return the issues of a graph, with the checks that need the org.

    A literal id in step params must name a resource in the org: a
    project, a gateway Webhook, a team, or a user who is a member. AI
    models are a global catalog, so ``model_id`` is not checked here.
    One graph query runs for each kind of resource.
    """
    result = validation.validate(wf_graph, settings)
    if any(i.code in validation.LIMIT_CODES for i in result.issues):
        return result
    found, invalid = _resource_ids(wf_graph)
    for node_id, kind in invalid:
        result.issues.append(
            wf.ValidationIssue(
                severity='error',
                code='invalid_reference',
                message=(
                    f'The {kind} id must be a literal id'
                    if kind in _LITERAL_ONLY
                    else f'The {kind} id must be a literal id or one '
                    'reference such as {{ trigger.project }}'
                ),
                node_id=node_id,
            )
        )
    for kind, refs in found.items():
        records = await db.execute(
            _ORG_RESOURCE_QUERIES[kind],
            {'org': org_id, 'ids': sorted({value for _, value in refs})},
            ['id'],
        )
        known = {str(graph.parse_agtype(r['id'])) for r in records}
        for node_id, value in refs:
            if value not in known:
                result.issues.append(
                    wf.ValidationIssue(
                        severity='error',
                        code='resource_not_in_organization',
                        message=f'No {kind} {value!r} in the organization',
                        node_id=node_id,
                    )
                )
    return result


def _version(row: workflows.Row) -> dict[str, typing.Any]:
    return {
        'version': row['version'],
        'graph': row['graph'],
        'settings': row['settings'],
        'validation': row['validation'],
        'created_by': row['created_by'],
        'created_at': row['created_at'],
    }


def _trigger_types(wf_graph: dict[str, typing.Any]) -> list[str]:
    found: list[str] = []
    for node in wf_graph.get('nodes', []):
        step = registry.STEP_TYPES.get(node.get('type'))
        if step is not None and step.trigger and step.type not in found:
            found.append(step.type)
    return found


def _workflow(
    row: workflows.Row, team_slugs: dict[str, str]
) -> dict[str, typing.Any]:
    return {
        **row,
        'owner_team_slug': team_slugs.get(row['owner_team_id']),
        'trigger_types': _trigger_types(row['graph']),
        'agent_ids': [],
        'version': _version(
            {
                **row,
                'version': row['latest_version'],
                'created_by': row['version_created_by'],
                'created_at': row['version_created_at'],
            }
        ),
    }


async def _get(
    store: workflows.WorkflowStore,
    db: graph.Graph,
    org_id: str,
    slug: str,
) -> dict[str, typing.Any]:
    row = await store.get(org_id, slug)
    if row is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Workflow {slug!r} not found'
        )
    return _workflow(row, await _team_slugs(db, org_id, [row]))


async def _definition(
    db: graph.Graph,
    org_id: str,
    data: WorkflowSave,
    auth: permissions.AuthContext,
) -> workflows.Definition:
    """Validate a save. A graph over the size limits is refused.

    Raises:
        422: The graph is too large, or the team is not in the org.

    """
    result = await _validate(db, org_id, data.graph, data.settings)
    limits = [i for i in result.issues if i.code in validation.LIMIT_CODES]
    if limits:
        raise fastapi.HTTPException(
            status_code=422, detail=[i.model_dump() for i in limits]
        )
    return workflows.Definition(
        name=data.name,
        description=data.description,
        owner_team_id=await _team_id(db, org_id, data.owner_team_slug),
        graph=data.graph.model_dump(mode='json'),
        settings=data.settings.model_dump(mode='json'),
        validation=result.model_dump(mode='json'),
        author=auth.principal_name,
    )


# --- Endpoints ---------------------------------------------------------

workflows_router = fastapi.APIRouter(
    tags=['Workflows'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)

step_types_router = fastapi.APIRouter(
    tags=['Workflows'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)


ReadAuth = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('workflow:read')),
]
CreateAuth = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('workflow:create')),
]
WriteAuth = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('workflow:write')),
]
DeleteAuth = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('workflow:delete')),
]


@step_types_router.get('/', response_model=list[StepType])
async def list_step_types(
    _: ReadAuth,
) -> list[dict[str, typing.Any]]:
    """Return the step types that a workflow can use."""
    return [step.describe() for step in registry.STEP_TYPES.values()]


@workflows_router.get('/', response_model=list[WorkflowSummary])
async def list_workflows(
    org_id: OrgId,
    db: graph.Pool,
    store: workflows.Store,
    _: ReadAuth,
) -> list[dict[str, typing.Any]]:
    rows = await store.list_all(org_id)
    team_slugs = await _team_slugs(db, org_id, rows)
    return [_workflow(row, team_slugs) for row in rows]


@workflows_router.post('/', status_code=201, response_model=Workflow)
async def create_workflow(
    org_id: OrgId,
    data: WorkflowCreate,
    db: graph.Pool,
    store: workflows.Store,
    auth: CreateAuth,
) -> dict[str, typing.Any]:
    """Make a workflow in ``draft`` with its version 1.

    Raises:
        409: The slug is in use in the org.
        422: The graph is too large, or the team is not in the org.

    """
    slug = data.slug or slugify.slugify(data.name)
    definition = await _definition(db, org_id, data, auth)
    with conflict_on_unique_violation(f'Workflow {slug!r} already exists'):
        await store.create(org_id, slug, definition)
    return await _get(store, db, org_id, slug)


@workflows_router.get('/{slug}', response_model=Workflow)
async def get_workflow(
    org_id: OrgId,
    slug: str,
    db: graph.Pool,
    store: workflows.Store,
    _: ReadAuth,
) -> dict[str, typing.Any]:
    return await _get(store, db, org_id, slug)


@workflows_router.put('/{slug}', response_model=Workflow)
async def save_workflow(
    org_id: OrgId,
    slug: str,
    data: WorkflowSave,
    db: graph.Pool,
    store: workflows.Store,
    auth: WriteAuth,
) -> dict[str, typing.Any]:
    """Save a new version. The active version does not change.

    The version is stored with its validation issues.

    Only an admin or a member of the current owner team can change the
    owner team, because the owner team controls the runs.

    Raises:
        403: ``owner_team_forbidden``: the caller changes the owner team
            and is not an admin or a member of the current owner team.
        404: No such workflow.
        409: ``conflict``: the workflow changed owner team or was
            deleted between the check and the save.
        422: The graph is too large, or the team is not in the org.

    """
    current = await store.get(org_id, slug)
    if current is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Workflow {slug!r} not found'
        )
    definition = await _definition(db, org_id, data, auth)
    if (
        definition.owner_team_id != current['owner_team_id']
        and not auth.is_admin
        and not (
            auth.user is not None
            and await db.execute(
                _TEAM_MEMBER_QUERY,
                {'email': auth.user.email, 'team': current['owner_team_id']},
                ['id'],
            )
        )
    ):
        raise fastapi.HTTPException(
            status_code=403,
            detail={
                'error': 'owner_team_forbidden',
                'message': 'Only an admin or a member of the current owner '
                'team can change the owner team',
            },
        )
    if not await store.save(
        org_id, slug, definition, current['owner_team_id']
    ):
        raise fastapi.HTTPException(
            status_code=409,
            detail={
                'error': 'conflict',
                'message': f'Workflow {slug!r} changed or was deleted '
                'during the save; read it again and retry',
            },
        )
    return await _get(store, db, org_id, slug)


@workflows_router.delete('/{slug}', status_code=204)
async def delete_workflow(
    org_id: OrgId,
    slug: str,
    store: workflows.Store,
    runs: workflows.Runs,
    _: DeleteAuth,
) -> None:
    """Delete a workflow that has no open runs.

    Raises:
        404: No such workflow.
        409: A run of the workflow is queued or running.

    """
    row = await store.get(org_id, slug)
    if row is not None and await runs.has_open_runs(row['id']):
        raise fastapi.HTTPException(
            status_code=409, detail=f'Workflow {slug!r} has open runs'
        )
    if not await store.delete(org_id, slug):
        raise fastapi.HTTPException(
            status_code=404, detail=f'Workflow {slug!r} not found'
        )


@workflows_router.get('/{slug}/versions', response_model=list[WorkflowVersion])
async def list_workflow_versions(
    org_id: OrgId,
    slug: str,
    db: graph.Pool,
    store: workflows.Store,
    _: ReadAuth,
) -> list[dict[str, typing.Any]]:
    """Return the versions of a workflow, newest first."""
    rows = await store.versions(org_id, slug)
    if not rows:
        await _get(store, db, org_id, slug)  # 404 for no workflow
    return [_version(row) for row in rows]


@workflows_router.get(
    '/{slug}/versions/{version}', response_model=WorkflowVersion
)
async def get_workflow_version(
    org_id: OrgId,
    slug: str,
    version: int,
    store: workflows.Store,
    _: ReadAuth,
) -> dict[str, typing.Any]:
    row = await store.version(org_id, slug, version)
    if row is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Workflow {slug!r} has no version {version}',
        )
    return _version(row)


@workflows_router.post('/{slug}/validate', response_model=wf.ValidationResult)
async def validate_workflow(
    org_id: OrgId,
    data: WorkflowValidate,
    db: graph.Pool,
    _: ReadAuth,
) -> wf.ValidationResult:
    """Return the issues of a graph. Nothing is written."""
    return await _validate(db, org_id, data.graph, data.settings)


@workflows_router.post('/{slug}/activate', response_model=Workflow)
async def activate_workflow(
    org_id: OrgId,
    slug: str,
    db: graph.Pool,
    store: workflows.Store,
    auth: WriteAuth,
    data: WorkflowActivate | None = None,
) -> dict[str, typing.Any]:
    """Make a version the active version.

    The version is validated again, because the step types can change
    after a save.

    Raises:
        403: ``missing_permissions``: the caller does not hold every
            permission that the steps of the version need.
        404: No such workflow or version.
        422: ``validation_failed``: the version has issues.

    """
    workflow = await _get(store, db, org_id, slug)
    number = (data.version if data else None) or workflow['latest_version']
    row = await store.version(org_id, slug, number)
    if row is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Workflow {slug!r} has no version {number}',
        )
    wf_graph = wf.Graph.model_validate(row['graph'])
    result = await _validate(
        db, org_id, wf_graph, wf.Settings.model_validate(row['settings'])
    )
    if result.issues:
        raise fastapi.HTTPException(
            status_code=422,
            detail={
                'error': 'validation_failed',
                'issues': [i.model_dump() for i in result.issues],
            },
        )
    required: set[str] = set()
    for node in wf_graph.nodes:
        step = registry.STEP_TYPES[node.type]
        required |= step.required_permissions(node.params)
    missing = set[str]() if auth.is_admin else required - auth.permissions
    if missing:
        raise fastapi.HTTPException(
            status_code=403,
            detail={
                'error': 'missing_permissions',
                'permissions': sorted(missing),
            },
        )
    await store.activate(org_id, slug, number, auth.principal_name)
    return await _get(store, db, org_id, slug)


@workflows_router.post('/{slug}/pause', response_model=Workflow)
async def pause_workflow(
    org_id: OrgId,
    slug: str,
    db: graph.Pool,
    store: workflows.Store,
    _: WriteAuth,
) -> dict[str, typing.Any]:
    """Pause an active workflow. Its triggers start no runs.

    Raises:
        404: No such workflow.
        409: The workflow is not active.

    """
    workflow = await _get(store, db, org_id, slug)
    if workflow['status'] != 'active':
        raise fastapi.HTTPException(
            status_code=409, detail=f'Workflow {slug!r} is not active'
        )
    await store.pause(org_id, slug)
    return await _get(store, db, org_id, slug)
