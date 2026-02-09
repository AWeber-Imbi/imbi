"""PostgreSQL connection pool integration with type-safe DI.

This module provides PostgreSQL connectivity using psycopg's
AsyncConnectionPool with FastAPI lifespan management. It follows the
lifespan pattern from src/imbi_gateway/lifespan.py for type-safe
dependency injection.

Usage Example:
    ::

        from imbi_gateway import postgres

        # In app creation
        app = fastapi.FastAPI(
            lifespan=lifespan.Lifespan(postgres.postgres_lifespan)
        )

        # In route handlers
        @app.get('/data')
        async def handler(*, cursor: postgres.PostgresCursor) -> None:
            await cursor.execute('SELECT ...')

Configuration:
    Set POSTGRES_URL environment variable with connection string.
    Connection URL supports tuning parameters as query string values.
    See: https://www.postgresql.org/docs/current/libpq-connect.html

Type Aliases:
    - PostgresPool: Annotated type for injecting pool

See Also:
    - src/imbi_gateway/lifespan.py for the lifespan pattern
    - docs/lifespan-pattern.md for comprehensive tutorial
"""

import contextlib
import typing as t
from collections import abc

import fastapi
import psycopg.rows
import psycopg_pool
import pydantic
import pydantic_settings

from imbi_gateway import lifespan

type RowType = psycopg.rows.DictRow
type ConnectionType = psycopg.AsyncConnection[RowType]
type CursorType = psycopg.AsyncCursor[RowType]
type PoolType = psycopg_pool.AsyncConnectionPool[ConnectionType]


class Settings(pydantic_settings.BaseSettings):
    """PostgreSQL connection settings from environment.

    Attributes:
        url: PostgreSQL connection URL (required). Supports connection
            parameters as query string values. Examples:
            - postgresql://user:pass@localhost/db
            - postgresql://localhost/db?pool_size=5&connect_timeout=10
    """

    model_config = pydantic_settings.SettingsConfigDict(env_prefix='POSTGRES_')

    url: pydantic.PostgresDsn


@contextlib.asynccontextmanager
async def postgres_lifespan() -> abc.AsyncIterator[PoolType]:
    """Set up PostgreSQL connection pool for application lifespan.

    Creates an AsyncConnectionPool from the POSTGRES_URL environment
    variable. The pool is opened on application startup and closed on
    shutdown. Connection parameters can be tuned via URL query string.

    Yields:
        PoolType: An opened AsyncConnectionPool ready for use.

    Raises:
        pydantic.ValidationError: If POSTGRES_URL is missing or invalid.
        psycopg.OperationalError: If database connection fails.

    See Also:
        Settings: Configuration from environment variables
    """
    settings = Settings()  # type: ignore[call-arg]
    async with psycopg_pool.AsyncConnectionPool(
        conninfo=str(settings.url),
        configure=_configure_connection,
        open=False,
    ) as pool:
        await pool.open(wait=True)
        # double cast required due to the psycopg class model
        yield t.cast('PoolType', t.cast('object', pool))


async def _configure_connection(conn: psycopg.AsyncConnection[t.Any]) -> None:
    """Configure new connections from the pool.

    Called automatically by AsyncConnectionPool when creating new
    connections. Configures connections to use autocommit mode and
    return query results as dictionaries instead of tuples.

    Autocommit mode eliminates the need for explicit transaction
    management in route handlers, simplifying code for typical CRUD
    operations. DictRow provides named access to query results.

    Args:
        conn: The newly created connection to configure.

    Example:
        ::

            # With autocommit and dict_row configured:
            async def handler(*, cursor: PostgresCursor) -> dict:
                await cursor.execute('SELECT id, name FROM users')
                row = await cursor.fetchone()
                # Access by column name instead of index
                return {'id': row['id'], 'name': row['name']}

    See Also:
        postgres_lifespan: Passes this function to AsyncConnectionPool
            via the configure parameter
    """
    await conn.set_autocommit(True)
    conn.row_factory = psycopg.rows.dict_row


def _get_pool(context: lifespan.InjectLifespan) -> PoolType:
    """Provide PostgreSQL connection pool for dependency injection.

    Retrieves the connection pool from lifespan state. The pool is
    shared across all requests and managed by the application lifespan.

    Args:
        context: Lifespan context with access to lifespan-managed
            resources.

    Returns:
        PoolType: The AsyncConnectionPool instance.

    Raises:
        fastapi.HTTPException: 500 error if postgres_lifespan hook is
            not registered with the application.

    Example:
        ::

            async def _get_pool(
                context: lifespan.InjectLifespan
            ) -> PoolType:
                pool = context.get_state(postgres_lifespan)
                return pool
    """
    return context.get_state(postgres_lifespan)


PostgresPool = t.Annotated[PoolType, fastapi.Depends(_get_pool)]
"""Type alias for injecting PostgreSQL connection pool.

Use this in route handler parameters to inject the shared connection
pool. The pool is managed by the application lifespan.

Example:
    ::

        @app.get('/stats')
        async def handler(*, pool: postgres.PostgresPool) -> dict:
            return pool.get_stats()
"""
