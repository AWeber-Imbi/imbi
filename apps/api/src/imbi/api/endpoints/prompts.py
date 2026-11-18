"""Global prompt CMS: prompts, immutable versions, and labels.

A :class:`~imbi.common.models.Prompt` is addressed by
``namespace/slug``, unique across the installation. Prompts are global
because their consumers (the assistant, the slackbot) serve every
organization. Only rendering takes an organization, because the
``project()`` template provider reads organization data. Its body, model,
and parameters live on immutable
:class:`~imbi.common.models.PromptVersion` nodes numbered from 1. A
label is a movable pointer to one version; consumers resolve
``namespace/slug@label`` (or ``@n``) and may ask the API to render the
template with their variables.

The CMS does not know who consumes a prompt. Grouping by namespace is
a convention only.
"""

import asyncio
import datetime
import decimal
import hashlib
import json
import logging
import re
import typing
import uuid

import fastapi
import psycopg
import pydantic
import slugify
from psycopg.types import json as pg_json

from imbi.api import model_calls, secret_broker, workflows
from imbi.api.agent_tasks import store as task_store
from imbi.api.auth import organizations, permissions
from imbi.api.endpoints import ai_providers, projects
from imbi.api.endpoints._helpers import (
    caller_org_slugs,
    conflict_on_unique_violation,
)
from imbi.api.graph_sql import escape_prop, props_template, set_clause
from imbi.api.llm import generate as model_generate
from imbi.common import graph, models, relational
from imbi.common import patch as json_patch
from imbi.common.auth import permissions as common_permissions
from imbi.common.auth.encryption import decrypt_config_value
from imbi.common.graph import cypher as graph_cypher
from imbi.common.llm import drivers, generate, typesafe
from imbi.common.prompts import rendering
from imbi.common.prompts import resolve as prompt_resolve
from imbi.common.workflows.registry import agent, llm_call

LOGGER = logging.getLogger(__name__)

prompts_router = fastapi.APIRouter(prefix='/prompts', tags=['Prompts'])

#: Mounted under ``/organizations/{org_slug}/prompts``.
prompt_render_router = fastapi.APIRouter(tags=['Prompts'])

#: Prompt fields a JSON Patch may change. Labels and the default label
#: change only through the ``promote`` endpoints.
_PATCHABLE_FIELDS: tuple[str, ...] = (
    'name',
    'slug',
    'namespace',
    'description',
    'icon',
    'type',
)

_READONLY_PATHS: frozenset[str] = json_patch.READONLY_PATHS | frozenset(
    [
        '/default_label',
        '/kind',
        '/labels',
        '/latest_version',
        '/ref',
    ]
)

#: Prompt properties stored as JSON strings.
_PROMPT_JSON_FIELDS: tuple[str, ...] = ('labels',)

#: Version properties stored as JSON strings.
_VERSION_JSON_FIELDS: tuple[str, ...] = (
    'messages',
    'tools',
    'params',
    'variable_schema',
    'questions',
    'eval_summary',
)

_PROVIDER_NAMES = rendering.PROVIDER_NAMES

#: Serializes timestamps the way ``model_dump(mode='json')`` stores
#: them, so a stored value compares equal to a value read back.
_DATETIME: pydantic.TypeAdapter[datetime.datetime | None] = (
    pydantic.TypeAdapter(datetime.datetime | None)
)


# --- Wire models -------------------------------------------------------


class PromptVersionContent(pydantic.BaseModel):
    """The fields that make up one version.

    ``content_sha256`` covers all of them, so two versions with the
    same content have the same hash.
    """

    system: str = ''
    messages: list[models.PromptMessage] = []
    tools: list[dict[str, typing.Any]] = []
    model: str | None = None
    params: models.PromptParams = pydantic.Field(
        default_factory=models.PromptParams
    )
    variable_schema: dict[str, models.PromptVariable] = {}
    #: Decision prompts only.
    state: str = ''
    #: Decision prompts only.
    questions: dict[models.DecisionQuestionId, models.DecisionQuestion] = {}


class PromptVersionCreate(PromptVersionContent):
    """Request body for saving a new version."""

    summary: str | None = pydantic.Field(default=None, max_length=500)


class PromptCreate(pydantic.BaseModel):
    """Request body for a new prompt and its first version."""

    namespace: models.PromptName
    name: str = pydantic.Field(min_length=1)
    slug: models.PromptName | None = None
    description: str | None = None
    icon: str | None = None
    type: str | None = None
    kind: models.PromptKind = 'generative'
    default_label: models.PromptName = 'stable'
    version: PromptVersionCreate = pydantic.Field(
        default_factory=PromptVersionCreate
    )


class PromptResponse(pydantic.BaseModel):
    """A prompt with its labels and newest version number."""

    id: str
    namespace: str
    slug: str
    ref: str
    name: str
    description: str | None = None
    icon: str | None = None
    type: str | None = None
    kind: models.PromptKind = 'generative'
    default_label: str
    labels: list[models.PromptLabel] = []
    latest_version: int = 0
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    archived_at: datetime.datetime | None = None


class PromptVersionResponse(PromptVersionContent):
    """One immutable version."""

    id: str
    ref: str
    n: int
    summary: str | None = None
    model_id: str | None = None
    content_sha256: str
    eval_summary: dict[str, typing.Any] | None = None
    created_by: str
    created_at: datetime.datetime
    #: Labels that point at this version now.
    labels: list[str] = []


class LabelUpdate(pydantic.BaseModel):
    """Request body that points a label at a version."""

    version: int = pydantic.Field(gt=0)


class DefaultLabelUpdate(pydantic.BaseModel):
    """Request body that sets the default label."""

    label: models.PromptName


class EvalMetric(pydantic.BaseModel):
    label: str
    value: str
    delta: str | None = None


class EvalSummary(pydantic.BaseModel):
    """The cached result of the latest evaluation of a version.

    The evaluation system owns the full run. This is a summary for
    display and never gates a promotion.
    """

    verdict: typing.Literal['pass', 'fail', 'mixed']
    run_id: str | None = None
    summary: str | None = None
    metrics: list[EvalMetric] = []
    evaluated_at: datetime.datetime = pydantic.Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )


class Resolution(pydantic.BaseModel):
    """The version a reference resolves to."""

    ref: str
    #: The label used, or ``None`` when the reference named a version.
    label: str | None
    version: PromptVersionResponse


class RenderRequest(pydantic.BaseModel):
    ref: str
    variables: dict[str, typing.Any] = {}


class RenderResponse(pydantic.BaseModel):
    """A prompt ready to send to a model.

    A ``generative`` prompt fills ``system``, ``messages``, and
    ``tools``; a ``decision`` prompt fills ``state`` and ``questions``.
    """

    model_config = pydantic.ConfigDict(protected_namespaces=())

    ref: str
    label: str | None
    n: int
    kind: models.PromptKind = 'generative'
    content_sha256: str
    model: str | None
    model_id: str | None
    params: models.PromptParams
    system: str
    messages: list[models.PromptMessage]
    tools: list[dict[str, typing.Any]]
    #: Decision prompts: an object or array when the state renders to
    #: JSON, else the text.
    state: typing.Any = None
    questions: dict[str, models.DecisionQuestion] = {}


class RunDraft(pydantic.BaseModel):
    """Unsaved version content of an existing prompt, to run as is."""

    namespace: str
    slug: str
    version: PromptVersionContent


class RunRequest(pydantic.BaseModel):
    """Run a prompt: a saved version (``ref``) or a draft."""

    ref: str | None = None
    draft: RunDraft | None = None
    variables: dict[str, typing.Any] = {}
    #: Generative prompts: the fields of a structured answer.
    output_fields: list[agent.OutputField] = pydantic.Field(
        default=[], max_length=agent.MAX_FIELDS
    )

    @pydantic.field_validator('output_fields')
    @classmethod
    def _check_output_fields(
        cls, fields: list[agent.OutputField]
    ) -> list[agent.OutputField]:
        return agent.check_output_fields(fields)

    @pydantic.model_validator(mode='after')
    def _one_source(self) -> typing.Self:
        if (self.ref is None) == (self.draft is None):
            raise ValueError('Send exactly one of ref or draft')
        return self


class RunRequestBody(pydantic.BaseModel):
    """The request sent to the decision model."""

    state: typing.Any
    questions: dict[str, typing.Any]


class RunResponse(pydantic.BaseModel):
    """The result of one run.

    A decision run fills ``request`` and ``answers``. A generative run
    fills ``text``, ``result`` (with ``output_fields`` only),
    ``content_sha256``, ``cost_usd``, and ``call_id``.
    """

    model_config = pydantic.ConfigDict(protected_namespaces=())

    ref: str
    #: The version run, or ``None`` for a draft.
    n: int | None
    model: str
    model_id: str
    request: RunRequestBody | None = None
    answers: dict[str, typing.Any] = {}
    #: Generative runs: ``input_tokens`` and ``output_tokens``, each
    #: ``None`` when the provider did not tell.
    usage: dict[str, typing.Any]
    content_sha256: str | None = None
    text: str | None = None
    result: dict[str, typing.Any] | None = None
    #: From the catalog prices; ``None`` when a price or a count is
    #: unknown.
    cost_usd: float | None = None
    #: The ``ai_runtime.ai_model_calls`` row of the call.
    call_id: uuid.UUID | None = None


