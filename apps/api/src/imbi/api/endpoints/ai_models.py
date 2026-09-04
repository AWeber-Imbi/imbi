"""Org-scoped CRUD for the AI model catalog.

An :class:`imbi.common.models.AIModel` names one model an organization
may call and the :class:`~imbi.common.models.AIProvider` that serves it.
``slug`` is a stable org-scoped alias so agent configuration can say
``default-chat``; ``model_id`` is what actually goes on the wire.

Both uniqueness rules are enforced here rather than by a graph index,
because both are scoped: ``slug`` within the organization and
``model_id`` within the provider.
"""

import datetime
import decimal
import logging
import typing

import fastapi
import pydantic
import slugify

from imbi.api.auth import permissions
from imbi.api.endpoints import ai_providers
from imbi.api.endpoints._helpers import conflict_on_unique_violation
from imbi.api.graph_sql import props_template, set_clause
from imbi.common import graph, models
from imbi.common import patch as json_patch

LOGGER = logging.getLogger(__name__)

ai_models_router = fastapi.APIRouter(tags=['AI Models'])

#: Mounted alongside ``ai_providers_router``: the route is addressed by
#: provider, but its whole job is creating models.
ai_provider_imports_router = fastapi.APIRouter(tags=['AI Models'])

#: Model fields an admin may set through create / patch. ``provider_id``
#: and ``allowed_team_ids`` are edges rather than properties and are
#: handled separately.
_PATCHABLE_FIELDS: tuple[str, ...] = (
    'name',
    'slug',
    'description',
    'icon',
    'model_id',
    'kind',
    'enabled',
    'access_scope',
    'context_window',
    'max_output_tokens',
    'input_cost_per_million',
    'output_cost_per_million',
    'default_temperature',
    'default_top_p',
    'monthly_spend_cap',
)

#: Paths a patch may not target. ``provider_id`` and
#: ``allowed_team_ids`` are the writable spellings of the two edges;
#: the response's own ``provider``/``provider_name``/``allowed_teams``
#: are derived, and patching one would be dropped silently and answered
#: 200, which reads as "applied".
_READONLY_PATHS: frozenset[str] = json_patch.READONLY_PATHS | frozenset(
    ['/allowed_teams', '/organization', '/provider', '/provider_name']
)

ModelKind = typing.Literal['chat', 'completion']
AccessScope = typing.Literal['organization', 'restricted']

#: Validates the patched ``allowed_team_ids`` back into a typed list —
#: a JSON Patch body can put anything at that path.
_TEAM_IDS: pydantic.TypeAdapter[list[str]] = pydantic.TypeAdapter(list[str])


class TeamRef(pydantic.BaseModel):
    """A team an access-restricted model is available to."""

    id: str
    name: str
    slug: str


class AIModelCreate(pydantic.BaseModel):
    """Request body for adding a model to the catalog."""

    model_config = pydantic.ConfigDict(protected_namespaces=())

    provider_id: str
    name: str
    model_id: str
    slug: str | None = None
    description: str | None = None
    icon: str | None = None
    kind: ModelKind = 'chat'
    enabled: bool = True
    access_scope: AccessScope = 'organization'
    allowed_team_ids: list[str] = pydantic.Field(default_factory=list)
    context_window: int | None = pydantic.Field(default=None, gt=0)
    max_output_tokens: int | None = pydantic.Field(default=None, gt=0)
    input_cost_per_million: decimal.Decimal | None = pydantic.Field(
        default=None, ge=0
    )
    output_cost_per_million: decimal.Decimal | None = pydantic.Field(
        default=None, ge=0
    )
    default_temperature: float | None = pydantic.Field(
        default=None, ge=0, le=2
    )
    default_top_p: float | None = pydantic.Field(default=None, ge=0, le=1)
    monthly_spend_cap: decimal.Decimal | None = pydantic.Field(
        default=None, ge=0
    )


