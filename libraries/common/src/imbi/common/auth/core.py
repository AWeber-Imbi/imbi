"""Core authentication functions for password hashing and JWT tokens."""

import datetime
import secrets
import typing

import argon2
import jwt

from imbi_common import settings

# Password hashing
password_hasher = argon2.PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password using Argon2id.

    Args:
        password: Plain text password to hash

    Returns:
        Hashed password string

    """
    hashed: str = password_hasher.hash(password)
    return hashed


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against an Argon2 hash.

    Args:
        password: Plain text password to verify
        password_hash: Hashed password to check against

    Returns:
        True if password matches, False otherwise

    """
    try:
        password_hasher.verify(password_hash, password)
        return True
    except argon2.exceptions.VerifyMismatchError:
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """Check if a password hash needs to be rehashed with updated parameters.

    Args:
        password_hash: Hashed password to check

    Returns:
        True if password should be rehashed, False otherwise

    """
    needs_rehash: bool = password_hasher.check_needs_rehash(password_hash)
    return needs_rehash


def create_access_token(
    user_id: str,
    auth_settings: settings.Auth,
    extra_claims: dict[str, typing.Any] | None = None,
) -> tuple[str, str]:
    """Create JWT access token.

    Args:
        user_id: Username to encode in token
        auth_settings: Auth settings for JWT configuration
        extra_claims: Optional additional claims to include

    Returns:
        Tuple of (token string, jti)

    """
    jti = secrets.token_urlsafe(16)
    now = datetime.datetime.now(datetime.UTC)
    expires = now + datetime.timedelta(
        seconds=auth_settings.access_token_expire_seconds
    )

    claims = {
        'sub': user_id,
        'jti': jti,
        'type': 'access',
        'iat': now,
        'exp': expires,
        **(extra_claims or {}),
    }

    token = jwt.encode(
        claims, auth_settings.jwt_secret, algorithm=auth_settings.jwt_algorithm
    )
    return token, jti


def create_refresh_token(
    user_id: str,
    auth_settings: settings.Auth,
) -> tuple[str, str]:
    """Create JWT refresh token.

    Args:
        user_id: Username to encode in token
        auth_settings: Auth settings for JWT configuration

    Returns:
        Tuple of (token string, jti)

    """
    jti = secrets.token_urlsafe(16)
    now = datetime.datetime.now(datetime.UTC)
    expires = now + datetime.timedelta(
        seconds=auth_settings.refresh_token_expire_seconds
    )

    claims = {
        'sub': user_id,
        'jti': jti,
        'type': 'refresh',
        'iat': now,
        'exp': expires,
    }

    token = jwt.encode(
        claims, auth_settings.jwt_secret, algorithm=auth_settings.jwt_algorithm
    )
    return token, jti


def decode_token(
    token: str, auth_settings: settings.Auth
) -> dict[str, typing.Any]:
    """Decode and validate JWT token.

    Args:
        token: JWT token string to decode
        auth_settings: Auth settings for JWT configuration

    Returns:
        Decoded token claims

    Raises:
        jwt.ExpiredSignatureError: If token has expired
        jwt.InvalidTokenError: If token is invalid

    """
    decoded: dict[str, typing.Any] = jwt.decode(
        token,
        auth_settings.jwt_secret,
        algorithms=[auth_settings.jwt_algorithm],
        options={'require': ['sub', 'jti', 'type', 'exp']},
    )
    return decoded