# --- Queries -----------------------------------------------------------

_PROMPT_QUERY = prompt_resolve.PROMPT_QUERY

_LIST_QUERY: typing.LiteralString = """
MATCH (p:Prompt)
WHERE p.archived_at IS NULL
OPTIONAL MATCH (v:PromptVersion)-[:VERSION_OF]->(p)
RETURN p, max(v.n) AS latest
"""

_LIST_NAMESPACE_QUERY: typing.LiteralString = """
MATCH (p:Prompt {{namespace: {namespace}}})
WHERE p.archived_at IS NULL
OPTIONAL MATCH (v:PromptVersion)-[:VERSION_OF]->(p)
RETURN p, max(v.n) AS latest
"""

_VERSION_QUERY = prompt_resolve.VERSION_QUERY

_VERSIONS_QUERY: typing.LiteralString = """
MATCH (v:PromptVersion)-[:VERSION_OF]->(:Prompt {{id: {prompt_id}}})
RETURN v
"""

_MODEL_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{slug: {slug}}})
RETURN m.model_id AS model_id, m.enabled AS enabled,
       m.model_type AS model_type
"""

_RUN_MODEL_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{slug: {slug}}})-[:SERVED_BY]->(p:AIProvider)
RETURN m.model_id AS model_id, m.enabled AS enabled,
       m.model_type AS model_type, m.kind AS kind, p.id AS provider_id,
       m.access_scope AS access_scope,
       m.supports_structured_output AS structured,
       m.supports_forced_tool_choice AS forced_tool_choice,
       m.input_cost_per_million AS input_cost,
       m.output_cost_per_million AS output_cost,
       m.cache_read_cost_per_million AS cache_read_cost
"""
_RUN_MODEL_COLUMNS = [
    'model_id',
    'enabled',
    'model_type',
    'kind',
    'provider_id',
    'access_scope',
    'structured',
    'forced_tool_choice',
    'input_cost',
    'output_cost',
    'cache_read_cost',
]

_DELETE_VERSIONS_QUERY: typing.LiteralString = """
MATCH (v:PromptVersion)-[:VERSION_OF]->(p:Prompt {{id: {id}}})
DETACH DELETE v
"""

_DELETE_PROMPT_QUERY: typing.LiteralString = """
MATCH (p:Prompt {{id: {id}}})
DETACH DELETE p
RETURN 1 AS deleted
"""

#: The prompts of an organization that is deleted go with it, so that
#: a later organization with the same slug does not get them. The
#: slug is read in the delete transaction, matched by id.
_DELETE_ORG_VERSIONS_QUERY: typing.LiteralString = """
MATCH (o:Organization {{id: {org_id}}})
MATCH (v:PromptVersion)-[:VERSION_OF]->(p:Prompt)
WHERE p.namespace IN {namespaces} AND p.slug STARTS WITH (o.slug + '.')
DETACH DELETE v
"""

_DELETE_ORG_PROMPTS_QUERY: typing.LiteralString = """
MATCH (o:Organization {{id: {org_id}}})
MATCH (p:Prompt)
WHERE p.namespace IN {namespaces} AND p.slug STARTS WITH (o.slug + '.')
DETACH DELETE p
"""

#: An organization rename moves its prompts and the references to them
#: from ``<old>.`` to ``<new>.``. Version numbers do not change. It
#: returns the ``namespace/slug`` that each moved prompt had.
_MOVE_ORG_PROMPTS_QUERY: typing.LiteralString = """
MATCH (p:Prompt)
WHERE p.namespace IN {namespaces} AND p.slug STARTS WITH {old}
WITH p, p.namespace + '/' + p.slug AS key
SET p.slug = {new} + substring(p.slug, {cut})
RETURN key
"""

_ORG_ID_QUERY: typing.LiteralString = (
    'MATCH (o:Organization {{slug: {slug}}}) RETURN o.id AS id'
)

#: The first statement of a rename into an organization's prefix
#: (:func:`patch_prompt`): the organization still has that slug.
_ORG_GUARD_QUERY: typing.LiteralString = (
    'MATCH (o:Organization {{id: {org_id}, slug: {org_slug}}})'
    ' RETURN o.id AS id'
)

_AGENT_REFS_QUERY: typing.LiteralString = """
MATCH (a:Agent)-[:BELONGS_TO]->(:Organization {{id: {org_id}}})
WHERE a.prompt_ref IS NOT NULL
RETURN a.id AS id, a.prompt_ref AS ref
"""

_SET_AGENT_REF_QUERY: typing.LiteralString = """
MATCH (a:Agent {{id: {id}}})
SET a.prompt_ref = {ref}
"""

_AGENT_VERSIONS_QUERY: typing.LiteralString = """
MATCH (v:AgentVersion)-[:VERSION_OF]->(:Agent)
      -[:BELONGS_TO]->(:Organization {{id: {org_id}}})
RETURN v.agent_id AS agent_id, v.n AS n, v.snapshot AS snapshot
"""

_SET_AGENT_SNAPSHOT_QUERY: typing.LiteralString = """
MATCH (v:AgentVersion {{agent_id: {agent_id}, n: {n}}})
SET v.snapshot = {snapshot}
"""

#: Labels change by read, modify, write. The ``updated_at`` match makes
#: the write fail when another write came first, instead of losing it.
_SET_LABELS_QUERY: typing.LiteralString = """
MATCH (p:Prompt {{id: {id}}})
WHERE p.updated_at = {expected_updated_at}
SET p.labels = {labels},
    p.default_label = {default_label},
    p.updated_at = {updated_at}
RETURN p
"""

_ARCHIVE_QUERY: typing.LiteralString = """
MATCH (p:Prompt {{namespace: {namespace}}})
WHERE p.archived_at IS NULL AND p.slug STARTS WITH {prefix}
  AND NOT (p.slug IN {keep})
SET p.archived_at = {now}, p.updated_at = {now}
RETURN p.slug AS slug
"""

_RESTORE_QUERY: typing.LiteralString = """
MATCH (p:Prompt {{namespace: {namespace}}})
WHERE p.archived_at IS NOT NULL AND p.slug IN {keep}
SET p.archived_at = NULL, p.updated_at = {now}
RETURN p.slug AS slug
"""

_UNARCHIVE_QUERY: typing.LiteralString = """
MATCH (p:Prompt {{id: {id}}})
SET p.archived_at = NULL, p.updated_at = {now}
RETURN p
"""

_SET_EVAL_QUERY: typing.LiteralString = """
MATCH (v:PromptVersion {{prompt_id: {prompt_id}, n: {n}}})
      -[:VERSION_OF]->(:Prompt {{id: {prompt_id}}})
SET v.eval_summary = {eval_summary}
RETURN v
"""


# --- Helpers -----------------------------------------------------------


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


_props = prompt_resolve.vertex_props
_parse_prompt = prompt_resolve.parse_prompt
_parse_version = prompt_resolve.parse_version


def _to_json_props(
    props: dict[str, typing.Any], fields: tuple[str, ...]
) -> dict[str, typing.Any]:
    """Store nested values as JSON strings, as Apache AGE needs."""
    return {
        k: json.dumps(v) if k in fields and v is not None else v
        for k, v in props.items()
    }


def _prompt_response(prompt: models.Prompt, latest: int) -> PromptResponse:
    return PromptResponse(
        id=prompt.id,
        namespace=prompt.namespace,
        slug=prompt.slug,
        ref=f'{prompt.namespace}/{prompt.slug}',
        name=prompt.name,
        description=prompt.description,
        icon=None if prompt.icon is None else str(prompt.icon),
        type=prompt.type,
        kind=prompt.kind,
        default_label=prompt.default_label,
        labels=sorted(prompt.labels, key=lambda label: label.name),
        latest_version=latest,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
        archived_at=prompt.archived_at,
    )


def _version_response(
    version: models.PromptVersion, prompt: models.Prompt
) -> PromptVersionResponse:
    return PromptVersionResponse(
        id=version.id,
        ref=f'{prompt.namespace}/{prompt.slug}@{version.n}',
        n=version.n,
        summary=version.summary,
        system=version.system,
        messages=version.messages,
        tools=version.tools,
        model=version.model,
        model_id=version.model_id,
        params=version.params,
        variable_schema=version.variable_schema,
        state=version.state,
        questions=version.questions,
        content_sha256=version.content_sha256,
        eval_summary=version.eval_summary,
        created_by=version.created_by,
        created_at=version.created_at,
        labels=sorted(
            label.name for label in prompt.labels if label.version == version.n
        ),
    )


