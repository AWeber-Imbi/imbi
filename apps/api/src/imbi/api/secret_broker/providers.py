"""The secret providers of the broker (ADR 0022, plan sections 9.2, 9.7).

The provider contract is :mod:`imbi.common.plugins.secrets`, re-exported
here. Plugins declare provider classes in
:attr:`PluginManifest.secret_providers
<imbi.common.plugins.base.PluginManifest.secret_providers>` (the AWS
plugin: ``aws_secrets_manager``, the GitHub plugin: ``github_app``).
:func:`get` creates one instance of each on first use, with
:class:`_Host` for the broker services. ``fake`` is for tests only.
"""

import datetime
import logging
import typing
import uuid

import pydantic

from imbi.common import graph
from imbi.common.plugins import registry as plugin_registry
from imbi.common.plugins import secrets
from imbi.common.plugins.identity import AccessToken, TokenExchanger
from imbi.common.plugins.secrets import (
    ALL_CAPABILITIES,
    ERROR_STATUS,
    BrokerError,
    CredentialClass,
    Health,
    InvalidConfiguration,
    Material,
    ResolveContext,
    select_field,
)
from imbi.common.plugins.secrets import SecretCapability as Capability
from imbi.common.plugins.secrets import SecretProvider as Provider

LOGGER = logging.getLogger(__name__)

__all__ = [
    'ALL_CAPABILITIES',
    'ERROR_STATUS',
    'PROVIDERS',
    'BrokerError',
    'Capability',
    'CredentialClass',
    'FakeProvider',
    'Health',
    'InvalidConfiguration',
    'Material',
    'Provider',
    'ResolveContext',
    'all_providers',
    'get',
    'select_field',
]


# --- fake ----------------------------------------------------------------


class _FakeLocator(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='forbid')

    key: str = pydantic.Field(min_length=1)


class FakeProvider(secrets.SecretProvider):
    """A provider for tests, with every capability.

    Values live in process memory (:attr:`values`), never in the
    configuration. A ``dynamic`` binding issues a revocable lease.
    """

    type = 'fake'
    label = 'Fake (tests only)'
    capabilities = ALL_CAPABILITIES

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.leases: set[str] = set()
        self.revoked: list[str] = []
        self.fail_revoke = False
        self.unavailable = False

    def validate_config(
        self, config: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        if config:
            raise secrets.InvalidConfiguration(
                'The fake provider takes no configuration'
            )
        return {}

    def validate_locator(
        self,
        locator: dict[str, typing.Any],
        credential_class: secrets.CredentialClass,
    ) -> dict[str, typing.Any]:
        return secrets.validate_model(_FakeLocator, locator)

    async def health(
        self, config: dict[str, typing.Any], organization_id: str
    ) -> secrets.Health:
        if self.unavailable:
            return secrets.Health('unhealthy', 'unreachable')
        return secrets.Health('healthy', identity={'provider': 'fake'})

    async def validate_binding(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        organization_id: str,
        binding_id: uuid.UUID | None = None,
    ) -> dict[str, typing.Any]:
        return {'exists': locator['key'] in self.values}

    async def resolve(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        field: str | None,
        context: secrets.ResolveContext,
    ) -> secrets.Material:
        if self.unavailable:
            raise secrets.BrokerError(
                'secret_provider_unavailable', 'unreachable'
            )
        value = self.values.get(locator['key'])
        if value is None:
            raise secrets.BrokerError(
                'secret_materialization_failed', 'not_found'
            )
        material = secrets.Material(secrets.select_field(value, field))
        if context.credential_class == 'dynamic':
            material.lease_id = f'fake-lease-{uuid.uuid4()}'
            material.revocable = True
            material.renewable = True
            material.credential_expires_at = datetime.datetime.now(
                datetime.UTC
            ) + datetime.timedelta(seconds=context.ttl_seconds)
            self.leases.add(material.lease_id)
        return material

    async def renew(
        self, config: dict[str, typing.Any], lease_id: str, ttl_seconds: int
    ) -> datetime.datetime:
        return datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            seconds=ttl_seconds
        )

    async def revoke(
        self, config: dict[str, typing.Any], lease_id: str
    ) -> None:
        if self.fail_revoke:
            raise secrets.BrokerError(
                'provider_revocation_failed', 'unreachable'
            )
        self.leases.discard(lease_id)
        self.revoked.append(lease_id)


