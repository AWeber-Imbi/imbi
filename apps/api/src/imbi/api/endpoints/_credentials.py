"""Shared helpers for API-key / client-credential creation and rotation.

`endpoints/api_keys.py`, `endpoints/sa_api_keys.py`, and
`endpoints/client_credentials.py` each generated a secret, hashed it,
validated the expiration window, and (for the service-account-scoped
endpoints) persisted a node wired to its ``ServiceAccount`` with
byte-identical code. These helpers are the single home for those steps.
"""

import asyncio
import datetime
import secrets
import typing

import fastapi

from imbi.api.auth import password
from imbi.common import graph


async def generate_secret() -> tuple[str, str]:
    """Return ``(secret, secret_hash)`` for a new credential.

    The plaintext secret is shown to the caller exactly once; only the
    hash is persisted. Hashing runs in a thread to keep the event loop
    free during the (deliberately slow) Argon2 work.
    """
    secret = secrets.token_urlsafe(32)
    secret_hash = await asyncio.to_thread(password.hash_password, secret)
    return secret, secret_hash


def compute_expires_at(
    expires_in_days: int | None,
    max_lifetime_days: int,
) -> datetime.datetime | None:
    """Resolve an expiration timestamp, enforcing the maximum lifetime.

    Returns ``None`` for a never-expiring credential
    (``expires_in_days`` falsy). Raises ``HTTPException(400)`` when the
    requested window exceeds ``max_lifetime_days``.
    """
    if not expires_in_days:
        return None
    if expires_in_days > max_lifetime_days:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                'Expiration exceeds maximum allowed lifetime of '
                f'{max_lifetime_days} days'
            ),
        )
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        days=expires_in_days
    )


async def create_service_account_owned_node(
    db: graph.Graph,
    *,
    label: str,
    props: dict[str, typing.Any],
    slug: str,
) -> bool:
    """``CREATE`` a *label* node owned by the ``ServiceAccount`` *slug*.

    Builds the ``{key: {key}}`` property map from *props* and wires the
    new node with ``-[:OWNED_BY]->(s)``. Returns ``True`` on success, or
    ``False`` when the service account does not exist (no row created).
    """
    prop_map = ', '.join(f'{key}: {{{key}}}' for key in props)
    records = await db.execute(
        f'MATCH (s:ServiceAccount {{{{slug: {{slug}}}}}})'
        f' CREATE (n:{label} {{{{{prop_map}}}}})'
        f'-[:OWNED_BY]->(s) RETURN n',
        {**props, 'slug': slug},
    )
    return bool(records)
