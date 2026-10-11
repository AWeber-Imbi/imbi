import json
import types
from unittest import mock

from apps.slackbot.tests import helpers
from imbi.common.prompts import system as prompt_system
from imbi.slackbot import identity, inflight, settings, slack_handler


class Resp(dict):
    """A Slack response that supports both ``r['x']`` and ``r.data['x']``."""

    @property
    def data(self):
        return self


class FakeSlackClient:
    def __init__(self, replies=None, replies_error=False) -> None:
        self._replies = replies or []
        self._error = replies_error
        self.posts: list = []
        self.updates: list = []
        self.deletes: list = []
        self.reactions: list = []

    async def conversations_replies(self, channel, ts, limit=None):
        if self._error:
            raise RuntimeError('nope')
        return Resp(messages=list(self._replies))

    async def users_info(self, user):
        return Resp(user={'profile': {'display_name': user}})

    async def chat_postMessage(
        self,
        channel,
        thread_ts=None,
        text=None,
        markdown_text=None,
        blocks=None,
    ):
        self.posts.append(
            {
                'text': text,
                'markdown_text': markdown_text,
                'blocks': blocks,
                'thread_ts': thread_ts,
            }
        )
        return Resp(ts=f'ts{len(self.posts)}')

    async def chat_update(self, channel, ts, text=None, **_kw):
        self.updates.append({'ts': ts, 'text': text})
        return Resp(ts=ts)

    async def chat_delete(self, channel, ts):
        self.deletes.append(ts)

    async def reactions_add(self, channel, timestamp, name):
        self.reactions.append(('add', name))

    async def reactions_remove(self, channel, timestamp, name):
        self.reactions.append(('remove', name))


class FakeManager:
    def get_tools(self) -> list:
        return [{'name': 'list'}]

    def get_tool_names(self) -> list:
        return ['list']


CREATE_TASK = (
    'create_agent_task_api_organizations__org_slug__agent_tasks__post'
)


