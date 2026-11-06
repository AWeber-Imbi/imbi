"""The vendor token cache of the AI Providers (WIF plan 4.6).

One cache for each process. An entry holds the access token of one AI
Provider that uses the ``workload_identity`` auth kind:

1. Time is monotonic. The entry renews at the lesser of 5 minutes or 20
   percent of the issued lifetime before expiry, less a jitter of at
   most half of that threshold.
2. One renewal at a time for each provider (a lock); concurrent calls
   wait for it.
3. While the old token is valid, a failed renewal returns the old token
   and the next attempt waits (1 to 30 seconds, doubled each time).
4. After a ``401``, :meth:`TokenCache.invalidate` drops the entry only
   when the failed token is still the current one. The caller retries
   one time.
5. The key holds the provider, its organization, driver, and target,
   and the identity source of the organization. A change to one of them
   makes a new entry.

The token is never logged.
"""

import asyncio
import dataclasses
import json
import random
import time
import typing

from imbi.api.secret_broker import identity, store
from imbi.common import models
from imbi.common.plugins.identity import IdentityError

RENEW_MAX = 300.0
RENEW_FRACTION = 0.2
BACKOFF_MIN = 1.0
BACKOFF_MAX = 30.0


@dataclasses.dataclass(slots=True)
class _Entry:
    key: str
    token: str
    expires: float
    renew_at: float
    retry_at: float = 0.0
    backoff: float = 0.0


def _renew_at(now: float, lifetime: float) -> float:
    threshold = min(RENEW_MAX, RENEW_FRACTION * lifetime)
    return now + lifetime - threshold - random.uniform(0, threshold / 2)  # noqa: S311


def _key(
    provider: models.AIProvider, setting: dict[str, typing.Any] | None
) -> str:
    wif = provider.workload_identity
    return json.dumps(
        [
            provider.driver,
            wif.model_dump() if wif else None,
            setting
            and [setting['type'], setting['config'], setting['updated_at']],
        ],
        sort_keys=True,
        default=str,
    )


class TokenCache:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(
        self, secrets: store.SecretStore, provider: models.AIProvider
    ) -> str:
        """Return a valid access token for ``provider``.

        Raises:
            IdentityError: No token could be minted and no valid token
                is cached.

        """
        wif = provider.workload_identity
        setting = (
            await secrets.identity_source(wif.organization_id) if wif else None
        )
        key = _key(provider, setting)
        entry = self._fresh(provider.id, key)
        if entry is not None:
            return entry.token
        lock = self._locks.setdefault(provider.id, asyncio.Lock())
        async with lock:
            entry = self._fresh(provider.id, key)
            if entry is not None:
                return entry.token
            current = self._entries.get(provider.id)
            if current is not None and current.key != key:
                current = None
            try:
                token = await identity.ai_provider_token(provider, setting)
            except IdentityError:
                now = time.monotonic()
                if current is None or now >= current.expires:
                    raise
                current.backoff = min(
                    BACKOFF_MAX, max(BACKOFF_MIN, current.backoff * 2)
                )
                current.retry_at = now + current.backoff
                return current.token
            now = time.monotonic()
            lifetime = max(0.0, token.expires_at.timestamp() - time.time())
            self._entries[provider.id] = _Entry(
                key=key,
                token=token.token,
                expires=now + lifetime,
                renew_at=_renew_at(now, lifetime),
            )
            return token.token

    def invalidate(self, provider_id: str, failed: str) -> None:
        """Drop the entry after a ``401`` when ``failed`` is current."""
        entry = self._entries.get(provider_id)
        if entry is not None and entry.token == failed:
            del self._entries[provider_id]

    def _fresh(self, provider_id: str, key: str) -> _Entry | None:
        """The entry when it needs no renewal attempt now."""
        entry = self._entries.get(provider_id)
        if entry is None or entry.key != key:
            return None
        now = time.monotonic()
        if now >= entry.expires:
            return None
        if now < entry.renew_at or now < entry.retry_at:
            return entry
        return None


#: The cache of this process.
CACHE = TokenCache()
