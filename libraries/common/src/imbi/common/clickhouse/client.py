"""
Abstracted Interface for interacting with Clickhouse

This module provides a singleton client for asynchronous interaction with
Clickhouse databases. It handles connection management, query execution,
and data insertion with proper error handling.

Example usage:
    # Query data
    data = await clickhouse.query(
        'SELECT * FROM table WHERE id = {id}', {'id': 123})

    # Insert data
    result = await clickhouse.insert(
        'table_name', [['value1', 'value2']], ['column1', 'column2'])
"""

import asyncio
import logging
import pathlib
import tomllib
import typing

import clickhouse_connect
import pydantic
from clickhouse_connect import driver
from clickhouse_connect.datatypes import format
from clickhouse_connect.driver import exceptions, summary

from imbi_common import settings

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None  # type: ignore[assignment,unused-ignore]

LOGGER = logging.getLogger(__name__)


class SchemataQuery(pydantic.BaseModel):
    """Query for the Clickhouse schemata."""

    name: str
    query: str
    enabled: bool = True


class DatabaseError(Exception):
    """Base class for errors raised by the Clickhouse client."""


class Clickhouse:
    _instance = None

    def __init__(self) -> None:
        self._clickhouse: driver.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._settings = settings.Clickhouse()
        format.set_read_format('IPv*', 'string')

    @classmethod
    def get_instance(cls) -> 'Clickhouse':
        """Get an instance of the Clickhouse client."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def initialize(self) -> bool:
        """Create a new async client and test the connection."""
        LOGGER.debug('Starting Clickhouse')
        async with self._lock:
            if self._clickhouse is None:
                self._clickhouse = await self._connect()

        return self._clickhouse is not None

    async def setup_schema(self) -> None:
        """Execute DDL queries from schemata.toml to set up database schema.

        This should be called explicitly during initial setup, not on every
        startup. Loads and executes enabled queries from schemata.toml.
        """
        if not self._clickhouse:
            await self.initialize()
        if not self._clickhouse:
            raise RuntimeError('Failed to initialize ClickHouse client')

        await self._execute_schemata_queries()

    async def aclose(self) -> None:
        """Close any open connections to Clickhouse."""
        async with self._lock:
            if self._clickhouse is not None:
                await self._clickhouse.close()
            self._clickhouse = None

    async def insert(
        self, table: str, data: list[list[typing.Any]], column_names: list[str]
    ) -> summary.QuerySummary:
        """Insert data into Clickhouse"""
        LOGGER.debug('Clickhouse INSERT: %s (%r)', table, column_names)
        if not self._clickhouse:
            await self.initialize()
        if not self._clickhouse:
            raise RuntimeError('Failed to initialize ClickHouse client')
        try:
            return await self._clickhouse.insert(
                table, data, column_names=column_names
            )
        except exceptions.DatabaseError as err:
            LOGGER.error('Error inserting data to %s: %s', table, err)
            if sentry_sdk:
                sentry_sdk.capture_exception(err)
            raise DatabaseError(str(err)) from err

    async def query(
        self, statement: str, parameters: dict[str, typing.Any] | None = None
    ) -> list[dict[str, typing.Any]]:
        """Query the Clickhouse database and return results as a list of dicts.

        Args:
           statement: SQL query string, possibly with parameter placeholders
           parameters: Optional dictionary of parameter values

        Returns:
           List of dictionaries mapping column names to values

        Raises:
           DatabaseError: If there's an error executing the query
        """
        if not self._clickhouse:
            await self.initialize()
        if not self._clickhouse:
            raise RuntimeError('Failed to initialize ClickHouse client')
        LOGGER.debug('Clickhouse QUERY: %s', statement)
        LOGGER.debug('Clickhouse QUERY Parameters: %r', parameters)
        try:
            result = await self._clickhouse.query(
                statement, parameters=parameters or {}
            )
        except exceptions.DatabaseError as err:
            LOGGER.error('Error querying data: %s', err)
            if sentry_sdk:
                sentry_sdk.capture_exception(err)
            raise DatabaseError(str(err)) from err
        results = []
        for row in result.result_rows:
            data = dict(zip(result.column_names, row, strict=False))
            results.append(data)
        return results

    async def _connect(
        self, delay: float = 0.5, attempt: int = 1
    ) -> clickhouse_connect.driver.AsyncClient | None:
        LOGGER.debug(
            'Connecting to Clickhouse at %s:%s (attempt %d)...',
            self._settings.url.host,
            self._settings.url.port,
            attempt,
        )
        try:
            # Extract database from path (strip leading /)
            path = self._settings.url.path
            database = path[1:] if path else 'internal'
            if not database:
                database = 'internal'

            return await clickhouse_connect.create_async_client(
                host=self._settings.url.host,
                port=self._settings.url.port,
                username=self._settings.url.username,
                password=self._settings.url.password,
                database=database,
            )
        except exceptions.OperationalError as err:
            LOGGER.warning(
                'Failed to connect to Clickhouse, sleeping %.2f seconds: %s',
                delay,
                err,
            )
            await asyncio.sleep(delay)
            if attempt >= 10:
                LOGGER.critical(
                    'Failed to Connect to Clickhouse after 10 attempts'
                )
                return None
            return await self._connect(delay * 2, attempt + 1)

    def _load_schemata_queries(self) -> list[SchemataQuery]:
        """Load queries from schemata.toml file.

        Returns:
            List of SchemataQuery objects parsed from the TOML file.
        """
        schemata_path = pathlib.Path(__file__).parent / 'schemata.toml'
        LOGGER.debug('Loading schemata from %s', schemata_path)

        if not schemata_path.exists():
            LOGGER.warning('Schemata file not found at %s', schemata_path)
            return []

        with schemata_path.open('rb') as f:
            schemata_data = tomllib.load(f)

        queries = []
        for name, data in schemata_data.items():
            try:
                query = SchemataQuery(name=name, **data)
                queries.append(query)
            except pydantic.ValidationError as err:
                LOGGER.error('Invalid schemata entry %s: %s', name, err)

        return queries

    async def _execute_schemata_queries(self) -> None:
        """Execute all enabled queries from schemata.toml."""
        queries = self._load_schemata_queries()
        enabled_queries = [q for q in queries if q.enabled]

        LOGGER.info(
            'Executing %d enabled schemata queries', len(enabled_queries)
        )

        for query_obj in enabled_queries:
            LOGGER.debug('Executing schemata query: %s', query_obj.name)
            try:
                await self.query(query_obj.query)
                LOGGER.debug(
                    'Successfully executed schemata query: %s', query_obj.name
                )
            except DatabaseError as err:
                LOGGER.error(
                    'Failed to execute schemata query %s: %s',
                    query_obj.name,
                    err,
                )
                # Continue with other queries even if one fails
                if sentry_sdk:
                    sentry_sdk.capture_exception(err)
