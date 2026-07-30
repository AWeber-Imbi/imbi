"""Lifespan hooks for imbi-scheduler."""

import asyncio
import contextlib
import logging
import typing

import fastapi
import httpx

from imbi.common import clickhouse, lifespan
from imbi.scheduler import engine as engine_module
from imbi.scheduler import executor as executor_module
from imbi.scheduler import identity, settings, store

if typing.TYPE_CHECKING:
    from collections import abc

LOGGER = logging.getLogger(__name__)

#: How long shutdown waits for `run_forever` to drain the ticks it has in
#: flight before cancelling it. Kept under Kubernetes' 30s default
#: `terminationGracePeriodSeconds`, since SIGKILL would end the drain anyway.
SHUTDOWN_DRAIN_TIMEOUT = 25.0


@contextlib.asynccontextmanager
async def clickhouse_hook() -> 'abc.AsyncGenerator[None]':
    """Initialize and manage the ClickHouse connection."""
    result = await clickhouse.initialize()
    if result is False:
        raise RuntimeError('ClickHouse initialization failed')
    async with contextlib.aclosing(clickhouse):
        yield


@contextlib.asynccontextmanager
async def engine_hook() -> 'abc.AsyncGenerator[engine_module.Engine]':
    """Run the trigger loop for the lifetime of the process.

    This is the only thing that makes the service a scheduler rather than a
    ``/status`` endpoint: nothing else constructs the engine, so a firing
    happens because this hook is registered. It must be registered after
    :func:`imbi.scheduler.store.store_lifespan`, whose pool it borrows.
    """
    config = settings.Scheduler()
    pool = store.pool()
    stop = asyncio.Event()
    async with httpx.AsyncClient() as client:
        resolver = identity.Resolver(client, config)
        engine = engine_module.Engine(
            store.Tasks(pool),
            executor_module.Executor(client, resolver, config),
            config,
        )
        async with engine.listening(pool):
            loop = asyncio.create_task(engine.run_forever(stop))
            try:
                yield engine
            finally:
                stop.set()
                engine.notify()
                # `stop.set()` and `notify()` only schedule the loop's waiters
                # to resume, so cancelling straight afterwards would always
                # tear `run_forever` out of its sleep before it could observe
                # `stop` and await the ticks still in flight. Give it that
                # chance first; cancellation is the fallback for a loop that
                # is genuinely stuck.
                await asyncio.wait({loop}, timeout=SHUTDOWN_DRAIN_TIMEOUT)
                if not loop.done():
                    LOGGER.warning(
                        'Trigger loop did not drain in %ss; cancelling',
                        SHUTDOWN_DRAIN_TIMEOUT,
                    )
                    loop.cancel()
                try:
                    await loop
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001
                    LOGGER.warning(
                        'Trigger loop exited with error', exc_info=True
                    )


def _inject_engine(
    context: lifespan.InjectLifespan,
) -> engine_module.Engine:
    return context.get_state(engine_hook)


#: The running engine, for the routes that fire or cancel a run. Declared here
#: rather than in the endpoints package so the dependency lives beside the hook
#: that opens it, matching :data:`imbi.scheduler.store.TaskStore`.
EngineDependency = typing.Annotated[
    engine_module.Engine, fastapi.Depends(_inject_engine)
]
