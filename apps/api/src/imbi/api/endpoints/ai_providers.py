"""Org-scoped CRUD for configured LLM providers.

An :class:`imbi.common.models.AIProvider` is one configured instance of
a *driver* — the drivers themselves are static code
(:mod:`imbi.common.llm.drivers`) exposed by ``GET /ai-provider-drivers``,
not graph nodes, so adding a driver is a release rather than a backfill.

The provider's API key is accepted as plaintext, encrypted immediately
via :mod:`imbi.common.auth.encryption`, and persisted only as
``credentials_encrypted``. It is never returned, echoed, or logged.
Responses carry ``has_credentials``, ``credential_hint`` (the last four
characters, stored in the clear at write time so an admin can tell two
keys apart) and ``credential_updated_at``.
"""

import datetime
import logging
import typing

import fastapi
import pydantic
import slugify

from imbi.api.auth import permissions
from imbi.api.endpoints._helpers import conflict_on_unique_violation
from imbi.api.graph_sql import props_template, set_clause
from imbi.common import graph, models
from imbi.common import patch as json_patch
from imbi.common.auth.encryption import (
    decrypt_config_value,
    encrypt_config_value,
)
from imbi.common.llm import discovery, drivers

LOGGER = logging.getLogger(__name__)

ai_provider_drivers_router = fastapi.APIRouter(
    prefix='/ai-provider-drivers',
    tags=['AI Models'],
)

ai_providers_router = fastapi.APIRouter(tags=['AI Models'])

AuthKind = typing.Literal['api_key', 'iam', 'none']

#: Provider fields an admin may set through create / patch. Everything
#: else on the node is either identity (``id``), timestamps, or
#: credential state, which only the credentials routes may touch.
_PATCHABLE_FIELDS: tuple[str, ...] = (
    'name',
    'slug',
    'description',
    'icon',
    'driver',
    'base_url',
    'enabled',
    'region',
    'project_id',
)

#: Paths a patch may not target. Credential state is reachable only
#: through the credentials routes, which carry their own permission, and
#: the derived fields are computed per response. Without these a patch
#: aimed at one of them would be dropped silently and answered 200,
#: which reads as "applied".
_READONLY_PATHS: frozenset[str] = json_patch.READONLY_PATHS | frozenset(
    [
        '/auth_kind',
        '/credential_hint',
        '/credential_updated_at',
        '/credentials_encrypted',
        '/enabled_model_count',
        '/has_credentials',
        '/is_builtin_driver',
        '/model_count',
        '/organization',
    ]
)


class AIProviderCreate(pydantic.BaseModel):
    """Request body for configuring a provider.

    ``api_key`` is write-only plaintext: it is encrypted before the node
    is persisted and never appears in a response.
    """

    name: str
    driver: models.AIProviderDriver
    slug: str | None = None
    base_url: str | None = None
    description: str | None = None
    icon: str | None = None
    enabled: bool = True
    region: str | None = None
    project_id: str | None = None
    api_key: str | None = None


class AIProviderResponse(pydantic.BaseModel):
    """A configured provider, with credential state but no credential."""

    id: str
    name: str
    slug: str
    description: str | None = None
    icon: str | None = None
    driver: models.AIProviderDriver
    base_url: str | None = None
    enabled: bool = True
    region: str | None = None
    project_id: str | None = None
    auth_kind: AuthKind = 'none'
    has_credentials: bool = False
    credential_hint: str | None = None
    credential_updated_at: datetime.datetime | None = None
    model_count: int = 0
    enabled_model_count: int = 0
    is_builtin_driver: bool = True
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None


class AIProviderCredentials(pydantic.BaseModel):
    """Request body for setting a provider's API key."""

    api_key: str = pydantic.Field(min_length=1)


class DiscoveredModel(pydantic.BaseModel):
    """One model reported by a provider's list-models API."""

    model_config = pydantic.ConfigDict(protected_namespaces=())

    model_id: str
    display_name: str
    created_at: datetime.datetime | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    already_configured: bool = False


class DiscoveryResponse(pydantic.BaseModel):
    """Result of pulling a provider's model list."""

    models: list[DiscoveredModel]
    fetched_at: datetime.datetime


