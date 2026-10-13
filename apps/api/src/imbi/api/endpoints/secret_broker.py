"""Management endpoints of the secrets broker (ADR 0022, plan 9.3).

Providers, bindings, grants, resolutions, and audit events of one
organization. No response contains secret material, a handle, or a
provider lease id: the response models have no field for them.

The runtime routes (create, materialize, release by the executor) need
the runner tokens and come with the harness (plan phase P2). They call
:class:`imbi.api.secret_broker.broker.Broker`.

Every route needs the caller to be a member of the organization
(``MEMBER_OF``): see :mod:`imbi.api.auth.organizations`.
"""

import contextlib
import datetime
import typing
import uuid
from collections import abc

import fastapi
import pydantic

from imbi.api import secret_broker
from imbi.api.auth import organizations, permissions
from imbi.api.endpoints._helpers import (
    conflict_on_unique_violation,
    fetch_or_404,
)
from imbi.api.secret_broker import audit, broker, providers, store

OrgId = organizations.MemberOrgId

DeliveryMode = broker.DeliveryMode
Purpose = typing.Annotated[
    str, pydantic.StringConstraints(pattern=r'^[a-z][a-z0-9_]{0,63}$')
]
FieldName = typing.Annotated[
    str, pydantic.StringConstraints(pattern=r'^[A-Za-z0-9_-]{1,128}$')
]
DeliveryTarget = typing.Annotated[
    str, pydantic.StringConstraints(pattern=r'^[A-Za-z0-9_.-]{1,128}$')
]
Ttl = typing.Annotated[int, pydantic.Field(ge=1, le=broker.MAX_TTL_SECONDS)]
Name = typing.Annotated[
    str, pydantic.StringConstraints(pattern=r'^[a-z0-9][a-z0-9_-]{0,99}$')
]
Id = typing.Annotated[
    str, pydantic.StringConstraints(min_length=1, max_length=256)
]


ProviderRead = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('secret_provider:read')),
]
ProviderWrite = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('secret_provider:write')),
]
BindingRead = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('secret_binding:read')),
]
BindingWrite = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('secret_binding:write')),
]
GrantRead = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('secret_grant:read')),
]
GrantWrite = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('secret_grant:write')),
]
ResolutionRead = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('secret_resolution:read')),
]
ResolutionManage = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(
        permissions.require_permission('secret_resolution:manage')
    ),
]
AuditRead = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission('secret_audit:read')),
]


def _error(err: providers.BrokerError) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=err.status,
        detail={
            'error': err.code,
            'reason': err.reason,
            'message': err.code.replace('_', ' ').capitalize(),
        },
    )


def _invalid(
    message: str, code: str = 'invalid_configuration'
) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=422,
        detail={'error': code, 'message': message},
    )


async def _audit(
    secrets: store.SecretStore,
    event_type: audit.EventType,
    org_id: str,
    auth: permissions.AuthContext,
    **ids: typing.Any,
) -> None:
    await secrets.audit(
        audit.Event.model_validate(
            {
                'organization_id': org_id,
                'type': event_type,
                'actor': auth.principal_name,
            }
            | {k: str(v) for k, v in ids.items()}
        )
    )


# --- Schemas -----------------------------------------------------------


class SecretProviderCreate(pydantic.BaseModel):
    name: Name
    type: str
    enabled: bool = True
    config: dict[str, typing.Any] = {}


class SecretProviderPatch(pydantic.BaseModel):
    name: Name | None = None
    enabled: bool | None = None
    config: dict[str, typing.Any] | None = None


class SecretProvider(pydantic.BaseModel):
    id: uuid.UUID
    name: str
    type: str
    enabled: bool
    config: dict[str, typing.Any]
    capabilities: list[str]
    health_status: str | None
    health_reason: str | None
    health_checked_at: datetime.datetime | None
    created_by: str
    created_at: datetime.datetime
    updated_at: datetime.datetime


class SecretProviderType(pydantic.BaseModel):
    type: str
    label: str
    capabilities: list[str]


class SecretProviderTest(pydantic.BaseModel):
    status: str
    reason: str | None
    checked_at: datetime.datetime | None
    capabilities: list[str]
    identity: dict[str, str]


