"""Single-use OAuth2 authorization codes backed by Valkey.

The ``/auth/authorize`` endpoint mints an opaque code bound to the
authorization context (client, redirect URI, PKCE challenge, the
authenticated principal, and scope) and stores it in Valkey with a short
TTL. ``/auth/token`` redeems it with an atomic ``GETDEL`` so a code can
only be exchanged once, then verifies the PKCE code verifier.

Before a code is minted the user must approve the client. The pending
request is held under a single-use consent token, and an approval is
remembered per (user, client) so a known client skips the prompt.
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


# -- user consent ---------------------------------------------------------

_CONSENT_TOKEN_PREFIX = 'oauth:consent-token:'
_CONSENT_GRANT_PREFIX = 'oauth:consent-grant:'
# Time the user has to click Approve or Deny on the consent page.
_CONSENT_TOKEN_TTL_SECONDS = 300
# Time a remembered approval lets a client skip the consent page.
_CONSENT_GRANT_TTL_SECONDS = 90 * 24 * 60 * 60


class ConsentPayload(typing.TypedDict):
    """Authorization request held while the user decides on consent."""

    client_id: str
    redirect_uri: str
    code_challenge: str
    principal_id: str
    scope: str | None
    state: str | None


async def issue_consent_token(
    valkey_client: valkey_module.Valkey, payload: ConsentPayload
) -> str:
    """Store a pending authorization request and return its token."""
    token = secrets.token_urlsafe(32)
    await valkey_client.set(  # pyright: ignore[reportUnknownMemberType]
        f'{_CONSENT_TOKEN_PREFIX}{token}',
        json.dumps(payload),
        ex=_CONSENT_TOKEN_TTL_SECONDS,
    )
    return token


async def consume_consent_token(
    valkey_client: valkey_module.Valkey, token: str
) -> ConsentPayload | None:
    """Atomically fetch-and-delete a consent token (single use)."""
    if not token:
        return None
    raw = await valkey_client.getdel(  # pyright: ignore[reportUnknownMemberType]
        f'{_CONSENT_TOKEN_PREFIX}{token}'
    )
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8')
    return typing.cast('ConsentPayload', json.loads(raw))


def _grant_key(principal_id: str, client_id: str, redirect_uri: str) -> str:
    # The redirect URI is part of the key: one client may register
    # several URIs, and the user approved only the host they were shown.
    return f'{_CONSENT_GRANT_PREFIX}{client_id}:{principal_id}:{redirect_uri}'


async def remember_consent(
    valkey_client: valkey_module.Valkey, payload: ConsentPayload
) -> None:
    """Record that the user approved the client for this redirect URI."""
    await valkey_client.set(  # pyright: ignore[reportUnknownMemberType]
        _grant_key(
            payload['principal_id'],
            payload['client_id'],
            payload['redirect_uri'],
        ),
        '1',
        ex=_CONSENT_GRANT_TTL_SECONDS,
    )


async def has_consent(
    valkey_client: valkey_module.Valkey, payload: ConsentPayload
) -> bool:
    """Return whether the user already approved this client and URI."""
    return bool(
        await valkey_client.exists(  # pyright: ignore[reportUnknownMemberType]
            _grant_key(
                payload['principal_id'],
                payload['client_id'],
                payload['redirect_uri'],
            )
        )
    )
