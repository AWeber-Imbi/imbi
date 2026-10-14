"""The runner's ``run_with_secret`` tool and its lease fence.

The SDK session and the user switches need the pod; the kind suite in
``isolation/`` covers them.
"""

import asyncio
import json
import pathlib
import typing
import unittest
from unittest import mock

from imbi.harness import api, ipc, runner

HANDLE = 'handle-that-must-not-reach-the-model-0123456789'
CLAIM = {
    'chain_id': 'c',
    'agent_token': 'iat_token',
    'task': {
        'id': 't',
        'short_id': 'T-1',
        'agent_id': 'a',
        'project_id': None,
        'description': 'Work.',
    },
}
ARGS = {
    'command': 'gh pr list',
    'secrets': [
        {
            'reference': 'secret://production/github/token',
            'purpose': 'github_write',
            'env': 'GH_TOKEN',
        }
    ],
}


class Fenced(Exception):
    pass


def make_runner() -> runner.Runner:
    settings = runner.Settings(
        api_url='http://imbi.test',
        pool='general',
        instance='pod',
        model_url='http://model.test',
        model=None,
    )
    return runner.Runner(
        settings, ('id', 'secret'), pathlib.Path('/nonexistent'), 'http://p'
    )


class RunWithSecretTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.runner = make_runner()
        self.api = mock.AsyncMock(spec=api.Api)
        self.runner.api = self.api
        self.api.create_resolution.return_value = {
            'resolution_id': 'r1',
            'handle': HANDLE,
            'state': 'active',
            'delivery': {'mode': 'environment', 'target': 'GH_TOKEN'},
        }
        patcher = mock.patch.object(ipc, 'call', mock.AsyncMock())
        self.call = patcher.start()
        self.addCleanup(patcher.stop)
        tool = self.runner._run_with_secret(CLAIM, pathlib.Path('/work/c'))
        self.handler = tool.handler

    async def run_tool(self) -> dict[str, typing.Any]:
        result = await self.handler(ARGS)
        self.assertNotIn(HANDLE, json.dumps(result))
        return result

    async def test_sends_handles_to_the_executor_only(self) -> None:
        self.call.return_value = {'exit_code': 0, 'output': 'ok'}
        result = await self.run_tool()
        self.assertEqual(
            result, {'content': [{'type': 'text', 'text': 'exit code 0\nok'}]}
        )
        body = self.api.create_resolution.call_args.args[1]
        self.assertEqual(body['short_id'], 'T-1')
        self.assertEqual(body['delivery']['target'], 'GH_TOKEN')
        (message,) = self.call.call_args.args
        self.assertEqual(message['secrets'][0]['handle'], HANDLE)
        self.assertEqual(message['cwd'], '/work/c')
        self.assertEqual(message['context']['task_id'], 't')

    async def test_refused_resolution(self) -> None:
        self.api.create_resolution.side_effect = api.Refused(
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

    async def test_invalid_input(self) -> None:
        result = await self.handler({'command': 'x', 'secrets': [{}]})
        self.assertTrue(result['is_error'])


class HeartbeatTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.runner = make_runner()
        self.api = mock.AsyncMock(spec=api.Api)
        self.runner.api = self.api
        patcher = mock.patch.object(runner, '_fence', side_effect=Fenced)
        self.fence = patcher.start()
        self.addCleanup(patcher.stop)

    async def test_fences_before_the_lease_expires(self) -> None:
        async def black_hole(*_: typing.Any) -> None:
            await asyncio.sleep(3600)

        self.api.heartbeat.side_effect = black_hole
        loop = asyncio.get_running_loop()
        started = loop.time()
        with self.assertRaises(Fenced):
            await self.runner.heartbeat(lease_seconds=3)
        # The margin is a third of the lease: fence at 2 s, not at 3 s.
        self.assertLess(loop.time() - started, 2.5)
        self.assertIn('lease', self.fence.call_args.args[0])

    async def test_fences_when_the_runner_is_unknown(self) -> None:
        self.api.heartbeat.side_effect = api.Refused(
            401, 'invalid_runner_credential'
        )
        with self.assertRaises(Fenced):
            await self.runner.heartbeat(lease_seconds=3)
        self.assertIn('does not know', self.fence.call_args.args[0])

    async def test_keeps_running_while_renewed(self) -> None:
        self.api.heartbeat.return_value = {'state': 'busy'}
        task = asyncio.create_task(self.runner.heartbeat(lease_seconds=3))
        await asyncio.sleep(3.5)
        self.assertFalse(task.done())
        task.cancel()
        self.fence.assert_not_called()
        self.assertGreaterEqual(self.api.heartbeat.await_count, 4)
