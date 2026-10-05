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

import datetime
import hashlib
import json
import re
import typing

import fastapi
import pydantic
import slugify

from imbi.api.auth import permissions
from imbi.api.endpoints import projects
from imbi.api.endpoints._helpers import conflict_on_unique_violation
from imbi.api.graph_sql import escape_prop, props_template, set_clause
from imbi.common import graph, models
from imbi.common import patch as json_patch
from imbi.common.prompts import rendering
from imbi.common.prompts import resolve as prompt_resolve

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
    'eval_summary',
)

#: Template providers, by the name a template calls them with.
_PROVIDER_NAMES: frozenset[str] = frozenset({'project'})

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
    default_label: str
    labels: list[models.PromptLabel] = []
    latest_version: int = 0
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None


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
    """A prompt ready to send to a model."""

    model_config = pydantic.ConfigDict(protected_namespaces=())

    ref: str
    label: str | None
    n: int
    content_sha256: str
    model: str | None
    model_id: str | None
    params: models.PromptParams
    system: str
    messages: list[models.PromptMessage]
    tools: list[dict[str, typing.Any]]


# --- Queries -----------------------------------------------------------

_PROMPT_QUERY = prompt_resolve.PROMPT_QUERY

_LIST_QUERY: typing.LiteralString = """
MATCH (p:Prompt)
OPTIONAL MATCH (v:PromptVersion)-[:VERSION_OF]->(p)
RETURN p, max(v.n) AS latest
"""

_LIST_NAMESPACE_QUERY: typing.LiteralString = """
MATCH (p:Prompt {{namespace: {namespace}}})
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

_DELETE_VERSIONS_QUERY: typing.LiteralString = """
MATCH (v:PromptVersion)-[:VERSION_OF]->(p:Prompt {{id: {id}}})
DETACH DELETE v
"""

_DELETE_PROMPT_QUERY: typing.LiteralString = """
MATCH (p:Prompt {{id: {id}}})
DETACH DELETE p
RETURN 1 AS deleted
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
        default_label=prompt.default_label,
        labels=sorted(prompt.labels, key=lambda label: label.name),
        latest_version=latest,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
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
        content_sha256=version.content_sha256,
        eval_summary=version.eval_summary,
        created_by=version.created_by,
        created_at=version.created_at,
        labels=sorted(
            label.name for label in prompt.labels if label.version == version.n
        ),
    )


def content_sha256(content: PromptVersionContent) -> str:
    """Hash the canonical JSON of a version's content."""
    canonical = json.dumps(
        PromptVersionContent.model_validate(content.model_dump()).model_dump(
            mode='json'
        ),
        sort_keys=True,
        separators=(',', ':'),
    )
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


def _check_templates(content: PromptVersionContent) -> None:
    """Reject a version whose templates or variable names are invalid."""
    sources = {'system': content.system} | {
        f'messages[{i}]': m.content for i, m in enumerate(content.messages)
    }
    try:
        rendering.check_syntax(sources)
        rendering.check_variable_schema(
            content.variable_schema, _PROVIDER_NAMES
        )
    except rendering.RenderError as e:
        raise _unprocessable(str(e)) from e


async def _model_id_for(db: graph.Graph, model: str | None) -> str | None:
    """Return the catalog ``model_id`` for a model slug, or raise 422."""
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
    # A version holds a system prompt and messages, which only a
    # generative model can use. A missing value predates model_type.
    if graph.parse_agtype(records[0].get('model_type')) == 'decision':
        raise _unprocessable(
            'Decision models are not supported in prompt versions yet'
        )
    return str(graph.parse_agtype(records[0]['model_id']))


async def _fetch_prompt(
    db: graph.Graph, namespace: str, slug: str
) -> tuple[models.Prompt, int]:
    """Read a prompt and its newest version number, or raise 404."""
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


async def _write_labels(
    db: graph.Graph,
    prompt: models.Prompt,
    labels: list[models.PromptLabel],
    default_label: str,
) -> models.Prompt:
    """Replace a prompt's labels, or raise 409 on a concurrent write."""
    now = _now()
    records = await db.execute(
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
            'updated_at': _DATETIME.dump_python(now, mode='json'),
        },
        ['p'],
    )
    props = _props(records[0]['p']) if records else None
    if props is None:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                'The prompt changed while this request ran; reload it '
                'and try again'
            ),
        )
    return _parse_prompt(props)


