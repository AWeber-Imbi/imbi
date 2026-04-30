"""OAuth2/OIDC integration helpers."""

import secrets
import time
import typing

import httpx
import jwt
from imbi_common import graph
from imbi_common.auth import encryption

from imbi_api import settings
from imbi_api.auth import login_providers, models

# Cache for OIDC discovery documents with TTL
# Format: {issuer_url: (discovery_data, timestamp)}
_oidc_discovery_cache: dict[str, tuple[dict[str, typing.Any], float]] = {}
_OIDC_CACHE_TTL_SECONDS = 86400  # 24 hours


async def _discover_oidc_endpoints(issuer_url: str) -> dict[str, typing.Any]:
    """Discover OIDC endpoints via .well-known/openid-configuration.

    Args:
        issuer_url: OIDC issuer URL

    Returns:
        Discovery document with token_endpoint, userinfo_endpoint, etc.

    Raises:
        ValueError: If discovery fails

    """
    if issuer_url in _oidc_discovery_cache:
        discovery_data, cached_at = _oidc_discovery_cache[issuer_url]
        age = time.time() - cached_at
        if age < _OIDC_CACHE_TTL_SECONDS:
            return discovery_data
        del _oidc_discovery_cache[issuer_url]

    issuer = issuer_url.rstrip('/')
    discovery_url = f'{issuer}/.well-known/openid-configuration'

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
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

    _oidc_discovery_cache[issuer_url] = (discovery_data, time.time())
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


def verify_oauth_state(
    state_token: str, auth_settings: settings.Auth, max_age_seconds: int = 600
) -> models.OAuthStateData:
    """Verify and decode OAuth state parameter.

    Args:
        state_token: State token from OAuth callback
        auth_settings: Auth settings instance
        max_age_seconds: Maximum age for state token (default 10 minutes)

    Returns:
        Decoded state data

    Raises:
        ValueError: If state is invalid or expired

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

    return state_data


async def exchange_oauth_code(
    slug: str,
    code: str,
    redirect_uri: str,
    db: graph.Graph,
) -> dict[str, typing.Any]:
    """Exchange OAuth authorization code for tokens.

    Args:
        slug: ServiceApplication slug for the login provider
        code: Authorization code from provider
        redirect_uri: Redirect URI used in authorization request
        db: Graph database used to look up provider configuration

    Returns:
        Token response with access_token, refresh_token (if available), etc.

    Raises:
        ValueError: If provider is invalid or token exchange fails

    """
    token_url, client_id, client_secret = await _get_provider_config(slug, db)

    async with httpx.AsyncClient(timeout=30.0) as client:
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
        slug: ServiceApplication slug for the login provider
        access_token: Access token from provider
        db: Graph database used to look up provider configuration

    Returns:
        Normalized user profile data with keys: id, email, name, avatar_url

    Raises:
        ValueError: If provider is invalid or profile fetch fails

    """
    app = await _load_active_login_app(slug, db)
    userinfo_url = await _get_userinfo_url(slug, db)

    async with httpx.AsyncClient(timeout=30.0) as client:
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


def _decrypt_secret(app: login_providers.LoginApp) -> str:
    """Decrypt the row's ``client_secret_encrypted`` value."""
    if not app.client_secret_encrypted:
        return ''
    encryptor = encryption.TokenEncryption.get_instance()
    secret = encryptor.decrypt(app.client_secret_encrypted)
    if secret is None:
        raise ValueError('Failed to decrypt OAuth client secret')
    return secret


async def _get_provider_config(
    slug: str, db: graph.Graph
) -> tuple[str, str, str]:
    """Get OAuth provider configuration from the graph.

    Returns:
        Tuple of (token_url, client_id, client_secret)
    """
    app = await _load_active_login_app(slug, db)
    client_id = app.client_id or ''
    client_secret = _decrypt_secret(app)
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
    # oidc: prefer parent ThirdPartyService.token_endpoint, else discover
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