class AIModelResponse(pydantic.BaseModel):
    """A configured model, with its provider and access list resolved."""

    model_config = pydantic.ConfigDict(protected_namespaces=())

    id: str
    name: str
    slug: str
    description: str | None = None
    icon: str | None = None
    provider_id: str
    provider_name: str
    model_id: str
    kind: ModelKind = 'chat'
    enabled: bool = True
    access_scope: AccessScope = 'organization'
    allowed_teams: list[TeamRef] = pydantic.Field(default_factory=list)
    context_window: int | None = None
    max_output_tokens: int | None = None
    input_cost_per_million: decimal.Decimal | None = None
    output_cost_per_million: decimal.Decimal | None = None
    default_temperature: float | None = None
    default_top_p: float | None = None
    monthly_spend_cap: decimal.Decimal | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None


class ImportModelRequest(pydantic.BaseModel):
    """One model selected from a discovery result."""

    model_config = pydantic.ConfigDict(protected_namespaces=())

    model_id: str
    display_name: str | None = None
    context_window: int | None = pydantic.Field(default=None, gt=0)
    max_output_tokens: int | None = pydantic.Field(default=None, gt=0)


class ImportModelsRequest(pydantic.BaseModel):
    """Request body for importing discovered models."""

    models: list[ImportModelRequest] = pydantic.Field(min_length=1)


class ImportResult(pydantic.BaseModel):
    """Outcome of an import: what was created, and what already existed."""

    created: list[AIModelResponse]
    skipped: list[str]


_LIST_QUERY: typing.LiteralString = """
MATCH (m:AIModel)-[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
MATCH (m)-[:SERVED_BY]->(p:AIProvider)
OPTIONAL MATCH (m)-[:ALLOWED_FOR]->(t:Team)
RETURN m, p, t
"""

_GET_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{id: {id}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
MATCH (m)-[:SERVED_BY]->(p:AIProvider)
OPTIONAL MATCH (m)-[:ALLOWED_FOR]->(t:Team)
RETURN m, p, t
"""

_SLUG_TAKEN_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{slug: {slug}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN m.id AS id
"""

_MODEL_ID_TAKEN_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{model_id: {model_id}}})
      -[:SERVED_BY]->(:AIProvider {{id: {provider_id}}})