def content_sha256(content: PromptVersionContent) -> str:
    """Hash the canonical JSON of a version's content.

    Empty decision fields are left out, so a generative version hashes
    as it did before decision prompts existed and an unchanged save
    stays a no-op.
    """
    document = PromptVersionContent.model_validate(
        content.model_dump()
    ).model_dump(mode='json')
    for key in ('state', 'questions'):
        if not document[key]:
            del document[key]
    canonical = json.dumps(document, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _unprocessable(detail: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(status_code=422, detail=detail)


def _check_label_name(label: str) -> None:
    """Reject a label made only of digits.

    A reference resolves ``@<digits>`` as a version number, so such a
    label could never be resolved.
    """
    if label.isascii() and label.isdigit():
        raise _unprocessable(
            f'Label {label!r} is not valid; a label made only of digits '
            'is read as a version number'
        )


def _check_kind(
    kind: models.PromptKind, content: PromptVersionContent
) -> None:
    """Reject content that does not fit the prompt's kind."""
    if kind == 'generative':
        if content.state or content.questions:
            raise _unprocessable(
                'A generative prompt cannot have a state or questions'
            )
        return
    if content.system or content.messages or content.tools:
        raise _unprocessable(
            'A decision prompt cannot have a system prompt, messages, or tools'
        )
    if content.params.model_dump(exclude_defaults=True):
        raise _unprocessable('A decision prompt takes no model parameters')


def _check_templates(content: PromptVersionContent) -> None:
    """Reject a version whose templates or variable names are invalid."""
    sources = (
        {'system': content.system}
        | {f'messages[{i}]': m.content for i, m in enumerate(content.messages)}
        | rendering.decision_sources(content.state, content.questions)
    )
    try:
        rendering.check_syntax(sources)
        rendering.check_variable_schema(
            content.variable_schema, _PROVIDER_NAMES
        )
        rendering.check_declared(
            sources, content.variable_schema, _PROVIDER_NAMES
        )
    except rendering.RenderError as e:
        raise _unprocessable(str(e)) from e


async def _model_id_for(
    db: graph.Graph, model: str | None, kind: models.PromptKind
) -> str | None:
    """Return the catalog ``model_id`` for a model slug, or raise 422.

    The model's type must match the prompt's kind.
    """
    if model is None:
        return None
    records = await db.execute(
        _MODEL_QUERY,
        {'slug': model},
        ['model_id', 'enabled', 'model_type'],
    )
    if not records:
        raise _unprocessable(f'AI model {model!r} is not in the catalog')
    if graph.parse_agtype(records[0]['enabled']) is False:
        raise _unprocessable(f'AI model {model!r} is disabled')
    # A missing value predates model_type, when every model was
    # generative.
    model_type = graph.parse_agtype(records[0].get('model_type'))
    if (model_type or 'generative') != kind:
        raise _unprocessable(
            f'AI model {model!r} is a {model_type or "generative"} model; '
            f'a {kind} prompt needs a {kind} model'
        )
    return str(graph.parse_agtype(records[0]['model_id']))


#: The namespace of the prompts of workflow steps:
#: ``workflows/<org slug>.<workflow slug>.<node key>``. A workflow
#: version pins a version number of the prompt, so such a prompt is
#: never deleted or renamed, has no tools, and is archived (not
#: deleted) with its node. Only an organization rename moves it, with
#: the references to it (:func:`move_org_prompts`).
WORKFLOWS_NAMESPACE = llm_call.NAMESPACE

#: The namespaces whose prompts are data of one organization, and the
#: organization permission of the owner. An agent's system prompt is
#: ``agents/<org slug>.<agent slug>``.
_ORG_NAMESPACES: dict[str, str] = {
    'agents': 'agent:write',
    WORKFLOWS_NAMESPACE: 'workflow:write',
}


def _prompt_org(namespace: str, slug: str) -> str | None:
    """The organization whose data a prompt is, or ``None``.

    A prompt in :data:`_ORG_NAMESPACES` named ``<org>.<rest>`` belongs
    to ``<org>``. An older agent prompt without the prefix belongs to
    no organization.
    """
    org, dot, _ = slug.partition('.')
    return org if namespace in _ORG_NAMESPACES and dot else None


async def _is_owner(
    db: graph.Graph,
    auth: permissions.AuthContext,
    namespace: str,
    slug: str,
) -> bool:
    """Whether the caller has the owner permission of an organization's
    prompt (see :data:`_ORG_NAMESPACES`) in that organization."""
    return namespace in _ORG_NAMESPACES and await _has_org_permission(
        db, auth, namespace, slug, _ORG_NAMESPACES[namespace]
    )


async def _has_org_permission(
    db: graph.Graph,
    auth: permissions.AuthContext,
    namespace: str,
    slug: str,
    permission: str,
) -> bool:
    """Whether the caller has ``permission`` in the organization of an
    organization's prompt."""
    org = _prompt_org(namespace, slug)
    return org is not None and permission in (
        await organizations.org_permissions(db, auth, org)
    )


async def can_promote(
    db: graph.Graph,
    auth: permissions.AuthContext,
    namespace: str,
    slug: str,
) -> bool:
    """Whether the caller may point a label of the prompt at a version.

    ``prompt:promote`` (or an admin) may move any label. An
    organization's agent or workflow prompt is part of the agent or the
    workflow, so ``agent:write`` or ``workflow:write`` in that
    organization may also move its labels; otherwise a developer could
    change an agent's prompt but never make the agent use it.
    Membership of that organization is checked by :func:`_require_access`
    before this.
    """
    if auth.is_admin or 'prompt:promote' in auth.permissions:
        return True
    return await _is_owner(db, auth, namespace, slug)


async def _require_permission(
    db: graph.Graph,
    auth: permissions.AuthContext,
    permission: str,
    namespace: str,
    slug: str,
    workflow_permission: str = 'workflow:write',
) -> None:
    """Raise 403 unless the caller has ``permission``.

    A workflow prompt is part of the workflow, so
    ``workflow_permission`` in its organization is also enough: the
    workflow editor reads the prompt, creates it, and adds its
    versions.
    """
    if auth.is_admin or permission in auth.permissions:
        return
    if namespace == WORKFLOWS_NAMESPACE and await _has_org_permission(
        db, auth, namespace, slug, workflow_permission
    ):
        return
    raise fastapi.HTTPException(
        status_code=403, detail=f'Permission denied: {permission} required'
    )


async def _require_read(
    db: graph.Graph, auth: permissions.AuthContext, namespace: str, slug: str
) -> None:
    """Raise 403 unless the caller may read the prompt."""
    await _require_permission(
        db, auth, 'prompt:read', namespace, slug, 'workflow:read'
    )


def _check_route_org(prompt: models.Prompt, org_slug: str) -> None:
    """Raise 422 when a workflow prompt is used in another organization."""
    org = _prompt_org(prompt.namespace, prompt.slug)
    if prompt.namespace == WORKFLOWS_NAMESPACE and org != org_slug:
        raise _unprocessable(
            f'Prompt {prompt.namespace}/{prompt.slug} belongs to '
            f'organization {org!r}, not {org_slug!r}'
        )


def _check_tools(namespace: str, content: PromptVersionContent) -> None:
    """Raise 422 when a workflow prompt has tools: a workflow step
    sends no tools to the model."""
    if namespace == WORKFLOWS_NAMESPACE and content.tools:
        raise _unprocessable('A workflows prompt cannot have tools')


def _check_not_archived(prompt: models.Prompt) -> None:
    """Raise 409 when the prompt is archived."""
    if prompt.archived_at is not None:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Prompt {prompt.namespace}/{prompt.slug} is archived',
        )


def _workflow_prompt_locked() -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=409,
        detail=(
            f'A {WORKFLOWS_NAMESPACE} prompt cannot be deleted or renamed: '
            'workflow versions use it. Delete the workflow step to archive it'
        ),
    )


async def archive_prompts_except(
    execute: graph.CypherExecute, namespace: str, prefix: str, keep: list[str]
) -> None:
    """Archive each prompt of ``namespace`` whose slug starts with
    ``prefix``, except the slugs in ``keep``. Restore the archived
    prompts of ``keep``.

    An archived prompt is no longer listed and gets no new versions or
    label moves. Its versions stay, so ``ref@n`` still resolves. A
    prompt that is already archived does not change.

    """
    params = {
        'namespace': namespace,
        'prefix': prefix,
        'keep': keep,
        'now': _DATETIME.dump_python(_now(), mode='json'),
    }
    await execute(_ARCHIVE_QUERY, params, ['slug'])
    if keep:
        await execute(_RESTORE_QUERY, params, ['slug'])


async def delete_org_prompts(
    execute: graph.CypherExecute, org_id: str
) -> None:
    """Delete the prompts of an organization and their versions.

    Call this in the transaction that deletes the organization, before
    the organization node is deleted.
    """
    params = {'org_id': org_id, 'namespaces': list(_ORG_NAMESPACES)}
    await execute(_DELETE_ORG_VERSIONS_QUERY, params, [])
    await execute(_DELETE_ORG_PROMPTS_QUERY, params, [])


