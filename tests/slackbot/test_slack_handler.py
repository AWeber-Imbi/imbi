from unittest import mock

from imbi_slackbot import identity, settings, slack_handler
from tests import helpers


class FakeSlackClient:
    def __init__(self, replies=None, replies_error=False) -> None:
        self._replies = replies
        self._error = replies_error
        self.posts: list = []

    async def conversations_replies(self, channel, ts, limit):
        if self._error:
            raise RuntimeError('nope')
        return {'messages': self._replies or []}

    async def chat_postMessage(self, channel, text, thread_ts):
        self.posts.append(
            {'channel': channel, 'text': text, 'thread_ts': thread_ts}
        )


class FakeManager:
    def get_tools(self) -> list:
        return [{'name': 'list'}]

    def get_tool_names(self) -> list:
        return ['list']


class StripMentionTests(helpers.TestCase):
    def test_strip(self) -> None:
        self.assertEqual(
            'hello there',
            slack_handler._strip_mentions('<@U123> hello there'),
        )

    def test_strip_labeled(self) -> None:
        self.assertEqual(
            'hello there',
            slack_handler._strip_mentions('<@U123|alice> hello there'),
        )


class ReconstructTests(helpers.TestCase):
    def test_roles_and_mention_strip(self) -> None:
        replies = [
            {'user': 'U1', 'text': '<@BOT> hi'},
            {'user': 'BOT', 'text': 'hello'},
            {'user': 'U1', 'text': 'thanks'},
        ]
        msgs = slack_handler._reconstruct_messages(replies, 'BOT', 30)
        self.assertEqual(3, len(msgs))
        self.assertEqual('user', msgs[0]['role'])
        self.assertEqual('hi', msgs[0]['content'])
        self.assertEqual('assistant', msgs[1]['role'])

    def test_coalesce_consecutive(self) -> None:
        replies = [
            {'user': 'U1', 'text': 'one'},
            {'user': 'U1', 'text': 'two'},
        ]
        msgs = slack_handler._reconstruct_messages(replies, 'BOT', 30)
        self.assertEqual(1, len(msgs))
        self.assertEqual('one\n\ntwo', msgs[0]['content'])

    def test_drops_leading_assistant(self) -> None:
        replies = [
            {'user': 'BOT', 'text': 'earlier'},
            {'user': 'U1', 'text': 'hi'},
        ]
        msgs = slack_handler._reconstruct_messages(replies, 'BOT', 30)
        self.assertEqual(1, len(msgs))
        self.assertEqual('user', msgs[0]['role'])

    def test_skips_subtype_and_no_user_and_empty(self) -> None:
        replies = [
            {'subtype': 'channel_join', 'user': 'U1', 'text': 'joined'},
            {'text': 'no user'},
            {'user': 'U1', 'text': '   '},
            {'user': 'U1', 'text': 'real'},
        ]
        msgs = slack_handler._reconstruct_messages(replies, 'BOT', 30)
        self.assertEqual(1, len(msgs))
        self.assertEqual('real', msgs[0]['content'])

    def test_cap(self) -> None:
        replies = [{'user': 'U1', 'text': f'm{i}'} for i in range(10)]
        msgs = slack_handler._reconstruct_messages(replies, 'BOT', 3)
        # Last 3 coalesce into a single user turn.
        self.assertEqual(1, len(msgs))
        self.assertIn('m9', msgs[0]['content'])
        self.assertNotIn('m0', msgs[0]['content'])


class LoadThreadTests(helpers.TestCase):
    async def test_fallback_on_error(self) -> None:
        fallback = {'user': 'U1', 'text': 'hi'}
        client = FakeSlackClient(replies_error=True)
        result = await slack_handler._load_thread(client, 'C', '1', fallback)
        self.assertEqual([fallback], result)


class FakeApp:
    def __init__(self, token: str) -> None:
        self.token = token
        self.handlers: dict = {}
        self.client = mock.AsyncMock()
        self.client.auth_test = mock.AsyncMock(return_value={'user_id': 'BOT'})

    def event(self, name: str):
        def deco(fn):
            self.handlers[name] = fn
            return fn

        return deco


class FakeHandler:
    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token
        self.connected = False
        self.closed = False

    async def connect_async(self) -> None:
        self.connected = True

    async def close_async(self) -> None:
        self.closed = True