RETURN m.id AS id
"""

_TEAM_QUERY: typing.LiteralString = """
MATCH (t:Team {{id: {team_id}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN t
"""

# Every edge write carries the BELONGS_TO hop for the same reason the
# reads do: an id alone is global, so without it a caller in one
# organization could rewire a model, or attach a team, belonging to
# another.
_CLEAR_TEAMS_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{id: {id}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
MATCH (m)-[r:ALLOWED_FOR]->(:Team)
DELETE r
"""

_ADD_TEAM_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{id: {id}}})
      -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
MATCH (t:Team {{id: {team_id}}})-[:BELONGS_TO]->(o)
MERGE (m)-[:ALLOWED_FOR]->(t)
RETURN t.id AS id
"""

_LINK_PROVIDER_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{id: {id}}})
      -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
MATCH (p:AIProvider {{id: {provider_id}}})-[:BELONGS_TO]->(o)
MERGE (m)-[:SERVED_BY]->(p)
RETURN p.id AS id
"""

#: Runs after ``_LINK_PROVIDER_QUERY`` and keeps the edge to the new
#: provider. Each ``execute`` autocommits, so linking first means a
#: failure between the two writes leaves the model with two provider
#: edges (repairable by another PATCH) rather than none (invisible to
#: ``_LIST_QUERY`` and ``_GET_QUERY``).
_UNLINK_OTHER_PROVIDERS_QUERY: typing.LiteralString = """
MATCH (m:AIModel {{id: {id}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
MATCH (m)-[r:SERVED_BY]->(p:AIProvider)
WHERE p.id <> {provider_id}
DELETE r
"""


def _to_response(
    node: models.AIModel,
    provider_id: str,
    provider_name: str,
    teams: list[TeamRef],
) -> AIModelResponse:
    """Build the wire shape for one model."""
    return AIModelResponse(
        id=node.id,
        name=node.name,
        slug=node.slug,
        description=node.description,
        icon=None if node.icon is None else str(node.icon),
        provider_id=provider_id,
        provider_name=provider_name,
        model_id=node.model_id,
        kind=node.kind,
        enabled=node.enabled,
        access_scope=node.access_scope,
        allowed_teams=sorted(teams, key=lambda t: t.name.lower()),
        context_window=node.context_window,
        max_output_tokens=node.max_output_tokens,
        input_cost_per_million=node.input_cost_per_million,
        output_cost_per_million=node.output_cost_per_million,
        default_temperature=node.default_temperature,
        default_top_p=node.default_top_p,
        monthly_spend_cap=node.monthly_spend_cap,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def parse_model(
    props: dict[str, typing.Any],
    provider_props: dict[str, typing.Any],
    org_slug: str,
) -> models.AIModel:
    """Build an ``AIModel`` from the properties of one graph row.

    Edges are stored as relationships, not properties, so the two edge
    fields the model declares are reconstructed from the same row: the
    provider vertex it was matched through, and the organization the
    request is scoped to.
    """
    org = {'name': '', 'slug': org_slug}
    return models.AIModel.model_validate(
        {
            **props,
            'organization': org,
            'provider': {**provider_props, 'organization': org},
        }
    )


def _props(raw: typing.Any) -> dict[str, typing.Any] | None:
    """Return an agtype vertex's properties, or ``None`` for a null."""
    parsed: typing.Any = graph.parse_agtype(raw)
    if not isinstance(parsed, dict):
        return None
    return typing.cast('dict[str, typing.Any]', parsed)


def _team_ref(raw: typing.Any) -> TeamRef | None:
    """Build a :class:`TeamRef` from an agtype vertex, if there is one.

    The team comes from an ``OPTIONAL MATCH``, so a null is expected
    whenever the model is organization-wide.
    """
    props = _props(raw)
    if props is None or not props.get('id'):
        return None
    return TeamRef(
        id=str(props['id']),
        name=str(props.get('name', '')),
        slug=str(props.get('slug', '')),
    )


def _rows_to_responses(
    records: list[dict[str, typing.Any]],
    org_slug: str,
) -> list[AIModelResponse]:
    """Fold ``(m, p, t)`` rows into one response per model.

    The team edge is an ``OPTIONAL MATCH``, so a model allowed for three
    teams arrives as three rows, and one allowed for none arrives as a
    single row whose ``t`` is null.
    """
    order: list[str] = []
    nodes: dict[str, models.AIModel] = {}
    providers: dict[str, tuple[str, str]] = {}
    teams: dict[str, dict[str, TeamRef]] = {}
    for record in records:
        props = _props(record.get('m'))
        provider_props = _props(record.get('p'))
        if props is None or provider_props is None:
            continue
        node = parse_model(props, provider_props, org_slug)
        if node.id not in nodes:
            order.append(node.id)
            nodes[node.id] = node
            teams[node.id] = {}
            providers[node.id] = (
                str(provider_props.get('id', '')),
                str(provider_props.get('name', '')),
            )
        team = _team_ref(record.get('t'))
        if team is not None:
            teams[node.id][team.id] = team
    return [
        _to_response(
            nodes[key],
            providers[key][0],
            providers[key][1],
            list(teams[key].values()),
        )
        for key in order
    ]


async def _resolve_teams(
    db: graph.Graph, org_slug: str, team_ids: list[str]
) -> list[TeamRef]:
    """Resolve team ids to references, rejecting any outside the org.

    Raises:
        fastapi.HTTPException: 422 when a team is unknown or belongs to
            another organization — the two are indistinguishable here on
            purpose, so the error cannot be used to probe other orgs.

    """
    refs: list[TeamRef] = []
    for team_id in dict.fromkeys(team_ids):
        records = await db.execute(
            _TEAM_QUERY, {'team_id': team_id, 'org_slug': org_slug}, ['t']
        )
        team = _team_ref(records[0]['t']) if records else None
        if team is None:
            raise fastapi.HTTPException(
                status_code=422,
                detail=(
                    f'Team {team_id!r} is not part of organization '
                    f'{org_slug!r}'
                ),
            )
        refs.append(team)
    return refs


def _validate_access(access_scope: str, teams: list[TeamRef]) -> None:
    """Reject a restricted model with nobody allowed to use it."""
    if access_scope == 'restricted' and not teams:
        raise fastapi.HTTPException(
            status_code=422,
            detail=(
                "access_scope 'restricted' requires at least one allowed team"
            ),
        )


def _teams_for_scope(access_scope: str, teams: list[TeamRef]) -> list[TeamRef]:
    """Return the teams that may actually hold an ``ALLOWED_FOR`` edge.

    The server's invariant is that edges exist if and only if the model
    is ``restricted``, so an ``organization``-wide model is stored with
    no edges however many team ids the request supplied. Enforcing it
    here rather than trusting the caller keeps "who may use this model"
    answerable from ``access_scope`` alone, and makes patching the scope
    on its own do the obvious thing to the edges.
    """
    return teams if access_scope == 'restricted' else []


async def _replace_team_edges(
    db: graph.Graph,
    org_slug: str,
    model_id: str,
    teams: list[TeamRef],
    clear_existing: bool = True,
) -> None:
    """Replace a model's ``ALLOWED_FOR`` edges with exactly ``teams``.

    Iterated in app code rather than driven by ``UNWIND``: Apache AGE
    has no ``FOR EACH`` and the lists here are a handful of teams.
    ``clear_existing`` is false for a node created moments ago, which
    cannot have edges yet.
    """
    if clear_existing:
        await db.execute(
            _CLEAR_TEAMS_QUERY, {'id': model_id, 'org_slug': org_slug}, []
        )
    for team in teams:
        await db.execute(
            _ADD_TEAM_QUERY,
            {'id': model_id, 'team_id': team.id, 'org_slug': org_slug},
            ['id'],
        )


async def _assert_slug_free(
    db: graph.Graph, org_slug: str, slug: str, exclude_id: str | None = None
) -> None:
    """Raise 409 when ``slug`` is taken elsewhere in the organization."""
    records = await db.execute(
        _SLUG_TAKEN_QUERY, {'slug': slug, 'org_slug': org_slug}, ['id']
    )
    for record in records:
        found = graph.parse_agtype(record['id'])
        if found and str(found) != exclude_id:
            raise fastapi.HTTPException(
                status_code=409,
                detail=(
                    f'AI model with slug {slug!r} already exists in '
                    f'organization {org_slug!r}'
                ),
            )


async def _assert_model_id_free(
    db: graph.Graph,
    provider_id: str,
    model_id: str,
    exclude_id: str | None = None,
) -> None:
    """Raise 409 when ``model_id`` is already served by the provider."""
    records = await db.execute(
        _MODEL_ID_TAKEN_QUERY,
        {'model_id': model_id, 'provider_id': provider_id},
        ['id'],
    )
    for record in records:
        found = graph.parse_agtype(record['id'])
        if found and str(found) != exclude_id:
            raise fastapi.HTTPException(
                status_code=409,
                detail=(
                    f'AI model with model_id {model_id!r} already exists '
                    f'on this provider'
                ),
            )


def _build(
    payload: dict[str, typing.Any],
    provider: models.AIProvider,
    org_slug: str,
) -> models.AIModel:
    """Validate model properties into a node or raise 422."""
    try:
        return models.AIModel(
            organization=models.Organization(name='', slug=org_slug),
            provider=provider,
            **payload,
        )
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=422,
            detail=f'Validation error: {e.errors()}',
        ) from e


async def _insert(
    db: graph.Graph,
    org_slug: str,
    node: models.AIModel,
    provider: models.AIProvider,
    teams: list[TeamRef],
) -> AIModelResponse:
    """Persist a new model, its edges, and return the wire shape."""
    now = datetime.datetime.now(datetime.UTC)
    node.created_at = now
    node.updated_at = now
    props = node.model_dump(
        mode='json', exclude={'organization', 'provider', 'allowed_teams'}
    )
    query = (
        f'MATCH (o:Organization {{{{slug: {{org_slug}}}}}})'
        f' MATCH (p:AIProvider {{{{id: {{provider_id}}}}}})-[:BELONGS_TO]->(o)'
        f' CREATE (m:AIModel {props_template(props)})'
        f' CREATE (m)-[:BELONGS_TO]->(o)'
        f' CREATE (m)-[:SERVED_BY]->(p)'
        f' RETURN m'
    )
    with conflict_on_unique_violation(
        f'AI model with slug {node.slug!r} already exists'
    ):
        records = await db.execute(
            query,
            {**props, 'org_slug': org_slug, 'provider_id': provider.id},
            ['m'],
        )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'AI provider with id {provider.id!r} not found',
        )
    # A node created moments ago has no edges to clear, and an
    # organization-wide model has none to write, so skip the round trip
    # entirely in the common case.
    if teams:
        await _replace_team_edges(
            db, org_slug, node.id, teams, clear_existing=False
        )
    stored = _props(records[0]['m'])
    if stored is None:
        raise fastapi.HTTPException(
            status_code=500, detail='AI model create returned no properties'
        )
    # Re-parse through the provider node already in hand rather than a
    # handful of its fields: ``AIProvider`` validates across fields (an
    # ``openai_compatible`` provider must carry a ``base_url``), so a
    # partial dict fails validation and 500s the create.
    return _to_response(
        parse_model(
            stored,
            provider.model_dump(mode='json', exclude={'organization'}),
            org_slug,
        ),
        provider.id,
        provider.name,
        teams,
    )


