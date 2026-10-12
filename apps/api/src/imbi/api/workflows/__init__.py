"""Workflow definitions and runs in Postgres (ADR 0021).

The ``workflows`` schema holds definitions and the ``workflow_runtime``
schema holds runs. They are plain Postgres schemas next to the graph,
managed like ``agent_runtime``: the declarative schemata are applied on
every start. imbi-api owns both; imbi-workflows executes the runs.

The store lifespan also runs the archive sweep of the run log
(:mod:`imbi.api.workflows.sweeper`), because it needs the pool.
"""

import asyncio
import contextlib
import pathlib
import typing
from collections import abc

import fastapi

from imbi.api.agent_tasks import create_pool
from imbi.api.workflows import runs, sweeper
from imbi.api.workflows.runs import NewRun, RunStore
from imbi.api.workflows.store import (
    SCHEMA,
    Definition,
    Pool,
    Row,
    WorkflowStore,
)
from imbi.common import lifespan, relational
from imbi.common.workflows import runtime

SCHEMATA_PATH = pathlib.Path(__file__).parent / 'schemata.toml'
RUNTIME_SCHEMATA_PATH = pathlib.Path(__file__).parent / 'runtime_schemata.toml'

_runs: RunStore | None = None


async def initialize() -> None:
    """Create the ``workflows`` and ``workflow_runtime`` schemas."""
    for schema, path in (
        (SCHEMA, SCHEMATA_PATH),
        (runtime.SCHEMA, RUNTIME_SCHEMATA_PATH),
    ):
        await relational.initialize(
            schema,
            relational.load_schemata(path),
            f'imbi.api.initialize.{schema}',
        )


@contextlib.asynccontextmanager
async def store_lifespan() -> abc.AsyncGenerator[WorkflowStore]:
    """Initialize the schemas, hold the workflow stores open, and sweep."""
    global _runs
    await initialize()
    pool = create_pool()
    try:
        await pool.open()
        _runs = RunStore(pool)
        stop = asyncio.Event()
        sweep = asyncio.create_task(sweeper.run_sweeper(_runs, stop=stop))
        try:
            yield WorkflowStore(pool)
        finally:
            stop.set()
            sweep.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweep
    finally:
        _runs = None
        await pool.close()


def run_store() -> RunStore:
    """Return the run store that :func:`store_lifespan` opened.

    A function, not lifespan state, so the deploy endpoint reaches it
    only when a caller sends an idempotency key.
    """
    if _runs is None:
        raise RuntimeError('store_lifespan has not opened the run store')
    return _runs


async def _inject_store(
    context: lifespan.InjectLifespan,
) -> abc.AsyncIterator[WorkflowStore]:
    yield context.get_state(store_lifespan)


Store = typing.Annotated[WorkflowStore, fastapi.Depends(_inject_store)]
Runs = typing.Annotated[RunStore, fastapi.Depends(run_store)]

__all__ = [
    'SCHEMA',
    'Definition',
    'NewRun',
    'Pool',
    'Row',
    'RunStore',
    'Runs',
    'Store',
    'WorkflowStore',
    'create_pool',
    'initialize',
    'run_store',
    'runs',
    'store_lifespan',
    'sweeper',
]
