"""Valkey async client and lifespan integration."""

import contextlib
import typing
from collections import abc

import fastapi
from valkey import asyncio as valkey

from imbi_common import lifespan, settings


@contextlib.asynccontextmanager
async def valkey_lifespan() -> abc.AsyncIterator[valkey.Valkey]:
    """Open a Valkey client and ensure it is closed on shutdown."""
    client = valkey.Valkey.from_url(str(settings.Valkey().url))
    try:
        yield client
    finally:
        await client.aclose()


async def _inject_client(
    context: lifespan.InjectLifespan,
) -> abc.AsyncIterator[valkey.Valkey]:
    yield context.get_state(valkey_lifespan)


Client = typing.Annotated[
    valkey.Valkey,
    fastapi.Depends(_inject_client),
]