async def move_org_prompts(
    execute: graph.CypherExecute,
    conn: psycopg.AsyncConnection[typing.Any],
    org_id: str,
    old_slug: str,
    new_slug: str,
) -> None:
    """Move the prompts of a renamed organization to the new slug.

    The ``agents/<old>.*`` and ``workflows/<old>.*`` prompts get the
    ``<new>.`` prefix. The ``prompt_ref`` of each agent and agent
    version, and of each LLM Call node of each workflow version, moves
    with them. Pinned version numbers do not change.

    Call this in the transaction that renames the organization.

    Only a reference to a prompt that moved changes. A reference to a
    prompt that does not exist keeps its slug, so it cannot come to
    name another prompt that has the new slug already.
    """
    old, new = f'{old_slug}.', f'{new_slug}.'
    with conflict_on_unique_violation(
        f'A prompt with the {new!r} prefix already exists'
    ):
        rows = await execute(
            _MOVE_ORG_PROMPTS_QUERY,
            {
                'namespaces': list(_ORG_NAMESPACES),
                'old': old,
                'new': new,
                'cut': len(old),
            },
            ['key'],
        )
    moved_keys = {str(graph.parse_agtype(r['key'])) for r in rows}

    def moved(ref: object) -> str | None:
        """The new ``ref``, or ``None`` when its prompt did not move."""
        if not isinstance(ref, str):
            return None
        key, at, label = ref.partition('@')
        if key not in moved_keys:
            return None
        namespace, _, slug = key.partition('/')
        return f'{namespace}/{new}{slug[len(old) :]}{at}{label}'

    for row in await execute(
        _AGENT_REFS_QUERY, {'org_id': org_id}, ['id', 'ref']
    ):
        agent_ref = moved(graph.parse_agtype(row['ref']))
        if agent_ref is not None:
            await execute(
                _SET_AGENT_REF_QUERY,
                {'id': graph.parse_agtype(row['id']), 'ref': agent_ref},
                [],
            )
    for row in await execute(
        _AGENT_VERSIONS_QUERY,
        {'org_id': org_id},
        ['agent_id', 'n', 'snapshot'],
    ):
        raw = graph.parse_agtype(row['snapshot'])
        snapshot: dict[str, typing.Any] = (
            json.loads(raw) if isinstance(raw, str) else raw or {}
        )
        snapshot_ref = moved(snapshot.get('prompt_ref'))
        if snapshot_ref is not None:
            snapshot['prompt_ref'] = snapshot_ref
            await execute(
                _SET_AGENT_SNAPSHOT_QUERY,
                {
                    'agent_id': graph.parse_agtype(row['agent_id']),
                    'n': graph.parse_agtype(row['n']),
                    'snapshot': json.dumps(snapshot),
                },
                [],
            )
    cursor = await conn.execute(
        'SELECT v.workflow_id, v.version, v.graph'
        ' FROM workflows.workflow_versions AS v'
        ' JOIN workflows.workflows AS w ON w.id = v.workflow_id'
        ' WHERE w.organization_id = %s',
        (org_id,),
    )
    for workflow_id, version, wf_graph in await cursor.fetchall():
        changed = False
        for node in wf_graph.get('nodes', []):
            params: dict[str, typing.Any] = node.get('params') or {}
            node_ref = moved(params.get('prompt_ref'))
            if node.get('type') == llm_call.STEP.type and node_ref:
                params['prompt_ref'] = node_ref
                changed = True
        if changed:
            await conn.execute(
                'UPDATE workflows.workflow_versions SET graph = %s'
                ' WHERE workflow_id = %s AND version = %s',
                (pg_json.Jsonb(wf_graph), workflow_id, version),
            )


async def _require_access(
    db: graph.Graph,
    auth: permissions.AuthContext,
    namespace: str,
    slug: str,
) -> None:
    """An organization's prompt is only for its members and platform
    admins (issue #414). Others get 404, so the name is not confirmed."""
    org = _prompt_org(namespace, slug)
    if org is None or auth.is_admin:
        return
    if org not in await caller_org_slugs(db, auth):
        raise fastapi.HTTPException(
            status_code=404, detail=f'Prompt {namespace}/{slug} not found'
        )


async def _fetch_prompt(
    db: graph.Graph,
    namespace: str,
    slug: str,
    auth: permissions.AuthContext,
) -> tuple[models.Prompt, int]:
    """Read a prompt and its newest version number, or raise 404."""
    await _require_access(db, auth, namespace, slug)
    try:
        return await prompt_resolve.fetch_prompt(db, namespace, slug)
    except prompt_resolve.PromptNotFound as e:
        raise fastapi.HTTPException(status_code=404, detail=str(e)) from e


async def _fetch_version(
    db: graph.Graph, prompt: models.Prompt, n: int
) -> models.PromptVersion:
    """Read version ``n`` of a prompt, or raise 404."""
    try:
        return await prompt_resolve.fetch_version(db, prompt, n)
    except prompt_resolve.PromptNotFound as e:
        raise fastapi.HTTPException(status_code=404, detail=str(e)) from e


async def _assert_ref_free(
    db: graph.Graph,
    namespace: str,
    slug: str,
    exclude_id: str | None = None,
) -> None:
    """Raise 409 when ``namespace/slug`` is taken by another prompt."""
    records = await db.execute(
        _PROMPT_QUERY,
        {'namespace': namespace, 'slug': slug},
        ['p', 'latest'],
    )
    for record in records:
        props = _props(record['p'])
        if props and props.get('id') != exclude_id:
            raise fastapi.HTTPException(
                status_code=409,
                detail=f'Prompt {namespace}/{slug} already exists',
            )


def _version_props(
    prompt: models.Prompt,
    n: int,
    content: PromptVersionCreate,
    model_id: str | None,
    created_by: str,
) -> tuple[models.PromptVersion, dict[str, typing.Any]]:
    """Build a version node and its graph properties."""
    version = models.PromptVersion.model_validate(
        {
            **content.model_dump(),
            'prompt': prompt,
            'prompt_id': prompt.id,
            'n': n,
            'model_id': model_id,
            'content_sha256': content_sha256(content),
            'created_by': created_by,
        }
    )
    props = _to_json_props(
        version.model_dump(mode='json', exclude={'prompt'}),
        _VERSION_JSON_FIELDS,
    )
    return version, props


PROMPT_CHANGED_DETAIL = (
    'The prompt changed while this request ran; reload it and try again'
)


def labels_statement(
    prompt: models.Prompt,
    labels: list[models.PromptLabel],
    default_label: str,
) -> graph_cypher.Statement:
    """Return the statement that replaces a prompt's labels.

    The statement returns no rows when another write changed the
    prompt after ``prompt`` was read. It has ``expect_rows`` set, so a
    batch that runs it then rolls back.
    """
    return graph_cypher.Statement(
        _SET_LABELS_QUERY,
        {
            'id': prompt.id,
            'expected_updated_at': _DATETIME.dump_python(
                prompt.updated_at, mode='json'
            ),
            'labels': json.dumps(
                [label.model_dump(mode='json') for label in labels]
            ),
            'default_label': default_label,
            'updated_at': _DATETIME.dump_python(_now(), mode='json'),
        },
        expect_rows=True,
    )


def moved_labels(
    prompt: models.Prompt, label: str, version: int, updated_by: str
) -> list[models.PromptLabel]:
    """Return the prompt's labels with ``label`` pointed at ``version``.

    The label is created when the prompt does not have it.
    """
    labels = [item for item in prompt.labels if item.name != label]
    labels.append(
        models.PromptLabel(
            name=label,
            version=version,
            updated_by=updated_by,
            updated_at=_now(),
        )
    )
    return labels


async def _write_labels(
    db: graph.Graph,
    prompt: models.Prompt,
    labels: list[models.PromptLabel],
    default_label: str,
) -> models.Prompt:
    """Replace a prompt's labels, or raise 409 on a concurrent write."""
    stmt = labels_statement(prompt, labels, default_label)
    records = await db.execute(stmt.cypher, stmt.params, ['p'])
    props = _props(records[0]['p']) if records else None
    if props is None:
        raise fastapi.HTTPException(
            status_code=409, detail=PROMPT_CHANGED_DETAIL
        )
    return _parse_prompt(props)


def parse_ref(ref: str) -> tuple[str, str, str | None]:
    """Split ``namespace/slug@label`` into its parts, or raise 422."""
    try:
        return prompt_resolve.parse_ref(ref)
    except prompt_resolve.InvalidRef as e:
        raise _unprocessable(str(e)) from e


async def _resolve(
    db: graph.Graph, ref: str, auth: permissions.AuthContext
) -> tuple[models.Prompt, models.PromptVersion, str | None]:
    """Find the version a reference names, or raise 404 / 422."""
    try:
        namespace, slug, _selector = prompt_resolve.parse_ref(ref)
    except prompt_resolve.InvalidRef as e:
        raise _unprocessable(str(e)) from e
    await _require_access(db, auth, namespace, slug)
    try:
        return await prompt_resolve.resolve(db, ref)
    except prompt_resolve.InvalidRef as e:
        raise _unprocessable(str(e)) from e
    except prompt_resolve.PromptNotFound as e:
        raise fastapi.HTTPException(status_code=404, detail=str(e)) from e


# --- Prompt endpoints --------------------------------------------------


@prompts_router.get('/', response_model=list[PromptResponse])
async def list_prompts(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('prompt:read')),
    ],
    namespace: str | None = None,
) -> list[PromptResponse]:
    """List prompts, ordered by namespace and slug.

    Parameters:
        namespace: Only list prompts in this namespace.

    """
    if namespace is None:
        records = await db.execute(_LIST_QUERY, {}, ['p', 'latest'])
    else:
        records = await db.execute(
            _LIST_NAMESPACE_QUERY,
            {'namespace': namespace},
            ['p', 'latest'],
        )
    members = None if auth.is_admin else await caller_org_slugs(db, auth)
    responses: list[PromptResponse] = []
    for record in records:
        props = _props(record['p'])
        if props is None:
            continue
        prompt = _parse_prompt(props)
        org = _prompt_org(prompt.namespace, prompt.slug)
        if members is not None and org is not None and org not in members:
            continue  # Another organization's prompt (issue #414).
        latest = graph.parse_agtype(record['latest'])
        responses.append(_prompt_response(prompt, int(latest or 0)))
    return sorted(responses, key=lambda r: (r.namespace, r.slug))