def auth_kind(driver: str, has_credentials: bool) -> AuthKind:
    """Derive how a provider authenticates.

    A stored key always wins. Otherwise a driver that can authenticate
    from ambient cloud credentials (``bedrock``, ``vertex``) reports
    ``iam``, and everything else reports ``none`` — which the UI renders
    as "not configured yet".
    """
    if has_credentials:
        return 'api_key'
    info = drivers.get_driver(driver)
    return 'iam' if info is not None and info.supports_iam else 'none'


def to_response(
    node: models.AIProvider,
    model_count: int = 0,
    enabled_model_count: int = 0,
) -> AIProviderResponse:
    """Build a credential-free response from a persisted provider."""
    has_credentials = node.credentials_encrypted is not None
    return AIProviderResponse(
        id=node.id,
        name=node.name,
        slug=node.slug,
        description=node.description,
        icon=None if node.icon is None else str(node.icon),
        driver=node.driver,
        base_url=node.base_url,
        enabled=node.enabled,
        region=node.region,
        project_id=node.project_id,
        auth_kind=auth_kind(node.driver, has_credentials),
        has_credentials=has_credentials,
        credential_hint=node.credential_hint,
        credential_updated_at=node.credential_updated_at,
        model_count=model_count,
        enabled_model_count=enabled_model_count,
        is_builtin_driver=node.driver != 'openai_compatible',
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


_LIST_QUERY: typing.LiteralString = """
MATCH (p:AIProvider)-[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN p
"""

_GET_QUERY: typing.LiteralString = """
MATCH (p:AIProvider {{id: {id}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN p
"""

_SLUG_TAKEN_QUERY: typing.LiteralString = """
MATCH (p:AIProvider {{slug: {slug}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN p.id AS id
"""

_COUNTS_QUERY: typing.LiteralString = """
MATCH (m:AIModel)-[:SERVED_BY]->(p:AIProvider)
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN p.id AS provider_id, m.enabled AS enabled
"""


async def model_counts(
    db: graph.Graph, org_slug: str
) -> dict[str, tuple[int, int]]:
    """Return ``{provider_id: (model_count, enabled_model_count)}``.

    Counted in Python from one flat row set rather than with Cypher
    aggregation: AGE drops ``ORDER BY`` ahead of an aggregate and the
    volume here is a handful of rows per organization.
    """
    records = await db.execute(
        _COUNTS_QUERY,
        {'org_slug': org_slug},
        ['provider_id', 'enabled'],
    )
    counts: dict[str, tuple[int, int]] = {}
    for record in records:
        provider_id = graph.parse_agtype(record['provider_id'])
        if not provider_id:
            continue
        total, enabled = counts.get(str(provider_id), (0, 0))
        is_enabled = bool(graph.parse_agtype(record['enabled']))
        counts[str(provider_id)] = (total + 1, enabled + int(is_enabled))
    return counts


def _parse(raw: typing.Any, org_slug: str) -> models.AIProvider:
    """Parse an agtype vertex into an ``AIProvider``.

    The ``BELONGS_TO`` edge is a relationship, not a property, so the
    organization is reattached from the scope the row was matched under.
    """
    props: typing.Any = graph.parse_agtype(raw)
    return models.AIProvider.model_validate(
        {**props, 'organization': {'name': '', 'slug': org_slug}}
    )


async def fetch_provider(
    db: graph.Graph, org_slug: str, id: str
) -> models.AIProvider:
    """Fetch a provider scoped to ``org_slug`` or raise 404.

    The organization edge is part of the match, so a valid id under the
    wrong organization is indistinguishable from a missing one.
    """
    records = await db.execute(
        _GET_QUERY, {'id': id, 'org_slug': org_slug}, ['p']
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'AI provider with id {id!r} not found',
        )
    return _parse(records[0]['p'], org_slug)


async def _assert_slug_free(
    db: graph.Graph, org_slug: str, slug: str, exclude_id: str | None = None
) -> None:
    """Raise 409 when ``slug`` is already used in this organization."""
    records = await db.execute(
        _SLUG_TAKEN_QUERY, {'slug': slug, 'org_slug': org_slug}, ['id']
    )
    for record in records:
        existing = graph.parse_agtype(record['id'])
        if existing and str(existing) != exclude_id:
            raise fastapi.HTTPException(
                status_code=409,
                detail=(
                    f'AI provider with slug {slug!r} already exists in '
                    f'organization {org_slug!r}'
                ),
            )


def _build(payload: dict[str, typing.Any], org_slug: str) -> models.AIProvider:
    """Validate provider properties into a node or raise 422."""
    try:
        return models.AIProvider(
            organization=models.Organization(name='', slug=org_slug),
            **payload,
        )
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=422,
            detail=f'Validation error: {e.errors()}',
        ) from e


