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
from imbi.scheduler.store.tasks import (
    NOTIFY_CHANNEL,
    DuplicateSlug,
    Tasks,
    UnresolvableIdentity,
)

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


_pool: Pool | None = None


def pool() -> Pool:
    """Return the pool `store_lifespan` opened.

    A lifespan hook receives no arguments and cannot read another hook's
    state, so the engine hook — which needs the pool itself for ``LISTEN``,
    not just the repository — reads it from here. Same shape as the API's
    `_graph`. Hooks are entered in the order `Lifespan` was given them, so
    `store_lifespan` must precede any hook that calls this.
    """
    if _pool is None:
        raise RuntimeError('store_lifespan has not opened the pool')
    return _pool


@contextlib.asynccontextmanager
async def store_lifespan() -> abc.AsyncGenerator[Tasks]:
    """Initialize the schema and hold the task repository open."""
    global _pool  # noqa: PLW0603 -- see pool()
    await initialize()
    # Published only once it is actually open. Assigning first would leave
    # `pool()` handing out a pool that never opened — and never gets closed —
    # instead of raising, if Postgres is unreachable at boot.
    candidate = create_pool()
    try:
        await candidate.open()
    except BaseException:
        await candidate.close()
        raise
    _pool = candidate
    try:
        yield Tasks(_pool)
    finally:
        await _pool.close()
        _pool = None


async def _inject_tasks(
    context: lifespan.InjectLifespan,
) -> abc.AsyncIterator[Tasks]:
    yield context.get_state(store_lifespan)


TaskStore = typing.Annotated[Tasks, fastapi.Depends(_inject_tasks)]

__all__ = [
    'NOTIFY_CHANNEL',
    'DuplicateSlug',
    'Pool',
    'TaskStore',
    'Tasks',
    'UnresolvableIdentity',
    'create_pool',
    'initialize',
    'load_schemata',
    'pool',
    'store_lifespan',
]