@prompts_router.post('/', response_model=PromptResponse, status_code=201)
async def create_prompt(
    data: PromptCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> PromptResponse:
    """Create a prompt with its first version.

    Needs ``prompt:create``. For a ``workflows/<org>.<workflow>.<node>``
    prompt, ``workflow:write`` in ``<org>`` is also enough.

    When the caller may promote (see :func:`can_promote`), the default
    label points at version 1. Otherwise the prompt is created
    with no labels: pointing a label at a version changes what consumers
    run, and only ``promote`` may do that. Until a promote holder sets a
    label, a reference to the prompt does not resolve, and a consumer
    such as the assistant uses its packaged prompt.

    Raises:
        403: No permission.
        409: ``namespace/slug`` is taken.
        422: A template does not parse, the model is not in the
            catalog, or a workflows prompt has tools or no
            ``<org>.`` slug prefix.

    """
    slug = data.slug or ''
    await _require_access(db, auth, data.namespace, slug)
    await _require_permission(db, auth, 'prompt:create', data.namespace, slug)
    return await insert_prompt(
        db,
        data,
        auth.principal_name,
        label_first_version=await can_promote(db, auth, data.namespace, slug),
    )


async def insert_prompt(
    db: graph.Graph,
    data: PromptCreate,
    created_by: str,
    *,
    label_first_version: bool,
) -> PromptResponse:
    """Validate and write a prompt with its first version.

    ``imbi-api setup-prompts`` uses this too, so a seeded prompt is
    written exactly like one created through the API.

    Parameters:
        label_first_version: Point the default label at version 1. Only
            a caller with promote authority may do this.

    Raises:
        fastapi.HTTPException: 409 when ``namespace/slug`` is taken, 422
            when a template or the model is not valid.

    """
    slug = data.slug or slugify.slugify(data.name)
    if not re.match(models.PROMPT_NAME_PATTERN, slug):
        raise _unprocessable(f'Slug {slug!r} is not valid')
    if data.namespace == WORKFLOWS_NAMESPACE and (
        _prompt_org(data.namespace, slug) is None
    ):
        raise _unprocessable(
            'A workflows prompt slug must be <org>.<workflow>.<node>'
        )
    if data.namespace == WORKFLOWS_NAMESPACE and data.kind != 'generative':
        # An LLM Call step runs only generative prompts, and kind is
        # read-only, so a decision prompt here could never be used.
        raise _unprocessable('A workflows prompt must be generative')
    _check_label_name(data.default_label)
    _check_kind(data.kind, data.version)
    _check_tools(data.namespace, data.version)
    _check_templates(data.version)
    model_id = await _model_id_for(db, data.version.model, data.kind)
    await _assert_ref_free(db, data.namespace, slug)

    now = _now()
    prompt = models.Prompt(
        namespace=data.namespace,
        slug=slug,
        name=data.name,
        description=data.description,
        icon=data.icon,
        type=data.type,
        kind=data.kind,
        default_label=data.default_label,
        labels=(
            [
                models.PromptLabel(
                    name=data.default_label,
                    version=1,
                    updated_by=created_by,
                    updated_at=now,
                )
            ]
            if label_first_version
            else []
        ),
        created_at=now,
        updated_at=now,
    )
    prompt_props = _to_json_props(
        prompt.model_dump(mode='json'),
        _PROMPT_JSON_FIELDS,
    )
    _version, version_props = _version_props(
        prompt, 1, data.version, model_id, created_by
    )
    # Both nodes are written in one statement, so the parameter names
    # of the version are prefixed to keep them apart from the prompt's.
    # The keys are model field names, never caller input.
    version_params = {f'v_{k}': v for k, v in version_props.items()}
    version_template = (
        '{{'
        + ', '.join(f'{escape_prop(k)}: {{v_{k}}}' for k in version_props)
        + '}}'
    )
    query = (
        f'CREATE (p:Prompt {props_template(prompt_props)})'
        f' CREATE (v:PromptVersion {version_template})'
        ' CREATE (v)-[:VERSION_OF]->(p)'
        ' RETURN p'
    )
    with conflict_on_unique_violation(
        f'Prompt {data.namespace}/{slug} already exists'
    ):
        records = await db.execute(
            query,
            {**prompt_props, **version_params},
            ['p'],
        )
    if not records:
        raise fastapi.HTTPException(
            status_code=500, detail='Prompt create returned no row'
        )
    return _prompt_response(prompt, 1)


@prompts_router.get('/resolve', response_model=Resolution)
async def resolve_prompt(
    ref: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> Resolution:
    """Resolve ``namespace/slug@label`` or ``@n`` to one version.

    Raises:
        404: No such prompt, version, or usable label.
        422: The reference is not valid.

    """
    namespace, slug, _selector = parse_ref(ref)
    await _require_read(db, auth, namespace, slug)
    prompt, version, label = await _resolve(db, ref, auth)
    return Resolution(
        ref=ref, label=label, version=_version_response(version, prompt)
    )


@prompt_render_router.post('/render', response_model=RenderResponse)
async def render_prompt(
    org_slug: str,
    data: RenderRequest,
    request: fastapi.Request,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('prompt:read')),
    ],
) -> RenderResponse:
    """Resolve a reference and render it with the caller's variables.

    The ``project(project_id)`` provider returns the project as
    ``GET /projects/{id}`` does, and requires ``project:read``.

    Raises:
        403: A template calls ``project()`` without ``project:read``.
        404: No such prompt, version, label, or project.
        422: The variables do not match the version's schema, or the
            template fails.

    """
    prompt, version, label = await _resolve(db, data.ref, auth)
    _check_route_org(prompt, org_slug)
    providers = _providers(auth, db, org_slug, request)
    response = RenderResponse(
        ref=f'{prompt.namespace}/{prompt.slug}@{version.n}',
        label=label,
        n=version.n,
        kind=prompt.kind,
        content_sha256=version.content_sha256,
        model=version.model,
        model_id=version.model_id,
        params=version.params,
        system='',
        messages=[],
        tools=version.tools,
    )
    try:
        if prompt.kind == 'decision':
            decision = await rendering.render_decision(
                version, data.variables, providers
            )
            response.state = decision.state
            response.questions = decision.questions
        else:
            rendered = await rendering.render(
                version, data.variables, providers
            )
            response.system = rendered.system
            response.messages = rendered.messages
    except rendering.RenderError as e:
        raise _unprocessable(str(e)) from e
    return response


def _providers(
    auth: permissions.AuthContext,
    db: graph.Graph,
    org_slug: str,
    request: fastapi.Request,
) -> dict[str, rendering.Provider]:
    """The template providers for a render in ``org_slug``."""

    async def project(project_id: object) -> object:
        if not (auth.is_admin or 'project:read' in auth.permissions):
            raise fastapi.HTTPException(
                status_code=403,
                detail='project() requires the project:read permission',
            )
        found = await projects.fetch_project(
            db, org_slug, str(project_id), request
        )
        return found.model_dump(mode='json')

    return {'project': project}


def _wire_question(question: models.DecisionQuestion) -> dict[str, typing.Any]:
    """A question in the shape the decision API takes."""
    wire: dict[str, typing.Any] = {
        'type': question.type,
        'instructions': question.instructions,
    }
    if question.criteria is not None:
        wire['criteria'] = (
            question.criteria.model_dump()
            if isinstance(question.criteria, models.NoulCriteria)
            else question.criteria
        )
    return wire


async def _run_target(
    db: graph.Graph, data: RunRequest, auth: permissions.AuthContext
) -> tuple[models.Prompt, models.PromptVersion, int | None]:
    """The prompt and version a run uses: saved, or the draft."""
    if data.ref is not None:
        prompt, version, _label = await _resolve(db, data.ref, auth)
        return prompt, version, version.n
    draft = typing.cast('RunDraft', data.draft)
    prompt, latest = await _fetch_prompt(db, draft.namespace, draft.slug, auth)
    _check_kind(prompt.kind, draft.version)
    _check_tools(prompt.namespace, draft.version)
    _check_templates(draft.version)
    version = models.PromptVersion.model_validate(
        {
            **draft.version.model_dump(),
            'prompt': prompt,
            'prompt_id': prompt.id,
            'n': latest + 1,
            'content_sha256': content_sha256(draft.version),
            'created_by': auth.principal_name,
        }
    )
    return prompt, version, None


#: Seconds one generative model call may take.
CALL_TIMEOUT = 120.0

#: Seconds for the whole call: the workload identity token, a second
#: request with a new token after a ``401``, and the generation. It
#: expires before ``STALE_AFTER``, so the row is finished first.
CALL_DEADLINE = CALL_TIMEOUT + 45

#: A ``running`` call older than this did not finish: a repeat of its
#: idempotency key sets it to ``outcome_unknown``.
STALE_AFTER = CALL_DEADLINE + 15

