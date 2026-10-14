"""The executor process (plan sections 6.1 and 9.6).

The executor listens on the socket in ``/run/executor`` and accepts
only the ``runner`` user. It holds the executor credential, which can
only materialize and release the resolutions of its runner. For a
``run`` request it:

1. materializes each handle, immediately before it starts the command,
2. runs the command as ``agent``, with only the secrets, ``HOME``,
   and a fixed ``PATH`` in its environment, and changes to the
   workspace only after the switch to ``agent``,
3. reads at most a bounded amount of output, and kills every ``agent``
   process when the command ends or times out,
4. filters the output (:mod:`imbi.harness.redact`), and
5. releases every resolution of the request, also when the runner goes
   away or the executor gets ``SIGTERM``.

The reply holds the exact values that the command got, for the
runner's event redactor (plan section 9.6 step 4). The runner holds
handles and its own credentials already; ``agent`` cannot read it.

Two more requests are for the runner's own setup secrets (H22):

- ``clone`` clones a repository or a marketplace commit as ``agent``.
  The token goes to git's credential helper through a file descriptor,
  so ``.git/config``, the command line, and the environment never hold
  it (plan section 6.2).
- ``fetch`` returns the material of a ``model_inference`` resolution to
  the runner, for its model proxy (plan section 6.4).

Rev 1 runs one request at a time (:attr:`Executor.lock`), so every
``agent`` process of this container belongs to the current command.
"""

import asyncio
import base64
import contextlib
import logging
import os
import pathlib
import re
import secrets
import select
import shlex
import signal
import socket
import subprocess
import threading
import time
import typing
import urllib.parse

import httpx

from imbi.harness import api, ipc, privilege, redact

LOGGER = logging.getLogger(__name__)

CREDENTIALS = '/run/creds'
PATH = '/usr/local/bin:/usr/bin:/bin'
COMMAND_TIMEOUT = 600
#: The time to read what is left in the pipe after the kill.
DRAIN_SECONDS = 5.0
#: The most output that is kept. The redaction overlap lets a value
#: that the cut splits be removed (:func:`redact.redact`).
OUTPUT_LIMIT = redact.MAX_OUTPUT + redact.OVERLAP
#: Runs as ``agent``: change to the workspace, then check that the real
#: path is in /work. A change before the switch to ``agent`` would let
#: ``agent`` swap the directory for a symlink while the child is still
#: privileged.
_SHIM = (
    'cd -P -- "$1" || exit 126\n'
    'case "$(pwd -P)" in\n'
    '  /work/?*) ;;\n'
    '  *) echo "The workspace is not in /work" >&2; exit 126 ;;\n'
    'esac\n'
    'unset OLDPWD\n'
    'exec /bin/sh -c "$2"\n'
)
_ENV_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,127}$')
_NAME = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$')
_SHA = re.compile(r'^[0-9a-f]{7,64}$')
#: Reads the token from ``IMBI_GIT_TOKEN_FD`` (``apps/harness/
#: git-credential-fd``). The empty value first removes other helpers.
#: Only http and https transports: no ``ext::``, ``file://``, or ssh.
_GIT = (
    'git -c credential.helper= '
    '-c credential.helper=/usr/local/libexec/git-credential-fd '
    '-c protocol.allow=never -c protocol.http.allow=always '
    '-c protocol.https.allow=always'
)
#: Setup secrets that the executor returns to the runner (H22).
FETCH_PURPOSES = frozenset({'model_inference'})
#: Setup secrets that git gets on a descriptor (H22).
CLONE_PURPOSES = frozenset({'marketplace_fetch', 'workspace_checkout'})
#: The runner's own secrets. ``run`` never delivers them: a command
#: that the model chose must not get the model key or a setup token.
SETUP_PURPOSES = FETCH_PURPOSES | CLONE_PURPOSES

type Message = ipc.Message


class Invalid(ValueError):
    """The request is not valid. The message is a safe error code."""


def _workspace(cwd: typing.Any) -> str:
    """A path under /work, checked as text only.

    The real check is the ``cd -P`` of :data:`_SHIM`, as ``agent``.
    """
    path = str(cwd or '')
    parts = pathlib.PurePosixPath(path).parts
    if len(parts) < 3 or parts[:2] != ('/', 'work') or '..' in parts:  # noqa: PLR2004
        raise Invalid('invalid_cwd')
    return path


