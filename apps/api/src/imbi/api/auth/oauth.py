"""OAuth2/OIDC integration helpers."""

import secrets
import time
import typing

import httpx
import jwt
from imbi_common import settings

from imbi_api.auth import models

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
    # Check cache first (with TTL validation)
    if issuer_url in _oidc_discovery_cache:
        discovery_data, cached_at = _oidc_discovery_cache[issuer_url]
        age = time.time() - cached_at
        if age < _OIDC_CACHE_TTL_SECONDS:
            return discovery_data
        # Cache expired, remove it
        del _oidc_discovery_cache[issuer_url]

    # Fetch discovery document
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

    # Validate required fields
    if 'token_endpoint' not in discovery_data:
        raise ValueError('OIDC discovery missing token_endpoint')
    if 'userinfo_endpoint' not in discovery_data:
        raise ValueError('OIDC discovery missing userinfo_endpoint')

    # Cache the result with timestamp
    _oidc_discovery_cache[issuer_url] = (discovery_data, time.time())
    return discovery_data


def generate_oauth_state(
    provider: str, redirect_uri: str, auth_settings: settings.Auth
) -> tuple[str, models.OAuthStateData]:
    """Generate OAuth state parameter with CSRF protection.

    Args:
        provider: OAuth provider identifier
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

    # Encode state data as JWT for tamper resistance
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
        # Decode state JWT
        payload = jwt.decode(
            state_token,
            auth_settings.jwt_secret,
            algorithms=[auth_settings.jwt_algorithm],
        )
        state_data = models.OAuthStateData(**payload)
    except jwt.InvalidTokenError as e:
        raise ValueError(f'Invalid OAuth state token: {e}') from e

    # Check age
    age = int(time.time()) - state_data.timestamp
    if age > max_age_seconds:
        raise ValueError(f'OAuth state expired (age: {age}s)')

    return state_data


async def exchange_oauth_code(
    provider: str,
    code: str,
    redirect_uri: str,
    auth_settings: settings.Auth,
) -> dict[str, typing.Any]:
    """Exchange OAuth authorization code for tokens.

    Args:
        provider: OAuth provider identifier
        code: Authorization code from provider
        redirect_uri: Redirect URI used in authorization request
        auth_settings: Auth settings instance

    Returns:
        Token response with access_token, refresh_token (if available), etc.

    Raises:
        ValueError: If provider is invalid or token exchange fails

    """
    # Get provider configuration
    token_url, client_id, client_secret = await _get_provider_config(
        provider, auth_settings
    )

    # Exchange code for token
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
    provider: str,
    access_token: str,
    auth_settings: settings.Auth,
) -> dict[str, typing.Any]:
    """Fetch user profile from OAuth provider.

    Args:
        provider: OAuth provider identifier
        access_token: Access token from provider
        auth_settings: Auth settings instance

    Returns:
        Normalized user profile data with keys: id, email, name, avatar_url

    Raises:
        ValueError: If provider is invalid or profile fetch fails

    """
    # Get userinfo URL
    userinfo_url = await _get_userinfo_url(provider, auth_settings)

    # Fetch userinfo
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

        # Normalize profile data
        return normalize_oauth_profile(provider, raw_profile)


def normalize_oauth_profile(
    provider: str, raw_profile: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    """Normalize OAuth profile to common format.

    Args:
        provider: OAuth provider identifier
        raw_profile: Raw profile data from provider

    Returns:
        Normalized profile with keys: id, email, name, avatar_url

    Raises:
        ValueError: If provider is invalid

    """
    if provider == 'google':
        email = raw_profile.get('email')
        if not email:
            raise ValueError('Google profile missing required email field')
        return {
            'id': raw_profile['id'],
            'email': email,
            'name': raw_profile['name'],
            'avatar_url': raw_profile.get('picture'),
        }
    elif provider == 'github':
        # GitHub users can set email to private, so it may be None
        email = raw_profile.get('email')
        if not email:
            raise ValueError(
                'GitHub profile missing email address. '
                'User must grant email access or make email public.'
            )
        return {
            'id': str(raw_profile['id']),
            'email': email,
            'name': raw_profile['name'] or raw_profile['login'],
            'avatar_url': raw_profile.get('avatar_url'),
        }
    elif provider == 'oidc':
        # Generic OIDC profile (OpenID Connect standard claims)
        email = raw_profile.get('email')
        if not email:
            raise ValueError('OIDC profile missing required email claim')

        # Validate identity field (sub or id must be present)
        user_id = raw_profile.get('sub') or raw_profile.get('id')
        if not user_id:
            raise ValueError(
                'OIDC profile missing required identity field (sub or id)'
            )

        # Generate name from available fields
        name = (
            raw_profile.get('name')
            or raw_profile.get('preferred_username')
            or email.split('@')[0]
        )

        return {
            'id': user_id,
            'email': email,
            'name': name,
            'avatar_url': raw_profile.get('picture'),
        }
    else:
        raise ValueError(f'Unsupported OAuth provider: {provider}')


async def _get_provider_config(
    provider: str, auth_settings: settings.Auth
) -> tuple[str, str, str]:
    """Get OAuth provider configuration.

    Args:
        provider: OAuth provider identifier
        auth_settings: Auth settings instance

    Returns:
        Tuple of (token_url, client_id, client_secret)

    Raises:
        ValueError: If provider is invalid or not configured

    """
    if provider == 'google':
        if not auth_settings.oauth_google_enabled:
            raise ValueError('Google OAuth is not enabled')
        return (
            'https://oauth2.googleapis.com/token',
            auth_settings.oauth_google_client_id or '',
            auth_settings.oauth_google_client_secret or '',
        )
    elif provider == 'github':
        if not auth_settings.oauth_github_enabled:
            raise ValueError('GitHub OAuth is not enabled')
        return (
            'https://github.com/login/oauth/access_token',
            auth_settings.oauth_github_client_id or '',
            auth_settings.oauth_github_client_secret or '',
        )
    elif provider == 'oidc':
        if not auth_settings.oauth_oidc_enabled:
            raise ValueError('OIDC OAuth is not enabled')
        if not auth_settings.oauth_oidc_issuer_url:
            raise ValueError('OIDC issuer URL not configured')

        # Use OIDC discovery to get endpoints
        discovery = await _discover_oidc_endpoints(
            auth_settings.oauth_oidc_issuer_url
        )
        return (
            discovery['token_endpoint'],
            auth_settings.oauth_oidc_client_id or '',
            auth_settings.oauth_oidc_client_secret or '',
        )
    else:
        raise ValueError(f'Unsupported OAuth provider: {provider}')


async def _get_userinfo_url(
    provider: str, auth_settings: settings.Auth
) -> str:
    """Get userinfo URL for OAuth provider.

    Args:
        provider: OAuth provider identifier
        auth_settings: Auth settings instance

    Returns:
        Userinfo endpoint URL

    Raises:
        ValueError: If provider is invalid or not configured

    """
    if provider == 'google':
        return 'https://www.googleapis.com/oauth2/v2/userinfo'
    elif provider == 'github':
        return 'https://api.github.com/user'
    elif provider == 'oidc':
        if not auth_settings.oauth_oidc_issuer_url:
            raise ValueError('OIDC issuer URL not configured')
        # Use OIDC discovery to get userinfo endpoint
        discovery = await _discover_oidc_endpoints(
            auth_settings.oauth_oidc_issuer_url
        )
        return str(discovery['userinfo_endpoint'])
    else:
        raise ValueError(f'Unsupported OAuth provider: {provider}')