#: The HTTP status and the ``retry`` flag of each error code of a
#: generative run (``detail={'error': <code>, 'retry': <bool>}``).
CALL_ERRORS: dict[str, tuple[int, bool]] = {
    'model_answer_invalid': (502, True),
    'provider_refused': (502, False),
    'credentials_failed': (502, False),
    'rate_limited': (503, True),
    'provider_unavailable': (503, True),
    'provider_unreachable': (503, True),
    'credentials_unavailable': (503, True),
    'provider_misconfigured': (409, False),
    'call_in_progress': (409, True),
    'outcome_unknown': (409, False),
    'model_unsupported': (422, False),
    'model_no_structured_output': (422, False),
    'model_not_allowed': (403, False),
}


def _call_error(code: str) -> fastapi.HTTPException:
    status, retry = CALL_ERRORS.get(code, (502, False))
    return fastapi.HTTPException(
        status_code=status, detail={'error': code, 'retry': retry}
    )


async def _check_run_permission(
    db: graph.Graph,
    auth: permissions.AuthContext,
    data: RunRequest,
    prompt: models.Prompt,
) -> None:
    """``prompt:update`` may run anything; ``prompt:run`` only a saved
    version of a generative prompt. The author of a workflow
    (``workflow:write``) may run its step prompts, also as a draft."""
    if auth.is_admin or 'prompt:update' in auth.permissions:
        return
    if (
        'prompt:run' in auth.permissions
        and data.ref is not None
        and prompt.kind == 'generative'
    ):
        return
    if prompt.namespace == WORKFLOWS_NAMESPACE and await _is_owner(
        db, auth, prompt.namespace, prompt.slug
    ):
        return
    raise fastapi.HTTPException(
        status_code=403,
        detail='Permission denied: prompt:update or prompt:run required',
    )


async def _check_model_teams(
    db: graph.Graph,
    store: workflows.WorkflowStore,
    auth: permissions.AuthContext,
    org_id: str,
    prompt: models.Prompt,
    model: str,
) -> None:
    """A ``restricted`` model runs only for its teams (#782).

    A user must be a member of an allowed team. The workflows service
    runs a workflow step prompt, so the owner team of that workflow must
    be allowed. Another principal without a user is refused.

    Raises:
        403: ``model_not_allowed``.

    """
    if auth.is_admin:
        return
    account = auth.service_account
    if auth.user is not None:
        allowed = await prompt_resolve.member_allowed(
            db, model, auth.user.email
        )
    elif (
        account is not None
        and account.slug == common_permissions.WORKFLOWS_ACCOUNT
        and prompt.namespace == WORKFLOWS_NAMESPACE
    ):
        # <org>.<workflow>.<node key>
        slug = prompt.slug.partition('.')[2].rpartition('.')[0]
        row = await store.get(org_id, slug)
        allowed = row is not None and await prompt_resolve.team_allowed(
            db, model, row['owner_team_id']
        )
    else:
        allowed = False
    if not allowed:
        raise _call_error('model_not_allowed')


@prompt_render_router.post('/run', response_model=RunResponse)
async def run_prompt(
    org_slug: str,
    data: RunRequest,
    request: fastapi.Request,
    db: graph.Pool,
    secrets: secret_broker.Store,
    calls: model_calls.Store,
    workflow_store: workflows.Store,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
    idempotency_key: typing.Annotated[
        str | None,
        fastapi.Header(alias='Idempotency-Key', min_length=1, max_length=200),
    ] = None,
) -> RunResponse:
    """Run a prompt against its model and return the answer.

    Renders the saved version ``ref``, or the unsaved ``draft``, then
    calls the version's model. A run spends provider credit, so it needs
    ``prompt:update`` (prompt authors), or ``prompt:run`` (the workflows
    service) for a saved version of a generative prompt. For a
    ``workflows/<org>.*`` prompt, ``workflow:write`` in ``<org>`` is
    also enough.

    A decision prompt goes to its TypeSafe model with the provider's
    stored key.

    A generative prompt goes to its catalog model (see
    :mod:`imbi.api.llm.generate` for the credentials). Each call is
    recorded in ``ai_runtime.ai_model_calls``. With an
    ``Idempotency-Key`` header (``<run_id>:<node_id>:<attempt>``), a
    repeat of the key gets the answer of the first call and makes no
    new call. An error has ``detail={'error': <code>, 'retry': <bool>}``
    (see :data:`CALL_ERRORS`).

    Raises:
        403: No permission, a template calls ``project()`` without
            ``project:read``, or the model is restricted to teams that
            do not include the caller (``model_not_allowed``).
        404: No such prompt, version, label, project, or organization.
        409: The provider has no usable credentials, a call with the key
            is still running (``call_in_progress``), or one did not
            finish (``outcome_unknown``).
        422: The prompt has no model or no questions, the model cannot
            run it, or the render fails.
        502: The model rejected or failed the call.
        503: The provider is unavailable or rate limited; try again.

    """
    # First, so that every check below uses only the permissions of the
    # caller in this organization, not those of their other orgs.
    org_id = await organizations.check_member(org_slug, db, auth)
    # A repeated key returns the first outcome before the live prompt
    # and model are resolved, so a deleted prompt or a disabled model
    # does not lose the answer. Only the organization member and
    # principal that made the call can repeat its key.
    if idempotency_key is not None:
        row = await calls.repeat(
            org_id, auth.principal_name, idempotency_key, STALE_AFTER
        )
        if row is not None:
            return _repeat(row)
    prompt, version, n = await _run_target(db, data, auth)
    _check_route_org(prompt, org_slug)
    await _check_run_permission(db, auth, data, prompt)
    ref = f'{prompt.namespace}/{prompt.slug}' + (
        f'@{n}' if n is not None else ' (draft)'
    )
    if prompt.kind == 'generative':
        return await _run_generative(
            org_slug,
            org_id,
            data,
            request,
            db,
            secrets,
            calls,
            workflow_store,
            auth,
            prompt,
            version,
            ref,
            idempotency_key,
        )
    if not version.questions:
        raise _unprocessable('The prompt has no questions to ask')
    if version.model is None:
        raise _unprocessable('Choose a decision model to run the prompt')
    records = await db.execute(
        _RUN_MODEL_QUERY,
        {'slug': version.model},
        _RUN_MODEL_COLUMNS,
    )
    if not records:
        raise _unprocessable(
            f'AI model {version.model!r} is not in the catalog'
        )
    record = records[0]
    if graph.parse_agtype(record['enabled']) is False:
        raise _unprocessable(f'AI model {version.model!r} is disabled')
    if graph.parse_agtype(record.get('access_scope')) == 'restricted':
        await _check_model_teams(
            db, workflow_store, auth, org_id, prompt, version.model
        )
    provider = await ai_providers.fetch_provider(
        db, str(graph.parse_agtype(record['provider_id']))
    )
    if not provider.enabled:
        raise _unprocessable(f'AI provider {provider.slug!r} is disabled')
    if (
        graph.parse_agtype(record['model_type']) != 'decision'
        or provider.driver != 'typesafe'
    ):
        raise _unprocessable(
            f'AI model {version.model!r} is not a TypeSafe decision model'
        )
    try:
        decision = await rendering.render_decision(
            version,
            data.variables,
            _providers(auth, db, org_slug, request),
        )
    except rendering.RenderError as e:
        raise _unprocessable(str(e)) from e
    api_key = decrypt_config_value(provider.credentials_encrypted)
    if not api_key:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'AI provider {provider.slug!r} has no stored credentials'
            ),
        )
    model_id = str(graph.parse_agtype(record['model_id']))
    questions = {
        qid: _wire_question(question)
        for qid, question in decision.questions.items()
    }
    base_url = drivers.resolve_base_url(provider.driver, provider.base_url)
    try:
        result = await typesafe.decide(
            api_key,
            base_url or '',
            model_id,
            decision.state,
            questions,
        )
    except typesafe.DecisionError as e:
        raise fastapi.HTTPException(status_code=502, detail=str(e)) from e
    LOGGER.info(
        'Ran decision prompt %s with %s for %s',
        ref,
        model_id,
        auth.principal_name,
    )
    return RunResponse(
        ref=ref,
        n=n,
        model=version.model,
        model_id=model_id,
        request=RunRequestBody(state=decision.state, questions=questions),
        answers=result['answers'],
        usage=result['usage'],
    )


def _key_context(key: str | None) -> dict[str, typing.Any]:
    """The workflow context in a key ``<run_id>:<node_id>:<attempt>``."""
    if key is None:
        return {
            'origin': 'preview',
            'run_id': None,
            'node_id': None,
            'attempt': None,
        }
    run_id, _, rest = key.partition(':')
    node_id, _, attempt = rest.rpartition(':')
    return {
        'origin': 'workflow',
        'run_id': run_id,
        'node_id': node_id or None,
        'attempt': int(attempt) if attempt.isdigit() else None,
    }


def _price(value: object) -> decimal.Decimal | None:
    """A catalog price as AGE returns it (a number or a string)."""
    return None if value is None else decimal.Decimal(str(value))


def _call_response(row: dict[str, typing.Any]) -> RunResponse:
    return RunResponse(
        ref=row['prompt_ref'],
        n=row['prompt_version'],
        model=row['model'],
        model_id=row['model_id'],
        usage=row['usage'],
        content_sha256=row['content_sha256'],
        text=row['text'],
        result=row['result'],
        cost_usd=row['cost_usd'],
        call_id=row['id'],
    )