def _collect(
    fd: int, deadline: float, limit: int, stop: threading.Event
) -> tuple[bytes, bool, bool]:
    """Read ``fd`` until the end, the deadline, or ``stop``.

    Keep at most ``limit`` bytes and read the rest to nothing. Return
    the kept bytes, whether bytes were dropped, and whether the end of
    the stream came.
    """
    kept = bytearray()
    dropped = False
    while not stop.is_set() and (left := deadline - time.monotonic()) > 0:
        ready, _, _ = select.select([fd], [], [], min(left, 0.2))
        if not ready:
            continue
        chunk = os.read(fd, 65536)
        if not chunk:
            return bytes(kept), dropped, True
        room = max(limit - len(kept), 0)
        dropped = dropped or len(chunk) > room
        kept += chunk[:room]
    return bytes(kept), dropped, False


async def _read(
    fd: int, deadline: float, limit: int
) -> tuple[bytes, bool, bool]:
    """:func:`_collect` in a thread. On cancel, stop the thread first,
    so that the caller can close ``fd`` safely."""
    stop = threading.Event()
    future = asyncio.ensure_future(
        asyncio.to_thread(_collect, fd, deadline, limit, stop)
    )
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        stop.set()
        await future
        raise


def _git_url(value: typing.Any) -> str:
    """An http or https URL with no user part: the token never goes in
    the URL."""
    url = str(value or '')
    parts = urllib.parse.urlsplit(url)
    if (
        parts.scheme not in {'http', 'https'}
        or not parts.hostname
        or '@' in parts.netloc
        or any(char.isspace() for char in url)
    ):
        raise Invalid('invalid_url')
    return url


def _clone_command(url: str, name: str, sha: str | None) -> str:
    """Clone ``url`` into ``name``; at ``sha`` with only that commit."""
    url, name = shlex.quote(url), shlex.quote(name)
    if sha is None:
        return f'{_GIT} clone --quiet -- {url} {name}'
    return (
        f'{_GIT} init --quiet -- {name} && cd -- {name} && '
        f'{_GIT} fetch --quiet --depth 1 -- {url} {sha} && '
        'git checkout --quiet --detach FETCH_HEAD'
    )


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


def _reply(
    exit_code: int, output: bytes, dropped: bool, values: list[str]
) -> Message:
    reply: Message = {
        'exit_code': exit_code,
        'output': redact.redact(
            output, [value.encode() for value in values], truncated=dropped
        ),
    }
    if values:
        reply['values'] = values
    return reply


