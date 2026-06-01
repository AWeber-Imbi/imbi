"""Single-use OAuth2 authorization codes backed by Valkey.

The ``/auth/authorize`` endpoint mints an opaque code bound to the
authorization context (client, redirect URI, PKCE challenge, the
authenticated principal, and scope) and stores it in Valkey with a short
TTL. ``/auth/token`` redeems it with an atomic ``GETDEL`` so a code can
only be exchanged once, then verifies the PKCE code verifier.
"""

import base64
import hashlib
import json
import logging
import secrets
import typing

from valkey import asyncio as valkey_module

LOGGER = logging.getLogger(__name__)

_KEY_PREFIX = 'oauth:authcode:'
# Authorization codes are exchanged immediately by the client; a tight
# TTL bounds the replay/guessing window (RFC 6749 §4.1.2 recommends
# <= 10 minutes; we are far stricter since the exchange is machine-fast).
_TTL_SECONDS = 60


class CodePayload(typing.TypedDict):
    """Authorization context bound to an issued code."""

    client_id: str
    redirect_uri: str
    code_challenge: str
    principal_id: str
    scope: str | None


async def issue_code(
    valkey_client: valkey_module.Valkey,
    *,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    principal_id: str,
    scope: str | None,
) -> str:
    """Mint and store a single-use authorization code, returning it."""
    code = secrets.token_urlsafe(32)
    payload: CodePayload = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'code_challenge': code_challenge,
        'principal_id': principal_id,
        'scope': scope,
    }
    await valkey_client.set(  # pyright: ignore[reportUnknownMemberType]
        f'{_KEY_PREFIX}{code}', json.dumps(payload), ex=_TTL_SECONDS
    )
    return code


async def consume_code(
    valkey_client: valkey_module.Valkey, code: str
) -> CodePayload | None:
    """Atomically fetch-and-delete a code, returning its payload or None.

    The ``GETDEL`` makes redemption single-use: a second exchange of the
    same code finds nothing and returns ``None``.
    """
    raw = await valkey_client.getdel(  # pyright: ignore[reportUnknownMemberType]
        f'{_KEY_PREFIX}{code}'
    )
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8')
    return typing.cast('CodePayload', json.loads(raw))


def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """Return whether *code_verifier* matches *code_challenge* (S256)."""
    if not code_verifier or not code_challenge:
        return False
    try:
        verifier_bytes = code_verifier.encode('ascii')
    except UnicodeEncodeError:
        return False
    digest = hashlib.sha256(verifier_bytes).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
    return secrets.compare_digest(expected, code_challenge)
