"""Integration credential decryption.

Lives in ``imbi-common`` so every host that owns an Integration (the API
process, the gateway, future workers) decrypts credentials through one
implementation. There is exactly one credential store per Integration —
``Integration.encrypted_credentials``, a mapping of field name to a
Fernet-encrypted value (see :mod:`imbi.common.auth.encryption`). There is
no sibling lookup, no fallback ordering, and no per-capability divergence:
every capability of an Integration receives the same decrypted blob.
"""

import logging
import typing

from imbi.common.auth.encryption import TokenEncryption

LOGGER = logging.getLogger(__name__)


class _HasEncryptedCredentials(typing.Protocol):
    encrypted_credentials: dict[str, str]


def decrypt_integration_credentials(
    source: _HasEncryptedCredentials | dict[str, str],
) -> dict[str, str]:
    """Decrypt an Integration's credential blob.

    Accepts either an ``Integration`` node (anything with an
    ``encrypted_credentials`` mapping) or the mapping itself. Each value
    is Fernet-decrypted via :class:`TokenEncryption`; entries whose
    ciphertext is empty or fails to decrypt are dropped rather than
    surfaced as an empty string a ``key in dict`` check would satisfy.
    """
    if isinstance(source, dict):
        encrypted = source
    else:
        encrypted = source.encrypted_credentials

    encryptor = TokenEncryption.get_instance()
    decrypted: dict[str, str] = {}
    for name, ciphertext in encrypted.items():
        if not ciphertext:
            continue
        try:
            plaintext = encryptor.decrypt(ciphertext)
        except Exception:  # noqa: BLE001 - treat as missing, log and skip
            LOGGER.warning(
                'Integration credential %r failed to decrypt; skipping',
                name,
            )
            continue
        if plaintext:
            decrypted[name] = plaintext
    return decrypted
