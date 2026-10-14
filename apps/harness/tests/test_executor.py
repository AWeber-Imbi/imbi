"""The executor's request handling, without the privileged parts.

The process start as ``agent`` (``_spawn``) needs Linux and uid 0; the
kind suite in ``isolation/`` covers it.
"""

import asyncio
import base64
import json
import os
import pathlib
import stat
import tempfile
import threading
import time
import typing
import unittest
from unittest import mock

from imbi.harness import api, executor, ipc, privilege, redact

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


class BaseTestCase(unittest.IsolatedAsyncioTestCase):
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
            return_value=(0, f'token={SECRET}\n'.encode(), False)
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


class ExecutorTestCase(BaseTestCase):
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
        # The exact value goes to the runner's event redactor.
        self.assertEqual(
            reply,
            {
                'exit_code': 0,
                'output': 'token=[REDACTED]\n',
                'values': [SECRET],
            },
        )
        body = self.api.materialize.call_args.args[1]
        self.assertEqual(body['handle'], 'h')
        self.assertEqual(body['task_id'], 't')
        self.assertGreaterEqual(len(body['nonce']), 16)
        command, cwd, env, timeout = self.spawn.call_args.args
        self.assertEqual(command, 'gh pr list')
        self.assertEqual(cwd, '/work/chain')
        self.assertEqual(
            env,
            {
                'PATH': executor.PATH,
                'HOME': '/work/chain/home',
                'GH_TOKEN': SECRET,
            },
        )
        self.assertEqual(timeout, executor.COMMAND_TIMEOUT)
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

    async def test_timeout_is_capped(self) -> None:
        await self.hello()
        await self.executor.dispatch(request(timeout_seconds=3))
        self.assertEqual(self.spawn.call_args.args[3], 3)
        await self.executor.dispatch(request(timeout_seconds=10**6))
        self.assertEqual(
            self.spawn.call_args.args[3], executor.COMMAND_TIMEOUT
        )

    async def test_dropped_output_is_marked(self) -> None:
        await self.hello()
        self.spawn.return_value = (0, b'x' * (redact.OVERLAP + 10), True)
        reply = await self.executor.dispatch(request())
        self.assertEqual(reply['output'], 'x' * 10 + '\n[output truncated]')

    async def test_end_chain_kills_agent_processes(self) -> None:
        with mock.patch.object(privilege, 'kill_agent') as kill:
            reply = await self.executor.dispatch({'op': 'end_chain'})
        self.assertEqual(reply, {'ok': True})
        kill.assert_called_once_with()

    async def test_invalid_requests(self) -> None:
        await self.hello()
        file_delivery = {'mode': 'file', 'target': 'token'}
        path_delivery = {'mode': 'environment', 'target': 'PATH'}
        cases = {
            'invalid_cwd': [
                request(cwd='/etc'),
                request(cwd='/work'),
                request(cwd='/work/../etc'),
                request(cwd='/work/chain/../../etc'),
                request(cwd='work/chain'),
                request(cwd=None),
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

    async def test_setup_purposes_are_never_run(self) -> None:
        await self.hello()
        for purpose in sorted(executor.SETUP_PURPOSES):
            with self.subTest(purpose=purpose):
                self.api.release.reset_mock()
                secret = request()['secrets'][0] | {'purpose': purpose}
                reply = await self.executor.dispatch(request(secrets=[secret]))
                self.assertEqual(reply, {'error': 'purpose_not_allowed'})
                self.api.release.assert_awaited_once_with('ihe_token', 'r1')
        self.api.materialize.assert_not_called()
        self.spawn.assert_not_called()

    async def test_home_in_the_workspace(self) -> None:
        await self.hello()
        await self.executor.dispatch(request(home='/work/chain/tasks/t/home'))
        self.assertEqual(
            self.spawn.call_args.args[2]['HOME'], '/work/chain/tasks/t/home'
        )
        reply = await self.executor.dispatch(request(home='/etc'))
        self.assertEqual(reply, {'error': 'invalid_cwd'})

    async def test_no_secret_no_values(self) -> None:
        await self.hello()
        reply = await self.executor.dispatch(request(secrets=[]))
        self.assertEqual(
            reply, {'exit_code': 0, 'output': f'token={SECRET}\n'}
        )


def clone(**changes: typing.Any) -> dict[str, typing.Any]:
    return {
        'op': 'clone',
        'url': 'https://github.com/acme/app',
        'dest': '/work/chain/repos/app',
        'sha': None,
        'context': {'task_id': 't', 'agent_id': 'a', 'project_id': 'p'},
        'secret': {
            'handle': 'h',
            'resolution_id': 'r1',
            'purpose': 'workspace_checkout',
            'delivery': {'mode': 'file_descriptor', 'target': '3'},
        },
    } | changes


class CloneTestCase(BaseTestCase):
    async def test_token_goes_on_a_descriptor(self) -> None:
        await self.hello()
        seen: dict[str, typing.Any] = {}

        async def spawn(
            command: str,
            cwd: str,
            env: dict[str, str],
            limit: float,
            pass_fds: tuple[int, ...] = (),
        ) -> tuple[int, bytes, bool]:
            (fd,) = pass_fds
            seen.update(
                command=command,
                cwd=cwd,
                env=env,
                token=os.read(fd, 1024).decode(),
                fd=fd,
            )
            return 0, f'cloned {SECRET}'.encode(), False

        self.spawn.side_effect = spawn
        reply = await self.executor.dispatch(clone())
        self.assertEqual(
            reply,
            {
                'exit_code': 0,
                'output': 'cloned [REDACTED]',
                'values': [SECRET],
            },
        )
        self.assertEqual(seen['token'], SECRET)
        self.assertEqual(seen['cwd'], '/work/chain/repos')
        self.assertEqual(seen['env']['IMBI_GIT_TOKEN_FD'], str(seen['fd']))
        self.assertNotIn(SECRET, seen['command'])
        self.assertNotIn(SECRET, json.dumps(seen['env']))
        self.assertIn(
            'clone --quiet -- https://github.com/acme/app app', seen['command']
        )
        self.assertIn('credential.helper= ', seen['command'])
        self.assertIn('protocol.allow=never', seen['command'])
        body = self.api.materialize.call_args.args[1]
        self.assertEqual(body['purpose'], 'workspace_checkout')
        self.api.release.assert_awaited_once_with('ihe_token', 'r1')
        with self.assertRaises(OSError):
            os.fstat(seen['fd'])

    async def test_anonymous_at_a_commit(self) -> None:
        reply = await self.executor.dispatch(
            clone(secret=None, sha='0123456789abcdef', dest='/work/c/p/m-0123')
        )
        self.assertEqual(reply['exit_code'], 0)
        command, cwd, env, _ = self.spawn.call_args.args
        self.assertEqual(cwd, '/work/c/p')
        self.assertNotIn('IMBI_GIT_TOKEN_FD', env)
        self.assertEqual(self.spawn.call_args.kwargs['pass_fds'], ())
        self.assertIn('init --quiet -- m-0123 && cd -- m-0123', command)
        self.assertIn(
            'fetch --quiet --depth 1 -- https://github.com/acme/app '
            '0123456789abcdef',
            command,
        )
        self.api.materialize.assert_not_called()
        self.api.release.assert_not_called()

    async def test_secret_needs_the_credential(self) -> None:
        reply = await self.executor.dispatch(clone())
        self.assertEqual(reply, {'error': 'no_executor_credential'})

    async def test_refused_secret(self) -> None:
        await self.hello()
        self.api.materialize.side_effect = api.Refused(
            403, 'resolution_context_mismatch'
        )
        reply = await self.executor.dispatch(clone())
        self.assertEqual(reply, {'error': 'resolution_context_mismatch'})
        self.spawn.assert_not_called()
        self.api.release.assert_awaited_once()

    async def test_invalid_clones(self) -> None:
        await self.hello()
        cases = {
            'invalid_url': [
                clone(url='ext::sh -c touch% /tmp/x'),
                clone(url='file:///etc'),
                clone(url='ssh://git@github.com/acme/app'),
                clone(url='https://x-access-token:t@github.com/acme/app'),
                clone(url='https://github.com/acme/app --upload-pack=x'),
                clone(url=None),
            ],
            'invalid_cwd': [
                clone(dest='/etc/app'),
                clone(dest='/work/app'),
                clone(dest='/work/c/../../etc/app'),
            ],
            'purpose_not_allowed': [
                clone(secret=clone()['secret'] | {'purpose': 'github_write'}),
                clone(
                    secret=clone()['secret'] | {'purpose': 'model_inference'}
                ),
            ],
            'invalid_clone': [
                clone(dest='/work/chain/repos/-rf'),
                clone(sha='HEAD; rm -rf /'),
                clone(sha='--upload-pack=x'),
            ],
        }
        for error, requests in cases.items():
            for item in requests:
                with self.subTest(error=error, request=item):
                    reply = await self.executor.dispatch(item)
                    self.assertEqual(reply, {'error': error})
        self.spawn.assert_not_called()
        self.api.materialize.assert_not_called()


class FetchTestCase(BaseTestCase):
    def fetch(self, purpose: str = 'model_inference') -> dict[str, typing.Any]:
        return {
            'op': 'fetch',
            'context': {'task_id': 't', 'agent_id': 'a', 'project_id': None},
            'secret': {
                'handle': 'h',
                'resolution_id': 'r1',
                'purpose': purpose,
                'delivery': {'mode': 'file_descriptor', 'target': '3'},
            },
        }

    async def test_returns_the_model_key_and_releases(self) -> None:
        await self.hello()
        reply = await self.executor.dispatch(self.fetch())
        self.assertEqual(reply, {'material': SECRET})
        self.api.release.assert_awaited_once_with('ihe_token', 'r1')
        self.spawn.assert_not_called()

    async def test_only_the_model_key(self) -> None:
        await self.hello()
        reply = await self.executor.dispatch(self.fetch('github_write'))
        self.assertEqual(reply, {'error': 'purpose_not_allowed'})
        self.api.materialize.assert_not_called()

    async def test_without_credential(self) -> None:
        reply = await self.executor.dispatch(self.fetch())
        self.assertEqual(reply, {'error': 'no_executor_credential'})

    async def test_refused(self) -> None:
        await self.hello()
        self.api.materialize.side_effect = api.Refused(
            410, 'resolution_expired'
        )
        reply = await self.executor.dispatch(self.fetch())
        self.assertEqual(reply, {'error': 'resolution_expired'})
        self.api.release.assert_awaited_once()


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

    async def test_other_peer_cannot_fetch_the_model_key(self) -> None:
        await self.hello()
        self.peer.stop()
        try:
            for uid in (10002, 10003):
                with (
                    self.subTest(uid=uid),
                    mock.patch.object(ipc, 'peer_uid', return_value=uid),
                    self.assertRaises(ConnectionError),
                ):
                    await ipc.call(
                        {
                            'op': 'fetch',
                            'context': {},
                            'secret': {
                                'handle': 'h',
                                'resolution_id': 'r1',
                                'purpose': 'model_inference',
                            },
                        },
                        self.path,
                    )
        finally:
            self.peer.start()
        self.api.materialize.assert_not_called()

    async def test_runner_gone_stops_the_work(self) -> None:
        await self.hello()
        started = asyncio.Event()

        async def forever(*_: typing.Any) -> tuple[int, bytes, bool]:
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


class CollectTestCase(unittest.TestCase):
    """The bounded pipe read of ``_spawn``."""

    def pipe(self) -> tuple[int, int]:
        read, write = os.pipe()
        self.addCleanup(os.close, read)
        return read, write

    def test_keeps_at_most_the_limit(self) -> None:
        read, write = self.pipe()

        def produce() -> None:
            with os.fdopen(write, 'wb') as out:
                for _ in range(160):  # 10 MiB
                    out.write(b'x' * 65536)

        writer = threading.Thread(target=produce)
        writer.start()
        kept, dropped, ended = executor._collect(
            read, time.monotonic() + 30, 1000, threading.Event()
        )
        writer.join()
        self.assertEqual(len(kept), 1000)
        self.assertTrue(dropped)
        self.assertTrue(ended)

    def test_returns_at_the_deadline_while_the_pipe_is_open(self) -> None:
        read, write = self.pipe()
        self.addCleanup(os.close, write)
        os.write(write, b'started\n')
        started = time.monotonic()
        kept, dropped, ended = executor._collect(
            read, started + 0.5, 1000, threading.Event()
        )
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(kept, b'started\n')
        self.assertFalse(dropped)
        self.assertFalse(ended)

    def test_stop(self) -> None:
        read, write = self.pipe()
        self.addCleanup(os.close, write)
        stop = threading.Event()
        stop.set()
        self.assertEqual(
            executor._collect(read, time.monotonic() + 30, 10, stop),
            (b'', False, False),
        )
