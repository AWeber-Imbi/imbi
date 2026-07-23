"""Advisory "currently editing" presence markers for documents.

Editors are tracked in a Valkey sorted set per document
(``imbi:document:editing:<org_slug>:<document_id>``) whose members are
principal names (emails) scored by their expiry timestamp. A heartbeat
refreshes the caller's entry; stale entries are pruned on every read. Presence
is purely advisory — it never blocks an edit — so every operation
degrades to "nobody is editing" when Valkey is unavailable rather
than failing the request.

Document existence is deliberately not verified here: heartbeats fire
every few seconds per open editor and a graph round-trip per beat
would be wasted load for a marker that expires on its own.
"""

import logging
import time
import typing

import fastapi
import pydantic
from valkey import asyncio as valkey_asyncio

from imbi.api.auth import permissions
from imbi.common import valkey

LOGGER = logging.getLogger(__name__)

document_presence_router = fastapi.APIRouter(tags=['Documents'])

PRESENCE_KEY_PREFIX = 'imbi:document:editing'
PRESENCE_TTL_SECONDS = 30


class DocumentEditorsResponse(pydantic.BaseModel):
    """Who currently holds an editing marker on the document."""

    editors: list[str]
    ttl_seconds: int = PRESENCE_TTL_SECONDS


def _key(org_slug: str, document_id: str) -> str:
    # Keyed by org so presence for one org's documents can never be
    # read or written through another org's URL space.
    return f'{PRESENCE_KEY_PREFIX}:{org_slug}:{document_id}'


def _decode_members(raw: typing.Any) -> list[str]:
    members = typing.cast('list[bytes]', raw)
    return sorted(m.decode() for m in members)


async def _active_editors(
    client: valkey_asyncio.Valkey, org_slug: str, document_id: str
) -> list[str]:
    """Prune expired entries and return the remaining editors, sorted.

    Batched in a single pipeline so a read costs one round-trip.
    """
    key = _key(org_slug, document_id)
    pipe = client.pipeline(transaction=False)
    pipe.zremrangebyscore(key, '-inf', time.time())
    pipe.zrange(key, 0, -1)  # pyright: ignore[reportUnknownMemberType]
    results = await pipe.execute()  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    return _decode_members(results[-1])


@document_presence_router.get('', response_model=DocumentEditorsResponse)
async def get_document_editors(
    org_slug: str,
    document_id: str,
    client: valkey.Client,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:read')),
    ],
) -> DocumentEditorsResponse:
    """List who is currently editing the document."""
    try:
        editors = await _active_editors(client, org_slug, document_id)
    except Exception:
        LOGGER.exception(
            'failed to read editing presence for document %s', document_id
        )
        editors = []
    return DocumentEditorsResponse(editors=editors)


@document_presence_router.put('', response_model=DocumentEditorsResponse)
async def heartbeat_document_editing(
    org_slug: str,
    document_id: str,
    client: valkey.Client,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:write')),
    ],
) -> DocumentEditorsResponse:
    """Start or refresh the caller's editing marker.

    Idempotent; clients call this every few seconds while the editor
    is open. The response includes every active editor (including the
    caller) so the editing client needs no separate GET poll. All four
    Valkey commands are batched in one pipeline (one round-trip).
    """
    key = _key(org_slug, document_id)
    now = time.time()
    try:
        pipe = client.pipeline(transaction=False)
        pipe.zadd(key, {auth.principal_name: now + PRESENCE_TTL_SECONDS})
        # Cap the key's own lifetime so abandoned documents leave no
        # keys behind once every member has expired.
        pipe.expire(key, PRESENCE_TTL_SECONDS)
        pipe.zremrangebyscore(key, '-inf', now)
        pipe.zrange(key, 0, -1)  # pyright: ignore[reportUnknownMemberType]
        results = await pipe.execute()  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        editors = _decode_members(results[-1])
    except Exception:
        LOGGER.exception(
            'failed to record editing presence for document %s', document_id
        )
        editors = []
    return DocumentEditorsResponse(editors=editors)


@document_presence_router.delete('', status_code=204)
async def clear_document_editing(
    org_slug: str,
    document_id: str,
    client: valkey.Client,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('document:write')),
    ],
) -> None:
    """Remove the caller's editing marker (done editing).

    Best-effort — the marker expires on its own within
    ``PRESENCE_TTL_SECONDS`` regardless.
    """
    try:
        await client.zrem(_key(org_slug, document_id), auth.principal_name)
    except Exception:
        LOGGER.exception(
            'failed to clear editing presence for document %s', document_id
        )