@ai_models_router.get('/', response_model=list[AIModelResponse])
async def list_ai_models(
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ai_model:read')),
    ],
) -> list[AIModelResponse]:
    """List an organization's models, ordered by name.

    Parameters:
        org_slug: Organization slug from the URL path.

    Returns:
        Every configured model with its provider and allowed teams.

    """
    _ = auth
    records = await db.execute(
        _LIST_QUERY, {'org_slug': org_slug}, ['m', 'p', 't']
    )
    return sorted(
        _rows_to_responses(records, org_slug),
        key=lambda r: r.name.lower(),
    )


@ai_models_router.post('/', response_model=AIModelResponse, status_code=201)
async def create_ai_model(
    org_slug: str,
    data: AIModelCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ai_model:create')),
    ],
) -> AIModelResponse:
    """Add a model to an organization's catalog.

    ``allowed_team_ids`` is still validated against the organization
    when ``access_scope`` is ``organization``, but no ``ALLOWED_FOR``
    edge is written: the model is available org-wide and the response
    reports an empty ``allowed_teams``.

    Parameters:
        org_slug: Organization slug from the URL path.
        data: Model configuration.

    Returns:
        The created model.

    Raises:
        404: The provider does not exist in this organization.
        409: The slug is taken in this organization, or the provider
            already serves this ``model_id``.
        422: A team is outside the organization, or ``restricted`` was
            requested with no teams.

    """
    _ = auth
    provider = await ai_providers.fetch_provider(
        db, org_slug, data.provider_id
    )
    teams = await _resolve_teams(db, org_slug, data.allowed_team_ids)
    _validate_access(data.access_scope, teams)
    teams = _teams_for_scope(data.access_scope, teams)

    payload = data.model_dump(
        exclude={'provider_id', 'allowed_team_ids', 'slug'}
    )
    payload['slug'] = data.slug or slugify.slugify(data.name)
    node = _build(payload, provider, org_slug)

    await _assert_slug_free(db, org_slug, node.slug)
    await _assert_model_id_free(db, provider.id, node.model_id)
    return await _insert(db, org_slug, node, provider, teams)


