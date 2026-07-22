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
import datetime
import logging
import time
import typing

import httpx
import jwt

from imbi.plugins.github.deployment import (
    _auth_headers,  # pyright: ignore[reportPrivateUsage]
    _raise_on_401,  # pyright: ignore[reportPrivateUsage]
)

LOGGER = logging.getLogger(__name__)


class AppNotInstalledError(Exception):
    """The GitHub App is not installed for the target repository.

    Raised by :func:`_discover_installation_id` when GitHub answers the
    installation lookup with a 404 -- the App has not been installed on
    the repo/org, or the repo was renamed/removed.  Sync callers treat
    this as a clean skip rather than a hard failure, so an uninstalled
    App never surfaces as a Sentry error on a backfill worker.
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

# Process-wide caches.  Token cache values are ``(token, deadline)`` where
# ``deadline`` is a ``time.monotonic()`` instant; the installation cache
# avoids re-discovering the installation id on every delivery.
_TOKEN_CACHE: dict[tuple[str, str, str], tuple[str, float]] = {}
_INSTALL_CACHE: dict[tuple[str, str, str, str], str] = {}


def reset_cache() -> None:
    """Clear the process-wide token / installation caches (tests)."""
    _TOKEN_CACHE.clear()
    _INSTALL_CACHE.clear()


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


def _cached_token(key: tuple[str, str, str]) -> str | None:
    entry = _TOKEN_CACHE.get(key)
    if entry is not None and entry[1] > time.monotonic():
        return entry[0]
    return None


async def _discover_installation_id(
    client: httpx.AsyncClient, owner: str, repo: str
) -> str:
    resp = await client.get(f'/repos/{owner}/{repo}/installation')
    if resp.status_code == 404:
        raise AppNotInstalledError(
            f'no GitHub App installation found for {owner}/{repo}'
        )
    resp.raise_for_status()
    data = typing.cast('dict[str, typing.Any]', resp.json())
    install_id = data.get('id')
    if install_id is None:
        raise AppNotInstalledError(
            f'no GitHub App installation found for {owner}/{repo}'
        )
    return str(install_id)


async def _mint(
    client: httpx.AsyncClient, installation_id: str
) -> tuple[str, object]:
    resp = await client.post(
        f'/app/installations/{installation_id}/access_tokens'
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
) -> str:
    """Return a valid installation token, minting/caching as needed.

    ``installation_id`` may be ``None``, in which case the installation
    is discovered from the target repo (and cached).  The resulting
    token is cached until shortly before it expires.
    """
    install = installation_id
    if install is not None and (
        cached := _cached_token((app_id, install, base))
    ):
        return cached
    if install is None:
        install = _INSTALL_CACHE.get((app_id, base, owner, repo))
        if install is not None and (
            cached := _cached_token((app_id, install, base))
        ):
            return cached

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
            _INSTALL_CACHE[(app_id, base, owner, repo)] = install
            if cached := _cached_token((app_id, install, base)):
                return cached
        try:
            token, expires_at = await _mint(client, install)
        except httpx.HTTPStatusError as exc:
            # A 404 (or 401, surfaced as PluginAuthenticationFailed by the
            # response hook) against a *cached* installation id means the
            # app was uninstalled/reinstalled or transferred. Evict the
            # stale id and rediscover once before giving up.
            if not install_was_cached or exc.response.status_code != 404:
                raise
            _INSTALL_CACHE.pop((app_id, base, owner, repo), None)
            install = await _discover_installation_id(client, owner, repo)
            _INSTALL_CACHE[(app_id, base, owner, repo)] = install
            token, expires_at = await _mint(client, install)
    _TOKEN_CACHE[(app_id, install, base)] = (
        token,
        _token_deadline(expires_at),
    )
    return token


async def resolve_bearer(
    credentials: dict[str, str], base: str, owner: str, repo: str
) -> str:
    """Resolve the Bearer token used for a repo's GitHub API calls.

    Prefers an explicit PAT (``access_token``/``token``).  Otherwise mints
    a short-lived GitHub App installation token from ``app_id`` +
    ``private_key`` (with an optional ``installation_id`` that skips
    per-repo installation discovery).  Tokens are cached process-wide.

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
        )
    raise ValueError(
        'GitHub plugin requires either an access_token (PAT) or '
        'app_id + private_key (GitHub App) credentials'
    )