# --- registry ------------------------------------------------------------


class _Host:
    """The broker services of :class:`secrets.SecretProviderHost`."""

    def graph(self) -> graph.Graph:
        from imbi.api import lifespans

        db = lifespans._graph  # pyright: ignore[reportPrivateUsage]
        if db is None:
            raise BrokerError(
                'secret_provider_unavailable', 'graph_unavailable'
            )
        return db

    async def provider_key(
        self,
        organization_id: str,
        reference: str,
        *,
        consumer: uuid.UUID | None,
        host: str,
        app_id: str,
        task_id: uuid.UUID | None = None,
    ) -> Material:
        from imbi.api import secret_broker

        return await secret_broker.get_broker().provider_key(
            organization_id,
            reference,
            consumer=consumer,
            host=host,
            app_id=app_id,
            task_id=task_id,
        )

    async def check_provider_key(
        self,
        organization_id: str,
        reference: str,
        *,
        host: str,
        app_id: str,
    ) -> object:
        from imbi.api import secret_broker

        return await secret_broker.get_broker().check_provider_key(
            organization_id, reference, host=host, app_id=app_id
        )

    async def vendor_token(
        self,
        organization_id: str,
        exchanger: TokenExchanger,
        target: dict[str, typing.Any],
        *,
        agent_id: str,
    ) -> AccessToken:
        from imbi.api import secret_broker
        from imbi.api.secret_broker import identity, store

        return await identity.vendor_token(
            self.graph(),
            store.SecretStore(secret_broker.get_broker().pool),
            organization_id,
            exchanger,
            target,
            agent_id=agent_id,
        )


#: The providers, by type. One instance each.
PROVIDERS: dict[str, Provider] = {'fake': FakeProvider()}
#: The ``(plugin slug, type)`` conflicts already logged.
_REPORTED: set[tuple[str, str]] = set()
#: The providers that :func:`_load` added, by type.
_LOADED: dict[str, Provider] = {}


def reconcile[T](
    attribute: str,
    kind: str,
    registry: dict[str, T],
    loaded: dict[str, T],
    reported: set[tuple[str, str]],
    factory: typing.Callable[[typing.Any], T],
) -> None:
    """Make ``registry`` agree with the loaded plugins.

    ``attribute`` is the manifest list of classes (``secret_providers``).
    Remove the instances that this function added for plugins that are
    now disabled or not installed. Add one instance (``factory(cls)``)
    for each new class. A type that is already registered keeps its
    instance. Each conflict is logged once.
    """
    entries = plugin_registry.list_plugins()
    declared = {
        cls for entry in entries for cls in getattr(entry.manifest, attribute)
    }
    for item_type, item in list(loaded.items()):
        if type(item) not in declared:
            del loaded[item_type]
            if registry.get(item_type) is item:
                del registry[item_type]
    for entry in entries:
        for cls in getattr(entry.manifest, attribute):
            current = registry.get(cls.type)
            key = (entry.manifest.slug, cls.type)
            if current is None:
                try:
                    registry[cls.type] = loaded[cls.type] = factory(cls)
                except Exception as err:  # noqa: BLE001 - skip this plugin
                    if key not in reported:
                        reported.add(key)
                        LOGGER.error(
                            'Plugin %s %s %r failed to load: %s',
                            entry.manifest.slug,
                            kind,
                            cls.type,
                            type(err).__name__,
                        )
            elif not isinstance(current, cls) and key not in reported:
                reported.add(key)
                LOGGER.error(
                    'Plugin %s declares %s type %r, which is already '
                    'registered; ignored',
                    entry.manifest.slug,
                    kind,
                    cls.type,
                )


def _load() -> None:
    reconcile(
        'secret_providers',
        'secret provider',
        PROVIDERS,
        _LOADED,
        _REPORTED,
        lambda cls: cls(_Host()),
    )


def all_providers() -> list[Provider]:
    """Return every provider, with those of newly loaded plugins."""
    _load()
    return list(PROVIDERS.values())


def get(provider_type: str) -> Provider:
    """Return the provider of a type.

    Raises:
        BrokerError: ``operation_not_supported`` for an unknown type, or
            the type of a plugin that is not installed or is disabled.

    """
    _load()
    provider = PROVIDERS.get(provider_type)
    if provider is None:
        raise BrokerError('operation_not_supported', 'unknown_provider_type')
    return provider
