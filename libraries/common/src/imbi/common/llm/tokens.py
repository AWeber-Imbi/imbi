"""Access token renewal for AI Providers (WIF plan 4.6).

- :class:`TokenCache` holds one token for each slot and renews it:

  1. Time is monotonic. The entry renews at the lesser of 5 minutes or
     20 percent of the issued lifetime before expiry, less a jitter of
     at most half of that threshold.
  2. One renewal at a time for each slot (a lock); concurrent calls
     wait for it.
  3. While the old token is valid, a failed renewal returns the old
     token and the next attempt waits (1 to 30 seconds, doubled each
     time).
  4. After a ``401``, :meth:`TokenCache.invalidate` drops the entry only
     when the failed token is still the current one.
  5. A different ``key`` for the same slot makes a new entry.

- :class:`BearerAuth` sends the token on each request of an ``httpx``
  client, and after a ``401`` sends the request one more time with a
  new token. A ``401`` comes before the body, so this is also safe for
  a streaming call.
- :class:`ServiceToken` gets the AI Provider token of this service from
  imbi-api (``POST /ai-providers/token``).

A token is never logged.
"""

import asyncio
import collections.abc
import dataclasses
import datetime
import random
import time
import typing

import anthropic
import httpx

from imbi.common.llm.discovery import OAUTH_BETA
from imbi.common.plugins.identity import AccessToken, IdentityError

RENEW_MAX = 300.0
RENEW_FRACTION = 0.2
BACKOFF_MIN = 1.0
BACKOFF_MAX = 30.0

Mint = collections.abc.Callable[[], collections.abc.Awaitable[AccessToken]]


@dataclasses.dataclass(slots=True)
class _Entry:
    key: str
    token: AccessToken
    expires: float
    renew_at: float
    retry_at: float = 0.0
    backoff: float = 0.0


def _renew_at(now: float, lifetime: float) -> float:
    threshold = min(RENEW_MAX, RENEW_FRACTION * lifetime)
    return now + lifetime - threshold - random.uniform(0, threshold / 2)  # noqa: S311


class TokenCache:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(self, slot: str, key: str, mint: Mint) -> AccessToken:
        """Return a valid token for ``slot``; ``mint`` makes a new one.

        Raises:
            IdentityError: No token could be minted and no valid token
                is cached.

        """
        entry = self._fresh(slot, key)
        if entry is not None:
            return entry.token
        lock = self._locks.setdefault(slot, asyncio.Lock())
        async with lock:
            entry = self._fresh(slot, key)
            if entry is not None:
                return entry.token
            current = self._entries.get(slot)
            if current is not None and current.key != key:
                current = None
            try:
                token = await mint()
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
            self._entries[slot] = _Entry(
                key=key,
                token=token,
                expires=now + lifetime,
                renew_at=_renew_at(now, lifetime),
            )
            return token

    def invalidate(self, slot: str, failed: str) -> None:
        """Drop the entry after a ``401`` when ``failed`` is current."""
        entry = self._entries.get(slot)
        if entry is not None and entry.token.token == failed:
            del self._entries[slot]

    def forget(self, slot: str) -> None:
        """Drop the entry of a slot that is no longer used."""
        self._entries.pop(slot, None)
        self._locks.pop(slot, None)

    def _fresh(self, slot: str, key: str) -> _Entry | None:
        """The entry when it needs no renewal attempt now."""
        entry = self._entries.get(slot)
        if entry is None or entry.key != key:
            return None
        now = time.monotonic()
        if now >= entry.expires:
            return None
        return entry if now < max(entry.renew_at, entry.retry_at) else None


class TokenSource(typing.Protocol):
    async def get(self) -> str: ...

    def invalidate(self, failed: str) -> None: ...


class BearerAuth(httpx.Auth):
    """Sign each request with the token of ``source`` (Anthropic OAuth)."""

    def __init__(self, source: TokenSource) -> None:
        self._source = source

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> collections.abc.AsyncGenerator[httpx.Request, httpx.Response]:
        token = await self._source.get()
        response = yield _sign(request, token)
        if response.status_code == httpx.codes.UNAUTHORIZED:
            self._source.invalidate(token)
            yield _sign(request, await self._source.get())


def _sign(request: httpx.Request, token: str) -> httpx.Request:
    request.headers['Authorization'] = f'Bearer {token}'
    # An SDK that read ANTHROPIC_API_KEY must not send it with a token.
    request.headers.pop('x-api-key', None)
    beta = request.headers.get('anthropic-beta', '')
    if OAUTH_BETA not in beta:
        request.headers['anthropic-beta'] = (
            f'{beta},{OAUTH_BETA}' if beta else OAUTH_BETA
        )
    return request


def bearer_client(
    source: TokenSource, **kwargs: typing.Any
) -> anthropic.AsyncAnthropic:
    """An ``AsyncAnthropic`` client that sends the token of ``source``."""
    return anthropic.AsyncAnthropic(
        # BearerAuth replaces it on each request.
        auth_token='imbi-ai-provider',
        http_client=anthropic.DefaultAsyncHttpxClient(auth=BearerAuth(source)),
        **kwargs,
    )


class ServiceToken:
    """The AI Provider token of this service, from imbi-api.

    ``api_token`` is the API key of the service account. imbi-api finds
    the AI Provider from that account; the request names no provider.
    """

    def __init__(self, api_url: str, api_token: str) -> None:
        self._url = f'{api_url.rstrip("/")}/ai-providers/token'
        self._api_token = api_token
        self._cache = TokenCache()
        self._failed: str | None = None

    async def get(self) -> str:
        return (await self._cache.get('service', '', self._mint)).token

    def invalidate(self, failed: str) -> None:
        self._cache.invalidate('service', failed)
        # imbi-api renews its own entry only when this token is current.
        self._failed = failed

    async def _mint(self) -> AccessToken:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    self._url,
                    json={'failed': self._failed},
                    headers={'Authorization': f'Bearer {self._api_token}'},
                )
        except httpx.HTTPError:
            raise IdentityError('unreachable', retryable=True) from None
        if response.status_code >= 500:
            raise IdentityError('unavailable', retryable=True)
        if response.status_code != httpx.codes.OK:
            raise IdentityError('token_refused')
        try:
            body = response.json()
            token = AccessToken(
                body['token'],
                datetime.datetime.fromisoformat(body['expires_at']),
            )
        except (ValueError, KeyError, TypeError):
            raise IdentityError('provider_error') from None
        self._failed = None
        return token
