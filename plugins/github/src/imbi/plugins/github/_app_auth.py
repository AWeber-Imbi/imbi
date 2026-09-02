"""GitHub App installation-token minting for webhook actions.

The commit-sync webhook plugin has no acting user, so when it is
configured with GitHub App credentials (``app_id`` + ``private_key``) it
mints a short-lived *installation* access token per call instead of
carrying a static PAT.  Tokens are cached process-wide until shortly
before they expire, so a busy org makes one token-exchange round-trip
per hour per ``(app, installation, host)`` rather than one per webhook
delivery.

All three GitHub flavors work unchanged: the caller resolves the API
base via :func:`imbi.plugins.github._hosts.host_to_api_base` and passes
it in, so the JWT exchange hits ``api.github.com``,
``api.<tenant>.ghe.com``, or ``<ghes>/api/v3`` as appropriate.
"""

from __future__ import annotations

import base64
import binascii
import collections.abc
import datetime
import logging
import time
import typing

import httpx
import jwt

from imbi.common import cache
from imbi.common.plugins.errors import PluginInstallationMissing
from imbi.plugins.github.deployment import (
    _auth_headers,  # pyright: ignore[reportPrivateUsage]
    _raise_on_401,  # pyright: ignore[reportPrivateUsage]
)

LOGGER = logging.getLogger(__name__)


class AppNotInstalledError(PluginInstallationMissing):
    """The GitHub App is not installed for the target repository.

    Raised by :func:`_discover_installation_id` when GitHub answers the
    installation lookup with a 404 -- the App has not been installed on
    the repo/org, or the repo was renamed/removed.  Sync callers treat
    this as a clean skip rather than a hard failure, so an uninstalled
    App never surfaces as a Sentry error on a backfill worker.

    A *mutating* caller must not treat it that way: a silent skip there
    means the deploy or rollback did not happen and nothing said so.
    Those callers pass ``cache_misses=False`` (see
    :func:`installation_token`) and surface it as a terminal error.
    """


_HTTP_TIMEOUT_SECONDS = 10.0
# GitHub rejects an App JWT whose ``exp`` is more than 10 minutes out;
# sign for 9 to leave room for clock skew between us and GitHub.
_JWT_TTL_SECONDS = 540
# Re-mint an installation token this many seconds before it actually
# expires so an in-flight request never races the expiry boundary.
_TOKEN_REFRESH_MARGIN_SECONDS = 300.0
# Installation tokens last an hour; assume ~55 minutes when GitHub omits
# (or we can't parse) the ``expires_at`` field.
_DEFAULT_TOKEN_TTL_SECONDS = 3300.0

# Upper bounds on the process-wide caches.  Both were unbounded, so a
# long-lived worker touching many repositories grew them for the life of
# the process -- one installation entry per repository, forever.  The
# bounds are generous: eviction costs one extra round-trip, and an
# installation covers an entire org, so a process rarely holds more than
# a handful of distinct ids.
_TOKEN_CACHE_MAX_ENTRIES = 1024
_INSTALL_CACHE_MAX_ENTRIES = 4096
_NOT_INSTALLED_CACHE_MAX_ENTRIES = 4096
# Long enough to stop a sweep re-paying the 404 on every call for an
# uninstalled repo, short enough that installing the App during an
# incident is visible within a minute.  Mutating callers do not consult
# this cache at all (see ``cache_misses``), so the blackout never
# outlives an operator's fix on the path that matters.
_NOT_INSTALLED_TTL_SECONDS = 60.0

#: The permission set a token is minted with, canonicalized for use as
#: part of a cache key.  ``None`` means "whatever the installation
#: grants" -- the pre-scoping behaviour, still used by callers that have
#: not declared what they need.
Scope: typing.TypeAlias = collections.abc.Mapping[str, str] | None
FrozenScope: typing.TypeAlias = tuple[tuple[str, str], ...] | None


def freeze_scope(scope: Scope) -> FrozenScope:
    """Canonical, hashable form of a requested permission set.

    Sorted so that ``{'a': 'read', 'b': 'write'}`` and
    ``{'b': 'write', 'a': 'read'}`` are one cache entry, and distinct
    from ``None`` -- a token minted with the App's full grant is *not*
    interchangeable with one minted for ``{'contents': 'read'}``, and
    conflating them would silently undo the down-scoping.
    """
    if scope is None:
        return None
    return tuple(sorted(scope.items()))


