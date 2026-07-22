"""Shared TOTP / MFA secret verification helpers.

The login flow (``endpoints/auth.py``) and the MFA enable/disable flows
(``endpoints/mfa.py``) each fetched the user's ``TOTPSecret`` node,
decrypted it, and verified a submitted TOTP or backup code with
byte-identical code. This module is the single home for the fetch +
decrypt + verify steps.

State mutation stays at the call sites because it differs per flow: the
login backup path atomically removes the used code (H6) without
touching ``enabled``; the enable path sets ``enabled``/``last_used`` and
removes the used code; the disable path verifies only and then deletes
the whole secret.
"""

from __future__ import annotations

import asyncio
import logging
import typing

import fastapi
import pyotp
from imbi_common import graph
from imbi_common.auth import encryption

from imbi_api.auth import password

LOGGER = logging.getLogger(__name__)

FETCH_TOTP_QUERY: typing.LiteralString = """
MATCH (u:User {{email: {email}}})
      <-[:MFA_FOR]-(t:TOTPSecret)
RETURN t AS n
"""


async def fetch_totp_secret(
    db: graph.Graph,
    email: str,
) -> dict[str, typing.Any] | None:
    """Return the user's parsed ``TOTPSecret`` node, or None if absent."""
    records = await db.execute(FETCH_TOTP_QUERY, {'email': email})
    if not records:
        return None
    return typing.cast(
        'dict[str, typing.Any]', graph.parse_agtype(records[0]['n'])
    )


def decrypt_totp_secret(encrypted_secret: str) -> str:
    """Decrypt a stored TOTP secret, raising HTTP 500 on failure."""
    encryptor = encryption.TokenEncryption.get_instance()
    try:
        secret = encryptor.decrypt(encrypted_secret)
        if secret is None:
            raise ValueError('Decryption returned None')
    except (ValueError, TypeError) as err:
        LOGGER.error('Failed to decrypt TOTP secret: %s', err)
        raise fastapi.HTTPException(
            status_code=500,
            detail='Failed to decrypt MFA secret',
        ) from err
    return secret


async def verify_totp_code(
    totp_data: dict[str, typing.Any],
    code: str,
    *,
    period: int,
    digits: int,
) -> tuple[bool, str | None]:
    """Verify *code* against a ``TOTPSecret`` node's secret + backup codes.

    Returns ``(is_valid, matched_backup_hash)``. ``matched_backup_hash``
    is the stored hash that a backup code matched, or ``None`` for a TOTP
    match (or no match at all).

    This does NOT consume the backup code or write any state — callers
    own the atomic removal (H6) and any ``enabled``/``last_used`` writes.
    A submitted code can match at most one backup hash (codes are
    distinct random values), so a matched hash that subsequently loses
    the consume race is a plain auth failure: there is no second hash to
    fall through to.
    """
    secret = decrypt_totp_secret(totp_data['secret'])
    totp = pyotp.TOTP(secret, interval=period, digits=digits)
    if totp.verify(code, valid_window=1):
        return True, None
    backup_codes = typing.cast(
        'list[str]', totp_data.get('backup_codes') or []
    )
    for backup_hash in backup_codes:
        if await asyncio.to_thread(
            password.verify_password, code, backup_hash
        ):
            return True, backup_hash
    return False, None
