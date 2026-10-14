"""The executor's request handling, without the privileged parts.

The process start as ``agent`` (``_spawn``) needs Linux and uid 0; the
kind suite in ``isolation/`` covers it.
"""

import asyncio
import base64
import pathlib
import stat
import tempfile
import typing
import unittest
from unittest import mock

from imbi.harness import api, executor, ipc, privilege

SECRET = 'ghs_0123456789abcdef0123456789abcdef'
RUNNER_UID = 10001


def request(**changes: typing.Any) -> dict[str, typing.Any]:
    return {
        'op': 'run',
        'command': 'gh pr list',
        'cwd': '/work/chain',
        'context': {'task_id': 't', 'agent_id': 'a', 'project_id': None},
        'secrets': [
            {
                'handle': 'h',
                'resolution_id': 'r1',
                'purpose': 'github_write',
                'delivery': {'mode': 'environment', 'target': 'GH_TOKEN'},
            }
        ],
    } | changes


class ExecutorTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.credentials = pathlib.Path(tmp.name)
        self.api = mock.AsyncMock(spec=api.Api)
        self.api.materialize.return_value = {
            'material': SECRET,
            'encoding': 'utf8',
        }
        with mock.patch.object(privilege, 'uid', return_value=RUNNER_UID):
            self.executor = executor.Executor(self.api, self.credentials)
        self.spawn = mock.AsyncMock(
            return_value=(0, f'token={SECRET}\n'.encode())
        )
        self.executor._spawn = self.spawn  # type: ignore[method-assign]

    async def hello(self) -> None:
        reply = await self.executor.dispatch(
            {
                'op': 'hello',
                'executor_token': 'ihe_token',
            }
        )
        self.assertEqual(reply, {'ok': True})

    async def test_hello_keeps_the_credential(self) -> None:
        await self.hello()
        path = self.credentials / 'executor.token'
        self.assertEqual(path.read_text(), 'ihe_token')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        with mock.patch.object(privilege, 'uid', return_value=RUNNER_UID):
            again = executor.Executor(self.api, self.credentials)
        self.assertEqual(again.token, 'ihe_token')

    async def test_hello_without_token(self) -> None:
        reply = await self.executor.dispatch({'op': 'hello'})
        self.assertEqual(reply, {'error': 'invalid_executor_credential'})

    async def test_run_without_credential(self) -> None:
        reply = await self.executor.dispatch(request())
        self.assertEqual(reply, {'error': 'no_executor_credential'})
        self.api.materialize.assert_not_called()

    async def test_run_filters_and_releases(self) -> None:
        await self.hello()
        reply = await self.executor.dispatch(request())
        self.assertEqual(
            reply, {'exit_code': 0, 'output': 'token=[REDACTED]\n'}
        )
        body = self.api.materialize.call_args.args[1]
        self.assertEqual(body['handle'], 'h')
        self.assertEqual(body['task_id'], 't')
        self.assertGreaterEqual(len(body['nonce']), 16)
        command, cwd, env = self.spawn.call_args.args
        self.assertEqual(command, 'gh pr list')
        self.assertEqual(cwd, '/work/chain')
        self.assertEqual(env, {'PATH': executor.PATH, 'GH_TOKEN': SECRET})
        self.api.release.assert_awaited_once_with('ihe_token', 'r1')

    async def test_new_nonce_for_each_materialization(self) -> None:
        await self.hello()
        await self.executor.dispatch(request())
        await self.executor.dispatch(request())
        first, second = (
            call.args[1]['nonce']
            for call in self.api.materialize.call_args_list
        )
        self.assertNotEqual(first, second)

    async def test_base64_material(self) -> None:
        await self.hello()
        self.api.materialize.return_value = {
            'material': base64.b64encode(SECRET.encode()).decode(),
            'encoding': 'base64',
        }
        await self.executor.dispatch(request())
        self.assertEqual(self.spawn.call_args.args[2]['GH_TOKEN'], SECRET)

    async def test_binary_material_is_refused(self) -> None:
        await self.hello()
        self.api.materialize.return_value = {
            'material': base64.b64encode(b'\xff\xfe').decode(),
            'encoding': 'base64',
        }
        reply = await self.executor.dispatch(request())
        self.assertEqual(reply, {'error': 'binary_material_in_environment'})
        self.spawn.assert_not_called()
        self.api.release.assert_awaited_once()

    async def test_refused_handle_does_not_run(self) -> None:
        await self.hello()
        self.api.materialize.side_effect = api.Refused(
            409, 'resolution_already_used'
        )
        reply = await self.executor.dispatch(request())
        self.assertEqual(reply, {'error': 'resolution_already_used'})
        self.spawn.assert_not_called()
        self.api.release.assert_awaited_once_with('ihe_token', 'r1')

    async def test_failed_release_is_logged(self) -> None:
        await self.hello()
        self.api.release.side_effect = api.Refused(404, 'not_found')
        with self.assertLogs('imbi.harness.executor', 'WARNING'):
            reply = await self.executor.dispatch(request())
        self.assertEqual(reply['exit_code'], 0)

    async def test_invalid_requests(self) -> None:
        await self.hello()
        file_delivery = {'mode': 'file', 'target': 'token'}
        path_delivery = {'mode': 'environment', 'target': 'PATH'}
        cases = {
            'invalid_cwd': [
                request(cwd='/etc'),
                request(cwd='/work'),
                request(cwd='/work/../etc'),
            ],
            'delivery_not_supported': [
                request(secrets=[{'handle': 'h', 'delivery': file_delivery}]),
                request(secrets=[{'handle': 'h', 'delivery': path_delivery}]),
                request(secrets=[{'handle': 'h'}]),
            ],
            'invalid_command': [request(command=''), request(command=None)],
            'unknown_op': [{'op': 'shell'}],
        }
        for error, requests in cases.items():
            for item in requests:
                with self.subTest(error=error, request=item):
                    reply = await self.executor.dispatch(item)
                    self.assertEqual(reply, {'error': error})
        self.api.materialize.assert_not_called()


