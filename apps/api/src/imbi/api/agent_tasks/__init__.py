"""Agent task state in Postgres (ADR 0020).

The ``agent_runtime`` schema holds task state. It is a plain Postgres
schema next to the graph, managed like the scheduler store: the
declarative ``schemata.toml`` is applied on every start.

The store lifespan also runs the archive sweep
(:mod:`imbi.api.agent_tasks.sweeper`), because the sweep needs the
store's connection pool.
"""

import asyncio
import contextlib
import pathlib
import typing
from collections import abc

import fastapi
import psycopg_pool

from imbi.api.agent_tasks import log, sweeper
from imbi.api.agent_tasks.store import (
    SCHEMA,
    Actor,
    CancelPending,
    NewTask,
    Pool,
    TaskClosed,
    TaskNotFound,
    TaskStore,
)
from imbi.common import lifespan, relational
from imbi.common import settings as common_settings

SCHEMATA_PATH = pathlib.Path(__file__).parent / 'schemata.toml'


async def initialize() -> None:
    """Create the ``agent_runtime`` schema, tables, and indexes."""
    await relational.initialize(
        SCHEMA,
        relational.load_schemata(SCHEMATA_PATH),
        f'imbi.api.initialize.{SCHEMA}',
    )


def create_pool() -> Pool:
    """Return an unopened connection pool for the task store."""
    postgres = common_settings.Postgres()
    return psycopg_pool.AsyncConnectionPool(
        conninfo=str(postgres.url),
        min_size=postgres.min_pool_size,
        max_size=postgres.max_pool_size,
        open=False,
    )


@contextlib.asynccontextmanager
async def store_lifespan() -> abc.AsyncGenerator[TaskStore]:
    """Initialize the schema, hold the task store open, and sweep."""
    await initialize()
    pool = create_pool()
    try:
        await pool.open()
        store = TaskStore(pool)
        stop = asyncio.Event()
        sweep = asyncio.create_task(sweeper.run_sweeper(store, stop=stop))
        try:
            yield store
        finally:
            stop.set()
            sweep.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweep
    finally:
        await pool.close()


async def _inject_store(
    context: lifespan.InjectLifespan,
) -> abc.AsyncIterator[TaskStore]:
    yield context.get_state(store_lifespan)


Store = typing.Annotated[TaskStore, fastapi.Depends(_inject_store)]

__all__ = [
    'SCHEMA',
    'Actor',
    'CancelPending',
    'NewTask',
    'Pool',
    'Store',
    'TaskClosed',
    'TaskNotFound',
    'TaskStore',
    'create_pool',
    'initialize',
    'log',
    'store_lifespan',
    'sweeper',
]
