"""OAuth2/OIDC integration helpers."""

import asyncio
import ipaddress
import logging
import os
import secrets
import socket
import time
import typing
from urllib import parse as urlparse

import httpx
import jwt
from valkey import asyncio as valkey_module

from imbi.api import settings
from imbi.api.auth import login_providers, models
from imbi.common import graph

_OAUTH_STATE_NONCE_PREFIX = 'imbi:oauth:state-nonce:'

LOGGER = logging.getLogger(__name__)

# Cache for OIDC discovery documents with TTL.
# Format: {issuer_url: (discovery_data, timestamp)}.
# Bounded to ``_OIDC_CACHE_MAX_ENTRIES`` so a deployment with many
# configured IdPs (or a misbehaving caller passing junk issuers) can't
# grow the cache without limit. When full, the oldest entry by insertion
# timestamp is evicted on the next miss.
_oidc_discovery_cache: dict[str, tuple[dict[str, typing.Any], float]] = {}
_OIDC_CACHE_TTL_SECONDS = 86400  # 24 hours
_OIDC_CACHE_MAX_ENTRIES = 64


def _bound_oidc_cache() -> None:
    """Drop the oldest cache entry while over the size cap."""
    while len(_oidc_discovery_cache) > _OIDC_CACHE_MAX_ENTRIES:
        oldest_key = min(
            _oidc_discovery_cache,
            key=lambda k: _oidc_discovery_cache[k][1],
        )
        del _oidc_discovery_cache[oldest_key]


def _insecure_urls_allowed() -> bool:
    """True iff the dev escape hatch ``IMBI_OAUTH_ALLOW_INSECURE_URLS`` is on.

    When set, ``_validate_external_url`` skips its scheme and IP-range
    checks *only* for hostnames in ``{'localhost', '127.0.0.1', '::1'}``.
    Intended only for local dev against mock OIDC providers on
    ``http://localhost``; never set in production.
    """
    return os.environ.get('IMBI_OAUTH_ALLOW_INSECURE_URLS', '').lower() in {
        '1',
        'true',
        'yes',
    }