class Executor:
    def __init__(self, client: api.Api, credentials: pathlib.Path) -> None:
        self.api = client
        self.credential_file = credentials / 'executor.token'
        self.token: str | None = None
        if self.credential_file.exists():
            self.token = self.credential_file.read_text().strip()
        self.runner_uid = privilege.uid(privilege.RUNNER)
        self.requests: set[asyncio.Task[None]] = set()
        #: One command at a time: the kill of every ``agent`` process
        #: after a command must not hit another command.
        self.lock = asyncio.Lock()

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

    async def dispatch(self, request: Message) -> Message:  # noqa: PLR0911
        try:
            match request.get('op'):
                case 'hello':
                    return self.hello(request)
                case 'run':
                    async with self.lock:
                        return await self.run(request)
                case 'clone':
                    async with self.lock:
                        return await self.clone(request)
                case 'fetch':
                    return await self.fetch(request)
                case 'end_chain':
                    async with self.lock:
                        privilege.kill_agent()
                    return {'ok': True}
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
        home = _workspace(request.get('home') or f'{cwd}/home')
        timeout = min(
            float(request.get('timeout_seconds') or COMMAND_TIMEOUT),
            COMMAND_TIMEOUT,
        )
        context: Message = request.get('context') or {}
        wanted = list(request.get('secrets') or [])
        targets = [_target(secret) for secret in wanted]
        try:
            # In the try, so that the resolution is released. imbi-api
            # materializes a handle only for the purpose that the
            # resolution has, so this checks the real purpose.
            if any(s.get('purpose') in SETUP_PURPOSES for s in wanted):
                raise Invalid('purpose_not_allowed')
            env = {'PATH': PATH, 'HOME': home}
            for secret, target in zip(wanted, targets, strict=True):
                env[target] = await self._materialize(secret, context)
            values = [env[target] for target in targets]
            exit_code, output, dropped = await self._spawn(
                command, cwd, env, timeout
            )
        except api.Refused as err:
            return {'error': err.code}
        except httpx.HTTPError:
            return {'error': 'imbi_unavailable'}
        finally:
            await self._release(wanted)
        return _reply(exit_code, output, dropped, values)

    async def clone(self, request: Message) -> Message:
        """Clone ``url`` into ``dest`` as ``agent``, with the token of
        ``secret`` (optional) on a file descriptor."""
        url = _git_url(request.get('url'))
        dest = _workspace(request.get('dest'))
        parent, _, name = dest.rpartition('/')
        _workspace(parent)
        sha = request.get('sha')
        if not _NAME.match(name) or (
            sha is not None and not _SHA.match(str(sha))
        ):
            raise Invalid('invalid_clone')
        secret: Message | None = request.get('secret')
        if secret is not None and secret.get('purpose') not in CLONE_PURPOSES:
            raise Invalid('purpose_not_allowed')
        if secret is not None and self.token is None:
            return {'error': 'no_executor_credential'}
        env = {
            'PATH': PATH,
            'HOME': '/nonexistent',
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_TERMINAL_PROMPT': '0',
        }
        values: list[str] = []
        read = -1
        try:
            if secret is not None:
                token = await self._materialize(
                    secret, request.get('context') or {}
                )
                values.append(token)
                read, write = os.pipe()
                # A pipe holds 64 KiB, so the write does not block.
                with os.fdopen(write, 'w') as out:
                    out.write(token)
                env['IMBI_GIT_TOKEN_FD'] = str(read)
            exit_code, output, dropped = await self._spawn(
                _clone_command(url, name, sha),
                parent,
                env,
                COMMAND_TIMEOUT,
                pass_fds=(read,) if read >= 0 else (),
            )
        except api.Refused as err:
            return {'error': err.code}
        except httpx.HTTPError:
            return {'error': 'imbi_unavailable'}
        finally:
            if read >= 0:
                os.close(read)
            await self._release([] if secret is None else [secret])
        return _reply(exit_code, output, dropped, values)

    async def fetch(self, request: Message) -> Message:
        """Return the material of a setup secret to the runner."""
        if self.token is None:
            return {'error': 'no_executor_credential'}
        secret: Message = request.get('secret') or {}
        if secret.get('purpose') not in FETCH_PURPOSES:
            raise Invalid('purpose_not_allowed')
        try:
            material = await self._materialize(
                secret, request.get('context') or {}
            )
        except api.Refused as err:
            return {'error': err.code}
        except httpx.HTTPError:
            return {'error': 'imbi_unavailable'}
        finally:
            # A static key: the release ends only Imbi access.
            await self._release([secret])
        return {'material': material}

    async def _materialize(self, secret: Message, context: Message) -> str:
        assert self.token is not None  # noqa: S101 - checked by callers
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
        return _material(body)

    async def _spawn(
        self,
        command: str,
        cwd: str,
        env: dict[str, str],
        limit: float,
        pass_fds: tuple[int, ...] = (),
    ) -> tuple[int, bytes, bool]:
        """Run the command as ``agent`` in its own session.

        ``limit`` is the time limit in seconds. Return the exit status,
        the kept output, and whether output was dropped. At the limit,
        kill every ``agent`` process (a child that left the session can
        hold the pipe open), then read what is left for at most
        :data:`DRAIN_SECONDS`.
        """
        with privilege.effective():
            # No cwd=: the shim changes the directory as agent.
            process = subprocess.Popen(  # noqa: S603, ASYNC220
                ['/bin/sh', '-c', _SHIM, 'run_with_secret', cwd, command],
                env=env,
                user=privilege.uid(privilege.AGENT),
                group=privilege.gid(privilege.AGENT),
                extra_groups=[],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                pass_fds=pass_fds,
            )
        assert process.stdout is not None  # noqa: S101 - stdout=PIPE
        fd = process.stdout.fileno()
        try:
            output, dropped, ended = await _read(
                fd, time.monotonic() + limit, OUTPUT_LIMIT
            )
            if not ended:
                LOGGER.warning('The command timed out after %.0fs', limit)
                privilege.kill_agent()
                more, lost, _ = await _read(
                    fd,
                    time.monotonic() + DRAIN_SECONDS,
                    OUTPUT_LIMIT - len(output),
                )
                output += more
                dropped = dropped or lost
        finally:
            # Also the children that closed the pipe and stayed: they
            # hold the secret in their environment.
            privilege.kill_agent()
            process.stdout.close()
            with contextlib.suppress(subprocess.TimeoutExpired):
                await asyncio.to_thread(process.wait, DRAIN_SECONDS)
        code = process.returncode
        return (-9 if code is None else code), output, dropped

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