class SecretBindingCreate(pydantic.BaseModel):
    reference: str = pydantic.Field(
        description='secret://<scope>/<path>, without a field'
    )
    provider_id: uuid.UUID
    credential_class: providers.CredentialClass
    locator: dict[str, typing.Any]
    allowed_fields: list[FieldName] = []
    allowed_delivery_modes: list[DeliveryMode] = pydantic.Field(min_length=1)
    allowed_delivery_targets: list[DeliveryTarget] = pydantic.Field(
        default=[],
        description='When not empty, the only targets allowed. The '
        'denylist of unsafe environment names still applies.',
    )
    max_ttl_seconds: Ttl = 900
    enabled: bool = True
    description: str = ''


class SecretBindingPatch(pydantic.BaseModel):
    credential_class: providers.CredentialClass | None = None
    locator: dict[str, typing.Any] | None = None
    allowed_fields: list[FieldName] | None = None
    allowed_delivery_targets: list[DeliveryTarget] | None = None
    allowed_delivery_modes: list[DeliveryMode] | None = pydantic.Field(
        default=None, min_length=1
    )
    max_ttl_seconds: Ttl | None = None
    enabled: bool | None = None
    description: str | None = None


class SecretBinding(pydantic.BaseModel):
    id: uuid.UUID
    reference: str
    provider_id: uuid.UUID
    credential_class: str
    locator: dict[str, typing.Any]
    allowed_fields: list[str]
    allowed_delivery_modes: list[str]
    allowed_delivery_targets: list[str]
    max_ttl_seconds: int
    enabled: bool
    description: str
    created_by: str
    created_at: datetime.datetime
    updated_at: datetime.datetime


class SecretBindingValidation(pydantic.BaseModel):
    valid: bool
    reason: str | None = None
    metadata: dict[str, typing.Any] = {}


class SecretGrantCreate(pydantic.BaseModel):
    description: str = ''
    agent_ids: list[Id] = pydantic.Field(min_length=1)
    project_ids: list[Id] = pydantic.Field(
        default=[], description='Empty allows any project, and no project.'
    )
    binding_ids: list[uuid.UUID] = pydantic.Field(min_length=1)
    purposes: list[Purpose] = pydantic.Field(min_length=1)
    delivery_modes: list[DeliveryMode] = pydantic.Field(min_length=1)
    max_ttl_seconds: Ttl = 900
    enabled: bool = True


class SecretGrantPatch(pydantic.BaseModel):
    description: str | None = None
    agent_ids: list[Id] | None = pydantic.Field(default=None, min_length=1)
    project_ids: list[Id] | None = None
    binding_ids: list[uuid.UUID] | None = pydantic.Field(
        default=None, min_length=1
    )
    purposes: list[Purpose] | None = pydantic.Field(default=None, min_length=1)
    delivery_modes: list[DeliveryMode] | None = pydantic.Field(
        default=None, min_length=1
    )
    max_ttl_seconds: Ttl | None = None
    enabled: bool | None = None


class SecretGrant(pydantic.BaseModel):
    id: uuid.UUID
    description: str
    agent_ids: list[str]
    project_ids: list[str]
    binding_ids: list[uuid.UUID]
    purposes: list[str]
    delivery_modes: list[str]
    max_ttl_seconds: int
    enabled: bool
    created_by: str
    created_at: datetime.datetime
    updated_at: datetime.datetime


class SecretGrantEvaluate(pydantic.BaseModel):
    agent_id: Id
    project_id: Id | None = None
    reference: str
    purpose: Purpose
    delivery_mode: DeliveryMode
    ttl_seconds: Ttl = 300
    delivery_target: DeliveryTarget | None = None


class SecretGrantDecision(pydantic.BaseModel):
    allowed: bool
    error: str | None = None
    reason: str | None = None
    grant_id: uuid.UUID | None = None
    binding_id: uuid.UUID | None = None


class SecretProviderLease(pydantic.BaseModel):
    """Lease state only. The lease id never leaves imbi-api."""

    present: bool
    revocation_state: str
    revocation_reason: str | None
    revocation_attempted_at: datetime.datetime | None


