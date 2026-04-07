"""Apache AGE async client singleton.

Manages an :class:`psycopg_pool.AsyncConnectionPool` and provides
a connection context manager that loads the AGE extension and sets
the search path on each checkout.
"""

import asyncio
import contextlib
import logging
import typing
from importlib import metadata

import psycopg
from psycopg_pool import AsyncConnectionPool

from imbi_common import settings

from . import constants

LOGGER = logging.getLogger(__name__)

try:
    version = metadata.version('imbi-common')
except metadata.PackageNotFoundError:
    version = '0.0.0'


class AGE:
    """Singleton async client for Apache AGE."""

    _instance: typing.ClassVar['AGE | None'] = None

    def __init__(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._settings = settings.AGE()
        self._pool: AsyncConnectionPool | None = None
        self._pool_lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> 'AGE':
        if cls._instance is None:
            cls._instance = AGE()
        else:
            current_loop = asyncio.get_event_loop()
            if cls._instance._loop != current_loop:
                LOGGER.debug('Event loop changed, reinitializing AGE')
                cls._instance._loop = current_loop
                cls._instance._pool = None
        return cls._instance

    @staticmethod
    async def _configure_connection(
        conn: psycopg.AsyncConnection[typing.Any],
    ) -> None:
        """Called once per connection when it is first created."""
        await conn.set_autocommit(True)
        await conn.execute("LOAD 'age'")
        await conn.execute('SET search_path = ag_catalog, "$user", public')

    async def _ensure_pool(self) -> AsyncConnectionPool:
        if self._pool is not None:
            return self._pool
        async with self._pool_lock:
            if self._pool is None:
                conninfo = str(self._settings.url)
                pool = AsyncConnectionPool(
                    conninfo=conninfo,
                    min_size=self._settings.min_pool_size,
                    max_size=self._settings.max_pool_size,
                    configure=self._configure_connection,
                    open=False,
                )
                await pool.open()
                self._pool = pool
        return self._pool

    async def aclose(self) -> None:
        LOGGER.debug('Closing AGE connection pool')
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def initialize(self) -> None:
        """Bootstrap the AGE extension, graph, and indexes."""
        LOGGER.debug('Initializing AGE')
        pool = await self._ensure_pool()
        async with pool.connection() as conn:
            await conn.set_autocommit(True)
            # Load AGE extension and set search path
            for stmt in constants.SETUP:
                await conn.execute(stmt)

            # Ensure graph exists
            await conn.execute(constants.ENSURE_GRAPH)

            # Create vertex label tables via create_vlabel() so index
            # DDL can reference them.  DuplicateObject means the label
            # already exists (idempotent on re-runs).
            for stmt in constants.ENSURE_LABELS:
                try:
                    await conn.execute(stmt)
                except psycopg.errors.DuplicateTable:
                    continue
                except Exception:  # noqa: BLE001
                    LOGGER.debug(
                        'Label bootstrap statement skipped: %s',
                        stmt[:80],
                    )

            # Create indexes and unique constraints
            for stmt in constants.INDEXES:
                try:
                    await conn.execute(stmt)
                except psycopg.errors.DuplicateTable:
                    # Index already exists
                    continue
                except Exception as err:  # noqa: BLE001
                    LOGGER.debug('Error creating index: %s', err)
                    continue

    @contextlib.asynccontextmanager
    async def connection(
        self,
    ) -> typing.AsyncGenerator[psycopg.AsyncConnection[typing.Any], None]:
        """Yield a connection with AGE loaded and search_path set.

        The pool's ``configure`` callback handles LOAD/SET on first
        use, so per-checkout overhead is just the pool checkout itself.
        """
        pool = await self._ensure_pool()
        async with pool.connection() as conn:
            yield conn
