"""Lifespan hooks for imbi-api services.

Each hook is an async context manager that initializes a service on
startup and cleans it up on shutdown. Hooks are composed using
:class:`imbi_common.lifespan.Lifespan` in the application factory.
"""

import contextlib
import logging
from collections import abc

from imbi_common import clickhouse, neo4j

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
async def neo4j_hook() -> abc.AsyncIterator[None]:
    """Initialize and manage the Neo4j connection."""
    await neo4j.initialize()
    async with contextlib.aclosing(neo4j):
        yield


@contextlib.asynccontextmanager
async def neo4j_setup_hook() -> abc.AsyncIterator[None]:
    """Refresh blueprint models after Neo4j is initialized.

    Must run after :func:`neo4j_hook`. Index/constraint creation is
    handled by :func:`imbi_common.neo4j.initialize`.
    """
    try:
        await openapi.refresh_blueprint_models()
    except Exception as err:  # noqa: BLE001
        LOGGER.warning('Failed to refresh blueprint models: %s', err)
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