@ai_models_router.get('/{id}', response_model=AIModelResponse)
async def get_ai_model(
    org_slug: str,
    id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ai_model:read')),
    ],
) -> AIModelResponse:
    """Get one model.

    Parameters:
        org_slug: Organization slug from the URL path.
        id: Model id.

    Returns:
        The model with its provider and allowed teams.

    Raises:
        404: No such model in this organization.

    """
    _ = auth
    return await _fetch_response(db, org_slug, id)


async def _fetch_response(
    db: graph.Graph, org_slug: str, id: str
) -> AIModelResponse:
    """Read one model scoped to ``org_slug`` or raise 404."""
    records = await db.execute(
        _GET_QUERY, {'id': id, 'org_slug': org_slug}, ['m', 'p', 't']
    )
    responses = _rows_to_responses(records, org_slug)
    if not responses:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'AI model with id {id!r} not found',
        )
    return responses[0]


@ai_models_router.patch('/{id}', response_model=AIModelResponse)
async def patch_ai_model(
    org_slug: str,
    id: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ai_model:update')),
    ],
) -> AIModelResponse:
    """Partially update a model using JSON Patch (RFC 6902).

    ``provider_id`` and ``allowed_team_ids`` are patchable alongside the
    properties; the team list is replaced as a set, so patching it to
    ``[]`` removes every ``ALLOWED_FOR`` edge. Patching ``access_scope``
    to ``organization`` clears them too, whatever the team list holds.

    Parameters:
        org_slug: Organization slug from the URL path.
        id: Model id.
        operations: JSON Patch operations.

    Returns:
        The updated model.

    Raises:
        400: Invalid patch or a read-only path.
        404: No such model, or the new provider is outside the org.
        409: The new slug or ``model_id`` collides.
        422: A team is outside the organization, ``restricted`` was left
            with no teams, or the patched values are invalid.

    """
    _ = auth
    current_response = await _fetch_response(db, org_slug, id)
    document: dict[str, typing.Any] = current_response.model_dump(
        mode='json',
        include={*_PATCHABLE_FIELDS, 'provider_id'},
    )
    document['allowed_team_ids'] = [
        team.id for team in current_response.allowed_teams
    ]
    patched = json_patch.apply_patch(document, operations, _READONLY_PATHS)

    provider_id = str(
        patched.get('provider_id') or current_response.provider_id
    )
    provider = await ai_providers.fetch_provider(db, org_slug, provider_id)
    try:
        team_ids = _TEAM_IDS.validate_python(
            patched.get('allowed_team_ids') or []
        )
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=422,
            detail=f'allowed_team_ids must be a list of ids: {e.errors()}',
        ) from e
    teams = await _resolve_teams(db, org_slug, team_ids)
    node = _build(
        {k: v for k, v in patched.items() if k in _PATCHABLE_FIELDS},
        provider,
        org_slug,
    )
    _validate_access(node.access_scope, teams)
    teams = _teams_for_scope(node.access_scope, teams)
    node.id = id
    node.created_at = current_response.created_at or node.created_at

    if node.slug != current_response.slug:
        await _assert_slug_free(db, org_slug, node.slug, exclude_id=id)
    if (
        node.model_id != current_response.model_id
        or provider.id != current_response.provider_id
    ):
        await _assert_model_id_free(
            db, provider.id, node.model_id, exclude_id=id
        )

    node.updated_at = datetime.datetime.now(datetime.UTC)
    props = node.model_dump(
        mode='json',
        exclude={
            'organization',
            'provider',
            'allowed_teams',
            'id',
            'created_at',
        },
    )
    set_stmt = set_clause('m', props)
    query = (
        f'MATCH (m:AIModel {{{{id: {{id}}}}}})'
        f' -[:BELONGS_TO]->(:Organization {{{{slug: {{org_slug}}}}}})'
        f' {set_stmt} RETURN m'
    )
    with conflict_on_unique_violation(
        f'AI model with slug {node.slug!r} already exists'
    ):
        records = await db.execute(
            query, {**props, 'id': id, 'org_slug': org_slug}, ['m']
        )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'AI model with id {id!r} not found',
        )
    if provider.id != current_response.provider_id:
        params = {'id': id, 'provider_id': provider.id, 'org_slug': org_slug}
        await db.execute(_LINK_PROVIDER_QUERY, params, ['id'])
        await db.execute(_UNLINK_OTHER_PROVIDERS_QUERY, params, [])
    await _replace_team_edges(db, org_slug, id, teams)
    return _to_response(node, provider.id, provider.name, teams)


