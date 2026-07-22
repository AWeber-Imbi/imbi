"""Valkey async client and lifespan integration."""

import contextlib
import typing
from collections import abc

import fastapi
from valkey import asyncio as valkey

from imbi.common import lifespan, settings

_client: valkey.Valkey | None = None


def get_client() -> valkey.Valkey:
    """Return the module-level Valkey client set by valkey_lifespan."""
    if _client is None:
        raise RuntimeError('Valkey client is not initialized')
    return _client


@contextlib.asynccontextmanager
async def valkey_lifespan() -> abc.AsyncIterator[valkey.Valkey]:
    """Open a Valkey client and ensure it is closed on shutdown."""
    global _client
    _client = valkey.Valkey.from_url(str(settings.Valkey().url))
    try:
        yield _client
    finally:
        client, _client = _client, None
        if client is not None:
            await client.aclose()


async def _inject_client(
    context: lifespan.InjectLifespan,
) -> abc.AsyncIterator[valkey.Valkey]:
    yield context.get_state(valkey_lifespan)


Client = typing.Annotated[
    valkey.Valkey,
    fastapi.Depends(_inject_client),
]