class SocketTestCase(ExecutorTestCase):
    """``handle`` on a real unix socket; the peer uid is patched."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # A short path: the unix socket path limit is about 100 bytes.
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        self.path = f'{tmp.name}/s'
        self.peer = mock.patch.object(ipc, 'peer_uid', return_value=RUNNER_UID)
        self.peer.start()
        self.addCleanup(self.peer.stop)
        self.server = await asyncio.start_unix_server(
            self.executor.handle, path=self.path
        )
        self.addAsyncCleanup(self._close)

    async def _close(self) -> None:
        self.server.close()
        await self.server.wait_closed()

    async def test_reply_to_the_runner(self) -> None:
        await self.hello()
        reply = await ipc.call(request(), self.path)
        self.assertEqual(reply['exit_code'], 0)

    async def test_other_peer_gets_no_reply(self) -> None:
        self.peer.stop()
        with mock.patch.object(ipc, 'peer_uid', return_value=10003):
            with self.assertRaises(ConnectionError):
                await ipc.call(
                    {'op': 'hello', 'executor_token': 'x'}, self.path
                )
        self.peer.start()
        self.assertIsNone(self.executor.token)

    async def test_runner_gone_stops_the_work(self) -> None:
        await self.hello()
        started = asyncio.Event()

        async def forever(*_: typing.Any) -> tuple[int, bytes]:
            started.set()
            await asyncio.sleep(3600)
            raise AssertionError('not reached')

        self.spawn.side_effect = forever
        reader, writer = await asyncio.open_unix_connection(self.path)
        await ipc.write(writer, request())
        await started.wait()
        writer.close()
        for _ in range(100):
            if self.api.release.await_count:
                break
            await asyncio.sleep(0.01)
        self.api.release.assert_awaited_once_with('ihe_token', 'r1')
        self.assertIsNone(await ipc.read(reader))