@ai_models_router.delete('/{id}', status_code=204)
async def delete_ai_model(
    org_slug: str,
    id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ai_model:delete')),
    ],
) -> None:
    """Delete a model.

    Parameters:
        org_slug: Organization slug from the URL path.
        id: Model id.

    Raises:
        404: No such model in this organization.

    """
    _ = auth
    query: typing.LiteralString = """
    MATCH (m:AIModel {{id: {id}}})
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    DETACH DELETE m
    RETURN m
    """
    records = await db.execute(query, {'id': id, 'org_slug': org_slug})
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'AI model with id {id!r} not found',
        )


@ai_provider_imports_router.post(
    '/{id}/import-models', response_model=ImportResult, status_code=201
)
async def import_ai_models(
    org_slug: str,
    id: str,
    data: ImportModelsRequest,
    response: fastapi.Response,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ai_model:create')),
    ],
) -> ImportResult:
    """Create models from a discovery result.

    Every imported model lands enabled, ``chat``, and organization-wide;
    an admin narrows it afterwards. A ``model_id`` the provider already
    serves is reported in ``skipped`` rather than failing the batch, so
    re-importing after adding one model is not an error.

    Answers 201 when at least one model was created and 200 when every
    requested model was skipped, since nothing came into existence.

    Parameters:
        org_slug: Organization slug from the URL path.
        id: Provider id.
        data: The models selected from the discovery result.

    Returns:
        The models created, and the ``model_id`` values skipped.

    Raises:
        404: No such provider in this organization.

    """
    _ = auth
    provider = await ai_providers.fetch_provider(db, org_slug, id)
    existing = await _existing_model_ids(db, provider.id)
    taken = await _taken_slugs(db, org_slug)

    created: list[AIModelResponse] = []
    skipped: list[str] = []
    for item in data.models:
        if item.model_id in existing:
            skipped.append(item.model_id)
            continue
        name = item.display_name or item.model_id
        slug = _unique_slug(slugify.slugify(name) or 'model', taken)
        node = _build(
            {
                'name': name,
                'slug': slug,
                'model_id': item.model_id,
                'context_window': item.context_window,
                'max_output_tokens': item.max_output_tokens,
            },
            provider,
            org_slug,
        )
        created.append(await _insert(db, org_slug, node, provider, []))
        existing.add(item.model_id)
        taken.add(slug)
    if not created:
        response.status_code = 200
    return ImportResult(created=created, skipped=skipped)


