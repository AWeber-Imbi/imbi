"""Postgres store for scheduled tasks."""

import contextlib
import typing
from collections import abc

import fastapi
import psycopg
import psycopg_pool

from imbi.common import lifespan
from imbi.common import settings as common_settings
from imbi.scheduler.store.initializer import initialize, load_schemata
from imbi.scheduler.store.tasks import NOTIFY_CHANNEL, Tasks

type Pool = psycopg_pool.AsyncConnectionPool[
    psycopg.AsyncConnection[typing.Any]
]


def create_pool() -> Pool:
    """Return an unopened connection pool for the scheduler schema."""
    postgres = common_settings.Postgres()
    return psycopg_pool.AsyncConnectionPool(
        conninfo=str(postgres.url),
        min_size=postgres.min_pool_size,
        max_size=postgres.max_pool_size,
        open=False,
    )


@contextlib.asynccontextmanager
async def store_lifespan() -> abc.AsyncGenerator[Tasks]:
    """Initialize the schema and hold the task repository open."""
    await initialize()
    pool = create_pool()
    await pool.open()
    try:
        yield Tasks(pool)
    finally:
        await pool.close()


async def _inject_tasks(
    context: lifespan.InjectLifespan,
) -> abc.AsyncIterator[Tasks]:
    yield context.get_state(store_lifespan)


TaskStore = typing.Annotated[Tasks, fastapi.Depends(_inject_tasks)]

__all__ = [
    'NOTIFY_CHANNEL',
    'Pool',
    'TaskStore',
    'Tasks',
    'create_pool',
    'initialize',
    'load_schemata',
    'store_lifespan',
]