#: A hint is only stored for keys long enough that four trailing
#: characters cannot reconstruct a meaningful part of the secret.
MIN_HINTABLE_KEY_LENGTH = 8


def credential_hint(api_key: str) -> str | None:
    """Return the stored hint for ``api_key`` (its last four chars).

    A key shorter than :data:`MIN_HINTABLE_KEY_LENGTH` gets no hint at
    all: four characters of an eight-character secret is half of it, and
    the hint is stored and returned in the clear.
    """
    if len(api_key) < MIN_HINTABLE_KEY_LENGTH:
        return None
    return api_key[-4:]


@ai_provider_drivers_router.get('', response_model=list[drivers.DriverInfo])
async def list_ai_provider_drivers(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ai_model:read')),
    ],
) -> list[drivers.DriverInfo]:
    """List the provider drivers this build knows how to talk to.

    Returns:
        The static driver catalog, in display order.

    """
    _ = auth
    return list(drivers.DRIVERS)


@ai_providers_router.get('/', response_model=list[AIProviderResponse])
async def list_ai_providers(
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ai_model:read')),
    ],
) -> list[AIProviderResponse]:
    """List an organization's configured providers, ordered by name.

    Parameters:
        org_slug: Organization slug from the URL path.

    Returns:
        Every configured provider, without credentials.

    """
    _ = auth
    records = await db.execute(_LIST_QUERY, {'org_slug': org_slug}, ['p'])
    counts = await model_counts(db, org_slug)
    responses = [
        to_response(node, *counts.get(node.id, (0, 0)))
        for node in (_parse(record['p'], org_slug) for record in records)
    ]
    return sorted(responses, key=lambda r: r.name.lower())


@ai_providers_router.post(
    '/', response_model=AIProviderResponse, status_code=201
)
async def create_ai_provider(
    org_slug: str,
    data: AIProviderCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ai_model:create')),
    ],
) -> AIProviderResponse:
    """Configure a provider for an organization.

    Parameters:
        org_slug: Organization slug from the URL path.
        data: Provider configuration. ``api_key`` is plaintext and is
            encrypted before persistence.

    Returns:
        The created provider, without credentials.

    Raises:
        404: The organization does not exist.
        409: A provider with the same slug exists in this organization.
        422: Invalid configuration (bad ``base_url``, or
            ``openai_compatible`` without one).

    """
    _ = auth
    payload = data.model_dump(exclude={'api_key', 'slug'})
    payload['slug'] = data.slug or slugify.slugify(data.name)
    node = _build(payload, org_slug)
    if data.api_key:
        node.credentials_encrypted = encrypt_config_value(data.api_key)
        node.credential_hint = credential_hint(data.api_key)
        node.credential_updated_at = datetime.datetime.now(datetime.UTC)

    await _assert_slug_free(db, org_slug, node.slug)

    now = datetime.datetime.now(datetime.UTC)
    node.created_at = now
    node.updated_at = now
    props = node.model_dump(mode='json', exclude={'organization'})
    query = (
        f'MATCH (o:Organization {{{{slug: {{org_slug}}}}}})'
        f' CREATE (p:AIProvider {props_template(props)})'
        f' CREATE (p)-[:BELONGS_TO]->(o)'
        f' RETURN p'
    )
    with conflict_on_unique_violation(
        f'AI provider with slug {node.slug!r} already exists'
    ):
        records = await db.execute(
            query, {**props, 'org_slug': org_slug}, ['p']
        )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization with slug {org_slug!r} not found',
        )
    return to_response(_parse(records[0]['p'], org_slug))


@ai_providers_router.get('/{id}', response_model=AIProviderResponse)
async def get_ai_provider(
    org_slug: str,
    id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ai_model:read')),
    ],
) -> AIProviderResponse:
    """Get one configured provider.

    Parameters:
        org_slug: Organization slug from the URL path.
        id: Provider id.

    Returns:
        The provider, without credentials.

    Raises:
        404: No such provider in this organization.

    """
    _ = auth
    node = await fetch_provider(db, org_slug, id)
    counts = await model_counts(db, org_slug)
    return to_response(node, *counts.get(node.id, (0, 0)))