class SecretResolution(pydantic.BaseModel):
    id: uuid.UUID
    binding_id: uuid.UUID
    grant_id: uuid.UUID
    provider_id: uuid.UUID
    reference: str
    agent_id: str
    project_id: str | None
    task_id: uuid.UUID
    runner_id: str
    purpose: str
    delivery_mode: str
    delivery_target: str | None
    state: str
    failure_reason: str | None
    materialization_limit: int
    materialization_count: int
    last_materialized_at: datetime.datetime | None
    credential_expires_at: datetime.datetime | None
    provider_lease: SecretProviderLease
    release_reason: str | None
    created_at: datetime.datetime
    expires_at: datetime.datetime
    released_at: datetime.datetime | None


class SecretAuditEvent(pydantic.BaseModel):
    event_id: str
    at: datetime.datetime
    type: str
    result: str
    reason: str
    actor: str
    agent_id: str
    project_id: str
    task_id: str
    runner_id: str
    provider_id: str
    binding_id: str
    grant_id: str
    resolution_id: str
    purpose: str
    delivery_mode: str


def _resolution(row: store.Row) -> dict[str, typing.Any]:
    return {
        **row,
        'provider_lease': {
            'present': row['lease_id'] is not None,
            'revocation_state': row['revocation_state'],
            'revocation_reason': row['revocation_reason'],
            'revocation_attempted_at': row['revocation_attempted_at'],
        },
    }


# --- Providers -----------------------------------------------------------

