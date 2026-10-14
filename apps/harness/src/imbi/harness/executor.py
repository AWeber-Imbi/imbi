"""The executor process (plan sections 6.1 and 9.6).

The executor listens on the socket in ``/run/executor`` and accepts
only the ``runner`` user. It holds the executor credential, which can
only materialize and release the resolutions of its runner. For a
``run`` request it:

1. materializes each handle, immediately before it starts the command,
2. runs the command as ``agent``, with only the secrets and a fixed
   ``PATH`` in its environment,
3. filters the output (:mod:`imbi.harness.redact`), and
4. releases every resolution of the request, also when the runner goes
   away or the executor gets ``SIGTERM``.
"""

import asyncio
import base64
import contextlib
import logging
import os
import pathlib
import re
import secrets
import signal
import socket
import subprocess
import typing

import httpx

from imbi.harness import api, ipc, privilege, redact

LOGGER = logging.getLogger(__name__)

CREDENTIALS = '/run/creds'
WORK = pathlib.Path('/work')
PATH = '/usr/local/bin:/usr/bin:/bin'
COMMAND_TIMEOUT = 600
_ENV_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,127}$')

type Message = ipc.Message


class Invalid(ValueError):
    """The request is not valid. The message is a safe error code."""


def _workspace(cwd: typing.Any) -> str:
    path = pathlib.Path(str(cwd)).resolve()
    if path == WORK or WORK not in path.parents:
        raise Invalid('invalid_cwd')
    return str(path)


def _target(secret: Message) -> str:
    delivery: Message = secret.get('delivery') or {}
    target = str(delivery.get('target') or '')
    # Rev 1 delivers by environment only (gh with GH_TOKEN, H19).
    if delivery.get('mode') != 'environment' or not _ENV_NAME.match(target):
        raise Invalid('delivery_not_supported')
    if target == 'PATH':
        raise Invalid('delivery_not_supported')
    return target


def _material(body: Message) -> str:
    material = str(body['material'])
    if body.get('encoding') == 'base64':
        try:
            return base64.b64decode(material).decode()
        except UnicodeDecodeError:
            raise Invalid('binary_material_in_environment') from None
    return material