# Process-wide caches.  Tokens carry a per-entry deadline derived from
# GitHub's own ``expires_at`` rather than a uniform TTL; installation ids
# do not expire (an App being uninstalled surfaces as a 404 on the next
# mint, which evicts the id).
#
# The requested scope is part of the token key, and that is a
# correctness requirement rather than an optimization: a narrower token
# must never be served to a caller that asked for a wider one, or a
# ``contents: read`` token would answer a ``contents: write`` request
# and the write would 403 from GitHub at the worst possible moment.
_TOKEN_CACHE: cache.LRUCache[tuple[str, str, str, FrozenScope], str] = (
    cache.LRUCache(_TOKEN_CACHE_MAX_ENTRIES)
)
_INSTALL_CACHE: cache.LRUCache[tuple[str, str, str, str], str] = (
    cache.LRUCache(_INSTALL_CACHE_MAX_ENTRIES)
)
# Negative cache: repositories the App is known not to be installed on.
# The value is unused; membership is the whole answer.
_NOT_INSTALLED_CACHE: cache.LRUCache[tuple[str, str, str, str], bool] = (
    cache.LRUCache(
        _NOT_INSTALLED_CACHE_MAX_ENTRIES, ttl=_NOT_INSTALLED_TTL_SECONDS
    )
)

# Serializes the cold-cache path.  Without it, N concurrent calls for
# one uncached key each mint their own token: GitHub happily issues them,
# the last write wins, and the rest are wasted round-trips against the
# App's rate limit.
#
# Two granularities, because a repo is not an installation.  The
# ``'repo'`` lock collapses concurrent callers for one repository, which
# is what dedupes *discovery*; the ``'install'`` lock collapses everyone
# who resolved to the same installation -- including callers for
# different repositories under it -- which is what dedupes *minting*,
# since the token belongs to the installation.  The tag keeps the two
# key spaces disjoint: an explicitly configured installation id takes the
# ``'repo'`` lock on its way in, and would otherwise deadlock against
# itself on the ``'install'`` lock, which is not reentrant.  Locks are
# always taken in that order, so the nesting cannot cycle.
_MINT_LOCK: cache.KeyedLock[tuple[str, ...]] = cache.KeyedLock()


def known_installation_id(
    app_id: str, base: str, owner: str, repo: str
) -> str | None:
    """The installation id already resolved for ``owner/repo``, if any.

    Read-only view of the discovery cache, for callers that want to
    *record* which installation carried an action out without forcing a
    lookup of their own.  Populated as a side effect of
    :func:`installation_token`, so a caller that just minted a token
    always finds it here.
    """
    return _INSTALL_CACHE.get((app_id, base, owner, repo))


def reset_cache() -> None:
    """Clear the process-wide token / installation caches (tests)."""
    _TOKEN_CACHE.clear()
    _INSTALL_CACHE.clear()
    _NOT_INSTALLED_CACHE.clear()


def _load_private_key(raw: str) -> str:
    """Return a PEM private key from raw PEM or a base64-encoded PEM.

    Operators may paste the key GitHub generated directly, or a
    single-line base64 encoding of it (handy where the config UI lacks a
    multi-line field).  Raises ``ValueError`` for anything else.
    """
    value = raw.strip()
    if '-----BEGIN' in value:
        return value
    try:
        decoded = base64.b64decode(value, validate=True).decode('utf-8')
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ValueError(
            'github-commit-sync private_key is neither a PEM nor a '
            'base64-encoded PEM'
        ) from exc
    if '-----BEGIN' not in decoded:
        raise ValueError(
            'github-commit-sync private_key decoded but is not a PEM'
        )
    return decoded


def _app_jwt(app_id: str, private_key: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {'iat': now - 60, 'exp': now + _JWT_TTL_SECONDS, 'iss': app_id},
        _load_private_key(private_key),
        algorithm='RS256',
    )


def _token_deadline(expires_at: object) -> float:
    """Map GitHub's ISO ``expires_at`` to a monotonic cache deadline."""
    now = time.monotonic()
    if not isinstance(expires_at, str):
        return now + _DEFAULT_TOKEN_TTL_SECONDS
    try:
        exp = datetime.datetime.fromisoformat(expires_at)
    except ValueError:
        return now + _DEFAULT_TOKEN_TTL_SECONDS
    remaining = (exp - datetime.datetime.now(datetime.UTC)).total_seconds()
    return now + max(0.0, remaining - _TOKEN_REFRESH_MARGIN_SECONDS)