@ai_providers_router.patch('/{id}', response_model=AIProviderResponse)
async def patch_ai_provider(
    org_slug: str,
    id: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ai_model:update')),
    ],
) -> AIProviderResponse:
    """Partially update a provider using JSON Patch (RFC 6902).

    Only the configuration fields are patchable; credentials are
    reachable solely through the credentials routes, which carry their
    own permission.

    Parameters:
        org_slug: Organization slug from the URL path.
        id: Provider id.
        operations: JSON Patch operations.

    Returns:
        The updated provider, without credentials.

    Raises:
        400: Invalid patch or a read-only path.
        404: No such provider in this organization.
        409: The new slug collides within this organization.
        422: The patched configuration is invalid.

    """
    _ = auth
    existing = await fetch_provider(db, org_slug, id)
    current = {field: getattr(existing, field) for field in _PATCHABLE_FIELDS}
    current['icon'] = None if existing.icon is None else str(existing.icon)
    patched = json_patch.apply_patch(current, operations, _READONLY_PATHS)
    node = _build(
        {k: v for k, v in patched.items() if k in _PATCHABLE_FIELDS},
        org_slug,
    )
    node.id = existing.id
    node.created_at = existing.created_at
    node.credentials_encrypted = existing.credentials_encrypted
    node.credential_hint = existing.credential_hint
    node.credential_updated_at = existing.credential_updated_at

    if node.slug != existing.slug:
        await _assert_slug_free(db, org_slug, node.slug, exclude_id=id)
    return to_response(await persist(db, org_slug, node))


@ai_providers_router.delete('/{id}', status_code=204)
async def delete_ai_provider(
    org_slug: str,
    id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ai_model:delete')),
    ],
) -> None:
    """Delete a provider that serves no models.

    There is deliberately no cascade: models outlive the provider row an
    operator happens to be editing, so they must be deleted or moved
    first.

    Parameters:
        org_slug: Organization slug from the URL path.
        id: Provider id.

    Raises:
        404: No such provider in this organization.
        409: The provider still serves models.

    """
    _ = auth
    await fetch_provider(db, org_slug, id)
    counts = await model_counts(db, org_slug)
    total = counts.get(id, (0, 0))[0]
    if total:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'AI provider {id!r} still serves {total} model(s); '
                f'delete or move them first'
            ),
        )
    query: typing.LiteralString = """
    MATCH (p:AIProvider {{id: {id}}})
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    DETACH DELETE p
    RETURN p
    """
    records = await db.execute(query, {'id': id, 'org_slug': org_slug})
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'AI provider with id {id!r} not found',
        )


@ai_providers_router.put(
    '/{id}/credentials', response_model=AIProviderResponse
)
async def set_ai_provider_credentials(
    org_slug: str,
    id: str,
    data: AIProviderCredentials,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('ai_model:credentials')
        ),
    ],
) -> AIProviderResponse:
    """Set or replace a provider's API key.

    The plaintext key is encrypted immediately and never echoed; only
    its last four characters are retained, as ``credential_hint``.

    Parameters:
        org_slug: Organization slug from the URL path.
        id: Provider id.
        data: The plaintext API key.

    Returns:
        The provider, with refreshed credential metadata.

    Raises:
        404: No such provider in this organization.

    """
    _ = auth
    node = await fetch_provider(db, org_slug, id)
    node.credentials_encrypted = encrypt_config_value(data.api_key)
    node.credential_hint = credential_hint(data.api_key)
    node.credential_updated_at = datetime.datetime.now(datetime.UTC)
    LOGGER.info(
        'Replaced credentials for AI provider %s in organization %s',
        id,
        org_slug,
    )
    counts = await model_counts(db, org_slug)
    return to_response(
        await persist(db, org_slug, node), *counts.get(id, (0, 0))
    )


