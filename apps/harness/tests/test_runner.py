"""The runner's ``run_with_secret`` tool and its lease fence.

The SDK session and the user switches need the pod; the kind suite in
``isolation/`` covers them.
"""

import asyncio
import contextlib
import json
import pathlib
import tempfile
import typing
import unittest
from unittest import mock

import respx

from imbi.harness import api, ipc, privilege, runner

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


class Fenced(BaseException):
    """Not an Exception, as os._exit is not: the heartbeat must not
    catch its own fence."""


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

    async def test_unexpected_error_is_a_failed_renewal(self) -> None:
        # For example a decode error: it must not end the heartbeat
        # before the fence.
        self.api.heartbeat.side_effect = ValueError('bad body')
        loop = asyncio.get_running_loop()
        started = loop.time()
        with (
            self.assertLogs('imbi.harness.runner', 'WARNING') as logs,
            self.assertRaises(Fenced),
        ):
            await self.runner.heartbeat(lease_seconds=3)
        self.assertGreaterEqual(loop.time() - started, 1.5)
        self.assertIn('lease', self.fence.call_args.args[0])
        self.assertNotIn('bad body', '\n'.join(logs.output))

    async def test_non_json_body_still_renews(self) -> None:
        # Api.heartbeat reads only the status; a 200 renews.
        self.mock = respx.mock(base_url='http://imbi.test')
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.mock.post('/harness/runners/r/heartbeat').respond(
            200, text='not json'
        )
        self.runner.api = api.Api('http://imbi.test')
        self.runner.runner_id = 'r'
        task = asyncio.create_task(self.runner.heartbeat(lease_seconds=3))
        await asyncio.sleep(3.5)
        self.assertFalse(task.done())
        task.cancel()
        self.fence.assert_not_called()

    async def test_heartbeat_that_stops_fences(self) -> None:
        with mock.patch.object(
            self.runner, '_renew', side_effect=RuntimeError('bug')
        ):
            with self.assertRaises(Fenced):
                await self.runner.heartbeat(lease_seconds=3)
        self.assertIn('RuntimeError', self.fence.call_args.args[0])

    async def test_cancel_does_not_fence(self) -> None:
        self.api.heartbeat.return_value = None
        task = asyncio.create_task(self.runner.heartbeat(lease_seconds=3))
        await asyncio.sleep(0.1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.fence.assert_not_called()

    async def test_keeps_running_while_renewed(self) -> None:
        self.api.heartbeat.return_value = None
        task = asyncio.create_task(self.runner.heartbeat(lease_seconds=3))
        await asyncio.sleep(3.5)
        self.assertFalse(task.done())
        task.cancel()
        self.fence.assert_not_called()
        self.assertGreaterEqual(self.api.heartbeat.await_count, 4)


class OneChainTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_serve_returns_after_the_claim_even_on_failure(self) -> None:
        subject = make_runner()
        calls = 0

        async def cycle() -> None:
            nonlocal calls
            calls += 1
            subject.claimed = True
            raise api.Refused(500, 'finish_failed')

        subject.cycle = cycle  # type: ignore[method-assign]
        subject.remove_old_workspaces = mock.Mock()  # type: ignore[method-assign]
        with mock.patch.object(pathlib.Path, 'exists', return_value=True):
            await asyncio.wait_for(subject.serve(), 2)
        self.assertEqual(calls, 1)

    async def test_end_chain_kills_and_removes_the_workspace(self) -> None:
        subject = make_runner()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        workspace = pathlib.Path(tmp.name) / 'chain'
        (workspace / 'home').mkdir(parents=True)
        (workspace / 'home' / 'file').write_text('x')
        with (
            mock.patch.object(privilege, 'kill_agent') as kill,
            mock.patch.object(
                privilege, 'effective', return_value=contextlib.nullcontext()
            ) as effective,
            mock.patch.object(ipc, 'call', mock.AsyncMock()) as call,
        ):
            await subject.end_chain(workspace)
        kill.assert_called_once_with()
        call.assert_awaited_once_with({'op': 'end_chain'})
        effective.assert_called_once_with(privilege.AGENT)
        self.assertFalse(workspace.exists())

    async def test_end_chain_without_executor(self) -> None:
        subject = make_runner()
        with (
            mock.patch.object(privilege, 'kill_agent'),
            mock.patch.object(
                privilege, 'effective', return_value=contextlib.nullcontext()
            ),
            mock.patch.object(
                ipc, 'call', mock.AsyncMock(side_effect=FileNotFoundError)
            ),
            self.assertLogs('imbi.harness.runner', 'WARNING'),
        ):
            await subject.end_chain(pathlib.Path('/nonexistent/chain'))