def _cached_token(
    app_id: str,
    base: str,
    installation_id: str | None,
    owner: str,
    repo: str,
    scope: FrozenScope,
) -> str | None:
    """Return a live cached token for ``scope``, or ``None`` to mint one.

    The installation id is the one the caller configured, falling back
    to a previously discovered one for the repo -- so a repo whose
    installation is already known is served from cache without the
    discovery round-trip.
    """
    install = installation_id or _INSTALL_CACHE.get(
        (app_id, base, owner, repo)
    )
    if install is None:
        return None
    return _TOKEN_CACHE.get((app_id, install, base, scope))


async def _discover_installation_id(
    client: httpx.AsyncClient, owner: str, repo: str
) -> str:
    resp = await client.get(f'/repos/{owner}/{repo}/installation')
    if resp.status_code == 404:
        raise AppNotInstalledError(
            f'no GitHub App installation found for {owner}/{repo}',
            owner_repo=f'{owner}/{repo}',
        )
    resp.raise_for_status()
    data = typing.cast('dict[str, typing.Any]', resp.json())
    install_id = data.get('id')
    if install_id is None:
        raise AppNotInstalledError(
            f'no GitHub App installation found for {owner}/{repo}',
            owner_repo=f'{owner}/{repo}',
        )
    return str(install_id)


async def _mint(
    client: httpx.AsyncClient, installation_id: str, scope: FrozenScope
) -> tuple[str, object]:
    """Exchange the App JWT for an installation access token.

    With ``scope`` set, GitHub mints a token carrying *only* those
    permissions -- a subset of what the installation grants -- instead
    of the installation's full set.  Requesting a permission the
    installation does not hold is a ``422``, which is the right failure:
    a capability asking for authority the App was never given should say
    so rather than act with less.
    """
    # ``is not None`` rather than truthiness: ``freeze_scope({})`` is an
    # empty tuple, and asking GitHub for *no* permissions must send
    # ``{'permissions': {}}``.  Omitting the body instead makes GitHub
    # grant the installation's entire set -- the narrowest request
    # would fail open to the widest token.
    body: dict[str, typing.Any] | None = (
        {'permissions': dict(scope)} if scope is not None else None
    )
    resp = await client.post(
        f'/app/installations/{installation_id}/access_tokens', json=body
    )
    resp.raise_for_status()
    data = typing.cast('dict[str, typing.Any]', resp.json())
    return str(data['token']), data.get('expires_at')


async def installation_token(
    *,
    base: str,
    app_id: str,
    private_key: str,
    installation_id: str | None,
    owner: str,
    repo: str,
    scope: Scope = None,
    cache_misses: bool = True,
) -> str:
    """Return a valid installation token, minting/caching as needed.

    ``installation_id`` may be ``None``, in which case the installation
    is discovered from the target repo (and cached).  The resulting
    token is cached until shortly before it expires.

    ``scope`` is the GitHub App permission set the calling operation
    needs (e.g. ``{'contents': 'read'}``).  The token is minted with
    exactly that set rather than the installation's full grant, so the
    authority in flight tracks the operation instead of the
    Integration's configuration.  ``None`` keeps the pre-scoping
    behaviour.  It is part of the cache key: see :func:`freeze_scope`.

    ``cache_misses=False`` skips the negative cache for a repo the App
    is known to be uninstalled on, paying the 404 instead.  Mutating
    callers pass it so that installing the App during an incident takes
    effect on the next attempt rather than after the negative TTL.

    Concurrent callers for the same installation mint once, whether they
    named the same repository or two repositories that turn out to share
    an installation: the first through stores the token and the rest read
    it back rather than each making their own exchange.
    """
    frozen = freeze_scope(scope)
    if (
        token := _cached_token(
            app_id, base, installation_id, owner, repo, frozen
        )
    ) is not None:
        return token
    if cache_misses and _NOT_INSTALLED_CACHE.get((app_id, base, owner, repo)):
        raise AppNotInstalledError(
            f'no GitHub App installation found for {owner}/{repo}',
            owner_repo=f'{owner}/{repo}',
        )
    # Held across discovery, so concurrent callers for one repository
    # look its installation up once.
    async with _MINT_LOCK(('repo', app_id, base, owner, repo)):
        # The coroutine that held the lock may have just minted this.
        if (
            token := _cached_token(
                app_id, base, installation_id, owner, repo, frozen
            )
        ) is not None:
            return token
        try:
            return await _mint_and_cache(
                base=base,
                app_id=app_id,
                private_key=private_key,
                installation_id=installation_id,
                owner=owner,
                repo=repo,
                scope=frozen,
            )
        except AppNotInstalledError:
            _NOT_INSTALLED_CACHE.set((app_id, base, owner, repo), True)
            raise