class FakeTaskApi(FakeManager):
    """The task create tool, with the API's idempotency behavior."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict] = {}
        self.calls: list = []

    async def execute_tool(self, name, tool_input, token):
        self.calls.append((name, tool_input, token))
        key = tool_input['idempotency_key']
        if key not in self.tasks:
            self.tasks[key] = {'short_id': f'T-{len(self.tasks) + 1}'}
        return json.dumps(self.tasks[key]), False


class FakeModel:
    """Asks for one task, then links the task that the tool returned."""

    def __init__(self) -> None:
        self.messages = self

    async def create(self, **kwargs):
        last = kwargs['messages'][-1]['content']
        if isinstance(last, list) and last[0].get('type') == 'tool_result':
            task = json.loads(last[0]['content'])
            link = f'<https://imbi/agents/tasks/eng/{task["short_id"]}|T>'
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(type='text', text=link)],
                stop_reason='end_turn',
            )
        tool_use = types.SimpleNamespace(
            type='tool_use',
            id='t1',
            name=CREATE_TASK,
            input={
                'org_slug': 'eng',
                'agent_slug': 'mender',
                'title': 'Fix the build',
                'description': 'The thread says the build fails.',
            },
        )
        return types.SimpleNamespace(
            content=[tool_use], stop_reason='tool_use'
        )


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
        self.client.auth_test = mock.AsyncMock(
            return_value={'user_id': 'BOT', 'bot_id': 'B_IMBI'}
        )

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

    @staticmethod
    def _patch_settings(*, enabled, bot_token, app_token):
        # A stub avoids the developer's local .env (read directly by
        # pydantic-settings) leaking real tokens into token-gating tests.
        stub = mock.Mock(
            enabled=enabled,
            slack_bot_token=bot_token,
            slack_app_token=app_token,
        )
        return mock.patch.object(
            slack_handler.settings,
            'get_slackbot_settings',
            return_value=stub,
        )

    async def test_disabled_does_not_connect(self) -> None:
        with self._patch_settings(enabled=False, bot_token='', app_token=''):
            await slack_handler.initialize()
        self.assertIsNone(slack_handler._handler)

    async def test_enabled_without_tokens(self) -> None:
        with self._patch_settings(enabled=True, bot_token='', app_token=''):
            await slack_handler.initialize()
        self.assertIsNone(slack_handler._handler)

    async def test_connects_and_dispatches(self) -> None:
        with (
            self._patch_settings(
                enabled=True, bot_token='xoxb', app_token='xapp'
            ),
            mock.patch.object(slack_handler, 'AsyncApp', FakeApp),
            mock.patch.object(
                slack_handler, 'AsyncSocketModeHandler', FakeHandler
            ),
        ):
            await slack_handler.initialize()
            self.assertEqual('BOT', slack_handler._bot_user_id)
            self.assertEqual('B_IMBI', slack_handler._bot_id)
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
        inflight.reset()
        system_prompt_patch = mock.patch.object(
            slack_handler.system_prompt,
            'build_system_prompt',
            new=mock.AsyncMock(
                return_value=prompt_system.SystemPrompt(
                    text='sys', source='fallback'
                )
            ),
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
        inflight.reset()
        super().tearDown()

    async def test_happy_path_renders_answer(self) -> None:
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
        # The answer is rendered through the Markdown sender (markdown_text),
        # the status reaction is added then removed, and the status message
        # is posted then deleted.
        self.assertEqual('the answer', client.posts[-1]['markdown_text'])
        self.assertEqual('1', client.posts[-1]['thread_ts'])
        self.assertEqual(
            [('add', mock.ANY), ('remove', mock.ANY)], client.reactions
        )
        self.assertEqual(1, len(client.deletes))

    async def test_prompt_settings_reach_run_turn(self) -> None:
        user = identity.ImbiUser('ada@example.com', 'Ada')
        event = {'channel': 'C', 'ts': '1', 'user': 'U1', 'text': '<@BOT> hi'}
        prompt = prompt_system.SystemPrompt(
            text='cms text',
            source='cms',
            model_id='claude-opus-5-5',
            max_tokens=2048,
            temperature=0.3,
        )
        run_turn = mock.AsyncMock(return_value='ok')
        with (
            mock.patch.object(
                slack_handler.identity,
                'resolve',
                new=mock.AsyncMock(return_value=user),
            ),
            mock.patch.object(
                slack_handler.system_prompt,
                'build_system_prompt',
                new=mock.AsyncMock(return_value=prompt),
            ),
            mock.patch.object(slack_handler.agent, 'run_turn', new=run_turn),
        ):
            await slack_handler.handle_event(
                event, FakeSlackClient(replies=[]), bot_user_id='BOT'
            )
        kwargs = run_turn.await_args.kwargs
        self.assertEqual(kwargs['system'], 'cms text')
        self.assertEqual(kwargs['model'], 'claude-opus-5-5')
        self.assertEqual(kwargs['max_tokens'], 2048)
        self.assertEqual(kwargs['temperature'], 0.3)

    async def test_run_turn_failure_posts_fallback(self) -> None:
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
                new=mock.AsyncMock(side_effect=RuntimeError('boom')),
            ),
        ):
            await slack_handler.handle_event(event, client, bot_user_id='BOT')
        self.assertIn(
            'something went wrong', client.posts[-1]['markdown_text']
        )
        # Status message is still cleaned up on failure.
        self.assertEqual(1, len(client.deletes))
        self.assertIn(('remove', mock.ANY), client.reactions)

    async def test_progress_updates_disabled(self) -> None:
        user = identity.ImbiUser('ada@example.com', 'Ada')
        event = {'channel': 'C', 'ts': '1', 'user': 'U1', 'text': '<@BOT> hi'}
        client = FakeSlackClient(replies=[])
        with (
            self.override_environment(IMBI_SLACKBOT_PROGRESS_UPDATES='false'),
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
            settings._slackbot_settings = None
            await slack_handler.handle_event(event, client, bot_user_id='BOT')
        self.assertEqual([], client.reactions)
        self.assertEqual([], client.deletes)
        self.assertEqual('the answer', client.posts[-1]['markdown_text'])

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

    async def test_mention_creates_one_task_per_delivery(self) -> None:
        user = identity.ImbiUser('ada@example.com', 'Ada')
        event = {
            'channel': 'C1',
            'ts': '1.5',
            'user': 'U1',
            'text': '<@BOT> make a task for mender',
        }
        api = FakeTaskApi()
        with (
            mock.patch.object(
                slack_handler.identity,
                'resolve',
                new=mock.AsyncMock(return_value=user),
            ),
            mock.patch.object(
                slack_handler.mcp, 'get_manager', return_value=api
            ),
            mock.patch.object(
                slack_handler.agent.client,
                'get_client',
                return_value=FakeModel(),
            ),
        ):
            first = FakeSlackClient(replies=[])
            await slack_handler.handle_event(event, first, bot_user_id='BOT')
            # Slack delivers the same event again.
            again = FakeSlackClient(replies=[])
            await slack_handler.handle_event(event, again, bot_user_id='BOT')
        self.assertEqual(['slack:C1:1.5:mender:1'], list(api.tasks))
        self.assertEqual(2, len(api.calls))
        self.assertEqual('tok', api.calls[0][2])
        for client in (first, again):
            self.assertIn(
                'https://imbi/agents/tasks/eng/T-1',
                client.posts[-1]['markdown_text'],
            )
            self.assertEqual('1.5', client.posts[-1]['thread_ts'])

    async def test_own_bot_events_are_ignored(self) -> None:
        resolve = mock.AsyncMock()
        events = [
            {'channel': 'C', 'ts': '1', 'user': 'BOT', 'text': '<@BOT>'},
            {
                'channel': 'C',
                'ts': '2',
                'user': 'U9',
                'bot_id': 'B_IMBI',
                'text': '<@BOT>',
            },
        ]
        client = FakeSlackClient(replies=[])
        with mock.patch.object(slack_handler.identity, 'resolve', new=resolve):
            for event in events:
                await slack_handler.handle_event(
                    event, client, bot_user_id='BOT', bot_id='B_IMBI'
                )
        resolve.assert_not_awaited()
        self.assertEqual([], client.posts)
        self.assertEqual([], client.reactions)

    async def test_other_bot_gets_unmapped_reply(self) -> None:
        event = {
            'channel': 'C',
            'ts': '1',
            'user': 'U_WORKFLOW',
            'bot_id': 'B_WORKFLOW',
            'text': '<@BOT> make a task',
        }
        client = FakeSlackClient(replies=[])
        run_turn = mock.AsyncMock()
        with (
            mock.patch.object(
                slack_handler.identity,
                'resolve',
                new=mock.AsyncMock(return_value=None),
            ),
            mock.patch.object(slack_handler.agent, 'run_turn', new=run_turn),
        ):
            await slack_handler.handle_event(
                event, client, bot_user_id='BOT', bot_id='B_IMBI'
            )
        run_turn.assert_not_awaited()
        self.assertIn('match your Slack account', client.posts[-1]['text'])