async def _validate_external_url(url: str, *, field: str) -> None:
    """Reject URLs that point at non-HTTPS or private network addresses.

    Used on every URL that this module is about to fetch (OIDC issuer,
    discovered token/userinfo endpoints) to close the SSRF channel an
    admin-configurable ``issuer_url`` would otherwise open. The
    ``IMBI_OAUTH_ALLOW_INSECURE_URLS=true`` dev escape hatch only
    bypasses validation for ``localhost``/``127.0.0.1``/``::1``; every
    other host is still validated normally.

    Raises:
        ValueError: If scheme is not ``https`` or hostname resolves to a
            loopback, link-local, private (RFC1918), multicast, or
            reserved address.
    """
    parsed = urlparse.urlparse(url)
    if _insecure_urls_allowed() and parsed.hostname in {
        'localhost',
        '127.0.0.1',
        '::1',
    }:
        return

    if parsed.scheme != 'https':
        raise ValueError(
            f'{field} must use https:// (got scheme {parsed.scheme!r})'
        )
    if not parsed.hostname:
        raise ValueError(f'{field} is missing a hostname')

    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            None,
            0,
            socket.SOCK_STREAM,
        )
    except socket.gaierror as err:
        raise ValueError(
            f'{field} hostname does not resolve: {parsed.hostname}'
        ) from err

    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        ip = ipaddress.ip_address(ip_str)
        if (
            ip.is_loopback
            or ip.is_link_local
            or ip.is_private
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError(
                f'{field} resolves to a non-public address '
                f'({parsed.hostname} -> {ip_str})'
            )


async def _discover_oidc_endpoints(issuer_url: str) -> dict[str, typing.Any]:
    """Discover OIDC endpoints via .well-known/openid-configuration.

    Args:
        issuer_url: OIDC issuer URL

    Returns:
        Discovery document with token_endpoint, userinfo_endpoint, etc.

    Raises:
        ValueError: If discovery fails or any URL involved would target
            a non-public network address (SSRF defense).

    """
    if issuer_url in _oidc_discovery_cache:
        discovery_data, cached_at = _oidc_discovery_cache[issuer_url]
        age = time.time() - cached_at
        if age < _OIDC_CACHE_TTL_SECONDS:
            return discovery_data
        del _oidc_discovery_cache[issuer_url]

    await _validate_external_url(issuer_url, field='OIDC issuer URL')

    issuer = issuer_url.rstrip('/')
    discovery_url = f'{issuer}/.well-known/openid-configuration'

    try:
        async with httpx.AsyncClient(
            timeout=10.0, follow_redirects=False
        ) as client:
            response = await client.get(discovery_url)
    except httpx.HTTPError as e:
        raise ValueError(f'OIDC discovery request failed: {e}') from e

    if response.status_code != 200:
        raise ValueError(
            f'OIDC discovery failed: {response.status_code} {response.text}'
        )

    discovery_data = typing.cast(dict[str, typing.Any], response.json())

    if 'token_endpoint' not in discovery_data:
        raise ValueError('OIDC discovery missing token_endpoint')
    if 'userinfo_endpoint' not in discovery_data:
        raise ValueError('OIDC discovery missing userinfo_endpoint')

    # The discovered endpoints can be set by whoever controls the
    # issuer's discovery document; revalidate so an HTTPS issuer cannot
    # point token/userinfo at an internal host.
    await _validate_external_url(
        discovery_data['token_endpoint'], field='OIDC token_endpoint'
    )
    await _validate_external_url(
        discovery_data['userinfo_endpoint'], field='OIDC userinfo_endpoint'
    )

    _oidc_discovery_cache[issuer_url] = (discovery_data, time.time())
    _bound_oidc_cache()
    return discovery_data


def generate_oauth_state(
    provider: str, redirect_uri: str, auth_settings: settings.Auth
) -> tuple[str, models.OAuthStateData]:
    """Generate OAuth state parameter with CSRF protection.

    Args:
        provider: OAuth provider slug
        redirect_uri: Where to redirect after OAuth flow
        auth_settings: Auth settings instance

    Returns:
        Tuple of (state_token, state_data)

    """
    state_data = models.OAuthStateData(
        provider=provider,
        nonce=secrets.token_urlsafe(32),
        redirect_uri=redirect_uri,
        timestamp=int(time.time()),
    )

    state_token = jwt.encode(
        state_data.model_dump(),
        auth_settings.jwt_secret,
        algorithm=auth_settings.jwt_algorithm,
    )

    return state_token, state_data


async def verify_oauth_state(
    state_token: str,
    auth_settings: settings.Auth,
    *,
    valkey_client: valkey_module.Valkey | None,
    max_age_seconds: int = 600,
) -> models.OAuthStateData:
    """Verify, decode, and single-use-consume an OAuth state parameter.

    Verifies the JWT signature and the 10-minute timestamp window, then
    atomically marks the embedded nonce as consumed in Valkey (SET NX
    EX) so a captured token cannot be replayed inside its TTL.

    Args:
        state_token: State token from OAuth callback
        auth_settings: Auth settings instance
        valkey_client: Valkey client used for the nonce consume.
            ``None`` means OAuth replay protection is unavailable and
            verification fails closed.
        max_age_seconds: Maximum age for state token (default 10 minutes)

    Returns:
        Decoded state data

    Raises:
        ValueError: If state is invalid, expired, or already consumed.
        RuntimeError: If no Valkey client is configured (replay
            protection must fail closed).
    """
    try:
        payload = jwt.decode(
            state_token,
            auth_settings.jwt_secret,
            algorithms=[auth_settings.jwt_algorithm],
        )
        state_data = models.OAuthStateData(**payload)
    except jwt.InvalidTokenError as e:
        raise ValueError(f'Invalid OAuth state token: {e}') from e

    age = int(time.time()) - state_data.timestamp
    if age > max_age_seconds:
        raise ValueError(f'OAuth state expired (age: {age}s)')

    if valkey_client is None:
        raise RuntimeError(
            'OAuth replay protection requires Valkey; no client is configured'
        )
    key = f'{_OAUTH_STATE_NONCE_PREFIX}{state_data.nonce}'
    fresh = await valkey_client.set(  # pyright: ignore[reportUnknownMemberType]
        key, '1', nx=True, ex=max_age_seconds
    )
    if not fresh:
        raise ValueError(
            'OAuth state already consumed; possible replay attempt'
        )

    return state_data


async def exchange_oauth_code(
    slug: str,
    code: str,
    redirect_uri: str,
    db: graph.Graph,
) -> dict[str, typing.Any]:
    """Exchange OAuth authorization code for tokens.

    Args:
        slug: Login-Integration slug
        code: Authorization code from provider
        redirect_uri: Redirect URI used in authorization request
        db: Graph database used to look up provider configuration

    Returns:
        Token response with access_token, refresh_token (if available), etc.

    Raises:
        ValueError: If provider is invalid or token exchange fails

    """
    token_url, client_id, client_secret = await _get_provider_config(slug, db)

    await _validate_external_url(token_url, field='OAuth token_url')

    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=False
    ) as client:
        response = await client.post(
            token_url,
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': redirect_uri,
                'client_id': client_id,
                'client_secret': client_secret,
            },
            headers={'Accept': 'application/json'},
        )

        if response.status_code != 200:
            raise ValueError(
                f'Token exchange failed: '
                f'{response.status_code} {response.text}'
            )

        return typing.cast(dict[str, typing.Any], response.json())


async def fetch_oauth_profile(
    slug: str,
    access_token: str,
    db: graph.Graph,
) -> dict[str, typing.Any]:
    """Fetch user profile from OAuth provider.

    Args:
        slug: Login-Integration slug
        access_token: Access token from provider
        db: Graph database used to look up provider configuration

    Returns:
        Normalized user profile data with keys: id, email, name, avatar_url

    Raises:
        ValueError: If provider is invalid or profile fetch fails

    """
    app = await _load_active_login_app(slug, db)
    userinfo_url = await _get_userinfo_url(slug, db)

    await _validate_external_url(userinfo_url, field='OAuth userinfo_url')

    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=False
    ) as client:
        response = await client.get(
            userinfo_url,
            headers={'Authorization': f'Bearer {access_token}'},
        )

        if response.status_code != 200:
            raise ValueError(
                f'Profile fetch failed: {response.status_code} {response.text}'
            )

        raw_profile = response.json()
        return normalize_oauth_profile(app.oauth_app_type, raw_profile)


