"""Prometheus gauges for the Iggy topics and their sink groups.

The gauges copy `iggy.topic_status()`, which is also what the admin
Iggy dashboard shows. A sink group with more members than owners has a
member that polls nothing (apache/iggy#4273).

The values are global, so every imbi-api pod reports the same values
without a lock between them. Alert rules aggregate with ``max()``.
"""

import asyncio
import logging

import prometheus_client

from imbi.common import iggy

LOGGER = logging.getLogger(__name__)

#: How often the gauges are refreshed.
REFRESH_INTERVAL_SECONDS = 30

#: How long one refresh can take before it counts as a failure. Without
#: a limit, a hung Iggy keeps `UP` at the value of the last refresh.
REFRESH_TIMEOUT_SECONDS = 10

_LABELS = ['stream', 'topic']

UP = prometheus_client.Gauge(
    'imbi_iggy_topic_status_up',
    '1 when the last read of the Iggy topic status worked, else 0.',
)
CURRENT_OFFSET = prometheus_client.Gauge(
    'imbi_iggy_topic_current_offset',
    'Highest offset in the topic.',
    _LABELS,
)
MESSAGES = prometheus_client.Gauge(
    'imbi_iggy_topic_messages',
    'Messages the topic holds.',
    _LABELS,
)
MEMBERS = prometheus_client.Gauge(
    'imbi_iggy_consumer_group_members',
    'Members of the sink consumer group of the topic.',
    _LABELS,
)
MEMBERS_OWNING = prometheus_client.Gauge(
    'imbi_iggy_consumer_group_members_owning',
    'Members of the sink consumer group that own a partition.',
    _LABELS,
)


async def refresh() -> None:
    """Read the topic status once and set the gauges from it.

    A failure logs a warning and sets `UP` to 0. It does not raise, and
    the other gauges keep the values of the last good read.
    """
    try:
        statuses = await asyncio.wait_for(
            iggy.topic_status(), REFRESH_TIMEOUT_SECONDS
        )
    except Exception as err:  # noqa: BLE001
        LOGGER.warning('Iggy topic status refresh failed: %s', err)
        UP.set(0)
        return
    for status in statuses:
        labels = (status.stream, status.topic)
        CURRENT_OFFSET.labels(*labels).set(status.current_offset)
        MESSAGES.labels(*labels).set(status.messages)
        MEMBERS.labels(*labels).set(status.members)
        MEMBERS_OWNING.labels(*labels).set(status.members_owning)
    UP.set(1)


async def run_refresher(*, stop: asyncio.Event) -> None:
    """Refresh the gauges every interval until ``stop`` is set."""
    while not stop.is_set():
        await refresh()
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=REFRESH_INTERVAL_SECONDS
            )
        except TimeoutError:
            pass
