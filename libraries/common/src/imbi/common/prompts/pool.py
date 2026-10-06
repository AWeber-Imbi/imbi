"""A pool of worker processes that render prompt templates.

Each service process keeps a few warm workers (:mod:`.worker`). A render
takes one worker, sends it the templates and variables, answers its
provider calls, and returns the rendered text. The parent enforces the
wall clock: a worker that runs past the render timeout, crashes, breaks
the protocol, or sends too much output is killed with ``SIGKILL`` and
replaced, and the render raises :class:`.rendering.RenderError`.

Settings (environment):

- ``IMBI_PROMPT_WORKERS``: workers per service process (default 2).
- ``IMBI_PROMPT_WORKER_MAX_RENDERS``: renders before a worker is
  replaced (default 500).
- ``IMBI_PROMPT_WORKER_MEMORY_MB``: address space a worker may add
  after start, Linux only (default 256).
- ``IMBI_PROMPT_RENDER_INPROCESS``: ``true`` renders in the service
  process instead, for debugging only; it removes the isolation.
"""

import asyncio
import atexit
import collections.abc
import contextlib
import json
import logging
import os
import signal
import sys
import typing

from imbi.common import models
from imbi.common.prompts import rendering

LOGGER = logging.getLogger(__name__)

#: Seconds the parent waits beyond the worker's own render timeout.
#: The worker stops itself at ``RENDER_TIMEOUT`` when it can; this is
#: for a worker that cannot (a CPU-bound template never yields).
KILL_GRACE = 1.0

#: Seconds a new worker may take to start.
START_TIMEOUT = 30.0

#: Largest protocol line the parent reads from a worker, in bytes. The
#: rendered output is capped at ``MAX_OUTPUT`` characters; JSON escaping
#: can make that up to six times larger.
MAX_LINE = rendering.MAX_OUTPUT * 6 + 64 * 1024

#: Environment variables a worker inherits. Everything else, including
#: database settings and credentials, stays in the service.
_INHERITED_ENV = (
    'HOME',
    'LANG',
    'LC_ALL',
    'LC_CTYPE',
    'PATH',
    'PYTHONPATH',
    'SYSTEMROOT',
    'TMPDIR',
)

#: The worker command. Tests replace it to simulate a worker that hangs
#: or crashes; services never change it.
WORKER_COMMAND: tuple[str, ...] = (
    sys.executable,
    '-m',
    'imbi.common.prompts.worker',
)

#: Process ids of every live worker, so none outlives the service.
_PIDS: set[int] = set()


def in_process() -> bool:
    """Return whether the debugging escape hatch is on."""
    value = os.environ.get('IMBI_PROMPT_RENDER_INPROCESS', '')
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _int_setting(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


def _worker_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in _INHERITED_ENV if k in os.environ}
    for name in ('IMBI_PROMPT_WORKER_MEMORY_MB',):
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def _kill_all() -> None:
    for pid in list(_PIDS):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)
    _PIDS.clear()


atexit.register(_kill_all)


class _WorkerFailed(Exception):
    """The worker cannot be trusted any more; kill and replace it."""


