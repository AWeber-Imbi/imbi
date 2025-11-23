"""
Database configuration and connection management using Piccolo ORM.
"""

from __future__ import annotations

import logging

from piccolo.engine.postgres import PostgresEngine

logger = logging.getLogger(__name__)

# Global database engine instance
DB: PostgresEngine | None = None


async def initialize_database(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    min_pool_size: int = 1,
    max_pool_size: int = 20,
    _query_timeout: int = 30,  # Not yet used - Piccolo doesn't support query timeout in engine
    log_queries: bool = False,
) -> None:
    """
    Initialize the Piccolo database engine.

    Args:
        host: PostgreSQL host
        port: PostgreSQL port
        database: Database name
        user: Database user
        password: Database password
        min_pool_size: Minimum connection pool size
        max_pool_size: Maximum connection pool size
        _query_timeout: Query timeout in seconds (not yet implemented in Piccolo)
        log_queries: Whether to log all queries (useful for debugging)
    """
    global DB

    logger.info(
        f"Initializing database connection to {host}:{port}/{database} "
        f"(pool: {min_pool_size}-{max_pool_size})"
    )

    DB = PostgresEngine(
        config={
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password,
        },
        extensions=[
            "uuid-ossp",  # UUID generation
            "citext",  # Case-insensitive text
            "pg_trgm",  # Trigram matching for search
        ],
        log_queries=log_queries,
        min_size=min_pool_size,
        max_size=max_pool_size,
    )

    # Test the connection
    try:
        async with DB.transaction():
            result = await DB.execute("SELECT version()")
            logger.info(f"Connected to PostgreSQL: {result[0]['version']}")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise


async def close_database() -> None:
    """Close the database connection pool."""
    global DB

    if DB:
        logger.info("Closing database connection pool")
        await DB.close_connection_pool()
        DB = None


def get_db() -> PostgresEngine:
    """
    Get the database engine instance.

    Returns:
        The initialized PostgresEngine instance

    Raises:
        RuntimeError: If database is not initialized
    """
    if DB is None:
        raise RuntimeError(
            "Database not initialized. Call initialize_database() first."
        )
    return DB
