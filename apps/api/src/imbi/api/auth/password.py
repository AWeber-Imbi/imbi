"""Password hashing utilities using Argon2id.

Now a re-export of :mod:`imbi.common.auth.password`: API-key secrets
are verified with the same hasher from the shared auth path, so the
implementation moved to imbi-common. The names stay here because
local-auth, MFA, and the user endpoints import them from this module.
"""

from imbi.common.auth.password import (
    hash_password,
    needs_rehash,
    password_hasher,
    verify_password,
)

__all__ = [
    'hash_password',
    'needs_rehash',
    'password_hasher',
    'verify_password',
]