class _Worker:
    """One worker process and its protocol streams."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process
        self.renders = 0
        self._next_id = 0
        if (
            process.stdin is None
            or process.stdout is None
            or process.stderr is None
        ):
            raise _WorkerFailed('worker has no pipes')
        self._stdin = process.stdin
        self._stdout = process.stdout
        self._stderr_task = asyncio.create_task(
            self._drain_stderr(process.stderr)
        )

    @classmethod
    async def start(cls) -> _Worker:
        process = await asyncio.create_subprocess_exec(
            *WORKER_COMMAND,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_worker_env(),
            cwd='/',
            limit=MAX_LINE,
        )
        _PIDS.add(process.pid)
        worker = cls(process)
        try:
            async with asyncio.timeout(START_TIMEOUT):
                ready = await worker._receive()
            if ready.get('type') != 'ready':
                raise _WorkerFailed('worker did not start')
        except BaseException:
            await worker.kill()
            raise
        return worker

    @property
    def pid(self) -> int:
        return self.process.pid

    async def _drain_stderr(self, stream: asyncio.StreamReader) -> None:
        with contextlib.suppress(Exception):
            while line := await stream.readline():
                LOGGER.warning(
                    'Prompt render worker %d: %s',
                    self.pid,
                    line.decode(errors='replace').rstrip(),
                )

    async def _receive(self) -> dict[str, typing.Any]:
        try:
            line = await self._stdout.readline()
        except (ValueError, asyncio.LimitOverrunError) as e:
            raise _WorkerFailed('worker output too large') from e
        if not line:
            raise _WorkerFailed('worker stopped')
        try:
            value = json.loads(line)
        except ValueError as e:
            raise _WorkerFailed('worker sent invalid data') from e
        if not isinstance(value, dict):
            raise _WorkerFailed('worker sent invalid data')
        return typing.cast('dict[str, typing.Any]', value)

    async def _send(self, message: dict[str, object]) -> None:
        try:
            self._stdin.write(json.dumps(message).encode() + b'\n')
            await self._stdin.drain()
        except (ConnectionError, RuntimeError) as e:
            raise _WorkerFailed('worker stopped') from e

    async def render(
        self,
        schema: collections.abc.Mapping[str, models.PromptVariable],
        variables: collections.abc.Mapping[str, object],
        providers: collections.abc.Mapping[str, rendering.Provider],
        sources: collections.abc.Mapping[str, str],
    ) -> dict[str, str]:
        self._next_id += 1
        self.renders += 1
        request_id = self._next_id
        await self._send(
            {
                'type': 'render',
                'id': request_id,
                'schema': {
                    name: spec.model_dump(mode='json')
                    for name, spec in schema.items()
                },
                'variables': dict(variables),
                'providers': sorted(providers),
                'sources': dict(sources),
            }
        )
        failures: dict[int, BaseException] = {}
        while True:
            message = await self._receive()
            if message.get('id') != request_id:
                raise _WorkerFailed('worker answered another request')
            kind = message.get('type')
            if kind == 'call':
                await self._answer_call(message, providers, failures)
            elif kind == 'result':
                return self._rendered(message, sources)
            elif kind == 'error':
                failed = failures.get(message.get('provider_call', -1))
                if failed is not None:
                    raise failed
                error = rendering.RenderError(
                    str(message.get('message', 'The render failed'))
                )
                if message.get('fatal'):
                    raise _WorkerFailed(str(error)) from error
                raise error
            else:
                raise _WorkerFailed('worker sent an unknown message')

    async def _answer_call(
        self,
        message: dict[str, typing.Any],
        providers: collections.abc.Mapping[str, rendering.Provider],
        failures: dict[int, BaseException],
    ) -> None:
        call_id = message.get('call_id')
        name = message.get('name')
        args = message.get('args')
        if (
            not isinstance(call_id, int)
            or not isinstance(name, str)
            or name not in providers
            or not isinstance(args, list)
        ):
            raise _WorkerFailed('worker made an invalid provider call')
        reply: dict[str, object] = {
            'type': 'call_result',
            'id': message['id'],
            'call_id': call_id,
            'ok': False,
        }
        try:
            value = await providers[name](*typing.cast('list[object]', args))
            size = rendering._measure(value)
            if size > rendering.MAX_OUTPUT:
                raise rendering.RenderError(
                    f'{name}() returned more than {rendering.MAX_OUTPUT} '
                    'characters'
                )
            json.dumps(value)
        except (TypeError, ValueError) as e:
            failures[call_id] = (
                e
                if isinstance(e, rendering.RenderError)
                else rendering.RenderError(f'{name}() returned bad data')
            )
        except Exception as e:  # noqa: BLE001 - re-raised to the caller
            failures[call_id] = e
        else:
            reply.update(ok=True, value=value)
        await self._send(reply)

    @staticmethod
    def _rendered(
        message: dict[str, typing.Any],
        sources: collections.abc.Mapping[str, str],
    ) -> dict[str, str]:
        rendered = message.get('rendered')
        if not isinstance(rendered, dict) or set(
            typing.cast('dict[str, object]', rendered)
        ) != set(sources):
            raise _WorkerFailed('worker sent an invalid result')
        result = typing.cast('dict[str, object]', rendered)
        if not all(isinstance(text, str) for text in result.values()):
            raise _WorkerFailed('worker sent an invalid result')
        total = sum(len(typing.cast('str', t)) for t in result.values())
        if total > rendering.MAX_OUTPUT:
            raise _WorkerFailed('worker sent too much output')
        return typing.cast('dict[str, str]', result)

    async def close(self) -> None:
        """Ask the worker to stop, and kill it if it does not."""
        with contextlib.suppress(Exception):
            self._stdin.close()
        try:
            async with asyncio.timeout(2.0):
                await self.process.wait()
        except TimeoutError:
            pass
        await self.kill()

    async def kill(self) -> None:
        if self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.process.kill()
            with contextlib.suppress(Exception):
                await self.process.wait()
        _PIDS.discard(self.pid)
        self._stderr_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._stderr_task

    def abandon(self) -> None:
        """Kill without the event loop, which may be closed."""
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(self.pid, signal.SIGKILL)
        _PIDS.discard(self.pid)


class RenderPool:
    """Warm render workers bound to one event loop."""

    def __init__(
        self,
        size: int | None = None,
        max_renders: int | None = None,
    ) -> None:
        self.size = size or _int_setting('IMBI_PROMPT_WORKERS', 2)
        self.max_renders = max_renders or _int_setting(
            'IMBI_PROMPT_WORKER_MAX_RENDERS', 500
        )
        self.loop = asyncio.get_running_loop()
        self._slots = asyncio.Semaphore(self.size)
        self._idle: list[_Worker] = []
        self._workers: set[_Worker] = set()
        self._closed = False

    async def start(self) -> None:
        """Start the workers now instead of on first use."""
        missing = self.size - len(self._workers)
        results = await asyncio.gather(
            *(_Worker.start() for _ in range(max(missing, 0))),
            return_exceptions=True,
        )
        failure: BaseException | None = None
        for result in results:
            if isinstance(result, _Worker):
                self._workers.add(result)
                self._idle.append(result)
            else:
                failure = result
        if failure is not None:
            raise failure

    async def render_sources(
        self,
        schema: collections.abc.Mapping[str, models.PromptVariable],
        variables: collections.abc.Mapping[str, object],
        providers: collections.abc.Mapping[str, rendering.Provider],
        sources: collections.abc.Mapping[str, str],
    ) -> dict[str, str]:
        """Render ``sources`` in a worker; see :func:`.rendering.render`.

        Raises:
            RenderError: The render failed, timed out, or the worker
                stopped.

        """
        if self._closed:
            raise rendering.RenderError('The render pool is closed')
        async with self._slots:
            worker = await self._take()
            healthy = False
            try:
                async with asyncio.timeout(
                    rendering.RENDER_TIMEOUT + KILL_GRACE
                ):
                    result = await worker.render(
                        schema, variables, providers, sources
                    )
                healthy = True
                return result
            except TimeoutError as e:
                raise rendering.RenderError(
                    f'Render took longer than {rendering.RENDER_TIMEOUT} '
                    'seconds'
                ) from e
            except _WorkerFailed as e:
                LOGGER.warning('Prompt render worker failed: %s', e)
                raise rendering.RenderError(
                    f'The render worker failed: {e}'
                ) from e
            except Exception:
                # A render error or a provider's own exception: the
                # worker finished the request and is still usable.
                healthy = True
                raise
            finally:
                await self._give_back(worker, healthy=healthy)

    async def _take(self) -> _Worker:
        while self._idle:
            worker = self._idle.pop()
            if worker.process.returncode is None:
                return worker
            await self._discard(worker)
        try:
            worker = await _Worker.start()
        except (_WorkerFailed, OSError, TimeoutError) as e:
            raise rendering.RenderError(
                'Could not start a render worker'
            ) from e
        self._workers.add(worker)
        return worker

    async def _give_back(self, worker: _Worker, *, healthy: bool) -> None:
        if (
            healthy
            and not self._closed
            and worker.renders < self.max_renders
            and worker.process.returncode is None
        ):
            self._idle.append(worker)
        elif healthy and worker.process.returncode is None:
            await self._discard(worker, graceful=True)
        else:
            await self._discard(worker)

    async def _discard(
        self, worker: _Worker, *, graceful: bool = False
    ) -> None:
        self._workers.discard(worker)
        if graceful:
            await worker.close()
        else:
            await worker.kill()

    async def close(self) -> None:
        """Stop every worker."""
        self._closed = True
        self._idle.clear()
        await asyncio.gather(
            *(worker.close() for worker in list(self._workers)),
            return_exceptions=True,
        )
        self._workers.clear()

    def abandon(self) -> None:
        """Kill every worker without the pool's event loop."""
        self._closed = True
        for worker in list(self._workers):
            worker.abandon()
        self._workers.clear()
        self._idle.clear()

    @property
    def pids(self) -> list[int]:
        return sorted(worker.pid for worker in self._workers)


_current: RenderPool | None = None


def get_pool() -> RenderPool:
    """Return the pool for the running event loop.

    Workers are tied to the loop that started them. A pool left by a
    loop that has ended (tests, ``TestClient`` portals) is killed and
    replaced.
    """
    global _current
    loop = asyncio.get_running_loop()
    if _current is not None and _current.loop is not loop:
        _current.abandon()
        _current = None
    if _current is None:
        _current = RenderPool()
    return _current


async def shutdown() -> None:
    """Stop the pool of the running loop, if there is one."""
    global _current
    pool, _current = _current, None
    if pool is None:
        return
    if pool.loop is asyncio.get_running_loop():
        await pool.close()
    else:
        pool.abandon()


@contextlib.asynccontextmanager
async def pool_lifespan() -> collections.abc.AsyncIterator[None]:
    """Start warm render workers with a service, and stop them after."""
    if not in_process():
        try:
            await get_pool().start()
        except Exception:  # rendering starts workers on demand instead
            LOGGER.exception('Could not start the prompt render workers')
    try:
        yield
    finally:
        await shutdown()