def normalize_oauth_profile(
    oauth_app_type: str, raw_profile: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    """Normalize OAuth profile to common format.

    Args:
        oauth_app_type: One of ``'google'``, ``'github'``, ``'oidc'``
        raw_profile: Raw profile data from provider

    Returns:
        Normalized profile with keys: id, email, name, avatar_url

    Raises:
        ValueError: If oauth_app_type is invalid or profile fields missing

    """
    if oauth_app_type == 'google':
        email = raw_profile.get('email')
        if not email:
            raise ValueError('Google profile missing required email field')
        # Google's userinfo endpoint sets verified_email on the primary
        # account; default to False when the claim is absent so a
        # malformed payload can't bypass auto-link verification.
        return {
            'id': raw_profile['id'],
            'email': email,
            'email_verified': bool(raw_profile.get('verified_email', False)),
            'name': raw_profile['name'],
            'avatar_url': raw_profile.get('picture'),
        }
    elif oauth_app_type == 'github':
        email = raw_profile.get('email')
        if not email:
            raise ValueError(
                'GitHub profile missing email address. '
                'User must grant email access or make email public.'
            )
        # GitHub's /user endpoint only returns the primary email when
        # verified, so a present email implies verified ownership.
        return {
            'id': str(raw_profile['id']),
            'email': email,
            'email_verified': True,
            'name': raw_profile['name'] or raw_profile['login'],
            'avatar_url': raw_profile.get('avatar_url'),
        }
    elif oauth_app_type == 'oidc':
        email = raw_profile.get('email')
        if not email:
            raise ValueError('OIDC profile missing required email claim')

        user_id = raw_profile.get('sub') or raw_profile.get('id')
        if not user_id:
            raise ValueError(
                'OIDC profile missing required identity field (sub or id)'
            )

        name = (
            raw_profile.get('name')
            or raw_profile.get('preferred_username')
            or email.split('@')[0]
        )

        # OIDC: trust only an explicit ``email_verified=true`` claim
        # (RFC 7519 / OIDC core). Absent or false → treated as unverified.
        return {
            'id': user_id,
            'email': email,
            'email_verified': bool(raw_profile.get('email_verified', False)),
            'name': name,
            'avatar_url': raw_profile.get('picture'),
        }
    else:
        raise ValueError(f'Unsupported oauth_app_type: {oauth_app_type}')


async def _load_active_login_app(
    slug: str, db: graph.Graph
) -> login_providers.LoginApp:
    """Load an active login app row or raise ``ValueError``."""
    app = await login_providers.get_login_app(db, slug)
    if app is None or app.status != 'active':
        raise ValueError(f'{slug} OAuth is not enabled')
    return app


async def _get_provider_config(
    slug: str, db: graph.Graph
) -> tuple[str, str, str]:
    """Get OAuth provider configuration from the graph.

    Returns:
        Tuple of (token_url, client_id, client_secret)
    """
    app = await _load_active_login_app(slug, db)
    client_id = app.client_id or ''
    # LoginApp.client_secret is already plaintext -- Integration
    # credentials are decrypted once when the login app is materialized
    # (imbi.api.auth.login_providers), unlike the old ServiceApplication
    # row which stored an encrypted value this module used to decrypt.
    client_secret = app.client_secret or ''
    if app.oauth_app_type == 'google':
        return (
            'https://oauth2.googleapis.com/token',
            client_id,
            client_secret,
        )
    if app.oauth_app_type == 'github':
        return (
            'https://github.com/login/oauth/access_token',
            client_id,
            client_secret,
        )
    # oidc: prefer the Integration's configured token_endpoint, else discover
    if app.token_endpoint:
        return (app.token_endpoint, client_id, client_secret)
    if not app.issuer_url:
        raise ValueError('OIDC issuer URL not configured')
    discovery = await _discover_oidc_endpoints(app.issuer_url)
    return (discovery['token_endpoint'], client_id, client_secret)


async def _get_userinfo_url(slug: str, db: graph.Graph) -> str:
    """Get userinfo URL for OAuth provider."""
    app = await _load_active_login_app(slug, db)
    if app.oauth_app_type == 'google':
        return 'https://www.googleapis.com/oauth2/v2/userinfo'
    if app.oauth_app_type == 'github':
        return 'https://api.github.com/user'
    if app.oauth_app_type == 'oidc':
        if not app.issuer_url:
            raise ValueError('OIDC issuer URL not configured')
        discovery = await _discover_oidc_endpoints(app.issuer_url)
        return str(discovery['userinfo_endpoint'])
    raise ValueError(f'Unsupported oauth_app_type: {app.oauth_app_type}')
