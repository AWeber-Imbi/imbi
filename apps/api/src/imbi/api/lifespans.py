"""Lifespan hooks for imbi-api services.

Each hook is an async context manager that initializes a service on
startup and cleans it up on shutdown. Hooks are composed using
:class:`imbi_common.lifespan.Lifespan` in the application factory.
"""

import asyncio
import contextlib
import logging
from collections import abc

from imbi_common import clickhouse, graph, valkey

from imbi_api import openapi
from imbi_api.email.client import EmailClient
from imbi_api.email.templates import TemplateManager
from imbi_api.scoring import queue as score_queue
from imbi_api.storage.client import StorageClient

LOGGER = logging.getLogger(__name__)

_graph: graph.Graph | None = None


async def _on_graph_startup(db: graph.Graph) -> None:
    """Refresh blueprint models after the graph pool opens."""
    global _graph
    _graph = db
    try:
        await openapi.refresh_blueprint_models(db)
    except Exception as err:  # noqa: BLE001
        LOGGER.warning(
            'Failed to refresh blueprint models: %s',
            err,
        )


graph.set_on_startup(_on_graph_startup)


@contextlib.asynccontextmanager
async def clickhouse_hook() -> abc.AsyncIterator[None]:
    """Initialize and manage the ClickHouse connection."""
    result = await clickhouse.initialize()
    if result is False:
        raise RuntimeError('ClickHouse initialization failed')
    async with contextlib.aclosing(clickhouse):
        yield


@contextlib.asynccontextmanager
async def email_hook() -> abc.AsyncIterator[
    tuple[EmailClient, TemplateManager]
]:
    """Initialize and manage the email subsystem."""
    email_client = EmailClient()
    await email_client.initialize()
    template_manager = TemplateManager()
    async with contextlib.aclosing(email_client):
        yield email_client, template_manager


@contextlib.asynccontextmanager
async def storage_hook() -> abc.AsyncIterator[StorageClient]:
    """Initialize and manage S3 storage."""
    storage_client = StorageClient()
    await storage_client.initialize()
    async with contextlib.aclosing(storage_client):
        yield storage_client


@contextlib.asynccontextmanager
async def score_worker_hook() -> abc.AsyncIterator[None]:
    """Run the score-recompute consumer for the API process."""
    try:
        client = valkey.get_client()
    except RuntimeError:
        LOGGER.warning('Valkey unavailable; score worker not started')
        yield None
        return
    if _graph is None:
        LOGGER.warning('Graph not ready; score worker not started')
        yield None
        return
    ch = clickhouse.client.Clickhouse.get_instance()
    stop = asyncio.Event()
    task = asyncio.create_task(
        score_queue.consume_recompute(client, _graph, ch, stop=stop)
    )
    try:
        yield None
    finally:
        stop.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            LOGGER.debug('score worker exited with error', exc_info=True)