async def _mint_and_cache(
    *,
    base: str,
    app_id: str,
    private_key: str,
    installation_id: str | None,
    owner: str,
    repo: str,
    scope: FrozenScope = None,
) -> str:
    """Mint a fresh installation token and cache it until it expires."""
    install = installation_id or _INSTALL_CACHE.get(
        (app_id, base, owner, repo)
    )
    install_was_cached = install is not None and installation_id is None
    app_token = _app_jwt(app_id, private_key)
    async with httpx.AsyncClient(
        base_url=base,
        headers=_auth_headers(app_token),
        timeout=_HTTP_TIMEOUT_SECONDS,
        event_hooks={'response': [_raise_on_401]},
    ) as client:
        if install is None:
            install = await _discover_installation_id(client, owner, repo)
            _INSTALL_CACHE.set((app_id, base, owner, repo), install)
        try:
            return await _mint_locked(client, app_id, base, install, scope)
        except httpx.HTTPStatusError as exc:
            # A 404 (or 401, surfaced as PluginAuthenticationFailed by the
            # response hook) against a *cached* installation id means the
            # app was uninstalled/reinstalled or transferred. Evict the
            # stale id and rediscover once before giving up.
            if not install_was_cached or exc.response.status_code != 404:
                raise
            _INSTALL_CACHE.pop((app_id, base, owner, repo))
            install = await _discover_installation_id(client, owner, repo)
            _INSTALL_CACHE.set((app_id, base, owner, repo), install)
            return await _mint_locked(client, app_id, base, install, scope)


async def _mint_locked(
    client: httpx.AsyncClient,
    app_id: str,
    base: str,
    install: str,
    scope: FrozenScope,
) -> str:
    """Mint one token per installation, however many callers want it.

    The recheck inside the lock is what makes this collapse rather than
    queue: a caller that waited here because someone else was minting
    finds their token and never asks GitHub for its own.  Rediscovery
    after a stale id re-enters under the new installation's lock, which
    is why the key is a parameter rather than derived from a repo.
    """
    async with _MINT_LOCK(('install', app_id, base, install, str(scope))):
        cached = _TOKEN_CACHE.get((app_id, install, base, scope))
        if cached is not None:
            return cached
        token, expires_at = await _mint(client, install, scope)
        _TOKEN_CACHE.set(
            (app_id, install, base, scope),
            token,
            expires_at=_token_deadline(expires_at),
        )
        return token


async def resolve_bearer(
    credentials: dict[str, str],
    base: str,
    owner: str,
    repo: str,
    *,
    scope: Scope = None,
    cache_misses: bool = True,
) -> str:
    """Resolve the Bearer token used for a repo's GitHub API calls.

    Prefers an explicit PAT (``access_token``/``token``).  Otherwise mints
    a short-lived GitHub App installation token from ``app_id`` +
    ``private_key`` (with an optional ``installation_id`` that skips
    per-repo installation discovery).  Tokens are cached process-wide.

    ``scope`` is the permission set the calling operation needs; the
    minted token carries that set rather than the App installation's
    full grant.  It has no effect on the PAT branch -- a PAT's scope is
    fixed when an operator creates it, and nothing here can narrow it.

    Shared by every host-agnostic behavioral plugin (commit-sync,
    pr-sync, deployment) so a service configured with only App
    credentials -- and therefore no acting user -- can still act.
    """
    token = credentials.get('access_token') or credentials.get('token')
    if token:
        return token
    app_id = credentials.get('app_id')
    private_key = credentials.get('private_key')
    if app_id and private_key:
        return await installation_token(
            base=base,
            app_id=app_id,
            private_key=private_key,
            installation_id=credentials.get('installation_id') or None,
            owner=owner,
            repo=repo,
            scope=scope,
            cache_misses=cache_misses,
        )
    raise ValueError(
        'GitHub plugin requires either an access_token (PAT) or '
        'app_id + private_key (GitHub App) credentials'
    )