providers_router = fastapi.APIRouter(
    tags=['Secrets'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)


def _plugin(provider_type: str) -> providers.Provider:
    try:
        return providers.get(provider_type)
    except providers.BrokerError:
        raise _invalid(f'Unknown provider type {provider_type!r}') from None


@contextlib.contextmanager
def _role_conflict() -> abc.Generator[None]:
    """Translate :class:`store.RoleInUse` into a 409."""
    try:
        yield
    except store.RoleInUse as err:
        raise fastapi.HTTPException(
            status_code=409,
            detail={'error': 'role_arn_in_use', 'message': str(err)},
        ) from None


async def _config(
    plugin: providers.Provider,
    config: dict[str, typing.Any],
    org_id: str,
) -> dict[str, typing.Any]:
    """Validate a configuration, then check it against the provider."""
    try:
        config = plugin.validate_config(config)
        await plugin.check_config(config, org_id)
    except providers.InvalidConfiguration as err:
        raise _invalid(str(err), err.code) from None
    return config


@providers_router.get('/types', response_model=list[SecretProviderType])
async def list_provider_types(_: ProviderRead) -> list[dict[str, typing.Any]]:
    return [
        {
            'type': plugin.type,
            'label': plugin.label,
            'capabilities': sorted(plugin.capabilities),
        }
        for plugin in providers.PROVIDERS.values()
    ]


@providers_router.get('/', response_model=list[SecretProvider])
async def list_providers(
    org_id: OrgId, secrets: secret_broker.Store, _: ProviderRead
) -> list[store.Row]:
    return await secrets.list_all('providers', org_id)


@providers_router.post('/', status_code=201, response_model=SecretProvider)
async def create_provider(
    org_id: OrgId,
    data: SecretProviderCreate,
    secrets: secret_broker.Store,
    auth: ProviderWrite,
) -> store.Row:
    """Create a provider. Its configuration holds no credentials.

    Raises:
        409: The name is in use, or the role cannot be used
            (``role_arn_in_use``).
        422: Unknown type, or the configuration is not valid, or the
            role does not require the ExternalId
            (``role_does_not_require_external_id``).

    """
    plugin = _plugin(data.type)
    config = await _config(plugin, data.config, org_id)
    with (
        conflict_on_unique_violation(f'Provider {data.name!r} exists'),
        _role_conflict(),
    ):
        row = await secrets.create(
            'providers',
            org_id,
            {
                'name': data.name,
                'type': data.type,
                'enabled': data.enabled,
                'config': config,
                'capabilities': sorted(plugin.capabilities),
                'created_by': auth.principal_name,
            },
        )
    await _audit(
        secrets, 'secret_provider_created', org_id, auth, provider_id=row['id']
    )
    return row


@providers_router.get('/{provider_id}', response_model=SecretProvider)
async def get_provider(
    org_id: OrgId,
    provider_id: uuid.UUID,
    secrets: secret_broker.Store,
    _: ProviderRead,
) -> store.Row:
    return await fetch_or_404(
        secrets.get,
        'providers',
        org_id,
        provider_id,
        detail='Provider not found',
    )


@providers_router.patch('/{provider_id}', response_model=SecretProvider)
async def update_provider(
    org_id: OrgId,
    provider_id: uuid.UUID,
    data: SecretProviderPatch,
    secrets: secret_broker.Store,
    auth: ProviderWrite,
) -> store.Row:
    """Change a provider. Disabling it stops every unused handle.

    Raises:
        404: No such provider.
        409: The name is in use, or the role cannot be used
            (``role_arn_in_use``).
        422: The configuration is not valid, or the role does not
            require the ExternalId.

    """
    current = await get_provider(org_id, provider_id, secrets, auth)
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if 'config' in changes:
        changes['config'] = await _config(
            _plugin(current['type']), changes['config'], org_id
        )
    if not changes:
        return current
    with (
        conflict_on_unique_violation('The provider name is in use'),
        _role_conflict(),
    ):
        row = await fetch_or_404(
            secrets.update,
            'providers',
            org_id,
            provider_id,
            changes,
            detail='Provider not found',
        )
    await _audit(
        secrets,
        'secret_provider_updated',
        org_id,
        auth,
        provider_id=provider_id,
    )
    return row


@providers_router.delete('/{provider_id}', status_code=204)
async def delete_provider(
    org_id: OrgId,
    provider_id: uuid.UUID,
    secrets: secret_broker.Store,
    auth: ProviderWrite,
) -> None:
    """Delete a provider that no binding uses.

    Raises:
        404: No such provider.
        409: A binding uses the provider.

    """
    try:
        deleted = await secrets.delete('providers', org_id, provider_id)
    except store.InUse as err:
        raise fastapi.HTTPException(status_code=409, detail=str(err)) from None
    if not deleted:
        raise fastapi.HTTPException(
            status_code=404, detail='Provider not found'
        )
    await _audit(
        secrets,
        'secret_provider_deleted',
        org_id,
        auth,
        provider_id=provider_id,
    )


@providers_router.post(
    '/{provider_id}/test', response_model=SecretProviderTest
)
async def test_provider(
    org_id: OrgId,
    provider_id: uuid.UUID,
    secrets: secret_broker.Store,
    auth: ProviderWrite,
) -> dict[str, typing.Any]:
    """Check the provider: identity metadata, health, and capabilities.

    Raises:
        404: No such provider.
        422: The provider has no health check.

    """
    current = await get_provider(org_id, provider_id, secrets, auth)
    plugin = _plugin(current['type'])
    try:
        health = await plugin.health(current['config'], org_id)
    except providers.BrokerError as err:
        raise _error(err) from None
    row = await secrets.set_health(
        org_id, provider_id, health.status, health.reason
    )
    await secrets.audit(
        audit.Event(
            organization_id=org_id,
            type='secret_provider_tested',
            result='succeeded' if health.status == 'healthy' else 'failed',
            reason=health.reason or '',
            actor=auth.principal_name,
            provider_id=str(provider_id),
        )
    )
    return {
        'status': health.status,
        'reason': health.reason,
        'checked_at': row['health_checked_at'] if row else None,
        'capabilities': sorted(plugin.capabilities),
        'identity': health.identity,
    }


# --- Bindings ------------------------------------------------------------

bindings_router = fastapi.APIRouter(
    tags=['Secrets'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)


async def _locator(
    secrets: store.SecretStore,
    org_id: str,
    provider_id: uuid.UUID,
    locator: dict[str, typing.Any],
    credential_class: providers.CredentialClass,
) -> dict[str, typing.Any]:
    provider = await secrets.get('providers', org_id, provider_id)
    if provider is None:
        raise _invalid('The provider is not in the organization')
    plugin = _plugin(provider['type'])
    needed = broker.required_capability(credential_class)
    if needed not in plugin.capabilities:
        raise _invalid(
            f'A {credential_class} binding needs the {needed} capability'
        )
    try:
        return plugin.validate_locator(locator, credential_class)
    except providers.InvalidConfiguration as err:
        raise _invalid(str(err)) from None


@bindings_router.get('/', response_model=list[SecretBinding])
async def list_bindings(
    org_id: OrgId, secrets: secret_broker.Store, _: BindingRead
) -> list[store.Row]:
    return await secrets.list_all('bindings', org_id)


@bindings_router.post('/', status_code=201, response_model=SecretBinding)
async def create_binding(
    org_id: OrgId,
    data: SecretBindingCreate,
    secrets: secret_broker.Store,
    auth: BindingWrite,
) -> store.Row:
    """Map a reference to a provider location.

    Raises:
        409: The reference is bound already.
        422: The reference, provider, or locator is not valid.

    """
    try:
        reference = broker.parse_reference(data.reference, field=False)
    except providers.BrokerError as err:
        raise _error(err) from None
    values = data.model_dump()
    values['reference'] = str(reference)
    values['locator'] = await _locator(
        secrets, org_id, data.provider_id, data.locator, data.credential_class
    )
    values['created_by'] = auth.principal_name
    with conflict_on_unique_violation(f'{reference} is bound already'):
        row = await secrets.create('bindings', org_id, values)
    await _audit(
        secrets, 'secret_binding_created', org_id, auth, binding_id=row['id']
    )
    return row


@bindings_router.get('/{binding_id}', response_model=SecretBinding)
async def get_binding(
    org_id: OrgId,
    binding_id: uuid.UUID,
    secrets: secret_broker.Store,
    _: BindingRead,
) -> store.Row:
    return await fetch_or_404(
        secrets.get,
        'bindings',
        org_id,
        binding_id,
        detail='Binding not found',
    )


@bindings_router.patch('/{binding_id}', response_model=SecretBinding)
async def update_binding(
    org_id: OrgId,
    binding_id: uuid.UUID,
    data: SecretBindingPatch,
    secrets: secret_broker.Store,
    auth: BindingWrite,
) -> store.Row:
    """Change a binding. The reference and the provider do not change.

    Raises:
        404: No such binding.
        422: The locator is not valid.

    """
    current = await get_binding(org_id, binding_id, secrets, auth)
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if 'locator' in changes or 'credential_class' in changes:
        changes['locator'] = await _locator(
            secrets,
            org_id,
            current['provider_id'],
            typing.cast(
                dict[str, typing.Any],
                changes.get('locator', current['locator']),
            ),
            typing.cast(
                providers.CredentialClass,
                changes.get('credential_class', current['credential_class']),
            ),
        )
    if not changes:
        return current
    row = await fetch_or_404(
        secrets.update,
        'bindings',
        org_id,
        binding_id,
        changes,
        detail='Binding not found',
    )
    await _audit(
        secrets, 'secret_binding_updated', org_id, auth, binding_id=binding_id
    )
    return row


@bindings_router.delete('/{binding_id}', status_code=204)
async def delete_binding(
    org_id: OrgId,
    binding_id: uuid.UUID,
    secrets: secret_broker.Store,
    auth: BindingWrite,
) -> None:
    """Delete a binding that no grant, no active resolution, and no
    unrevoked provider lease uses.

    Raises:
        404: No such binding.
        409: A grant, an active resolution, or an unrevoked provider
            lease uses the binding.

    """
    try:
        deleted = await secrets.delete('bindings', org_id, binding_id)
    except store.InUse as err:
        raise fastapi.HTTPException(status_code=409, detail=str(err)) from None
    if not deleted:
        raise fastapi.HTTPException(
            status_code=404, detail='Binding not found'
        )
    await _audit(
        secrets, 'secret_binding_deleted', org_id, auth, binding_id=binding_id
    )


@bindings_router.post(
    '/{binding_id}/validate', response_model=SecretBindingValidation
)
async def validate_binding(
    org_id: OrgId,
    binding_id: uuid.UUID,
    secrets: secret_broker.Store,
    auth: BindingWrite,
) -> dict[str, typing.Any]:
    """Ask the provider for metadata of the bound secret, not its value.

    Raises:
        404: No such binding.

    """
    binding = await get_binding(org_id, binding_id, secrets, auth)
    provider = await secrets.get('providers', org_id, binding['provider_id'])
    if provider is None:  # pragma: no cover - the foreign key keeps it
        raise fastapi.HTTPException(status_code=404, detail='No provider')
    try:
        metadata = await _plugin(provider['type']).validate_binding(
            provider['config'], binding['locator'], org_id
        )
    except providers.BrokerError as err:
        return {'valid': False, 'reason': err.reason}
    return {'valid': True, 'metadata': metadata}


# --- Grants --------------------------------------------------------------

grants_router = fastapi.APIRouter(
    tags=['Secrets'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)


def _unknown_bindings() -> fastapi.HTTPException:
    return _invalid('A binding is not in the organization')


@grants_router.get('/', response_model=list[SecretGrant])
async def list_grants(
    org_id: OrgId, secrets: secret_broker.Store, _: GrantRead
) -> list[store.Row]:
    return await secrets.list_all('grants', org_id)


@grants_router.post('/', status_code=201, response_model=SecretGrant)
async def create_grant(
    org_id: OrgId,
    data: SecretGrantCreate,
    secrets: secret_broker.Store,
    auth: GrantWrite,
) -> store.Row:
    """Create an allow rule with exact ids.

    Raises:
        422: A binding is not in the organization.

    """
    try:
        row = await secrets.create(
            'grants',
            org_id,
            data.model_dump() | {'created_by': auth.principal_name},
        )
    except store.UnknownBindings:
        raise _unknown_bindings() from None
    await _audit(
        secrets, 'secret_grant_created', org_id, auth, grant_id=row['id']
    )
    return row


@grants_router.post('/evaluate', response_model=SecretGrantDecision)
async def evaluate_grants(
    org_id: OrgId,
    data: SecretGrantEvaluate,
    secrets: secret_broker.Store,
    _: GrantRead,
) -> dict[str, typing.Any]:
    """Say whether the grants allow a request. No provider call, and
    no resolution."""
    try:
        reference = broker.parse_reference(data.reference)
        target = broker.check_delivery(
            data.delivery_mode, data.delivery_target
        )
        decision = await secrets.evaluate(
            org_id,
            data.agent_id,
            data.project_id,
            reference,
            data.purpose,
            data.delivery_mode,
            data.ttl_seconds,
            target,
        )
    except providers.BrokerError as err:
        return {'allowed': False, 'error': err.code, 'reason': err.reason}
    return {
        'allowed': True,
        'grant_id': decision.grant['id'],
        'binding_id': decision.binding['id'],
    }


@grants_router.get('/{grant_id}', response_model=SecretGrant)
async def get_grant(
    org_id: OrgId,
    grant_id: uuid.UUID,
    secrets: secret_broker.Store,
    _: GrantRead,
) -> store.Row:
    return await fetch_or_404(
        secrets.get, 'grants', org_id, grant_id, detail='Grant not found'
    )


@grants_router.patch('/{grant_id}', response_model=SecretGrant)
async def update_grant(
    org_id: OrgId,
    grant_id: uuid.UUID,
    data: SecretGrantPatch,
    secrets: secret_broker.Store,
    auth: GrantWrite,
) -> store.Row:
    """Change a grant. Disabling it stops every unused handle.

    Raises:
        404: No such grant.
        422: A binding is not in the organization.

    """
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        return await get_grant(org_id, grant_id, secrets, auth)
    try:
        row = await fetch_or_404(
            secrets.update,
            'grants',
            org_id,
            grant_id,
            changes,
            detail='Grant not found',
        )
    except store.UnknownBindings:
        raise _unknown_bindings() from None
    await _audit(
        secrets, 'secret_grant_updated', org_id, auth, grant_id=grant_id
    )
    return row


@grants_router.delete('/{grant_id}', status_code=204)
async def delete_grant(
    org_id: OrgId,
    grant_id: uuid.UUID,
    secrets: secret_broker.Store,
    auth: GrantWrite,
) -> None:
    """Delete a grant. Unused handles that it allowed stop working."""
    if not await secrets.delete('grants', org_id, grant_id):
        raise fastapi.HTTPException(status_code=404, detail='Grant not found')
    await _audit(
        secrets, 'secret_grant_deleted', org_id, auth, grant_id=grant_id
    )


# --- Resolutions ---------------------------------------------------------

resolutions_router = fastapi.APIRouter(
    tags=['Secrets'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)


@resolutions_router.get('/', response_model=list[SecretResolution])
async def list_resolutions(
    org_id: OrgId,
    secrets: secret_broker.Store,
    _: ResolutionRead,
    state: typing.Literal['active', 'released', 'expired', 'failed']
    | None = None,
    task_id: uuid.UUID | None = None,
    limit: typing.Annotated[int, fastapi.Query(ge=1, le=500)] = 100,
) -> list[dict[str, typing.Any]]:
    """Return resolutions, newest first."""
    found = await secrets.resolutions(
        org_id, state=state, task_id=task_id, limit=limit
    )
    return [_resolution(row) for row in found]


@resolutions_router.get('/{resolution_id}', response_model=SecretResolution)
async def get_resolution(
    org_id: OrgId,
    resolution_id: uuid.UUID,
    secrets: secret_broker.Store,
    _: ResolutionRead,
) -> dict[str, typing.Any]:
    row = await fetch_or_404(
        secrets.resolution,
        org_id,
        resolution_id,
        detail='Resolution not found',
    )
    return _resolution(row)


@resolutions_router.post(
    '/{resolution_id}/release', response_model=SecretResolution
)
async def release_resolution(
    org_id: OrgId,
    resolution_id: uuid.UUID,
    service: secret_broker.Broker,
    auth: ResolutionManage,
) -> dict[str, typing.Any]:
    """Release a resolution and revoke its provider lease. Idempotent.

    A failed revocation shows in ``provider_lease.revocation_state``.

    Raises:
        404: No such resolution.

    """
    try:
        row = await service.release(
            resolution_id,
            reason='released_by_operator',
            actor=auth.principal_name,
            organization_id=org_id,
        )
    except providers.BrokerError as err:
        raise _error(err) from None
    return _resolution(row)


@resolutions_router.post(
    '/{resolution_id}/revoke-provider-lease', response_model=SecretResolution
)
async def revoke_provider_lease(
    org_id: OrgId,
    resolution_id: uuid.UUID,
    service: secret_broker.Broker,
    auth: ResolutionManage,
) -> dict[str, typing.Any]:
    """Revoke the provider lease of a resolution, or retry a failure.

    Raises:
        404: No such resolution.
        409: The resolution has no revocable lease.
        502: The provider did not revoke the lease.

    """
    try:
        row = await service.revoke_provider_lease(
            org_id, resolution_id, auth.principal_name
        )
    except providers.BrokerError as err:
        raise _error(err) from None
    return _resolution(row)


# --- Audit ---------------------------------------------------------------

audit_router = fastapi.APIRouter(
    tags=['Secrets'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)


@audit_router.get('/', response_model=list[SecretAuditEvent])
async def list_audit_events(
    org_id: OrgId,
    _: AuditRead,
    resolution_id: uuid.UUID | None = None,
    event_type: typing.Annotated[str, fastapi.Query(alias='type')] = '',
    before: datetime.datetime | None = None,
    before_event_id: str = '',
    limit: typing.Annotated[int, fastapi.Query(ge=1, le=500)] = 100,
) -> list[dict[str, typing.Any]]:
    """Return audit events, newest first.

    To page, send the ``at`` and ``event_id`` of the last event as
    ``before`` and ``before_event_id``. Events with the same ``at`` are
    then not skipped.

    Raises:
        503: ClickHouse is not available.

    """
    try:
        return await audit.search(
            org_id,
            resolution_id=str(resolution_id) if resolution_id else '',
            event_type=event_type,
            before=before,
            before_event_id=before_event_id,
            limit=limit,
        )
    except Exception:  # noqa: BLE001 - ClickHouse is down
        raise fastapi.HTTPException(
            status_code=503, detail='Audit events are not available'
        ) from None
