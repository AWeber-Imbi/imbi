"""Workflow definitions in Postgres (ADR 0021).

The ``workflows`` schema holds definitions. It is a plain Postgres
schema next to the graph, managed like ``agent_runtime``: the
declarative ``schemata.toml`` is applied on every start.
"""

import contextlib
import pathlib
import typing
from collections import abc

import fastapi

from imbi.api.agent_tasks import create_pool
from imbi.api.workflows.store import (
    SCHEMA,
    Definition,
    Pool,
    Row,
    WorkflowStore,
)
from imbi.common import lifespan, relational

SCHEMATA_PATH = pathlib.Path(__file__).parent / 'schemata.toml'


async def initialize() -> None:
    """Create the ``workflows`` schema, tables, and indexes."""
    await relational.initialize(
        SCHEMA,
        relational.load_schemata(SCHEMATA_PATH),
        f'imbi.api.initialize.{SCHEMA}',
    )


@contextlib.asynccontextmanager
async def store_lifespan() -> abc.AsyncGenerator[WorkflowStore]:
    """Initialize the schema and hold the workflow store open."""
    await initialize()
    pool = create_pool()
    try:
        await pool.open()
        yield WorkflowStore(pool)
    finally:
        await pool.close()


async def _inject_store(
    context: lifespan.InjectLifespan,
) -> abc.AsyncIterator[WorkflowStore]:
    yield context.get_state(store_lifespan)


Store = typing.Annotated[WorkflowStore, fastapi.Depends(_inject_store)]

__all__ = [
    'SCHEMA',
    'Definition',
    'Pool',
    'Row',
    'Store',
    'WorkflowStore',
    'create_pool',
    'initialize',
    'store_lifespan',
]