def _repeat(row: dict[str, typing.Any]) -> RunResponse:
    """The answer to a repeat of an idempotency key."""
    match row['status']:
        case 'succeeded':
            return _call_response(row)
        case 'running':
            raise _call_error('call_in_progress')
        case 'failed':
            raise _call_error(str(row['error']))
        case _:
            raise _call_error('outcome_unknown')


async def _run_generative(
    org_slug: str,
    org_id: str,
    data: RunRequest,
    request: fastapi.Request,
    db: graph.Graph,
    secrets: secret_broker.store.SecretStore,
    calls: model_calls.ModelCallStore,
    workflow_store: workflows.WorkflowStore,
    auth: permissions.AuthContext,
    prompt: models.Prompt,
    version: models.PromptVersion,
    ref: str,
    idempotency_key: str | None,
) -> RunResponse:
    """Run a generative prompt; see :func:`run_prompt`."""
    if version.model is None:
        raise _unprocessable('Choose a generative model to run the prompt')
    records = await db.execute(
        _RUN_MODEL_QUERY,
        {'slug': version.model},
        _RUN_MODEL_COLUMNS,
    )
    if not records:
        raise _unprocessable(
            f'AI model {version.model!r} is not in the catalog'
        )
    record = {k: graph.parse_agtype(v) for k, v in records[0].items()}
    if record['enabled'] is False:
        raise _unprocessable(f'AI model {version.model!r} is disabled')
    # A missing value predates model_type, when every model was
    # generative.
    if (record.get('model_type') or 'generative') != 'generative':
        raise _unprocessable(
            f'AI model {version.model!r} is not a generative model'
        )
    # The provider adapters send chat requests only. A missing value
    # predates kind, when every model was a chat model.
    if (record.get('kind') or 'chat') != 'chat':
        raise _unprocessable(
            f'AI model {version.model!r} is a completion model; '
            'a generative run needs a chat model'
        )
    if record.get('access_scope') == 'restricted':
        await _check_model_teams(
            db, workflow_store, auth, org_id, prompt, version.model
        )
    provider = await ai_providers.fetch_provider(
        db, str(record['provider_id'])
    )
    if not provider.enabled:
        raise _unprocessable(f'AI provider {provider.slug!r} is disabled')
    if data.output_fields and not record.get('structured'):
        raise _call_error('model_no_structured_output')
    try:
        rendered = await rendering.render(
            version,
            data.variables,
            _providers(auth, db, org_slug, request),
        )
    except rendering.RenderError as e:
        raise _unprocessable(str(e)) from e
    model_id = str(record['model_id'])
    call = generate.Request(
        driver=provider.driver,
        model_id=model_id,
        messages=rendered.messages,
        system=rendered.system,
        params=version.params,
        output_fields=data.output_fields,
        # A missing value predates the field: a forced tool choice.
        forced_tool_choice=record.get('forced_tool_choice') is not False,
        base_url=drivers.resolve_base_url(provider.driver, provider.base_url),
        region=provider.region,
        project_id=provider.project_id,
        timeout=CALL_TIMEOUT,
    )
    row, new = await calls.start(
        {
            'organization_id': org_id,
            'principal': auth.principal_name,
            **_key_context(idempotency_key),
            'idempotency_key': idempotency_key,
            'prompt_ref': ref,
            'prompt_version': version.n if data.ref is not None else None,
            'content_sha256': version.content_sha256,
            'model': version.model,
            'model_id': model_id,
            'driver': provider.driver,
            'system': rendered.system,
            'messages': [m.model_dump() for m in rendered.messages],
            'output_schema': agent.output_schema(data.output_fields),
        },
        STALE_AFTER,
    )
    if not new:
        return _repeat(row)
    try:
        async with asyncio.timeout(CALL_DEADLINE):
            answer = await model_generate.call(secrets, provider, call)
    except TimeoutError:
        await calls.finish(row['id'], 'failed', error='provider_unreachable')
        raise _call_error('provider_unreachable') from None
    except generate.GenerateError as e:
        await calls.finish(row['id'], 'failed', error=e.code)
        raise _call_error(e.code) from None
    usage = dict(answer.usage)
    tokens_in = answer.usage['input_tokens']
    tokens_out = answer.usage['output_tokens']
    # The cost is unknown when a count is unknown, not a subtotal.
    cost = (
        None
        if tokens_in is None or tokens_out is None
        else task_store.usage_cost(
            {
                'tokens_in': tokens_in,
                'tokens_out': tokens_out,
                'cache_read_tokens': answer.usage.get('cache_read_tokens'),
                'cache_write_tokens': None,
            },
            {
                'input_cost_per_million': _price(record.get('input_cost')),
                'output_cost_per_million': _price(record.get('output_cost')),
                'cache_read_cost_per_million': _price(
                    record.get('cache_read_cost')
                ),
                'cache_write_cost_per_million': None,
            },
        )
    )
    await calls.finish(
        row['id'],
        'succeeded',
        text=answer.text,
        result=answer.result,
        usage=usage,
        cost_usd=cost,
        provider_request_id=answer.request_id,
    )
    LOGGER.info(
        'Ran generative prompt %s with %s for %s',
        ref,
        model_id,
        auth.principal_name,
    )
    return _call_response(
        {
            **row,
            'text': answer.text,
            'result': answer.result,
            'usage': usage,
            'cost_usd': cost,
        }
    )


@prompts_router.get('/{namespace}/{slug}', response_model=PromptResponse)
async def get_prompt(
    namespace: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> PromptResponse:
    """Get one prompt with its labels."""
    await _require_read(db, auth, namespace, slug)
    prompt, latest = await _fetch_prompt(db, namespace, slug, auth)
    return _prompt_response(prompt, latest)


@prompts_router.patch('/{namespace}/{slug}', response_model=PromptResponse)
async def patch_prompt(
    namespace: str,
    slug: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('prompt:update')),
    ],
) -> PromptResponse:
    """Change a prompt's metadata with JSON Patch (RFC 6902).

    Renaming ``namespace`` or ``slug`` changes the reference every
    consumer uses, and frees the old reference for another prompt. So
    a rename requires ``prompt:promote``, like a label move.

    Raises:
        400: Invalid patch or a read-only path.
        403: A rename without ``prompt:promote``.
        404: No such prompt.
        409: The new ``namespace/slug`` is taken, the rename moves
            a prompt into or out of the ``workflows`` namespace, or the
            prompt moved or was deleted while this request ran.
        422: The patched values are not valid.

    """
    prompt, latest = await _fetch_prompt(db, namespace, slug, auth)
    document = prompt.model_dump(mode='json', include=set(_PATCHABLE_FIELDS))
    patched = json_patch.apply_patch(document, operations, _READONLY_PATHS)
    try:
        updated = models.Prompt.model_validate(
            {
                **prompt.model_dump(),
                **{k: patched.get(k) for k in _PATCHABLE_FIELDS},
            }
        )
    except pydantic.ValidationError as e:
        raise _unprocessable(f'Validation error: {e.errors()}') from e
    if not re.match(models.PROMPT_NAME_PATTERN, updated.slug):
        raise _unprocessable(f'Slug {updated.slug!r} is not valid')
    if (updated.namespace, updated.slug) != (namespace, slug):
        if WORKFLOWS_NAMESPACE in (namespace, updated.namespace):
            raise _workflow_prompt_locked()
        if not (auth.is_admin or 'prompt:promote' in auth.permissions):
            raise fastapi.HTTPException(
                status_code=403,
                detail='Renaming a prompt requires prompt:promote',
            )
        await _require_access(db, auth, updated.namespace, updated.slug)
        await _assert_ref_free(db, updated.namespace, updated.slug, prompt.id)
    updated.updated_at = _now()
    props = updated.model_dump(
        mode='json', include={*_PATCHABLE_FIELDS, 'updated_at'}
    )
    # The match on the reference that this patch read stops it from
    # writing an old slug back over a move (an organization rename).
    query = (
        'MATCH (p:Prompt {{id: {id}, namespace: {read_namespace},'
        ' slug: {read_slug}}})'
        f' {set_clause("p", props)} RETURN p'
    )
    params = {
        **props,
        'id': prompt.id,
        'read_namespace': prompt.namespace,
        'read_slug': prompt.slug,
    }
    dest_org = _prompt_org(updated.namespace, updated.slug)
    org_rows = (
        await db.execute(_ORG_ID_QUERY, {'slug': dest_org}, ['id'])
        if dest_org is not None
        and (namespace, slug)
        != (
            updated.namespace,
            updated.slug,
        )
        else []
    )
    records: list[dict[str, typing.Any]]
    with conflict_on_unique_violation(
        f'Prompt {updated.namespace}/{updated.slug} already exists'
    ):
        if org_rows:
            # A rename into an organization's prefix holds the shared
            # lock on that organization, which an organization rename
            # holds exclusively, and writes only while the organization
            # still has that slug.
            org_id = str(graph.parse_agtype(org_rows[0]['id']))
            try:
                await db._execute_batch(  # pyright: ignore[reportPrivateUsage]
                    [
                        graph_cypher.Statement(
                            _ORG_GUARD_QUERY,
                            {'org_id': org_id, 'org_slug': dest_org},
                            expect_rows=True,
                        ),
                        graph_cypher.Statement(
                            query, params, expect_rows=True
                        ),
                    ],
                    shared_lock=relational.organization_delete_lock_key(
                        org_id
                    ),
                )
                records = [{'p': None}]
            except graph.StatementMatchedNothing:
                records = []
        else:
            records = await db.execute(query, params, ['p'])
    if not records:
        raise fastapi.HTTPException(
            status_code=409, detail=PROMPT_CHANGED_DETAIL
        )
    return _prompt_response(updated, latest)