def parse_ref(ref: str) -> tuple[str, str, str | None]:
    """Split ``namespace/slug@label`` into its parts, or raise 422."""
    try:
        return prompt_resolve.parse_ref(ref)
    except prompt_resolve.InvalidRef as e:
        raise _unprocessable(str(e)) from e


async def _resolve(
    db: graph.Graph, ref: str
) -> tuple[models.Prompt, models.PromptVersion, str | None]:
    """Find the version a reference names, or raise 404 / 422."""
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
    _ = auth
    if namespace is None:
        records = await db.execute(_LIST_QUERY, {}, ['p', 'latest'])
    else:
        records = await db.execute(
            _LIST_NAMESPACE_QUERY,
            {'namespace': namespace},
            ['p', 'latest'],
        )
    responses: list[PromptResponse] = []
    for record in records:
        props = _props(record['p'])
        if props is None:
            continue
        latest = graph.parse_agtype(record['latest'])
        responses.append(
            _prompt_response(_parse_prompt(props), int(latest or 0))
        )
    return sorted(responses, key=lambda r: (r.namespace, r.slug))


@prompts_router.post('/', response_model=PromptResponse, status_code=201)
async def create_prompt(
    data: PromptCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('prompt:create')),
    ],
) -> PromptResponse:
    """Create a prompt with its first version.

    The default label points at version 1.

    Raises:
        409: ``namespace/slug`` is taken.
        422: A template does not parse, or the model is not in the
            catalog.

    """
    return await insert_prompt(db, data, auth.principal_name)


async def insert_prompt(
    db: graph.Graph, data: PromptCreate, created_by: str
) -> PromptResponse:
    """Validate and write a prompt with its first version.

    ``imbi-api setup-prompts`` uses this too, so a seeded prompt is
    written exactly like one created through the API.

    Raises:
        fastapi.HTTPException: 409 when ``namespace/slug`` is taken, 422
            when a template or the model is not valid.

    """
    slug = data.slug or slugify.slugify(data.name)
    if not re.match(models.PROMPT_NAME_PATTERN, slug):
        raise _unprocessable(f'Slug {slug!r} is not valid')
    _check_label_name(data.default_label)
    _check_templates(data.version)
    model_id = await _model_id_for(db, data.version.model)
    await _assert_ref_free(db, data.namespace, slug)

    now = _now()
    prompt = models.Prompt(
        namespace=data.namespace,
        slug=slug,
        name=data.name,
        description=data.description,
        icon=data.icon,
        type=data.type,
        default_label=data.default_label,
        labels=[
            models.PromptLabel(
                name=data.default_label,
                version=1,
                updated_by=created_by,
                updated_at=now,
            )
        ],
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
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('prompt:read')),
    ],
) -> Resolution:
    """Resolve ``namespace/slug@label`` or ``@n`` to one version.

    Raises:
        404: No such prompt, version, or usable label.
        422: The reference is not valid.

    """
    _ = auth
    prompt, version, label = await _resolve(db, ref)
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
    prompt, version, label = await _resolve(db, data.ref)

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

    try:
        rendered = await rendering.render(
            version, data.variables, {'project': project}
        )
    except rendering.RenderError as e:
        raise _unprocessable(str(e)) from e
    return RenderResponse(
        ref=f'{prompt.namespace}/{prompt.slug}@{version.n}',
        label=label,
        n=version.n,
        content_sha256=version.content_sha256,
        model=version.model,
        model_id=version.model_id,
        params=version.params,
        system=rendered.system,
        messages=rendered.messages,
        tools=version.tools,
    )