class InitializeTests(helpers.TestCase):
    def setUp(self) -> None:
        super().setUp()
        settings._slackbot_settings = None
        slack_handler._app = None
        slack_handler._handler = None
        slack_handler._bot_user_id = None

    async def asyncTearDown(self) -> None:
        await slack_handler.aclose()
        settings._slackbot_settings = None
        await super().asyncTearDown()

    async def test_disabled_does_not_connect(self) -> None:
        with self.override_environment(
            ANTHROPIC_API_KEY=None,
            SLACK_BOT_TOKEN=None,
            SLACK_APP_TOKEN=None,
            IMBI_SLACKBOT_ENABLED=None,
        ):
            await slack_handler.initialize()
        self.assertIsNone(slack_handler._handler)

    async def test_enabled_without_tokens(self) -> None:
        with self.override_environment(
            ANTHROPIC_API_KEY=None,
            SLACK_BOT_TOKEN=None,
            SLACK_APP_TOKEN=None,
            IMBI_SLACKBOT_ENABLED='true',
        ):
            await slack_handler.initialize()
        self.assertIsNone(slack_handler._handler)

    async def test_connects_and_dispatches(self) -> None:
        with (
            self.override_environment(
                ANTHROPIC_API_KEY='sk-test',
                SLACK_BOT_TOKEN='xoxb',
                SLACK_APP_TOKEN='xapp',
                IMBI_SLACKBOT_ENABLED=None,
            ),
            mock.patch.object(slack_handler, 'AsyncApp', FakeApp),
            mock.patch.object(
                slack_handler, 'AsyncSocketModeHandler', FakeHandler
            ),
        ):
            await slack_handler.initialize()
            self.assertEqual('BOT', slack_handler._bot_user_id)
            self.assertTrue(slack_handler._handler.connected)

            app = slack_handler._app
            client = mock.AsyncMock()
            with mock.patch.object(
                slack_handler, 'handle_event', new=mock.AsyncMock()
            ) as handle:
                await app.handlers['app_mention']({'user': 'U1'}, client)
                self.assertEqual(1, handle.await_count)

                await app.handlers['message'](
                    {'channel_type': 'channel'}, client
                )
                await app.handlers['message'](
                    {'channel_type': 'im', 'bot_id': 'B1'}, client
                )
                await app.handlers['message'](
                    {'channel_type': 'im', 'user': 'U1'}, client
                )
                # Only the clean DM dispatched (plus the mention).
                self.assertEqual(2, handle.await_count)

            handler = slack_handler._handler
            await slack_handler.aclose()
            self.assertTrue(handler.closed)
            self.assertIsNone(slack_handler._handler)


class HandleEventTests(helpers.TestCase):
    def setUp(self) -> None:
        super().setUp()
        settings._slackbot_settings = None
        system_prompt_patch = mock.patch.object(
            slack_handler.system_prompt,
            'build_system_prompt',
            return_value='sys',
        )
        manager_patch = mock.patch.object(
            slack_handler.mcp, 'get_manager', return_value=FakeManager()
        )
        mint_patch = mock.patch.object(
            slack_handler.identity, 'mint_token', return_value='tok'
        )
        self._patches = [system_prompt_patch, manager_patch, mint_patch]
        for patch in self._patches:
            patch.start()

    def tearDown(self) -> None:
        for patch in self._patches:
            patch.stop()
        settings._slackbot_settings = None
        super().tearDown()

    async def test_happy_path(self) -> None:
        user = identity.ImbiUser('ada@example.com', 'Ada')
        event = {'channel': 'C', 'ts': '1', 'user': 'U1', 'text': '<@BOT> hi'}
        client = FakeSlackClient(replies=[])
        with (
            mock.patch.object(
                slack_handler.identity,
                'resolve',
                new=mock.AsyncMock(return_value=user),
            ),
            mock.patch.object(
                slack_handler.agent,
                'run_turn',
                new=mock.AsyncMock(return_value='the answer'),
            ),
        ):
            await slack_handler.handle_event(event, client, bot_user_id='BOT')
        self.assertEqual('the answer', client.posts[-1]['text'])
        self.assertEqual('1', client.posts[-1]['thread_ts'])

    async def test_unknown_user(self) -> None:
        event = {'channel': 'C', 'ts': '1', 'user': 'U1', 'text': 'hi'}
        client = FakeSlackClient(replies=[])
        with mock.patch.object(
            slack_handler.identity,
            'resolve',
            new=mock.AsyncMock(return_value=None),
        ):
            await slack_handler.handle_event(event, client, bot_user_id='BOT')
        self.assertIn('match your Slack account', client.posts[-1]['text'])

    async def test_empty_messages(self) -> None:
        user = identity.ImbiUser('ada@example.com', 'Ada')
        event = {'channel': 'C', 'ts': '1', 'user': 'U1', 'text': '<@BOT>'}
        # Thread holds only a prior bot message -> drops to empty history.
        client = FakeSlackClient(replies=[{'user': 'BOT', 'text': 'hello'}])
        with mock.patch.object(
            slack_handler.identity,
            'resolve',
            new=mock.AsyncMock(return_value=user),
        ):
            await slack_handler.handle_event(event, client, bot_user_id='BOT')
        self.assertIn('Ask me anything', client.posts[-1]['text'])

    async def test_missing_fields_ignored(self) -> None:
        client = FakeSlackClient(replies=[])
        await slack_handler.handle_event({}, client, bot_user_id='BOT')
        self.assertEqual([], client.posts)
