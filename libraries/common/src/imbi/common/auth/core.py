"""Core authentication functions for JWT tokens."""

import datetime
import secrets
import typing

import jwt

from imbi.common import settings


def _create_token(
    subject: str,
    *,
    token_type: str,
    ttl_seconds: int,
    extra_claims: dict[str, typing.Any] | None,
    auth_settings: settings.Auth,
) -> str:
    """Build and sign a JWT with the shared claim structure.

    Args:
        subject: Subject (user identifier) to encode in token
        token_type: Value for the ``type`` claim (e.g. ``access``)
        ttl_seconds: Token lifetime in seconds
        extra_claims: Optional additional claims to include
        auth_settings: Auth settings for JWT configuration

    Returns:
        JWT token string

    """
    now = datetime.datetime.now(datetime.UTC)
    claims = {
        'sub': subject,
        'jti': secrets.token_urlsafe(16),
        'type': token_type,
        'iat': now,
        'exp': now + datetime.timedelta(seconds=ttl_seconds),
        **(extra_claims or {}),
    }
    token: str = jwt.encode(
        claims,
        auth_settings.jwt_secret,
        algorithm=auth_settings.jwt_algorithm,
    )
    return token


def create_access_token(
    subject: str,
    extra_claims: dict[str, typing.Any] | None = None,
    auth_settings: settings.Auth | None = None,
) -> str:
    """Create JWT access token.

    Args:
        subject: Subject (user identifier) to encode in token
        extra_claims: Optional additional claims to include
        auth_settings: Optional auth settings for JWT configuration
            (uses singleton if not provided)

    Returns:
        JWT token string

    """
    if auth_settings is None:
        auth_settings = settings.get_auth_settings()
    return _create_token(
        subject,
        token_type='access',
        ttl_seconds=auth_settings.access_token_expire_seconds,
        extra_claims=extra_claims,
        auth_settings=auth_settings,
    )


def create_refresh_token(
    subject: str,
    extra_claims: dict[str, typing.Any] | None = None,
    auth_settings: settings.Auth | None = None,
) -> str:
    """Create JWT refresh token.

    Args:
        subject: Subject (user identifier) to encode in token
        extra_claims: Optional additional claims to include
        auth_settings: Optional auth settings for JWT configuration
            (uses singleton if not provided)

    Returns:
        JWT token string

    """
    if auth_settings is None:
        auth_settings = settings.get_auth_settings()
    return _create_token(
        subject,
        token_type='refresh',
        ttl_seconds=auth_settings.refresh_token_expire_seconds,
        extra_claims=extra_claims,
        auth_settings=auth_settings,
    )


def verify_token(
    token: str, auth_settings: settings.Auth | None = None
) -> dict[str, typing.Any]:
    """Decode and validate JWT token.

    Args:
        token: JWT token string to decode
        auth_settings: Optional auth settings for JWT configuration
            (uses singleton if not provided)

    Returns:
        Decoded token claims

    Raises:
        jwt.ExpiredSignatureError: If token has expired
        jwt.InvalidTokenError: If token is invalid

    """
    if auth_settings is None:
        auth_settings = settings.get_auth_settings()

    decoded: dict[str, typing.Any] = jwt.decode(
        token,
        auth_settings.jwt_secret,
        algorithms=[auth_settings.jwt_algorithm],
        options={'require': ['sub', 'jti', 'type', 'exp']},
    )
    return decoded
