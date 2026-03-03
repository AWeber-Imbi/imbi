"""Password hashing utilities using Argon2id.

Moved from imbi_common.auth.core since password management
is specific to the API service.
"""

import argon2

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
    except (
        argon2.exceptions.VerifyMismatchError,
        argon2.exceptions.VerificationError,
        argon2.exceptions.InvalidHashError,
    ):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Check if a password hash needs rehashing with updated parameters.

    Args:
        password_hash: Hashed password to check

    Returns:
        True if password should be rehashed, False otherwise

    """
    return password_hasher.check_needs_rehash(  # type: ignore[no-any-return]
        password_hash
    )
