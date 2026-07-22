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
import contextlib
import logging
import pathlib
import tomllib
import typing

import clickhouse_connect.driver
import pydantic
from clickhouse_connect.datatypes import format
from clickhouse_connect.driver import asyncclient, exceptions, summary

from imbi.common import helpers, settings

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)


class SchemataQuery(pydantic.BaseModel):
    """Query for the Clickhouse schemata."""

    name: str
    query: str
    enabled: bool = True


#: Placeholder in ``schemata.toml`` DDL replaced with an ``ON CLUSTER
#: <name>`` clause when ``CLICKHOUSE_CLUSTER_NAME`` is set, or with an empty
#: string for single-node deployments.
ON_CLUSTER_PLACEHOLDER = '{on_cluster}'

#: Placeholder preceding a table engine name, replaced with ``Replicated``
#: when ``CLICKHOUSE_CLUSTER_NAME`` is set so engines become their
#: ``Replicated*`` variants, or with an empty string otherwise.
REPLICATED_PLACEHOLDER = '{replicated}'


def _render_cluster_placeholders(
    statement: str, cluster_name: str | None
) -> str:
    """Resolve cluster-related placeholders in a DDL statement.

    When ``cluster_name`` is set, ``{on_cluster}`` becomes ``ON CLUSTER
    <cluster_name> `` and ``{replicated}`` becomes ``Replicated`` so table
    engines replicate across the cluster (relying on the server's
    ``default_replica_path``/``default_replica_name`` macros for the Keeper
    path and replica name). Both placeholders are removed when no cluster
    name is configured.
    """
    on_cluster = f'ON CLUSTER {cluster_name} ' if cluster_name else ''
    replicated = 'Replicated' if cluster_name else ''
    return statement.replace(ON_CLUSTER_PLACEHOLDER, on_cluster).replace(
        REPLICATED_PLACEHOLDER, replicated
    )


class DatabaseError(Exception):
    """Base class for errors raised by the Clickhouse client."""


@contextlib.contextmanager
def _translate_errors(operation: str) -> typing.Iterator[None]:
    """Translate clickhouse driver errors into `DatabaseError`.

    Logs the failure, reports it to Sentry when `sentry_sdk` is
    installed, and re-raises as `DatabaseError` with a clear message.
    """
    try:
        yield
    except exceptions.DatabaseError as err:
        LOGGER.error('Error during clickhouse %s: %s', operation, err)
        if sentry_sdk is not None:
            sentry_sdk.capture_exception(err)
        raise DatabaseError(f'Clickhouse {operation} failed: {err}') from err


class Clickhouse:
    _instance = None

    def __init__(self) -> None:
        self._clickhouse: asyncclient.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._settings = settings.Clickhouse()
        format.set_read_format('IPv*', 'string')

    @classmethod
    def get_instance(cls) -> Clickhouse:
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
        with _translate_errors(f'insert into {table}'):
            return await self._clickhouse.insert(
                table, data, column_names=column_names
            )

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
        with _translate_errors('query'):
            result = await self._clickhouse.query(
                statement, parameters=parameters or {}
            )
        results = []
        for row in result.result_rows:
            data = dict(zip(result.column_names, row, strict=True))
            results.append(data)
        return results

    async def _connect(
        self, delay: float = 0.5
    ) -> asyncclient.AsyncClient | None:
        host = helpers.unwrap_as(str, self._settings.url.host)
        port = (
            8123
            if self._settings.url.port is None
            else self._settings.url.port
        )
        path = self._settings.url.path
        database = path[1:] if path else 'internal'
        if not database:
            database = 'internal'

        max_attempts = self._settings.max_connect_attempts
        current_delay = delay
        for attempt in range(1, max_attempts + 1):
            LOGGER.debug(
                'Connecting to Clickhouse at %s:%s (attempt %d)...',
                host,
                port,
                attempt,
            )
            try:
                return await clickhouse_connect.driver.create_async_client(
                    host=host,
                    port=port,
                    username=self._settings.url.username,
                    password=self._settings.url.password or '',
                    database=database,
                    connect_timeout=self._settings.connect_timeout,
                )
            except exceptions.OperationalError as err:
                if attempt >= max_attempts:
                    LOGGER.critical(
                        'Failed to Connect to Clickhouse after %s attempts',
                        attempt,
                    )
                    return None
                LOGGER.warning(
                    'Failed to connect to Clickhouse, sleeping %.2f '
                    'seconds: %s',
                    current_delay,
                    err,
                )
                await asyncio.sleep(current_delay)
                current_delay *= 2
        return None

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
        cluster_name = self._settings.cluster_name

        LOGGER.info(
            'Executing %d enabled schemata queries', len(enabled_queries)
        )

        for query_obj in enabled_queries:
            LOGGER.debug('Executing schemata query: %s', query_obj.name)
            statement = _render_cluster_placeholders(
                query_obj.query, cluster_name
            )
            try:
                await self.query(statement)
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
