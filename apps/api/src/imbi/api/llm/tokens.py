"""The vendor token cache of the AI Providers (WIF plan 4.6).

One :class:`imbi.common.llm.tokens.TokenCache` for each process, with
one slot for each AI Provider that uses the ``workload_identity`` auth
kind. The key holds the provider driver and target, and the identity
source of its organization. A change to one of them makes a new entry.

The token is never logged.
"""

import collections.abc
import json
import typing

from imbi.api.secret_broker import identity, store
from imbi.common import graph, models
from imbi.common.llm import tokens
from imbi.common.plugins.identity import AccessToken, IdentityError

#: The cache of this process.
CACHE = tokens.TokenCache()


def _key(
    provider: models.AIProvider,
    wif: models.AIProviderWorkloadIdentity,
    setting: dict[str, typing.Any] | None,
) -> str:
    return json.dumps(
        [
            provider.driver,
            wif.model_dump(),
            setting
            and [setting['type'], setting['config'], setting['updated_at']],
        ],
        sort_keys=True,
        default=str,
    )


async def get(
    secrets: store.SecretStore, provider: models.AIProvider
) -> AccessToken:
    """Return a valid access token for ``provider``.

    Raises:
        IdentityError: The provider has no workload identity, or no
            token could be minted and no valid token is cached.

    """
    wif = provider.workload_identity
    if wif is None:
        raise IdentityError('workload_identity_not_configured')
    setting = await secrets.identity_source(wif.organization_id)
    return await CACHE.get(
        provider.id,
        _key(provider, wif, setting),
        lambda: identity.ai_provider_token(provider, setting),
    )


async def call[T](
    secrets: store.SecretStore,
    provider: models.AIProvider,
    fn: collections.abc.Callable[[str], collections.abc.Awaitable[T]],
    unauthorized: collections.abc.Callable[[Exception], bool],
) -> T:
    """Return ``fn(token)``; after a ``401``, one retry with a new token.

    ``unauthorized(exc)`` tells if an exception of ``fn`` is a ``401``.
    """
    token = (await get(secrets, provider)).token
    try:
        return await fn(token)
    except Exception as exc:
        if not unauthorized(exc):
            raise
    CACHE.invalidate(provider.id, token)
    return await fn((await get(secrets, provider)).token)


class ProviderToken:
    """The token of one fixed AI Provider, for an SDK client of imbi-api.

    Each :meth:`get` reads the provider again, so a change to it takes
    effect at the next call.
    """

    def __init__(
        self,
        provider_id: str,
        db: collections.abc.Callable[[], graph.Graph | None],
        secrets: collections.abc.Callable[[], store.SecretStore],
    ) -> None:
        self._id = provider_id
        self._db = db
        self._secrets = secrets

    async def get(self) -> str:
        from imbi.api.endpoints import ai_providers

        db = self._db()
        if db is None:
            raise IdentityError('unavailable', retryable=True)
        provider = await ai_providers.fetch_provider(db, self._id)
        return (await get(self._secrets(), provider)).token

    def invalidate(self, failed: str) -> None:
        CACHE.invalidate(self._id, failed)
