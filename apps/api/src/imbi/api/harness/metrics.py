"""Prometheus gauges for the runner pools (harness plan section 6.1).

The gauges come from Postgres and the graph, so every imbi-api pod
reports the same values without a lock between them. Alert and scaling
rules aggregate with ``max()``. ``imbi_harness_pool_queued`` is the same
number as ``GET /harness/pools/{name}/queue``, which KEDA can poll.
"""

import asyncio
import logging
import typing

import prometheus_client

from imbi.common import graph

if typing.TYPE_CHECKING:
    from imbi.api.harness.store import HarnessStore

LOGGER = logging.getLogger(__name__)

#: How often the gauges are refreshed.
REFRESH_INTERVAL_SECONDS = 15

#: How long one refresh can take before it counts as a failure.
REFRESH_TIMEOUT_SECONDS = 10

UP = prometheus_client.Gauge(
    'imbi_harness_metrics_up',
    '1 when the last read of the harness gauges worked, else 0.',
)
QUEUED = prometheus_client.Gauge(
    'imbi_harness_pool_queued',
    'Tasks that a new runner of the pool could claim now.',
    ['pool'],
)
RUNNERS = prometheus_client.Gauge(
    'imbi_harness_runners',
    'Runners that are not offline, by pool and state.',
    ['pool', 'state'],
)
CHAINS = prometheus_client.Gauge(
    'imbi_harness_chains',
    'Chains that are not done, by state.',
    ['state'],
)


async def refresh(store: HarnessStore, db: graph.Graph) -> None:
    """Read the pools once and set the gauges.

    A failure logs a warning and sets `UP` to 0; the other gauges keep
    the values of the last good read.
    """
    # Imported here: endpoints.harness imports this package.
    from imbi.api.endpoints import harness as endpoints

    try:
        async with asyncio.timeout(REFRESH_TIMEOUT_SECONDS):
            agents, limits = await endpoints.eligible_agents(db)
            pools = await store.pools()
            queued = {
                pool['name']: await store.queue_depth(pool, agents, limits)
                for pool in pools
            }
            runners = await store.runner_counts()
            chains = await store.chain_counts()
    except Exception as err:  # noqa: BLE001
        LOGGER.warning('Harness gauge refresh failed: %s', err)
        UP.set(0)
        return
    # Clear first, so a deleted pool or an empty state does not keep
    # its last value.
    for gauge in (QUEUED, RUNNERS, CHAINS):
        gauge.clear()
    for name, count in queued.items():
        QUEUED.labels(name).set(count)
    for row in runners:
        RUNNERS.labels(row['pool'], row['state']).set(row['runners'])
    for row in chains:
        CHAINS.labels(row['state']).set(row['chains'])
    UP.set(1)


async def run_refresher(store: HarnessStore, *, stop: asyncio.Event) -> None:
    """Refresh the gauges every interval until ``stop`` is set."""
    db = graph.Graph()
    await db.open()
    try:
        while not stop.is_set():
            await refresh(store, db)
            try:
                await asyncio.wait_for(stop.wait(), REFRESH_INTERVAL_SECONDS)
            except TimeoutError:
                pass
    finally:
        await db.close()
