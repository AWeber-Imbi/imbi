"""Valkey pub/sub subscriber for cross-pod plugin reload."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator

from imbi_common import graph, valkey
from imbi_common.plugins.registry import (
    reload_plugins,
)
from valkey import asyncio as _valkey_asyncio

from imbi_api.plugins.lifecycle import (
    _audit_unavailable,  # pyright: ignore[reportPrivateUsage]
)

LOGGER = logging.getLogger(__name__)

_CHANNEL = 'imbi:plugins:reload'


async def _subscribe_reload(
    client: _valkey_asyncio.Valkey,
    db: graph.Graph,
    stop: asyncio.Event,
) -> None:
    pubsub = client.pubsub()
    await pubsub.subscribe(_CHANNEL)  # pyright: ignore[reportUnknownMemberType]
    LOGGER.info('Plugin reload subscriber started on channel %r', _CHANNEL)
    try:
        while not stop.is_set():
            try:
                msg = await asyncio.wait_for(  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
                    pubsub.get_message(ignore_subscribe_messages=True),  # pyright: ignore[reportUnknownArgumentType,reportUnknownMemberType]
                    timeout=1.0,
                )
            except TimeoutError:
                continue
            if msg is not None:
                LOGGER.info('Plugin reload triggered via pub/sub')
                reload_plugins()
                await _audit_unavailable(db)
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(_CHANNEL)  # pyright: ignore[reportUnknownMemberType]


@contextlib.asynccontextmanager
async def plugin_reload_hook(
    db: graph.Graph | None = None,
) -> AsyncGenerator[None]:
    """Async context manager that runs the Valkey reload subscriber."""
    try:
        client = valkey.get_client()
    except RuntimeError:
        LOGGER.warning('Valkey unavailable; plugin reload not started')
        yield
        return
    if db is None:
        LOGGER.warning('Graph not ready; plugin reload not started')
        yield
        return
    stop = asyncio.Event()
    task = asyncio.create_task(_subscribe_reload(client, db, stop))
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def publish_reload(
    client: _valkey_asyncio.Valkey,
) -> None:
    """Publish a reload notification to all pods."""
    await client.publish(_CHANNEL, 'reload')  # pyright: ignore[reportUnknownMemberType]
