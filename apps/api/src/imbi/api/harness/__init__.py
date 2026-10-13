"""Runner pools and dispatch in Postgres (ADR 0022).

The ``harness`` schema holds pools, runners, chain pins, claims, and
tool call counters. It is a plain Postgres schema next to the graph,
managed like ``agent_runtime``: the declarative ``schemata.toml`` is
applied on every start. Its tables refer to ``agent_runtime.tasks``, so
it initializes after that schema.

The store lifespan also runs the lease sweep
(:mod:`imbi.api.harness.sweeper`).
"""

import asyncio
import contextlib
import pathlib
import typing
from collections import abc

import fastapi

from imbi.api.agent_tasks import create_pool
from imbi.api.harness import sweeper, tokens
from imbi.api.harness.store import (
    GRACE_SECONDS,
    LEASE_SECONDS,
    SCHEMA,
    HarnessStore,
    PoolExists,
    PoolInUse,
    RunnerBusy,
)
from imbi.common import lifespan, relational

SCHEMATA_PATH = pathlib.Path(__file__).parent / 'schemata.toml'


async def initialize() -> None:
    """Create the ``harness`` schema, tables, and indexes."""
    await relational.initialize(
        SCHEMA,
        relational.load_schemata(SCHEMATA_PATH),
        f'imbi.api.initialize.{SCHEMA}',
    )


@contextlib.asynccontextmanager
async def store_lifespan() -> abc.AsyncGenerator[HarnessStore]:
    """Initialize the schema, hold the store open, and sweep leases."""
    await initialize()
    pool = create_pool()
    try:
        await pool.open()
        store = HarnessStore(pool)
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
) -> abc.AsyncIterator[HarnessStore]:
    yield context.get_state(store_lifespan)


Store = typing.Annotated[HarnessStore, fastapi.Depends(_inject_store)]

__all__ = [
    'GRACE_SECONDS',
    'LEASE_SECONDS',
    'SCHEMA',
    'HarnessStore',
    'PoolExists',
    'PoolInUse',
    'RunnerBusy',
    'Store',
    'initialize',
    'store_lifespan',
    'sweeper',
    'tokens',
]