@ai_providers_router.delete(
    '/{id}/credentials', response_model=AIProviderResponse
)
async def delete_ai_provider_credentials(
    org_slug: str,
    id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('ai_model:credentials')
        ),
    ],
) -> AIProviderResponse:
    """Remove a provider's stored API key.

    Parameters:
        org_slug: Organization slug from the URL path.
        id: Provider id.

    Returns:
        The provider, with credential metadata cleared.

    Raises:
        404: No such provider in this organization.

    """
    _ = auth
    node = await fetch_provider(db, org_slug, id)
    node.credentials_encrypted = None
    node.credential_hint = None
    node.credential_updated_at = None
    LOGGER.info(
        'Removed credentials for AI provider %s in organization %s',
        id,
        org_slug,
    )
    counts = await model_counts(db, org_slug)
    return to_response(
        await persist(db, org_slug, node), *counts.get(id, (0, 0))
    )


@ai_providers_router.post('/{id}/discover', response_model=DiscoveryResponse)
async def discover_ai_provider_models(
    org_slug: str,
    id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('ai_model:read')),
    ],
) -> DiscoveryResponse:
    """Pull a provider's model list using its stored credentials.

    Doubles as a connection test. Nothing is written: the caller picks
    from the result and posts to ``/import-models``. Errors from the
    provider are sanitized to a status line so a failing call can never
    surface the key.

    Parameters:
        org_slug: Organization slug from the URL path.
        id: Provider id.

    Returns:
        The provider's models, each flagged with whether it is already
        configured in this organization.

    Raises:
        404: No such provider in this organization.
        409: The provider has no stored credentials.
        422: The driver does not support discovery.
        502: The provider rejected or failed the call.

    """
    _ = auth
    node = await fetch_provider(db, org_slug, id)
    info = drivers.get_driver(node.driver)
    if info is None or not info.supports_discovery:
        raise fastapi.HTTPException(
            status_code=422,
            detail=f'Driver {node.driver!r} does not support discovery',
        )
    api_key = decrypt_config_value(node.credentials_encrypted)
    if not api_key:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'AI provider {id!r} has no stored credentials to '
                f'discover models with'
            ),
        )
    try:
        found = await discovery.list_models(
            node.driver,
            api_key,
            drivers.resolve_base_url(node.driver, node.base_url),
        )
    except discovery.DiscoveryError as exc:
        raise fastapi.HTTPException(status_code=502, detail=str(exc)) from exc

    configured = await _configured_model_ids(db, org_slug, id)
    return DiscoveryResponse(
        models=[
            DiscoveredModel(
                model_id=item.model_id,
                display_name=item.display_name,
                created_at=item.created_at,
                context_window=item.context_window,
                max_output_tokens=item.max_output_tokens,
                already_configured=item.model_id in configured,
            )
            for item in found
        ],
        fetched_at=datetime.datetime.now(datetime.UTC),
    )


_CONFIGURED_QUERY: typing.LiteralString = """
MATCH (m:AIModel)-[:SERVED_BY]->(p:AIProvider {{id: {id}}})
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN m.model_id AS model_id
"""


async def _configured_model_ids(
    db: graph.Graph, org_slug: str, provider_id: str
) -> set[str]:
    """Return the ``model_id`` values already configured on a provider."""
    records = await db.execute(
        _CONFIGURED_QUERY,
        {'id': provider_id, 'org_slug': org_slug},
        ['model_id'],
    )
    found: set[str] = set()
    for record in records:
        value = graph.parse_agtype(record['model_id'])
        if value:
            found.add(str(value))
    return found


async def persist(
    db: graph.Graph, org_slug: str, node: models.AIProvider
) -> models.AIProvider:
    """Write a mutated provider back, scoped to its organization."""
    node.updated_at = datetime.datetime.now(datetime.UTC)
    props = node.model_dump(
        mode='json', exclude={'organization', 'id', 'created_at'}
    )
    set_stmt = set_clause('p', props)
    query = (
        f'MATCH (p:AIProvider {{{{id: {{id}}}}}})'
        f' -[:BELONGS_TO]->(:Organization {{{{slug: {{org_slug}}}}}})'
        f' {set_stmt} RETURN p'
    )
    with conflict_on_unique_violation(
        f'AI provider with slug {node.slug!r} already exists'
    ):
        records = await db.execute(
            query, {**props, 'id': node.id, 'org_slug': org_slug}, ['p']
        )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'AI provider with id {node.id!r} not found',
        )
    return _parse(records[0]['p'], org_slug)


__all__ = [
    'AIProviderResponse',
    'ai_provider_drivers_router',
    'ai_providers_router',
    'fetch_provider',
    'model_counts',
    'to_response',
]
