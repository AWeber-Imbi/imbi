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


def needs_rehash(password_hash: str) -> bool:
    """Check if a password hash needs to be rehashed with updated parameters.

    Args:
        password_hash: Hashed password to check

    Returns:
        True if password should be rehashed, False otherwise

    """
    return password_hasher.check_needs_rehash(password_hash)


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

    jti = secrets.token_urlsafe(16)
    now = datetime.datetime.now(datetime.UTC)
    expires = now + datetime.timedelta(
        seconds=auth_settings.access_token_expire_seconds
    )

    claims = {
        'sub': subject,
        'jti': jti,
        'type': 'access',
        'iat': now,
        'exp': expires,
        **(extra_claims or {}),
    }

    token: str = jwt.encode(
        claims, auth_settings.jwt_secret, algorithm=auth_settings.jwt_algorithm
    )
    return token


def create_refresh_token(
    subject: str,
    auth_settings: settings.Auth | None = None,
) -> str:
    """Create JWT refresh token.

    Args:
        subject: Subject (user identifier) to encode in token
        auth_settings: Optional auth settings for JWT configuration
            (uses singleton if not provided)

    Returns:
        JWT token string

    """
    if auth_settings is None:
        auth_settings = settings.get_auth_settings()

    jti = secrets.token_urlsafe(16)
    now = datetime.datetime.now(datetime.UTC)
    expires = now + datetime.timedelta(
        seconds=auth_settings.refresh_token_expire_seconds
    )

    claims = {
        'sub': subject,
        'jti': jti,
        'type': 'refresh',
        'iat': now,
        'exp': expires,
    }

    token: str = jwt.encode(
        claims, auth_settings.jwt_secret, algorithm=auth_settings.jwt_algorithm
    )
    return token


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