def _unique_slug(base: str, taken: set[str]) -> str:
    """Return ``base``, or ``base-2``/``base-3``/... if it is taken."""
    if base not in taken:
        return base
    suffix = 2
    while f'{base}-{suffix}' in taken:
        suffix += 1
    return f'{base}-{suffix}'


_EXISTING_IDS_QUERY: typing.LiteralString = """
MATCH (m:AIModel)-[:SERVED_BY]->(:AIProvider {{id: {provider_id}}})
RETURN m.model_id AS model_id
"""

_TAKEN_SLUGS_QUERY: typing.LiteralString = """
MATCH (m:AIModel)-[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN m.slug AS slug
"""


async def _existing_model_ids(db: graph.Graph, provider_id: str) -> set[str]:
    """Return the ``model_id`` values the provider already serves."""
    records = await db.execute(
        _EXISTING_IDS_QUERY, {'provider_id': provider_id}, ['model_id']
    )
    return {
        str(value)
        for value in (
            graph.parse_agtype(record['model_id']) for record in records
        )
        if value
    }


async def _taken_slugs(db: graph.Graph, org_slug: str) -> set[str]:
    """Return every model slug already used in the organization."""
    records = await db.execute(
        _TAKEN_SLUGS_QUERY, {'org_slug': org_slug}, ['slug']
    )
    return {
        str(value)
        for value in (graph.parse_agtype(record['slug']) for record in records)
        if value
    }


__all__ = [
    'AIModelResponse',
    'ai_models_router',
    'ai_provider_imports_router',
]
