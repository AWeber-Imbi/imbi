"""The secrets broker (ADR 0022, plan section 9).

imbi-api brokers secrets that external systems hold and stores no
secret values. The ``secrets`` schema holds providers, bindings,
grants, and resolutions. It is a plain Postgres schema, managed like
``agent_runtime``: the declarative schemata are applied on every start.

The store lifespan also runs the expiry sweep and publishes the audit
outbox, because both need the pool. It registers the broker's release
of a runner as a fencer of the harness lease sweep, and its release of
a task as a close hook of the task store.
"""

import asyncio
import contextlib
import logging
import pathlib
import typing
from collections import abc

import fastapi

from imbi.api.agent_tasks import create_pool
from imbi.api.agent_tasks import store as task_store
from imbi.api.harness import sweeper
from imbi.api.secret_broker import audit, broker, github_app, providers, store
from imbi.common import lifespan, relational

LOGGER = logging.getLogger(__name__)

SCHEMATA_PATH = pathlib.Path(__file__).parent / 'schemata.toml'

providers.PROVIDERS[github_app.GitHubApp.type] = github_app.GitHubApp()

#: How often the expiry sweep runs.
SWEEP_INTERVAL_SECONDS = 30

_broker: broker.Broker | None = None


async def initialize() -> None:
    """Create the ``secrets`` schema, tables, and indexes."""
    await relational.initialize(
        store.SCHEMA,
        relational.load_schemata(SCHEMATA_PATH),
        f'imbi.api.initialize.{store.SCHEMA}',
    )


async def run_sweeper(service: broker.Broker, *, stop: asyncio.Event) -> None:
    """Expire resolutions and publish the audit outbox every
    :data:`SWEEP_INTERVAL_SECONDS`."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=SWEEP_INTERVAL_SECONDS)
        except TimeoutError:
            pass
        else:
            return
        try:
            await service.sweep()
        except Exception:  # noqa: BLE001
            LOGGER.warning('Secret resolution sweep failed', exc_info=True)
        try:
            await service.flush_audit()
        except Exception:  # noqa: BLE001 - the rows stay for the next sweep
            LOGGER.warning('Secret audit publish failed', exc_info=True)


@contextlib.asynccontextmanager
async def store_lifespan() -> abc.AsyncGenerator[store.SecretStore]:
    """Initialize the schema, hold the store open, and sweep."""
    global _broker
    await initialize()
    pool = create_pool()
    try:
        await pool.open()
        _broker = broker.Broker(pool)
        fencer = _broker.release_runner_resolutions
        close_hook = _broker.release_task_resolutions
        sweeper.register_fencer(fencer)
        task_store.register_close_hook(close_hook)
        stop = asyncio.Event()
        sweep = asyncio.create_task(run_sweeper(_broker, stop=stop))
        try:
            yield store.SecretStore(pool)
        finally:
            sweeper.unregister_fencer(fencer)
            task_store.unregister_close_hook(close_hook)
            stop.set()
            sweep.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweep
    finally:
        _broker = None
        await pool.close()


def get_broker() -> broker.Broker:
    """Return the resolution service that :func:`store_lifespan` opened."""
    if _broker is None:
        raise RuntimeError('store_lifespan has not opened the broker')
    return _broker


async def _inject_store(
    context: lifespan.InjectLifespan,
) -> abc.AsyncIterator[store.SecretStore]:
    yield context.get_state(store_lifespan)


Store = typing.Annotated[store.SecretStore, fastapi.Depends(_inject_store)]
Broker = typing.Annotated[broker.Broker, fastapi.Depends(get_broker)]

__all__ = [
    'Broker',
    'Store',
    'audit',
    'broker',
    'get_broker',
    'github_app',
    'initialize',
    'providers',
    'run_sweeper',
    'store',
    'store_lifespan',
]
