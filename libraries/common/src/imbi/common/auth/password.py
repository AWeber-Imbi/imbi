"""Password hashing utilities using Argon2id.

Shared rather than API-local because API-key verification lives in
:mod:`imbi.common.auth.permissions` and hashes key secrets with the
same hasher: every member that authenticates an ``ik_`` bearer needs
:func:`verify_password`. ``imbi.api.auth.password`` re-exports these
names, so local-auth password flows in imbi-api are unaffected.
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
        # `VerificationError` alone. `VerifyMismatchError` is a subclass of it
        # -- VerifyMismatchError -> VerificationError -> Argon2Error -- so
        # naming both caught nothing the parent did not. `InvalidHashError`
        # is a sibling under `Argon2Error`, not a subclass, so it stays.
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
    return bool(password_hasher.check_needs_rehash(password_hash))
