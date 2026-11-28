"""The model key of an agent task (ADR 0022 amendment).

The reserved reference :data:`REFERENCE` means "the key of the AI
provider that the claim pinned on the task". A ``model_inference``
resolution of it needs no binding and no grant: the claim authorized
the model with the resolver. The broker gets the provider id from the
task row, never from the runner.

:class:`ModelKeyProvider` gives the material: the decrypted stored key
of the provider, or a workload identity access token (``bearer``, with
its expiry). It is not in the provider registry, so no admin can make a
secret provider of its type.
"""

import typing

from imbi.api.secret_broker import providers
from imbi.common.auth.encryption import decrypt_config_value
from imbi.common.llm import resolve as llm_resolve
from imbi.common.plugins import secrets
from imbi.common.plugins.identity import IdentityError

if typing.TYPE_CHECKING:
    import psycopg_pool

#: No binding can use this scope.
SCOPE = 'imbi'
REFERENCE = f'secret://{SCOPE}/model'
PURPOSE = 'model_inference'
#: The ``type`` of the provider row of a model key decision.
TYPE = 'ai_provider'


def pinned(task: dict[str, typing.Any], purpose: str) -> str:
    """Return the AI provider id that the claim pinned on ``task`` (the
    row that the broker locked), for a request of :data:`REFERENCE`.

    Raises:
        BrokerError: Another purpose, or a task with no pinned provider.

    """
    if purpose != PURPOSE:
        raise secrets.BrokerError('secret_access_denied', 'model_key_purpose')
    if task['ai_provider_id'] is None:
        raise secrets.BrokerError('secret_access_denied', 'model_not_pinned')
    return str(task['ai_provider_id'])


def recheck(task: dict[str, typing.Any], ai_provider_id: str) -> None:
    """Refuse a materialization when a later claim pinned another
    provider on the task.

    Raises:
        BrokerError: ``ai_provider_changed``.

    """
    if task['ai_provider_id'] != ai_provider_id:
        raise secrets.BrokerError(
            'secret_access_denied', 'ai_provider_changed'
        )


def decision_rows(
    ai_provider_id: str,
) -> tuple[dict[str, typing.Any], dict[str, typing.Any]]:
    """Return the binding and provider rows of a model key decision.

    They are not stored. They hold only what the materialization reads.
    """
    binding: dict[str, typing.Any] = {
        'id': None,
        'locator': {'ai_provider_id': ai_provider_id},
        'allowed_fields': [],
        'allowed_delivery_targets': [],
        'credential_class': 'static',
    }
    return binding, {'id': None, 'type': TYPE, 'config': {}}


class ModelKeyProvider(secrets.SecretProvider):
    """Reads the credential of an AI provider of the task's
    organization."""

    type = TYPE
    label = 'AI provider (model key)'
    capabilities = frozenset()

    def __init__(
        self, pool: psycopg_pool.AsyncConnectionPool[typing.Any]
    ) -> None:
        super().__init__(providers._Host())  # pyright: ignore[reportPrivateUsage]
        #: Gives the identity source of a workload identity.
        self.pool = pool

    async def resolve(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        field: str | None,
        context: secrets.ResolveContext,
    ) -> secrets.Material:
        # Not at the top: store imports the broker, which imports this.
        # The shared generate.with_credentials is not used: the runner
        # needs the expiry of a workload identity token to renew it.
        from imbi.api.llm import tokens
        from imbi.api.secret_broker import store

        provider = await llm_resolve.find_provider(
            self.host.graph(),
            context.organization_id,
            locator['ai_provider_id'],
        )
        if provider is None:
            raise secrets.BrokerError(
                'secret_materialization_failed', 'ai_provider_not_found'
            )
        if not provider.enabled:
            raise secrets.BrokerError(
                'secret_access_denied', 'ai_provider_disabled'
            )
        key = decrypt_config_value(provider.credentials_encrypted)
        if key:
            return secrets.Material(key.encode())
        if provider.workload_identity is None:
            raise secrets.BrokerError(
                'secret_materialization_failed', 'ai_provider_no_credential'
            )
        try:
            token = await tokens.get(store.SecretStore(self.pool), provider)
        except IdentityError as err:
            raise secrets.BrokerError(
                'secret_provider_unavailable'
                if err.retryable
                else 'secret_materialization_failed',
                err.reason,
            ) from None
        return secrets.Material(
            token.token.encode(),
            bearer=True,
            credential_expires_at=token.expires_at,
        )
