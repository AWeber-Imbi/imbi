"""One task: setup secrets, workspace, config, SDK run, and outcome.

The user switches and the CLI start need the pod; the kind suite in
``isolation/`` covers them. Here ``privilege.effective`` is a no-op.
"""

import asyncio
import contextlib
import decimal
import json
import pathlib
import tempfile
import typing
import unittest
from unittest import mock

import claude_agent_sdk as sdk

from imbi.harness import api, ipc, privilege, proxy, redact, task

HANDLE = 'handle-that-must-not-reach-the-model-0123456789'
KEY = 'sk-ant-model-key-0123456789abcdef'
BINDING = 'secret://production/github/app'


def claim(**config: typing.Any) -> dict[str, typing.Any]:
    return {
        'chain_id': 'c',
        'attempt': 1,
        'organization_slug': 'org',
        'agent_token': 'iat_token',
        'task': {
            'id': 't',
            'short_id': 'T-1',
            'agent_id': 'a',
            'project_id': 'p',
            'description': 'Work.',
        },
        'bundle': {
            'prompt': {'system': 'You fix bugs.', 'model_id': 'claude-x'},
            'repositories': [
                {
                    'host': 'github.com',
                    'name': 'acme/app',
                    'url': 'https://github.com/acme/app',
                }
            ],
            'config': {
                'model_upstream': {
                    'kind': 'anthropic',
                    'base_url': None,
                    'key_ref': 'secret://production/anthropic/key',
                },
                'plugins': [],
                'allowed_tools': None,
                'denied_tools': ['WebFetch'],
                'permission_mode': 'default',
                'sandbox': {'enabled': False},
                'system_prompt_prefix': 'Org rules.',
                'hooks': {},
                'secrets': ['secret://production/github/token'],
                'github_app_binding': None,
            }
            | config,
        },
    }


def created(purpose: str = 'github_write') -> dict[str, typing.Any]:
    return {
        'resolution_id': f'r-{purpose}',
        'handle': HANDLE,
        'state': 'active',
        'delivery': {'mode': 'file_descriptor', 'target': '3'},
    }


class TaskTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name)
        patcher = mock.patch.object(
            privilege, 'effective', return_value=contextlib.nullcontext()
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.call = mock.AsyncMock()
        patcher = mock.patch.object(ipc, 'call', self.call)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = mock.AsyncMock(spec=api.Api)
        self.client.create_resolution.side_effect = (
            lambda _token, body: created(body['purpose'])
        )
        self.redactor = redact.Redactor()
        self.run_task = self.make()

    def make(self, **config: typing.Any) -> task.TaskRun:
        layout = task.Layout(self.tmp / 'chain')
        layout.make()
        return task.TaskRun(
            self.client,
            claim(**config),
            layout,
            self.redactor,
            instance='pod',
            transcripts=self.tmp / 'transcripts',
        )

    def posted(self, path: str) -> list[typing.Any]:
        """The bodies posted to a task route, in order."""
        return [
            call.kwargs.get('json')
            for call in self.client.post.await_args_list
            if call.args[0].endswith(path)
        ]


class RunWithSecretTestCase(TaskTestCase):
    ARGS: typing.ClassVar[dict[str, typing.Any]] = {
        'command': 'gh pr list',
        'secrets': [
            {
                'reference': 'secret://production/github/token',
                'purpose': 'github_write',
                'env': 'GH_TOKEN',
            }
        ],
    }

    async def run_tool(self, args: typing.Any = None) -> dict[str, typing.Any]:
        tool = self.run_task.run_with_secret_tool()
        result = await tool.handler(args or self.ARGS)
        self.assertNotIn(HANDLE, json.dumps(result))
        return result

    async def test_sends_handles_to_the_executor_only(self) -> None:
        self.call.return_value = {
            'exit_code': 0,
            'output': 'ok',
            'values': ['ghs_delivered_value_0123456789'],
        }
        result = await self.run_tool()
        self.assertEqual(
            result, {'content': [{'type': 'text', 'text': 'exit code 0\nok'}]}
        )
        body = self.client.create_resolution.call_args.args[1]
        self.assertEqual(body['short_id'], 'T-1')
        self.assertEqual(body['delivery']['target'], 'GH_TOKEN')
        (message,) = self.call.call_args.args
        self.assertEqual(message['secrets'][0]['handle'], HANDLE)
        self.assertEqual(message['cwd'], str(self.tmp / 'chain' / 'repos'))
        self.assertEqual(
            message['home'], str(self.tmp / 'chain' / 'tasks' / 't' / 'home')
        )
        self.assertEqual(message['context']['task_id'], 't')
        # The delivered value is redacted from every later event.
        self.assertEqual(
            self.redactor.text('x ghs_delivered_value_0123456789'),
            'x [REDACTED]',
        )

    async def test_refused_resolution(self) -> None:
        self.client.create_resolution.side_effect = api.Refused(
            403, 'secret_access_denied'
        )
        result = await self.run_tool()
        self.assertTrue(result['is_error'])
        self.assertIn('secret_access_denied', result['content'][0]['text'])
        self.call.assert_not_called()

    async def test_executor_error(self) -> None:
        self.call.return_value = {'error': 'resolution_expired'}
        result = await self.run_tool()
        self.assertTrue(result['is_error'])
        self.assertIn('resolution_expired', result['content'][0]['text'])

    async def test_executor_unavailable(self) -> None:
        self.call.side_effect = FileNotFoundError(ipc.SOCKET_PATH)
        result = await self.run_tool()
        self.assertTrue(result['is_error'])

    async def test_setup_secrets_are_refused(self) -> None:
        cases = [
            {'purpose': 'model_inference'},
            {'purpose': 'workspace_checkout'},
            {'purpose': 'marketplace_fetch'},
            {'reference': 'secret://production/anthropic/key'},
        ]
        for change in cases:
            with self.subTest(change=change):
                secret = self.ARGS['secrets'][0] | change
                result = await self.run_tool(
                    {'command': 'echo "$GH_TOKEN"', 'secrets': [secret]}
                )
                self.assertTrue(result['is_error'])
                self.assertIn('harness only', result['content'][0]['text'])
        self.client.create_resolution.assert_not_called()
        self.call.assert_not_called()

    async def test_invalid_input(self) -> None:
        result = await self.run_tool({'command': 'x', 'secrets': [{}]})
        self.assertTrue(result['is_error'])


class OutcomeTestCase(unittest.TestCase):
    def result(self, **changes: typing.Any) -> sdk.ResultMessage:
        values: dict[str, typing.Any] = {
            'subtype': 'success',
            'duration_ms': 1,
            'duration_api_ms': 1,
            'is_error': False,
            'num_turns': 1,
            'session_id': 's',
        } | changes
        return sdk.ResultMessage(**values)

    def test_outcomes(self) -> None:
        cases = [
            (None, ('failed_external', 'no_result')),
            (self.result(), ('done_acted', None)),
            (
                self.result(subtype='error_max_turns', is_error=True),
                ('partial_capped', 'max_turns'),
            ),
            (
                self.result(is_error=True, api_error_status=400),
                ('failed_external', 'model_api_error'),
            ),
            (
                self.result(subtype='error_during_execution', is_error=True),
                ('failed_external', 'error_during_execution'),
            ),
            (
                self.result(subtype='Bad Value', is_error=True),
                ('failed_external', 'sdk_error'),
            ),
        ]
        for result, expected in cases:
            with self.subTest(result=result):
                self.assertEqual(task.outcome(result), expected)


class ConfigTestCase(TaskTestCase):
    def test_all_builtins_less_the_denied(self) -> None:
        allowed, denied = self.run_task.tools()
        self.assertEqual(denied, ['WebFetch'])
        self.assertNotIn('WebFetch', allowed)
        self.assertIn('Bash', allowed)
        self.assertEqual(allowed[-1], 'mcp__imbi__run_with_secret')

    def test_allowed_list(self) -> None:
        subject = self.make(allowed_tools=['Read', 'WebFetch'])
        self.assertEqual(
            subject.tools()[0], ['Read', 'mcp__imbi__run_with_secret']
        )

    def test_writes_settings_and_rules(self) -> None:
        subject = self.make(
            hooks={'PreToolUse': []},
            sandbox={'enabled': True, 'allow_unsandboxed_commands': False},
        )
        subject.layout.make_task('t')
        subject.write_config()
        config = self.tmp / 'chain' / 'tasks' / 't' / '.claude'
        settings = json.loads((config / 'settings.json').read_text())
        self.assertEqual(settings['permissions']['deny'], ['WebFetch'])
        self.assertEqual(settings['hooks'], {'PreToolUse': []})
        self.assertEqual(
            settings['sandbox'],
            {'enabled': True, 'allowUnsandboxedCommands': False},
        )
        rules = (config / 'CLAUDE.md').read_text()
        self.assertIn('`secret://production/github/token`', rules)
        self.assertNotIn('\n@', rules)  # No repository: no import.

    def test_imports_the_repository_instructions(self) -> None:
        repo = self.tmp / 'chain' / 'repos' / 'app'
        repo.mkdir()
        (repo / 'CLAUDE.md').write_text('repo rules')
        self.run_task.layout.make_task('t')
        self.run_task.write_config()
        rules = (
            self.tmp / 'chain' / 'tasks' / 't' / '.claude' / 'CLAUDE.md'
        ).read_text()
        self.assertIn(f'\n@{repo}/CLAUDE.md\n', rules)
        self.assertNotIn('AGENTS.md', rules)

    def test_options(self) -> None:
        subject = self.make(permission_mode='plan')
        subject.plugins = [self.tmp / 'plugin']
        options = subject.options('http://127.0.0.1:1')
        self.assertEqual(options.cli_path, task.CLI_WRAPPER)
        self.assertEqual(options.permission_mode, 'plan')
        self.assertEqual(options.setting_sources, ['user'])
        self.assertEqual(options.max_buffer_size, task.SDK_BUFFER)
        self.assertEqual(options.model, 'claude-x')
        self.assertEqual(
            options.plugins,
            [{'type': 'local', 'path': str(self.tmp / 'plugin')}],
        )
        env = options.env
        self.assertEqual(env['ANTHROPIC_API_KEY'], 'placeholder')
        self.assertEqual(env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'], '1')
        self.assertEqual(env['CLAUDE_CODE_ENABLE_TASKS'], '0')
        self.assertEqual(
            options.thinking, {'type': 'adaptive', 'display': 'summarized'}
        )
        prompt = typing.cast('dict[str, str]', options.system_prompt)
        self.assertEqual(prompt['append'], 'Org rules.\n\nYou fix bugs.')
        self.assertEqual(self.make().options('u').permission_mode, 'dontAsk')


class ModelKeyTestCase(TaskTestCase):
    async def test_fetches_through_the_executor(self) -> None:
        self.call.return_value = {'material': KEY}
        self.assertEqual(await self.run_task.model_key(), KEY)
        body = self.client.create_resolution.call_args.args[1]
        self.assertEqual(body['purpose'], 'model_inference')
        self.assertEqual(body['delivery'], task.SETUP_DELIVERY)
        (message,) = self.call.call_args.args
        self.assertEqual(message['op'], 'fetch')
        self.assertEqual(message['secret']['handle'], HANDLE)
        self.assertEqual(self.redactor.text(KEY), '[REDACTED]')

    async def test_failures(self) -> None:
        cases: list[tuple[task.TaskRun, str]] = []
        cases.append((self.make(model_upstream={}), 'model_key_missing'))
        refused = self.make()
        cases.append((refused, 'model_key_refused'))
        unavailable = self.make()
        cases.append((unavailable, 'model_key_unavailable'))
        for subject, reason in cases:
            self.client.create_resolution.side_effect = (
                api.Refused(403, 'secret_access_denied')
                if subject is refused
                else (lambda _token, body: created(body['purpose']))
            )
            self.call.return_value = {'error': 'resolution_expired'}
            with self.subTest(reason=reason):
                with self.assertRaises(task.Failed) as ctx:
                    await subject.model_key()
                self.assertEqual(ctx.exception.reason, reason)

    async def test_executor_gone(self) -> None:
        self.call.side_effect = ConnectionRefusedError()
        with self.assertRaises(task.Failed) as ctx:
            await self.run_task.model_key()
        self.assertEqual(ctx.exception.reason, 'executor_unavailable')


class UsageTestCase(TaskTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_task.session_id = 's'
        self.run_task.loop = asyncio.get_event_loop()

    def reply(self, **state: typing.Any) -> dict[str, typing.Any]:
        return {
            'task': {
                'status': 'running',
                'control': 'run',
                'budget_remaining': '1.5',
            }
            | state
        }

    async def test_report_with_absent_cache_fields(self) -> None:
        self.client.post.return_value = mock.Mock(
            json=mock.Mock(return_value=self.reply())
        )
        await self.run_task.report(
            'claude-x', {'input_tokens': 10, 'output_tokens': 5}
        )
        (body,) = self.posted('/usage')
        self.assertEqual(body['model_id'], 'claude-x')
        self.assertEqual(body['tokens_in'], 10)
        self.assertEqual(body['tokens_out'], 5)
        self.assertEqual(body['cache_read_tokens'], 0)
        self.assertEqual(body['cache_write_tokens'], 0)
        self.assertEqual(body['session_id'], 's')
        self.assertEqual(self.run_task.remaining, decimal.Decimal('1.5'))
        self.assertTrue(self.run_task.allowed())

    async def test_unmeasured_report(self) -> None:
        self.client.post.return_value = mock.Mock(
            json=mock.Mock(return_value=self.reply())
        )
        await self.run_task.report('', {})
        (body,) = self.posted('/usage')
        self.assertEqual(body['model_id'], 'unknown')
        self.assertIsNone(body['tokens_in'])
        self.assertIsNone(body['cache_read_tokens'])

    async def test_budget_spent_stops_the_task(self) -> None:
        self.client.post.return_value = mock.Mock(
            json=mock.Mock(
                return_value=self.reply(status='closed', budget_remaining='0')
            )
        )
        self.run_task.client = mock.AsyncMock()
        await self.run_task.report('m', {'input_tokens': 1})
        self.assertFalse(self.run_task.allowed())
        assert self.run_task.stopping is not None
        await self.run_task.stopping
        self.run_task.client.interrupt.assert_awaited_once()

    async def test_closed_task(self) -> None:
        self.client.post.side_effect = api.Refused(409, 'task_closed')
        await self.run_task.report('m', {'input_tokens': 1})
        self.assertTrue(self.run_task.closed)

    async def test_meter_from_the_proxy_thread(self) -> None:
        self.client.post.return_value = mock.Mock(
            json=mock.Mock(return_value=self.reply(budget_remaining='0'))
        )
        await asyncio.to_thread(self.run_task.meter, 'm', {})
        self.assertFalse(self.run_task.allowed())

    async def test_meter_failure_is_logged(self) -> None:
        self.client.post.side_effect = api.Refused(500, 'boom')
        with self.assertLogs('imbi.harness.task', 'WARNING'):
            await asyncio.to_thread(self.run_task.meter, 'm', {})


class WorkspaceTestCase(TaskTestCase):
    def clone_calls(self) -> list[dict[str, typing.Any]]:
        return [
            call.args[0]
            for call in self.call.await_args_list
            if call.args[0]['op'] == 'clone'
        ]

    async def test_anonymous_clone_without_binding(self) -> None:
        self.call.return_value = {'exit_code': 0, 'output': ''}
        await self.run_task.build_workspace()
        (request,) = self.clone_calls()
        self.assertEqual(request['url'], 'https://github.com/acme/app')
        self.assertEqual(
            request['dest'], str(self.tmp / 'chain' / 'repos' / 'app')
        )
        self.assertNotIn('secret', request)
        self.assertEqual(
            self.run_task._cwd(), self.tmp / 'chain' / 'repos' / 'app'
        )

    async def test_checkout_token_with_binding(self) -> None:
        subject = self.make(github_app_binding=BINDING)
        self.call.return_value = {
            'exit_code': 0,
            'output': '',
            'values': ['ghs_checkout_token_0123456789'],
        }
        await subject.build_workspace()
        (request,) = self.clone_calls()
        self.assertEqual(request['secret']['purpose'], 'workspace_checkout')
        body = self.client.create_resolution.call_args.args[1]
        self.assertEqual(body['reference'], BINDING)
        self.assertEqual(body['delivery'], task.SETUP_DELIVERY)
        self.assertEqual(
            self.redactor.text('ghs_checkout_token_0123456789'), '[REDACTED]'
        )

    async def test_failed_checkout(self) -> None:
        self.call.return_value = {'exit_code': 128, 'output': 'fatal'}
        with self.assertRaises(task.Failed) as ctx:
            await self.run_task.build_workspace()
        self.assertEqual(ctx.exception.reason, 'workspace_checkout_failed')

    async def test_refused_checkout(self) -> None:
        subject = self.make(github_app_binding=BINDING)
        self.client.create_resolution.side_effect = api.Refused(
            403, 'secret_access_denied'
        )
        with self.assertRaises(task.Failed) as ctx:
            await subject.build_workspace()
        self.assertEqual(ctx.exception.reason, 'workspace_checkout_refused')

    def plugin(self, **changes: typing.Any) -> dict[str, typing.Any]:
        return {
            'marketplace': 'tools',
            'plugin': 'hello',
            'url': 'https://github.com/acme/tools',
            'sha': '0123456789abcdef0123',
            'path': 'plugins/hello',
        } | changes

    async def test_plugins_share_one_marketplace_clone(self) -> None:
        subject = self.make(
            plugins=[self.plugin(), self.plugin(plugin='bye', path='bye')]
        )
        subject.bundle['repositories'] = []
        self.call.return_value = {'exit_code': 0, 'output': ''}
        await subject.build_workspace()
        (request,) = self.clone_calls()
        self.assertEqual(request['sha'], '0123456789abcdef0123')
        dest = self.tmp / 'chain' / 'plugins' / 'tools-0123456789ab'
        self.assertEqual(request['dest'], str(dest))
        self.assertEqual(
            subject.plugins, [dest / 'plugins' / 'hello', dest / 'bye']
        )

    async def test_marketplace_with_a_token(self) -> None:
        subject = self.make(
            plugins=[self.plugin()], github_app_binding=BINDING
        )
        subject.bundle['repositories'] = []
        self.call.return_value = {'exit_code': 0, 'output': ''}
        with self.assertLogs('imbi.harness.task', 'INFO') as logs:
            await subject.build_workspace()
        (request,) = self.clone_calls()
        self.assertEqual(request['secret']['purpose'], 'marketplace_fetch')
        self.assertIn('cloned with a token', logs.output[-1])

    async def test_public_github_falls_back_to_anonymous(self) -> None:
        subject = self.make(
            plugins=[self.plugin()], github_app_binding=BINDING
        )
        subject.bundle['repositories'] = []
        self.call.side_effect = [
            {'exit_code': 128, 'output': 'denied'},
            {'exit_code': 0, 'output': ''},
        ]
        with self.assertLogs('imbi.harness.task', 'INFO') as logs:
            await subject.build_workspace()
        first, second = self.clone_calls()
        self.assertIn('secret', first)
        self.assertNotIn('secret', second)
        self.assertIn('cloned anonymously', logs.output[-1])

    async def test_refused_token_on_github(self) -> None:
        subject = self.make(
            plugins=[self.plugin()], github_app_binding=BINDING
        )
        subject.bundle['repositories'] = []
        self.client.create_resolution.side_effect = api.Refused(
            403, 'secret_access_denied'
        )
        self.call.return_value = {'exit_code': 0, 'output': ''}
        await subject.build_workspace()
        (request,) = self.clone_calls()
        self.assertNotIn('secret', request)

    async def test_ghe_marketplace_never_falls_back(self) -> None:
        subject = self.make(
            plugins=[self.plugin(url='https://ghe.example.com/acme/tools')],
            github_app_binding=BINDING,
        )
        subject.bundle['repositories'] = []
        self.call.return_value = {'exit_code': 128, 'output': 'denied'}
        with self.assertRaises(task.Failed) as ctx:
            await subject.build_workspace()
        self.assertEqual(ctx.exception.reason, 'marketplace_fetch_failed')
        self.assertEqual(len(self.clone_calls()), 1)

    async def test_marketplace_failures(self) -> None:
        cases = [
            ([self.plugin(sha=None)], 'plugin_not_pinned'),
            ([self.plugin(path='../x')], 'plugin_path_invalid'),
            ([self.plugin()], 'marketplace_fetch_failed'),
        ]
        self.call.return_value = {'exit_code': 0, 'output': ''}
        for plugins, reason in cases:
            subject = self.make(plugins=plugins)
            subject.bundle['repositories'] = []
            if reason == 'marketplace_fetch_failed':
                self.call.return_value = {'exit_code': 1, 'output': ''}
            with self.subTest(reason=reason):
                with self.assertRaises(task.Failed) as ctx:
                    await subject.build_workspace()
                self.assertEqual(ctx.exception.reason, reason)

    async def test_executor_gone(self) -> None:
        self.call.side_effect = ConnectionRefusedError()
        with self.assertRaises(task.Failed) as ctx:
            await self.run_task.build_workspace()
        self.assertEqual(ctx.exception.reason, 'executor_unavailable')


class FakeClient:
    """Stands in for ``ClaudeSDKClient``: replays messages."""

    messages: typing.ClassVar[list[typing.Any]] = []

    def __init__(self, *_: typing.Any, **__: typing.Any) -> None:
        self.prompts: list[str] = []
        self.interrupt = mock.AsyncMock()

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *_: typing.Any) -> None:
        return None

    async def query(self, prompt: str) -> None:
        self.prompts.append(prompt)

    async def receive_response(self) -> typing.AsyncIterator[typing.Any]:
        for message in self.messages:
            yield message


class RunTestCase(TaskTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.responses: dict[str, typing.Any] = {
            '/sessions': {
                'session': {'id': 's'},
                'task': {'status': 'running', 'control': 'run'},
            },
        }

        async def post(
            path: str, *_: typing.Any, **__: typing.Any
        ) -> typing.Any:
            for suffix, body in self.responses.items():
                if path.endswith(suffix):
                    if isinstance(body, Exception):
                        raise body
                    return mock.Mock(json=mock.Mock(return_value=body))
            return mock.Mock(json=mock.Mock(return_value={}))

        self.client.post.side_effect = post
        self.call.side_effect = self.executor
        for name, value in (
            ('ClaudeSDKClient', FakeClient),
            ('AgentTransport', mock.Mock()),
        ):
            target = sdk if name == 'ClaudeSDKClient' else task
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(
            proxy, 'start', return_value='http://127.0.0.1:1'
        )
        self.proxy = patcher.start()
        self.addCleanup(patcher.stop)
        FakeClient.messages = [
            sdk.AssistantMessage(
                content=[
                    sdk.ToolUseBlock('tu1', 'Bash', {'command': 'ls'}),
                ],
                model='m',
            ),
            sdk.UserMessage(
                content=[sdk.ToolResultBlock('tu1', f'key {KEY}', False)]
            ),
            sdk.AssistantMessage(content=[sdk.TextBlock('done')], model='m'),
            sdk.ResultMessage(
                subtype='success',
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=2,
                session_id='x',
            ),
        ]

    async def executor(self, message: dict[str, typing.Any]) -> typing.Any:
        if message['op'] == 'fetch':
            return {'material': KEY}
        return {'exit_code': 0, 'output': ''}

    async def test_runs_to_done(self) -> None:
        await self.run_task.run()
        self.assertEqual(
            self.posted('/outcome'),
            [{'outcome': 'done_acted', 'reason': None}],
        )
        events = [
            event
            for batch in self.posted('/events')
            for event in batch['events']
        ]
        kinds = [event['type'] for event in events]
        self.assertEqual(kinds, ['tool.called', 'turn'])
        self.assertEqual(events[0]['payload']['result'], 'key [REDACTED]')
        self.assertNotIn(KEY, json.dumps(events))
        upstream, key = self.proxy.call_args.args
        self.assertEqual(upstream, task.ANTHROPIC_API)
        self.assertEqual(key, KEY)
        self.assertFalse(self.proxy.call_args.kwargs['litellm'])
        transcript = self.tmp / 'transcripts' / 't.jsonl'
        self.assertEqual(len(transcript.read_text().splitlines()), 4)

    async def test_litellm_upstream(self) -> None:
        subject = self.make(
            model_upstream={
                'kind': 'litellm',
                'base_url': 'https://llm.test',
                'key_ref': 'secret://production/llm/key',
            }
        )
        await subject.run()
        self.assertEqual(self.proxy.call_args.args[0], 'https://llm.test')
        self.assertTrue(self.proxy.call_args.kwargs['litellm'])

    async def test_failed_setup_sets_the_reason(self) -> None:
        subject = self.make(model_upstream={})
        await subject.run()
        self.assertEqual(
            self.posted('/outcome'),
            [{'outcome': 'failed_external', 'reason': 'model_key_missing'}],
        )

    async def test_unexpected_error(self) -> None:
        self.call.side_effect = RuntimeError('boom')
        with self.assertLogs('imbi.harness.task', 'ERROR'):
            await self.run_task.run()
        self.assertEqual(
            self.posted('/outcome'),
            [{'outcome': 'failed_external', 'reason': 'harness_error'}],
        )

    async def test_cancel_closes_the_session(self) -> None:
        self.responses['/sessions']['task']['control'] = 'cancel'
        await self.run_task.run()
        self.assertEqual(self.posted('/outcome'), [])
        self.assertEqual(self.posted('/close'), [{'reason': 'cancelled'}])

    async def test_refused_session(self) -> None:
        self.responses['/sessions'] = api.Refused(409, 'task_cancelled')
        with self.assertLogs('imbi.harness.task', 'WARNING'):
            await self.run_task.run()
        self.call.assert_not_called()

    async def test_missing_plugin_fails_the_task(self) -> None:
        FakeClient.messages.insert(
            0, sdk.SystemMessage('init', {'plugins': [], 'plugin_errors': []})
        )
        subject = self.make(
            plugins=[
                {
                    'marketplace': 'tools',
                    'plugin': 'hello',
                    'url': 'https://github.com/acme/tools',
                    'sha': '0123456789abcdef',
                }
            ]
        )
        with self.assertLogs('imbi.harness.task', 'ERROR'):
            await subject.run()
        self.assertEqual(
            self.posted('/outcome'),
            [{'outcome': 'failed_external', 'reason': 'plugin_not_loaded'}],
        )


class HeartbeatTestCase(TaskTestCase):
    async def test_cancel_stops_the_sdk(self) -> None:
        self.run_task.loop = asyncio.get_running_loop()
        self.run_task.client = mock.AsyncMock()
        self.client.post.return_value = mock.Mock(
            json=mock.Mock(
                return_value={'status': 'running', 'control': 'cancel'}
            )
        )
        with mock.patch.object(task, 'SESSION_HEARTBEAT', 0.01):
            beat = asyncio.create_task(self.run_task._heartbeat())
            for _ in range(100):
                if self.run_task.stopping is not None:
                    break
                await asyncio.sleep(0.01)
            beat.cancel()
        assert self.run_task.stopping is not None
        await self.run_task.stopping
        self.run_task.client.interrupt.assert_awaited_once()

    async def test_closed_task_stops_the_sdk(self) -> None:
        self.run_task.loop = asyncio.get_running_loop()
        self.client.post.side_effect = api.Refused(409, 'task_closed')
        with (
            mock.patch.object(task, 'SESSION_HEARTBEAT', 0.01),
            self.assertLogs('imbi.harness.task', 'WARNING'),
        ):
            beat = asyncio.create_task(self.run_task._heartbeat())
            await asyncio.sleep(0.05)
            beat.cancel()
        self.assertTrue(self.run_task.closed)
        self.assertFalse(self.run_task.allowed())
