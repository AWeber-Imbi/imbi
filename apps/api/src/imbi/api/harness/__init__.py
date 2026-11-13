"""Runner pools and dispatch in Postgres (ADR 0022).

The ``harness`` schema holds pools, runners, chain pins, claims, tool
call counters, the agent platform configuration of each organization,
and plugin marketplaces. It is a plain Postgres schema next to the graph,
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
from imbi.api.harness import metrics, sweeper, tokens
from imbi.api.harness.store import (
    GRACE_SECONDS,
    LEASE_SECONDS,
    SCHEMA,
    EgressDestinationExists,
    EgressPortLimit,
    HarnessStore,
    MarketplaceExists,
    PoolExists,
    PoolInUse,
    RunnerBusy,
)
from imbi.common import lifespan, relational

SCHEMATA_PATH = pathlib.Path(__file__).parent / 'schemata.toml'

#: The store that :func:`store_lifespan` opened, for code outside a
#: request (the maintenance worker).
_store: HarnessStore | None = None


async def initialize() -> None:
    """Create the ``harness`` schema, tables, and indexes."""
    await relational.initialize(
        SCHEMA,
        relational.load_schemata(SCHEMATA_PATH),
        f'imbi.api.initialize.{SCHEMA}',
    )


@contextlib.asynccontextmanager
async def store_lifespan() -> abc.AsyncGenerator[HarnessStore]:
    """Initialize the schema, hold the store open, sweep leases, and
    refresh the pool gauges."""
    global _store
    await initialize()
    pool = create_pool()
    try:
        await pool.open()
        store = HarnessStore(pool)
        stop = asyncio.Event()
        sweep = asyncio.create_task(sweeper.run_sweeper(store, stop=stop))
        gauges = asyncio.create_task(metrics.run_refresher(store, stop=stop))
        _store = store
        try:
            yield store
        finally:
            _store = None
            stop.set()
            for task in (sweep, gauges):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    finally:
        await pool.close()


def get_store() -> HarnessStore:
    """Return the store that :func:`store_lifespan` opened."""
    if _store is None:
        raise RuntimeError('store_lifespan has not opened the store')
    return _store


async def _inject_store(
    context: lifespan.InjectLifespan,
) -> abc.AsyncIterator[HarnessStore]:
    yield context.get_state(store_lifespan)


Store = typing.Annotated[HarnessStore, fastapi.Depends(_inject_store)]

__all__ = [
    'GRACE_SECONDS',
    'LEASE_SECONDS',
    'SCHEMA',
    'EgressDestinationExists',
    'EgressPortLimit',
    'HarnessStore',
    'MarketplaceExists',
    'PoolExists',
    'PoolInUse',
    'RunnerBusy',
    'Store',
    'initialize',
    'metrics',
    'store_lifespan',
    'sweeper',
    'tokens',
]
