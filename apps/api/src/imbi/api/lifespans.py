"""Lifespan hooks for imbi-api services.

Each hook is an async context manager that initializes a service on
startup and cleans it up on shutdown. Hooks are composed using
:class:`imbi_common.lifespan.Lifespan` in the application factory.
"""

import contextlib
import logging
from collections import abc

from imbi_common import clickhouse, neo4j
from neo4j import exceptions as neo4j_exc

from imbi_api import email, neo4j_indexes, openapi, storage

LOGGER = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def clickhouse_hook() -> abc.AsyncIterator[None]:
    """Initialize and manage the ClickHouse connection."""
    result = await clickhouse.initialize()
    if result is False:
        raise RuntimeError('ClickHouse initialization failed')
    try:
        yield
    finally:
        await clickhouse.aclose()


@contextlib.asynccontextmanager
async def neo4j_hook() -> abc.AsyncIterator[None]:
    """Initialize Neo4j, create indexes, and refresh blueprints."""
    await neo4j.initialize()
    try:
        # Create API-specific indexes (must run after init)
        async with neo4j.session() as sess:
            for index in neo4j_indexes.INDEXES:
                try:
                    await sess.run(index)
                except neo4j_exc.ConstraintError as err:
                    LOGGER.debug('Index already exists: %s', err)
                except Exception:  # noqa: BLE001
                    LOGGER.warning(
                        'Failed to create index: %s',
                        index,
                    )
        # Refresh blueprint models for OpenAPI schema
        try:
            await openapi.refresh_blueprint_models()
        except Exception as err:  # noqa: BLE001
            LOGGER.warning('Failed to refresh blueprint models: %s', err)
        yield
    finally:
        await neo4j.aclose()


@contextlib.asynccontextmanager
async def email_hook() -> abc.AsyncIterator[None]:
    """Initialize and manage the email subsystem."""
    await email.initialize()
    try:
        yield
    finally:
        await email.aclose()


@contextlib.asynccontextmanager
async def storage_hook() -> abc.AsyncIterator[None]:
    """Initialize and manage S3 storage."""
    await storage.initialize()
    try:
        yield
    finally:
        await storage.aclose()