@prompts_router.get('/{namespace}/{slug}', response_model=PromptResponse)
async def get_prompt(
    namespace: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('prompt:read')),
    ],
) -> PromptResponse:
    """Get one prompt with its labels."""
    _ = auth
    prompt, latest = await _fetch_prompt(db, namespace, slug)
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
        409: The new ``namespace/slug`` is taken.
        422: The patched values are not valid.

    """
    prompt, latest = await _fetch_prompt(db, namespace, slug)
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
        if not (auth.is_admin or 'prompt:promote' in auth.permissions):
            raise fastapi.HTTPException(
                status_code=403,
                detail='Renaming a prompt requires prompt:promote',
            )
        await _assert_ref_free(db, updated.namespace, updated.slug, prompt.id)
    updated.updated_at = _now()
    props = updated.model_dump(
        mode='json', include={*_PATCHABLE_FIELDS, 'updated_at'}
    )
    query = (
        'MATCH (p:Prompt {{id: {id}}})'
        f' {set_clause("p", props)} RETURN p'
    )
    with conflict_on_unique_violation(
        f'Prompt {updated.namespace}/{updated.slug} already exists'
    ):
        await db.execute(query, {**props, 'id': prompt.id}, ['p'])
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
    """Delete a prompt and every version of it."""
    _ = auth
    prompt, _latest = await _fetch_prompt(db, namespace, slug)
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
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('prompt:read')),
    ],
) -> list[PromptVersionResponse]:
    """List every version of a prompt, newest first."""
    _ = auth
    prompt, _latest = await _fetch_prompt(db, namespace, slug)
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
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('prompt:read')),
    ],
) -> PromptVersionResponse:
    """Get one version of a prompt."""
    _ = auth
    prompt, _latest = await _fetch_prompt(db, namespace, slug)
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
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('prompt:update')),
    ],
) -> PromptVersionResponse:
    """Save a new version. Versions are never changed after this.

    When the content is the same as the newest version, nothing is
    written and the newest version is returned with status 200.

    Raises:
        404: No such prompt.
        409: Another version was saved at the same time.
        422: A template does not parse, or the model is not in the
            catalog.

    """
    prompt, latest = await _fetch_prompt(db, namespace, slug)
    _check_templates(data)
    if latest:
        newest = await _fetch_version(db, prompt, latest)
        if newest.content_sha256 == content_sha256(data):
            response.status_code = 200
            return _version_response(newest, prompt)
    model_id = await _model_id_for(db, data.model)
    version, props = _version_props(
        prompt, latest + 1, data, model_id, auth.principal_name
    )
    query = (
        'MATCH (p:Prompt {{id: {prompt_id}}})'
        f' CREATE (v:PromptVersion {props_template(props)})'
        ' CREATE (v)-[:VERSION_OF]->(p)'
        ' RETURN v'
    )
    with conflict_on_unique_violation(
        f'Version {latest + 1} of {namespace}/{slug} was saved by another '
        'request; reload the prompt and try again'
    ):
        records = await db.execute(query, props, ['v'])
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
    prompt, _latest = await _fetch_prompt(db, namespace, slug)
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
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('prompt:promote')),
    ],
) -> PromptResponse:
    """Point a label at a version, creating the label if needed.

    This changes what every consumer of ``namespace/slug@label`` gets.

    Raises:
        404: No such prompt or version.
        409: The prompt changed while this request ran.
        422: The label is made only of digits.

    """
    _check_label_name(label)
    prompt, latest = await _fetch_prompt(db, namespace, slug)
    await _fetch_version(db, prompt, data.version)
    labels = [item for item in prompt.labels if item.name != label]
    labels.append(
        models.PromptLabel(
            name=label,
            version=data.version,
            updated_by=auth.principal_name,
            updated_at=_now(),
        )
    )
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
        409: The label is the default label, or the prompt changed
            while this request ran.

    """
    _ = auth
    prompt, latest = await _fetch_prompt(db, namespace, slug)
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
        409: The prompt changed while this request ran.
        422: The prompt has no such label.

    """
    _ = auth
    prompt, latest = await _fetch_prompt(db, namespace, slug)
    if data.label not in {item.name for item in prompt.labels}:
        raise _unprocessable(
            f'Prompt {namespace}/{slug} has no label {data.label!r}'
        )
    updated = await _write_labels(db, prompt, prompt.labels, data.label)
    return _prompt_response(updated, latest)
