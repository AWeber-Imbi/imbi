"""Ticket state in Postgres (ADR 0020, ADR 0028).

The ``tickets`` schema holds ticket state. It is a plain Postgres
schema next to the graph, managed like the scheduler store: the
declarative ``schemata.toml`` is applied on every start.

The store lifespan also runs the archive sweep
(:mod:`imbi.api.tickets.sweeper`), because the sweep needs the
store's connection pool.
"""

import asyncio
import contextlib
import pathlib
import typing
from collections import abc

import fastapi
import psycopg_pool

from imbi.api.tickets import log, sweeper
from imbi.api.tickets.store import (
    SCHEMA,
    Actor,
    CancelPending,
    ConcurrencyLimit,
    DigestMismatch,
    EventIdConflict,
    NewEvent,
    NewRequest,
    NewTask,
    Outcome,
    ParentCycle,
    Pool,
    RequestKeyConflict,
    RequestNotFound,
    RequestNotOpen,
    Resolution,
    ResolutionInvalid,
    SelfDependency,
    SessionClosed,
    SessionNotFound,
    TaskArchived,
    TaskClosed,
    TaskNotFound,
    TaskOpen,
    TicketHeld,
    TicketStarted,
    TicketStore,
    TransitionInvalid,
    Usage,
    WrongAssigneeKind,
)
from imbi.common import lifespan, relational
from imbi.common import settings as common_settings

SCHEMATA_PATH = pathlib.Path(__file__).parent / 'schemata.toml'

#: The advisory lock of the initializer. It keeps the key of the
#: ``agent_runtime`` schema, so that a pod of the previous release and
#: this one never initialize at the same time (ADR 0028).
LOCK_KEY = 'imbi.api.initialize.agent_runtime'


async def initialize() -> None:
    """Create the ``tickets`` schema, tables, and indexes, and move the
    ``agent_runtime`` tables of an earlier install there."""
    await relational.initialize(
        SCHEMA, relational.load_schemata(SCHEMATA_PATH), LOCK_KEY
    )
    await relational.initialize_deleted_organizations()


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
async def store_lifespan() -> abc.AsyncGenerator[TicketStore]:
    """Initialize the schema, hold the task store open, and sweep."""
    await initialize()
    pool = create_pool()
    try:
        await pool.open()
        store = TicketStore(pool)
        await store.move_legacy_projects()
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
) -> abc.AsyncIterator[TicketStore]:
    yield context.get_state(store_lifespan)


Store = typing.Annotated[TicketStore, fastapi.Depends(_inject_store)]

__all__ = [
    'SCHEMA',
    'Actor',
    'CancelPending',
    'ConcurrencyLimit',
    'DigestMismatch',
    'EventIdConflict',
    'NewEvent',
    'NewRequest',
    'NewTask',
    'Outcome',
    'ParentCycle',
    'Pool',
    'RequestKeyConflict',
    'RequestNotFound',
    'RequestNotOpen',
    'Resolution',
    'ResolutionInvalid',
    'SelfDependency',
    'SessionClosed',
    'SessionNotFound',
    'Store',
    'TaskArchived',
    'TaskClosed',
    'TaskNotFound',
    'TaskOpen',
    'TicketHeld',
    'TicketStarted',
    'TicketStore',
    'TransitionInvalid',
    'Usage',
    'WrongAssigneeKind',
    'create_pool',
    'initialize',
    'log',
    'store_lifespan',
    'sweeper',
]
