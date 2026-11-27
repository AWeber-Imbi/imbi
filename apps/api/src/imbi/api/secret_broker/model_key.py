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
from imbi.common import graph, models
from imbi.common.auth.encryption import decrypt_config_value
from imbi.common.plugins import secrets
from imbi.common.plugins.identity import IdentityError

if typing.TYPE_CHECKING:
    from imbi.api.secret_broker import store

#: No binding can use this scope.
SCOPE = 'imbi'
REFERENCE = f'secret://{SCOPE}/model'
PURPOSE = 'model_inference'
#: The ``type`` of the provider row of a model key decision.
TYPE = 'ai_provider'

_QUERY: typing.LiteralString = """
MATCH (p:AIProvider {{id: {id}}})
      -[:BELONGS_TO]->(o:Organization {{id: {org_id}}})
RETURN p, o
"""


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

    def __init__(self, secret_store: store.SecretStore) -> None:
        super().__init__(providers._Host())  # pyright: ignore[reportPrivateUsage]
        #: Gives the identity source of a workload identity.
        self.secret_store = secret_store

    async def resolve(
        self,
        config: dict[str, typing.Any],
        locator: dict[str, typing.Any],
        field: str | None,
        context: secrets.ResolveContext,
    ) -> secrets.Material:
        from imbi.api.llm import tokens

        records = await self.host.graph().execute(
            _QUERY,
            {
                'id': locator['ai_provider_id'],
                'org_id': context.organization_id,
            },
            ['p', 'o'],
        )
        if not records:
            raise secrets.BrokerError(
                'secret_materialization_failed', 'ai_provider_not_found'
            )
        provider = models.AIProvider.model_validate(
            {
                **graph.parse_agtype(records[0]['p']),
                'organization': graph.parse_agtype(records[0]['o']),
            }
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
            token = await tokens.get(self.secret_store, provider)
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