@prompts_router.delete('/{namespace}/{slug}', status_code=204)
async def delete_prompt(
    namespace: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('prompt:delete')),
    ],
) -> None:
    """Delete a prompt and every version of it.

    Raises:
        404: No such prompt.
        409: The prompt is a workflows prompt.

    """
    prompt, _latest = await _fetch_prompt(db, namespace, slug, auth)
    if prompt.namespace == WORKFLOWS_NAMESPACE:
        raise _workflow_prompt_locked()
    params = {'id': prompt.id}
    # Versions first: a failure between the two writes leaves a prompt
    # with no versions, which a second DELETE removes.
    await db.execute(_DELETE_VERSIONS_QUERY, params, [])
    await db.execute(_DELETE_PROMPT_QUERY, params, ['deleted'])


# --- Version endpoints -------------------------------------------------


@prompts_router.get(
    '/{namespace}/{slug}/versions',
    response_model=list[PromptVersionResponse],
)
async def list_prompt_versions(
    namespace: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> list[PromptVersionResponse]:
    """List every version of a prompt, newest first."""
    await _require_read(db, auth, namespace, slug)
    prompt, _latest = await _fetch_prompt(db, namespace, slug, auth)
    records = await db.execute(
        _VERSIONS_QUERY, {'prompt_id': prompt.id}, ['v']
    )
    versions = [
        _parse_version(props, prompt)
        for record in records
        if (props := _props(record['v'])) is not None
    ]
    versions.sort(key=lambda v: v.n, reverse=True)
    return [_version_response(v, prompt) for v in versions]


@prompts_router.get(
    '/{namespace}/{slug}/versions/{n}',
    response_model=PromptVersionResponse,
)
async def get_prompt_version(
    namespace: str,
    slug: str,
    n: int,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> PromptVersionResponse:
    """Get one version of a prompt."""
    await _require_read(db, auth, namespace, slug)
    prompt, _latest = await _fetch_prompt(db, namespace, slug, auth)
    version = await _fetch_version(db, prompt, n)
    return _version_response(version, prompt)


@prompts_router.post(
    '/{namespace}/{slug}/versions',
    response_model=PromptVersionResponse,
    status_code=201,
)
async def create_prompt_version(
    namespace: str,
    slug: str,
    data: PromptVersionCreate,
    response: fastapi.Response,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> PromptVersionResponse:
    """Save a new version. Versions are never changed after this.

    Needs ``prompt:update``. For a ``workflows/<org>.*`` prompt,
    ``workflow:write`` in ``<org>`` is also enough.

    When the content is the same as the newest version, nothing is
    written and the newest version is returned with status 200.

    A new version of an archived workflows prompt un-archives it: a
    workflow step with the same key is back.

    Raises:
        403: No permission.
        404: No such prompt.
        409: The prompt is archived and not a workflows prompt, or
            another version was saved at the same time.
        422: A template does not parse, the model is not in the
            catalog, or a workflows prompt has tools.

    """
    await _require_permission(db, auth, 'prompt:update', namespace, slug)
    prompt, latest = await _fetch_prompt(db, namespace, slug, auth)
    if prompt.namespace != WORKFLOWS_NAMESPACE:
        _check_not_archived(prompt)
    _check_kind(prompt.kind, data)
    _check_tools(prompt.namespace, data)
    _check_templates(data)
    archived = prompt.archived_at is not None
    now = _DATETIME.dump_python(_now(), mode='json')
    if latest:
        newest = await _fetch_version(db, prompt, latest)
        if newest.content_sha256 == content_sha256(data):
            if archived:
                await db.execute(
                    _UNARCHIVE_QUERY, {'id': prompt.id, 'now': now}, ['p']
                )
            response.status_code = 200
            return _version_response(newest, prompt)
    model_id = await _model_id_for(db, data.model, prompt.kind)
    version, props = _version_props(
        prompt, latest + 1, data, model_id, auth.principal_name
    )
    # The prompt is un-archived in the same statement, so a failed
    # write leaves it archived.
    query = (
        'MATCH (p:Prompt {{id: {prompt_id}}})'
        + (
            ' SET p.archived_at = NULL, p.updated_at = {now}'
            if archived
            else ''
        )
        + f' CREATE (v:PromptVersion {props_template(props)})'
        ' CREATE (v)-[:VERSION_OF]->(p)'
        ' RETURN v'
    )
    with conflict_on_unique_violation(
        f'Version {latest + 1} of {namespace}/{slug} was saved by another '
        'request; reload the prompt and try again'
    ):
        records = await db.execute(query, {**props, 'now': now}, ['v'])
    if not records:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Prompt {namespace}/{slug} not found'
        )
    return _version_response(version, prompt)


@prompts_router.put(
    '/{namespace}/{slug}/versions/{n}/evaluation',
    response_model=PromptVersionResponse,
)
async def set_prompt_version_evaluation(
    namespace: str,
    slug: str,
    n: int,
    data: EvalSummary,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('prompt:evaluate')),
    ],
) -> PromptVersionResponse:
    """Record the latest evaluation result for a version.

    This is a cache for display. It never gates a promotion.
    """
    _ = auth
    prompt, _latest = await _fetch_prompt(db, namespace, slug, auth)
    version = await _fetch_version(db, prompt, n)
    summary = data.model_dump(mode='json')
    await db.execute(
        _SET_EVAL_QUERY,
        {
            'prompt_id': prompt.id,
            'n': n,
            'eval_summary': json.dumps(summary),
        },
        ['v'],
    )
    version.eval_summary = summary
    return _version_response(version, prompt)


# --- Label endpoints ---------------------------------------------------


@prompts_router.put(
    '/{namespace}/{slug}/labels/{label}', response_model=PromptResponse
)
async def set_prompt_label(
    namespace: str,
    slug: str,
    label: models.PromptName,
    data: LabelUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> PromptResponse:
    """Point a label at a version, creating the label if needed.

    This changes what every consumer of ``namespace/slug@label`` gets,
    so it needs :func:`can_promote`.

    Raises:
        403: The caller cannot promote this prompt.
        404: No such prompt or version.
        409: The prompt is archived, or it changed while this request
            ran.
        422: The label is made only of digits.

    """
    _check_label_name(label)
    # Check before the read, so a 404 cannot tell a caller that
    # cannot promote that the prompt exists.
    if not await can_promote(db, auth, namespace, slug):
        raise fastapi.HTTPException(
            status_code=403,
            detail=f'Moving a label of {namespace}/{slug} requires '
            'prompt:promote',
        )
    prompt, latest = await _fetch_prompt(db, namespace, slug, auth)
    _check_not_archived(prompt)
    await _fetch_version(db, prompt, data.version)
    labels = moved_labels(prompt, label, data.version, auth.principal_name)
    updated = await _write_labels(db, prompt, labels, prompt.default_label)
    return _prompt_response(updated, latest)


@prompts_router.delete(
    '/{namespace}/{slug}/labels/{label}', response_model=PromptResponse
)
async def delete_prompt_label(
    namespace: str,
    slug: str,
    label: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('prompt:promote')),
    ],
) -> PromptResponse:
    """Remove a label. The default label cannot be removed.

    Raises:
        404: No such prompt or label.
        409: The label is the default label, the prompt is archived,
            or the prompt changed while this request ran.

    """
    _ = auth
    prompt, latest = await _fetch_prompt(db, namespace, slug, auth)
    _check_not_archived(prompt)
    if label == prompt.default_label:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'{label!r} is the default label; set another default '
                'label first'
            ),
        )
    labels = [item for item in prompt.labels if item.name != label]
    if len(labels) == len(prompt.labels):
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Prompt {namespace}/{slug} has no label {label!r}',
        )
    updated = await _write_labels(db, prompt, labels, prompt.default_label)
    return _prompt_response(updated, latest)


@prompts_router.put(
    '/{namespace}/{slug}/default-label', response_model=PromptResponse
)
async def set_prompt_default_label(
    namespace: str,
    slug: str,
    data: DefaultLabelUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('prompt:promote')),
    ],
) -> PromptResponse:
    """Set the label used when a reference names no usable label.

    Raises:
        404: No such prompt.
        409: The prompt is archived, or it changed while this request
            ran.
        422: The prompt has no such label.

    """
    _ = auth
    prompt, latest = await _fetch_prompt(db, namespace, slug, auth)
    _check_not_archived(prompt)
    if data.label not in {item.name for item in prompt.labels}:
        raise _unprocessable(
            f'Prompt {namespace}/{slug} has no label {data.label!r}'
        )
    updated = await _write_labels(db, prompt, prompt.labels, data.label)
    return _prompt_response(updated, latest)
