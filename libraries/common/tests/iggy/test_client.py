import unittest
from unittest import mock

import orjson
import pydantic

from imbi.common import iggy as common_iggy
from imbi.common.iggy import client


class SampleModel(pydantic.BaseModel):
    """Sample model for publish operations."""

    id: int
    name: str


class SampleModelDifferent(pydantic.BaseModel):
    """Different sample model for type validation."""

    value: str


class TranslateErrorsTestCase(unittest.TestCase):
    def test_runtime_error_becomes_publish_error(self) -> None:
        with self.assertRaises(client.PublishError) as ctx:
            with client._translate_errors('publish to events/gateway'):
                raise RuntimeError('Cannot establish connection')
        self.assertIn('publish to events/gateway', str(ctx.exception))
        self.assertIn('Cannot establish connection', str(ctx.exception))

    def test_other_errors_are_not_translated(self) -> None:
        with self.assertRaises(ValueError):
            with client._translate_errors('publish'):
                raise ValueError('unrelated')

    def test_error_is_reported_to_sentry(self) -> None:
        sentry = mock.Mock()
        with mock.patch.object(client, 'sentry_sdk', sentry):
            with self.assertRaises(client.PublishError):
                with client._translate_errors('publish'):
                    raise RuntimeError('boom')
        sentry.capture_exception.assert_called_once()


class PayloadTestCase(unittest.TestCase):
    def test_payload_matches_the_clickhouse_dump(self) -> None:
        model = SampleModel(id=1, name='one')
        self.assertEqual(
            {'id': 1, 'name': 'one'}, client._payload(model, None)
        )

    def test_columns_restrict_and_order_the_payload(self) -> None:
        model = SampleModel(id=1, name='one')
        self.assertEqual(
            ['name'], list(client._payload(model, ['name']).keys())
        )


class IggyClientTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()

        client.Iggy._instance = None

        self.mock_client = mock.AsyncMock()
        # `get_stream`/`get_topic` return details or None; default to
        # "already provisioned" so a test opts in to the create path.
        self.mock_client.get_stream.return_value = mock.Mock()
        self.mock_client.get_topic.return_value = mock.Mock()

        # The SDK class is a compiled PyO3 type, so the whole name is
        # replaced rather than one of its attributes.
        self.mock_client_class = self.enterContext(
            mock.patch.object(client, 'IggyClient')
        )
        self.mock_from_connection_string = (
            self.mock_client_class.from_connection_string
        )
        self.mock_from_connection_string.return_value = self.mock_client

    async def test_singleton(self) -> None:
        self.assertIs(client.Iggy.get_instance(), client.Iggy.get_instance())

    async def test_initialize(self) -> None:
        iggy = client.Iggy.get_instance()
        self.assertTrue(await iggy.initialize())
        self.mock_from_connection_string.assert_called_once_with(
            str(iggy._settings.url)
        )
        self.mock_client.connect.assert_awaited_once()

    async def test_initialize_provisions_every_topic(self) -> None:
        # The ClickHouse sink exits at startup on a missing topic, so
        # every pair has to exist before the sink is started, not on
        # whatever publishes first.
        iggy = client.Iggy.get_instance()
        self.mock_client.get_stream.return_value = None
        self.mock_client.get_topic.return_value = None
        with mock.patch.dict(
            common_iggy.TOPICS, {'operations_log': ('deployments',)}
        ):
            self.assertTrue(await iggy.initialize())
            expected = {
                (stream, topic)
                for stream, topics in common_iggy.TOPICS.items()
                for topic in topics
            }
        self.assertEqual(expected, iggy._provisioned)
        self.assertEqual(
            [mock.call('events'), mock.call('operations_log')],
            self.mock_client.create_stream.await_args_list,
        )

    async def test_initialize_tolerates_provisioned_topics(self) -> None:
        iggy = client.Iggy.get_instance()
        self.mock_client.get_stream.return_value = None
        self.mock_client.get_topic.return_value = None
        self.mock_client.create_stream.side_effect = RuntimeError(
            'Stream with name: events already exists.'
        )
        self.mock_client.create_topic.side_effect = RuntimeError(
            'Topic with name: gateway for stream with ID: 1 already exists.'
        )
        self.assertTrue(await iggy.initialize())
        self.assertIn(('events', 'gateway'), iggy._provisioned)

    async def test_initialize_is_idempotent(self) -> None:
        iggy = client.Iggy.get_instance()
        self.assertTrue(await iggy.initialize())
        self.assertTrue(await iggy.initialize())
        self.mock_from_connection_string.assert_called_once()

    async def test_connect_retries_then_succeeds(self) -> None:
        iggy = client.Iggy.get_instance()
        self.mock_client.connect.side_effect = [
            RuntimeError('Cannot establish connection'),
            RuntimeError('Cannot establish connection'),
            None,
        ]
        result = await iggy._connect(delay=0.01)
        self.assertIs(result, self.mock_client)
        self.assertEqual(3, self.mock_client.connect.await_count)

    async def test_connect_gives_up_after_max_attempts(self) -> None:
        iggy = client.Iggy.get_instance()
        iggy._settings.max_connect_attempts = 3
        self.mock_client.connect.side_effect = RuntimeError('refused')
        self.assertIsNone(await iggy._connect(delay=0.01))
        self.assertEqual(3, self.mock_client.connect.await_count)

    async def test_initialize_returns_false_when_connect_fails(self) -> None:
        iggy = client.Iggy.get_instance()
        iggy._settings.max_connect_attempts = 1
        self.mock_client.connect.side_effect = RuntimeError('refused')
        self.assertFalse(await iggy.initialize())

    async def test_aclose_drops_the_client_and_the_cache(self) -> None:
        iggy = client.Iggy.get_instance()
        await iggy.initialize()
        await iggy.ensure_topic('events', 'gateway')
        await iggy.aclose()
        self.assertIsNone(iggy._iggy)
        self.assertEqual(set(), iggy._provisioned)

    async def test_aclose_without_initialize(self) -> None:
        await client.Iggy.get_instance().aclose()

    async def test_ensure_topic_creates_what_is_missing(self) -> None:
        iggy = client.Iggy.get_instance()
        self.mock_client.get_stream.return_value = None
        self.mock_client.get_topic.return_value = None
        await iggy.ensure_topic('events', 'gateway')
        self.mock_client.create_stream.assert_awaited_once_with('events')
        self.mock_client.create_topic.assert_awaited_once_with(
            'events', 'gateway', partitions_count=client.PARTITIONS_COUNT
        )

    async def test_ensure_topic_skips_what_exists(self) -> None:
        iggy = client.Iggy.get_instance()
        await iggy.ensure_topic('events', 'gateway')
        self.mock_client.create_stream.assert_not_awaited()
        self.mock_client.create_topic.assert_not_awaited()

    async def test_ensure_topic_is_cached(self) -> None:
        iggy = client.Iggy.get_instance()
        await iggy.ensure_topic('events', 'gateway')
        await iggy.ensure_topic('events', 'gateway')
        self.mock_client.get_stream.assert_awaited_once()

    async def test_ensure_topic_tolerates_a_lost_create_race(self) -> None:
        iggy = client.Iggy.get_instance()
        self.mock_client.get_stream.return_value = None
        self.mock_client.get_topic.return_value = None
        self.mock_client.create_stream.side_effect = RuntimeError(
            'Stream with name: events already exists.'
        )
        self.mock_client.create_topic.side_effect = RuntimeError(
            'Topic with name: gateway for stream with ID: 1 already exists.'
        )
        await iggy.ensure_topic('events', 'gateway')
        self.assertIn(('events', 'gateway'), iggy._provisioned)

    async def test_ensure_topic_reraises_other_create_failures(self) -> None:
        iggy = client.Iggy.get_instance()
        self.mock_client.get_stream.return_value = None
        self.mock_client.create_stream.side_effect = RuntimeError(
            'Invalid stream name'
        )
        with self.assertRaises(client.PublishError):
            await iggy.ensure_topic('events', 'gateway')
        self.assertNotIn(('events', 'gateway'), iggy._provisioned)

    async def test_publish_sends_one_message_per_row(self) -> None:
        iggy = client.Iggy.get_instance()
        models = [SampleModel(id=1, name='one'), SampleModel(id=2, name='2')]
        await iggy.publish('events', 'gateway', models)

        self.mock_client.send_messages.assert_awaited_once()
        args = self.mock_client.send_messages.await_args.args
        self.assertEqual('events', args[0])
        self.assertEqual('gateway', args[1])
        self.assertEqual(client.PARTITION_ID, args[2])
        self.assertEqual(2, len(args[3]))

    async def test_publish_payload_is_the_clickhouse_dump(self) -> None:
        iggy = client.Iggy.get_instance()
        with mock.patch.object(client, 'SendMessage') as send_message:
            await iggy.publish(
                'events',
                'gateway',
                [SampleModel(id=1, name='one')],
                headers={'producer': 'gateway'},
            )
        send_message.assert_called_once_with(
            orjson.dumps({'id': 1, 'name': 'one'}),
            user_headers={'producer': 'gateway'},
        )

    async def test_publish_restricts_the_payload_to_columns(self) -> None:
        iggy = client.Iggy.get_instance()
        with mock.patch.object(client, 'SendMessage') as send_message:
            await iggy.publish(
                'events',
                'gateway',
                [SampleModel(id=1, name='one')],
                columns=['name'],
            )
        send_message.assert_called_once_with(
            orjson.dumps({'name': 'one'}), user_headers=None
        )

    async def test_publish_provisions_the_topic_first(self) -> None:
        iggy = client.Iggy.get_instance()
        await iggy.publish('events', 'gateway', [SampleModel(id=1, name='a')])
        self.assertIn(('events', 'gateway'), iggy._provisioned)

    async def test_publish_rejects_an_empty_list(self) -> None:
        iggy = client.Iggy.get_instance()
        with self.assertRaises(ValueError):
            await iggy.publish('events', 'gateway', [])

    async def test_publish_rejects_mixed_model_types(self) -> None:
        iggy = client.Iggy.get_instance()
        with self.assertRaises(ValueError):
            await iggy.publish(
                'events',
                'gateway',
                [SampleModel(id=1, name='a'), SampleModelDifferent(value='b')],
            )
        self.mock_client.send_messages.assert_not_awaited()

    async def test_publish_translates_sdk_errors(self) -> None:
        iggy = client.Iggy.get_instance()
        self.mock_client.send_messages.side_effect = RuntimeError(
            'Cannot send messages due to client disconnection'
        )
        with self.assertRaises(client.PublishError) as ctx:
            await iggy.publish(
                'events', 'gateway', [SampleModel(id=1, name='a')]
            )
        self.assertIn('publish to events/gateway', str(ctx.exception))

    async def test_publish_raises_when_the_client_cannot_connect(
        self,
    ) -> None:
        iggy = client.Iggy.get_instance()
        iggy._settings.max_connect_attempts = 1
        self.mock_client.connect.side_effect = RuntimeError('refused')
        with self.assertRaises(RuntimeError):
            await iggy.publish(
                'events', 'gateway', [SampleModel(id=1, name='a')]
            )