class Executor:
    def __init__(self, client: api.Api, credentials: pathlib.Path) -> None:
        self.api = client
        self.credential_file = credentials / 'executor.token'
        self.token: str | None = None
        if self.credential_file.exists():
            self.token = self.credential_file.read_text().strip()
        self.runner_uid = privilege.uid(privilege.RUNNER)
        self.requests: set[asyncio.Task[None]] = set()

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Serve one request of the runner."""
        task = typing.cast('asyncio.Task[None]', asyncio.current_task())
        self.requests.add(task)
        try:
            peer = ipc.peer_uid(writer.get_extra_info('socket'))
            if peer != self.runner_uid:
                LOGGER.warning('Refused a connection from uid %d', peer)
                return
            request = await ipc.read(reader)
            if request is None:
                return
            reply = await self._until_gone(reader, request)
            if reply is not None:
                await ipc.write(writer, reply)
        except (TypeError, ValueError, ConnectionError) as err:
            LOGGER.warning('Bad request: %s', type(err).__name__)
        finally:
            self.requests.discard(task)
            writer.close()

    async def _until_gone(
        self, reader: asyncio.StreamReader, request: Message
    ) -> Message | None:
        """Do the request. Stop it when the runner closes the socket."""
        work = asyncio.ensure_future(self.dispatch(request))
        gone = asyncio.ensure_future(reader.read())
        try:
            await asyncio.wait({work, gone}, return_when='FIRST_COMPLETED')
        finally:
            gone.cancel()
            if not work.done():
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
        return None if work.cancelled() else work.result()

    async def dispatch(self, request: Message) -> Message:
        try:
            match request.get('op'):
                case 'hello':
                    return self.hello(request)
                case 'run':
                    return await self.run(request)
                case _:
                    return {'error': 'unknown_op'}
        except Invalid as err:
            return {'error': str(err)}

    def hello(self, request: Message) -> Message:
        """Keep the executor credential that the runner registered."""
        token = str(request.get('executor_token') or '')
        if not token:
            raise Invalid('invalid_executor_credential')
        old = os.umask(0o077)
        try:
            self.credential_file.write_text(token)
        finally:
            os.umask(old)
        self.token = token
        return {'ok': True}

    async def run(self, request: Message) -> Message:
        if self.token is None:
            return {'error': 'no_executor_credential'}
        command = request.get('command')
        if not isinstance(command, str) or not command:
            raise Invalid('invalid_command')
        cwd = _workspace(request.get('cwd'))
        context: Message = request.get('context') or {}
        wanted = list(request.get('secrets') or [])
        targets = [_target(secret) for secret in wanted]
        try:
            env = {'PATH': PATH}
            for secret, target in zip(wanted, targets, strict=True):
                body = await self.api.materialize(
                    self.token,
                    {
                        'handle': secret.get('handle'),
                        'nonce': secrets.token_urlsafe(32),
                        'task_id': context.get('task_id'),
                        'agent_id': context.get('agent_id'),
                        'project_id': context.get('project_id'),
                        'purpose': secret.get('purpose'),
                    },
                )
                env[target] = _material(body)
            values = [env[target].encode() for target in targets]
            exit_code, output = await self._spawn(command, cwd, env)
        except api.Refused as err:
            return {'error': err.code}
        except httpx.HTTPError:
            return {'error': 'imbi_unavailable'}
        finally:
            await self._release(wanted)
        return {
            'exit_code': exit_code,
            'output': redact.redact(output, values),
        }

    async def _spawn(
        self, command: str, cwd: str, env: dict[str, str]
    ) -> tuple[int, bytes]:
        """Run the command as ``agent`` in its own process group."""
        with privilege.effective():
            process = subprocess.Popen(  # noqa: S603, ASYNC220
                ['/bin/sh', '-c', command],
                cwd=cwd,
                env=env,
                user=privilege.uid(privilege.AGENT),
                group=privilege.gid(privilege.AGENT),
                extra_groups=[],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        try:
            output, _ = await asyncio.to_thread(
                process.communicate, timeout=COMMAND_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            privilege.kill_agent(-process.pid)
            output, _ = await asyncio.to_thread(process.communicate)
        finally:
            if process.poll() is None:
                privilege.kill_agent(-process.pid)
        return process.returncode, output

    async def _release(self, wanted: list[Message]) -> None:
        for secret in wanted:
            resolution_id = secret.get('resolution_id')
            if not resolution_id or self.token is None:
                continue
            try:
                await self.api.release(self.token, resolution_id)
            except (api.Refused, httpx.HTTPError) as err:
                # The lease sweep of imbi-api releases it later.
                LOGGER.warning(
                    'Release of %s failed: %s',
                    resolution_id,
                    type(err).__name__,
                )


def _prepare() -> pathlib.Path:
    """As uid 0: set the socket directory and the credential directory.

    ``/run/executor`` becomes ``root:harness-ipc`` mode ``0750``. Root
    owns the ``emptyDir``, and it can give the directory a group that
    it is in without ``CAP_CHOWN``.
    """
    os.setgroups([privilege.ipc_gid()])
    os.chown(ipc.SOCKET_DIR, -1, privilege.ipc_gid())
    pathlib.Path(ipc.SOCKET_DIR).chmod(0o750)
    return privilege.make_private_dir(CREDENTIALS, privilege.EXECUTOR)


def _listen() -> socket.socket:
    """Bind the socket as uid 0: ``root:harness-ipc``, mode ``0660``."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    with privilege.effective():
        with contextlib.suppress(FileNotFoundError):
            pathlib.Path(ipc.SOCKET_PATH).unlink()
        sock.bind(ipc.SOCKET_PATH)
        os.chown(ipc.SOCKET_PATH, -1, privilege.ipc_gid())
        pathlib.Path(ipc.SOCKET_PATH).chmod(0o660)
    return sock


async def serve(executor: Executor) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    server = await asyncio.start_unix_server(
        executor.handle, sock=_listen(), limit=ipc.LIMIT
    )
    LOGGER.info('Listening on %s', ipc.SOCKET_PATH)
    async with server:
        await stop.wait()
        LOGGER.info('Stopping: ending %d requests', len(executor.requests))
        server.close()
        for task in list(executor.requests):
            task.cancel()
        await asyncio.gather(*executor.requests, return_exceptions=True)


def main() -> None:
    credentials = _prepare()
    privilege.drop(privilege.EXECUTOR)
    client = api.Api(os.environ['IMBI_API_URL'])
    asyncio.run(serve(Executor(client, credentials)))
