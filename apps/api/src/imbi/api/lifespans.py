"""Lifespan hooks for imbi-api services.

Each hook is an async context manager that initializes a service on
startup and cleans it up on shutdown. Hooks are composed using
:class:`imbi_common.lifespan.Lifespan` in the application factory.
"""

import contextlib
import logging
from collections import abc

import imbi_common.graph
from imbi_common import clickhouse, graph

from imbi_api import openapi
from imbi_api.email.client import EmailClient
from imbi_api.email.templates import TemplateManager
from imbi_api.storage.client import StorageClient

LOGGER = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def clickhouse_hook() -> abc.AsyncIterator[None]:
    """Initialize and manage the ClickHouse connection."""
    result = await clickhouse.initialize()
    if result is False:
        raise RuntimeError('ClickHouse initialization failed')
    async with contextlib.aclosing(clickhouse):
        yield


@contextlib.asynccontextmanager
async def _graph_lifespan_with_setup() -> abc.AsyncIterator[graph.Graph]:
    """Open a Graph pool, refresh blueprints, and yield the pool.

    Replaces the plain ``graph.graph_lifespan`` so that blueprint
    refresh reuses the same connection pool that serves requests,
    instead of opening a second temporary pool.

    Assigned to ``imbi_common.graph.graph_lifespan`` at module load
    so that ``graph.Pool`` dependency injection continues to work
    (``graph._inject_graph`` resolves ``graph_lifespan`` at call
    time from the module namespace).
    """
    db = graph.Graph()
    await db.open()
    try:
        await openapi.refresh_blueprint_models(db)
    except Exception as err:  # noqa: BLE001
        LOGGER.warning('Failed to refresh blueprint models: %s', err)
    yield db
    await db.close()


# Replace graph.graph_lifespan so that graph._inject_graph (which
# looks up graph_lifespan at call time) resolves to the combined
# version.  This keeps graph.Pool working across all endpoints
# without changing any import sites.
imbi_common.graph.graph_lifespan = _graph_lifespan_with_setup


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
