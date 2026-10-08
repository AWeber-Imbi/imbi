import asyncio
import unittest
from unittest import mock

import prometheus_client

from imbi.api import iggy_metrics, lifespans
from imbi.common import iggy


def _value(name: str, stream: str | None = None) -> float | None:
    labels = {} if stream is None else {'stream': stream, 'topic': 'gateway'}
    return prometheus_client.REGISTRY.get_sample_value(name, labels)


def _status(**overrides: int) -> iggy.TopicStatus:
    values = {
        'messages': 10,
        'current_offset': 9,
        'members': 2,
        'members_owning': 1,
    } | overrides
    return iggy.TopicStatus(
        stream='events',
        topic='gateway',
        size_bytes=100,
        consumer_group='events',
        **values,
    )


class RefreshTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_gauges_copy_the_topic_status(self) -> None:
        with mock.patch.object(iggy, 'topic_status', return_value=[_status()]):
            await iggy_metrics.refresh()
        self.assertEqual(1, _value('imbi_iggy_topic_status_up'))
        for name, expected in (
            ('imbi_iggy_topic_current_offset', 9),
            ('imbi_iggy_topic_messages', 10),
            ('imbi_iggy_consumer_group_members', 2),
            ('imbi_iggy_consumer_group_members_owning', 1),
        ):
            with self.subTest(name=name):
                self.assertEqual(expected, _value(name, 'events'))

    async def test_a_failure_sets_up_to_zero(self) -> None:
        with mock.patch.object(iggy, 'topic_status', return_value=[_status()]):
            await iggy_metrics.refresh()
        with (
            mock.patch.object(
                iggy, 'topic_status', side_effect=iggy.PublishError('down')
            ),
            self.assertLogs(iggy_metrics.LOGGER, 'WARNING'),
        ):
            await iggy_metrics.refresh()
        self.assertEqual(0, _value('imbi_iggy_topic_status_up'))

    async def test_a_hung_read_sets_up_to_zero(self) -> None:
        async def hang() -> list[iggy.TopicStatus]:
            await asyncio.Event().wait()
            return []

        with (
            mock.patch.object(iggy, 'topic_status', side_effect=hang),
            mock.patch.object(iggy_metrics, 'REFRESH_TIMEOUT_SECONDS', 0.01),
            self.assertLogs(iggy_metrics.LOGGER, 'WARNING'),
        ):
            await iggy_metrics.refresh()
        self.assertEqual(0, _value('imbi_iggy_topic_status_up'))

    async def test_the_refresher_stops_when_asked(self) -> None:
        stop = asyncio.Event()
        with mock.patch.object(iggy_metrics, 'refresh') as refresh:
            refresh.side_effect = stop.set
            await asyncio.wait_for(
                iggy_metrics.run_refresher(stop=stop), timeout=1
            )
        refresh.assert_awaited_once()

    async def test_the_hook_starts_and_stops_the_refresher(self) -> None:
        with mock.patch.object(iggy_metrics, 'refresh') as refresh:
            async with lifespans.iggy_metrics_hook():
                await asyncio.sleep(0)
        refresh.assert_awaited_once()
