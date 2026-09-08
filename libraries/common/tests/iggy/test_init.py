import unittest
from unittest import mock

import pydantic

from imbi.common import iggy
from imbi.common.iggy import client


class SampleModel(pydantic.BaseModel):
    id: int


class TopicsTestCase(unittest.TestCase):
    def test_events_stream_carries_the_gateway_topic(self) -> None:
        # The sink configuration imbi-api serves to the connectors
        # runtime is generated from this, so a stream or topic dropped
        # here is one the ClickHouse sink stops draining.
        self.assertEqual({'events': ('gateway',)}, iggy.TOPICS)

    def test_publish_error_is_exported(self) -> None:
        self.assertIs(client.PublishError, iggy.PublishError)


class ModuleFunctionsTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        client.Iggy._instance = None
        self.instance = mock.AsyncMock(spec=client.Iggy)
        self.enterContext(
            mock.patch.object(
                client.Iggy, 'get_instance', return_value=self.instance
            )
        )

    async def test_initialize(self) -> None:
        self.instance.initialize.return_value = True
        self.assertTrue(await iggy.initialize())
        self.instance.initialize.assert_awaited_once_with()

    async def test_aclose(self) -> None:
        await iggy.aclose()
        self.instance.aclose.assert_awaited_once_with()

    async def test_ensure_topic(self) -> None:
        await iggy.ensure_topic('events', 'gateway')
        self.instance.ensure_topic.assert_awaited_once_with(
            'events', 'gateway'
        )

    async def test_publish(self) -> None:
        models = [SampleModel(id=1)]
        await iggy.publish(
            'events',
            'gateway',
            models,
            columns=['id'],
            headers={'producer': 'gateway'},
        )
        self.instance.publish.assert_awaited_once_with(
            'events',
            'gateway',
            models,
            columns=['id'],
            headers={'producer': 'gateway'},
        )
