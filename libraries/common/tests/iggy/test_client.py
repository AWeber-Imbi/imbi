import asyncio
import typing
import unittest
from unittest import mock

import orjson
import pydantic

from imbi.common import iggy as common_iggy
from imbi.common import settings
from imbi.common.iggy import client


def _topics(sizes: list[int]) -> list[mock.Mock]:
    """Stand-ins for `Topic`, carrying only the size the probe reads."""
    return [mock.Mock(size=size) for size in sizes]


def _pending_tasks() -> list[asyncio.Task[typing.Any]]:
    """Every task still running besides the test's own."""
    current = asyncio.current_task()
    return [
        task
        for task in asyncio.all_tasks()
        if task is not current and not task.done()
    ]


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

    def test_a_lost_connection_discards_the_owner_client(self) -> None:
        # Every fragment, because each one is a separate Iggy error and
        # a missed one strands the producer until its process restarts.
        for message in (
            'Disconnected',
            'Cannot establish connection',
            'Connection closed',
            'Stale client',
            'TCP error',
            'Background worker disconnected',
        ):
            with self.subTest(message=message):
                owner, failed = mock.Mock(), mock.Mock()
                with self.assertRaises(client.PublishError):
                    with client._translate_errors('publish', owner, failed):
                        raise RuntimeError(message)
                owner.discard.assert_called_once_with(failed)

    def test_a_refused_request_keeps_the_owner_client(self) -> None:
        owner = mock.Mock()
        with self.assertRaises(client.PublishError):
            with client._translate_errors('publish', owner):
                raise RuntimeError('Topic with name: gateway already exists.')
        owner.discard.assert_not_called()

    def test_no_owner_is_left_alone(self) -> None:
        with self.assertRaises(client.PublishError):
            with client._translate_errors('publish'):
                raise RuntimeError('Disconnected')


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

    async def test_initialize_decodes_userinfo(self) -> None:
        # pydantic serializes `=` in the password as `%3D`; the SDK does
        # not decode it, so the raw password has to be restored.
        iggy = client.Iggy.get_instance()
        iggy._settings = settings.Iggy(
            url='iggy+tcp://iggy:c2VjcmV0=@iggy:8090', _env_file=None
        )
        self.assertIn('%3D', str(iggy._settings.url))
        self.assertTrue(await iggy.initialize())
        self.mock_from_connection_string.assert_called_once_with(
            'iggy+tcp://iggy:c2VjcmV0=@iggy:8090'
        )

    async def test_initialize_rejects_reserved_userinfo_characters(
        self,
    ) -> None:
        # A decoded `@` would be split on by the SDK, so it has to be
        # refused before the connection string is built.
        iggy = client.Iggy.get_instance()
        iggy._settings = settings.Iggy(
            url='iggy+tcp://iggy:p%40ss@iggy:8090', _env_file=None
        )
        with self.assertRaises(ValueError):
            await iggy.initialize()
        self.mock_from_connection_string.assert_not_called()

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
            expected_streams = set(common_iggy.TOPICS)
        self.assertEqual(expected, iggy._provisioned)
        # The mocked `get_stream` never reports a stream as existing, so
        # a stream with several topics is created once per topic here.
        self.assertEqual(
            expected_streams,
            {
                call.args[0]
                for call in self.mock_client.create_stream.await_args_list
            },
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
        # `_require_client` initializes on first use, which provisions
        # every pair in TOPICS; pin it to the one under test.
        self.enterContext(
            mock.patch.dict(
                common_iggy.TOPICS, {'events': ('gateway',)}, clear=True
            )
        )
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
        # `_require_client` initializes on first use, which provisions
        # every pair in TOPICS; pin it to the one under test.
        self.enterContext(
            mock.patch.dict(
                common_iggy.TOPICS, {'events': ('gateway',)}, clear=True
            )
        )
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

    async def test_publish_rows_sends_each_row_as_is(self) -> None:
        iggy = client.Iggy.get_instance()
        with mock.patch.object(client, 'SendMessage') as send_message:
            await iggy.publish_rows(
                'operations_log',
                'api',
                [{'id': 'a', '_row_version': 2}, {'id': 'b'}],
                headers={'producer': 'api'},
            )
        self.assertEqual(
            [
                mock.call(
                    orjson.dumps({'id': 'a', '_row_version': 2}),
                    user_headers={'producer': 'api'},
                ),
                mock.call(
                    orjson.dumps({'id': 'b'}),
                    user_headers={'producer': 'api'},
                ),
            ],
            send_message.call_args_list,
        )
        self.mock_client.send_messages.assert_awaited_once()
        args = self.mock_client.send_messages.await_args.args
        self.assertEqual(
            ('operations_log', 'api', client.PARTITION_ID), args[:3]
        )
        self.assertIn(('operations_log', 'api'), iggy._provisioned)

    async def test_publish_rows_rejects_an_empty_list(self) -> None:
        iggy = client.Iggy.get_instance()
        with self.assertRaises(ValueError):
            await iggy.publish_rows('operations_log', 'api', [])
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

    async def test_publish_reconnects_after_the_server_restarts(self) -> None:
        # What an Iggy restart looks like to a long-lived producer: the
        # cached client raises, and every later publish has to build a
        # new one rather than reuse the dead connection.
        iggy = client.Iggy.get_instance()
        await iggy.initialize()
        self.mock_from_connection_string.reset_mock()
        self.mock_client.send_messages.side_effect = RuntimeError(
            'Disconnected'
        )
        with self.assertRaises(client.PublishError):
            await iggy.publish(
                'events', 'gateway', [SampleModel(id=1, name='a')]
            )
        self.assertIsNone(iggy._iggy)
        self.assertEqual(set(), iggy._provisioned)

        self.mock_client.send_messages.side_effect = None
        await iggy.publish('events', 'gateway', [SampleModel(id=1, name='a')])
        self.mock_from_connection_string.assert_called_once()

    async def test_a_late_error_does_not_discard_the_replacement(
        self,
    ) -> None:
        # Concurrent publishes all fail the same lost connection, so the
        # slowest of them reports a client that has already been
        # replaced. Only the first discard may take effect.
        iggy = client.Iggy.get_instance()
        await iggy.initialize()
        stale = self.mock_client
        replacement = mock.AsyncMock()
        iggy._iggy = replacement
        iggy._provisioned.add(('events', 'gateway'))

        iggy.discard(stale)

        self.assertIs(replacement, iggy._iggy)
        self.assertIn(('events', 'gateway'), iggy._provisioned)

    async def test_aclose_discards_whatever_is_cached(self) -> None:
        iggy = client.Iggy.get_instance()
        await iggy.initialize()
        await iggy.aclose()
        self.assertIsNone(iggy._iggy)
        self.assertEqual(set(), iggy._provisioned)

    async def test_provisioning_is_not_cached_for_a_discarded_client(
        self,
    ) -> None:
        # A concurrent failure discards the client while `ensure_topic`
        # is mid-flight. Caching the pair anyway would have the
        # replacement skip a topic the Iggy restart took with it.
        iggy = client.Iggy.get_instance()
        await iggy.initialize()
        iggy._provisioned.clear()

        async def discard_then_answer(
            stream: str, topic: str
        ) -> mock.Mock | None:
            iggy.discard(self.mock_client)
            return mock.Mock()

        self.mock_client.get_topic.side_effect = discard_then_answer
        await iggy.ensure_topic('events', 'gateway')
        self.assertNotIn(('events', 'gateway'), iggy._provisioned)

    async def test_publish_keeps_the_client_on_a_refused_request(
        self,
    ) -> None:
        iggy = client.Iggy.get_instance()
        await iggy.initialize()
        self.mock_client.send_messages.side_effect = RuntimeError(
            'Invalid message payload'
        )
        with self.assertRaises(client.PublishError):
            await iggy.publish(
                'events', 'gateway', [SampleModel(id=1, name='a')]
            )
        self.assertIs(self.mock_client, iggy._iggy)

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

    async def test_ping_round_trips_through_the_sdk(self) -> None:
        iggy = client.Iggy.get_instance()
        await iggy.ping()
        self.mock_client.ping.assert_awaited_once()

    async def test_ping_translates_sdk_errors(self) -> None:
        iggy = client.Iggy.get_instance()
        self.mock_client.ping.side_effect = RuntimeError('disconnected')
        with self.assertRaises(client.PublishError) as ctx:
            await iggy.ping()
        self.assertIn('ping', str(ctx.exception))

    async def test_stored_bytes_totals_every_stream(self) -> None:
        iggy = client.Iggy.get_instance()
        self.mock_client.get_topics.side_effect = lambda stream: _topics(
            {'events': [16, 32], 'tags': [8]}[stream]
        )
        with mock.patch.dict(
            common_iggy.TOPICS,
            {'events': ('gateway',), 'tags': ('github',)},
            clear=True,
        ):
            self.assertEqual(56, await iggy.stored_bytes())

    async def test_stored_bytes_cancels_the_siblings_of_a_failure(
        self,
    ) -> None:
        # `gather` abandons the calls still in flight when one raises.
        # Left alone they outlive the health probe that started them,
        # and the next probe stacks another set on top.
        iggy = client.Iggy.get_instance()
        hung = asyncio.Event()

        async def get_topics(stream: str) -> list[mock.Mock]:
            if stream == 'events':
                raise RuntimeError('stream not found')
            await hung.wait()
            raise AssertionError('the sibling read was not cancelled')

        self.mock_client.get_topics.side_effect = get_topics
        with mock.patch.dict(
            common_iggy.TOPICS,
            {'events': ('gateway',), 'tags': ('github',)},
            clear=True,
        ):
            with self.assertRaises(client.PublishError):
                await iggy.stored_bytes()
        self.assertEqual([], _pending_tasks())

    async def test_stored_bytes_cancels_the_siblings_of_a_timeout(
        self,
    ) -> None:
        # The dashboard probe wraps this in `wait_for`, and the reads
        # it started must not outlive it. `gather` propagates that
        # cancel on its own today, so this pins the behaviour down
        # rather than covering the fix above.
        iggy = client.Iggy.get_instance()
        hung = asyncio.Event()

        async def get_topics(stream: str) -> list[mock.Mock]:
            await hung.wait()
            raise AssertionError('the topic read was not cancelled')

        self.mock_client.get_topics.side_effect = get_topics
        with mock.patch.dict(
            common_iggy.TOPICS, {'events': ('gateway',)}, clear=True
        ):
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(iggy.stored_bytes(), 0.01)
        self.assertEqual([], _pending_tasks())
