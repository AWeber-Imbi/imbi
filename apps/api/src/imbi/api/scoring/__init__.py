"""Scoring queue and triggers for imbi-api."""

import typing
from collections import abc

import fastapi
from valkey import asyncio as valkey

from imbi.api.scoring.queue import (
    affected_projects,
    consume_recompute,
    enqueue_recompute,
)
from imbi.common import helpers, lifespan
from imbi.common import valkey as common_valkey

__all__ = [
    'OptionalValkeyClient',
    'affected_projects',
    'consume_recompute',
    'enqueue_recompute',
]


async def _inject_optional_client(
    request: fastapi.Request,
) -> abc.AsyncIterator[valkey.Valkey | None]:
    """Yield the Valkey client, or ``None`` when lifespan is absent."""
    client: valkey.Valkey | None = None
    try:
        ctx = helpers.unwrap_as(
            lifespan.Lifespan,
            typing.cast(object, request.state.lifespan_data),
        )
        client = ctx.get_state(common_valkey.valkey_lifespan)
    except AttributeError, ValueError, fastapi.HTTPException:
        client = None
    yield client


OptionalValkeyClient = typing.Annotated[
    valkey.Valkey | None,
    fastapi.Depends(_inject_optional_client),
]
