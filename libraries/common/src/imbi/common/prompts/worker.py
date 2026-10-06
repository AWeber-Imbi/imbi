"""Render prompt templates in a separate, disposable process.

Run as ``python -m imbi.common.prompts.worker``. The parent
(:mod:`.pool`) sends one JSON object per line on stdin and reads one
JSON object per line from stdout. The worker renders one request at a
time with the in-process sandbox (:func:`.rendering.render_sources_local`).

A template that calls a provider, such as ``project(42)``, does not run
the provider here: the worker asks the parent with a ``call`` message
and waits for the ``call_result``. The worker never has database access
or credentials; its environment is built by the parent.

Messages, each with the request ``id``:

- parent to worker: ``render`` (``schema``, ``variables``,
  ``providers``, ``sources``) and ``call_result`` (``call_id``, ``ok``,
  ``value``).
- worker to parent: ``ready`` (once, at start), ``call`` (``call_id``,
  ``name``, ``args``), ``result`` (``rendered``), and ``error``
  (``message``, and ``provider_call`` when a provider failed).

At start the worker limits its own address space
(``IMBI_PROMPT_WORKER_MEMORY_MB`` above the size it has after its
imports; Linux only) and its CPU time, so a template that escapes the
sandbox budgets ends this process, not the service.
"""

import asyncio
import json
import os
import resource
import sys
import traceback
import typing

from imbi.common import models
from imbi.common.prompts import rendering

#: Default address space, in MiB, allowed above the size after imports.
DEFAULT_MEMORY_MB = 256

#: CPU seconds one worker may use in total. A backstop only: the parent
#: kills a worker whose render runs past the render timeout.
CPU_LIMIT_SECONDS = 300


class _ProviderFailed(Exception):
    """The parent reported that a provider call failed."""

    def __init__(self, call_id: int) -> None:
        super().__init__(call_id)
        self.call_id = call_id


def _limit_resources() -> None:
    try:
        resource.setrlimit(
            resource.RLIMIT_CPU, (CPU_LIMIT_SECONDS, CPU_LIMIT_SECONDS)
        )
    except ValueError, OSError:
        pass
    # macOS does not enforce RLIMIT_AS; there the parent's wall-clock
    # kill is the only limit.
    if not sys.platform.startswith('linux'):
        return
    headroom = int(
        os.environ.get('IMBI_PROMPT_WORKER_MEMORY_MB', DEFAULT_MEMORY_MB)
    )
    with open('/proc/self/statm') as handle:
        pages = int(handle.read().split()[0])
    current = pages * os.sysconf('SC_PAGE_SIZE')
    limit = current + headroom * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


class _Channel:
    """Line-delimited JSON over the protocol file descriptors."""

    def __init__(self, reader: asyncio.StreamReader, out: typing.BinaryIO):
        self._reader = reader
        self._out = out

    async def receive(self) -> dict[str, typing.Any] | None:
        line = await self._reader.readline()
        if not line:
            return None
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError('protocol message is not an object')
        return typing.cast('dict[str, typing.Any]', value)

    def send(self, message: dict[str, object]) -> None:
        self._out.write(json.dumps(message).encode() + b'\n')
        self._out.flush()


async def _render(
    channel: _Channel, message: dict[str, typing.Any]
) -> dict[str, object]:
    request_id = message['id']
    call_ids = iter(range(1, 1_000_000))

    def provider(name: str) -> rendering.Provider:
        async def call(*args: object) -> object:
            call_id = next(call_ids)
            channel.send(
                {
                    'type': 'call',
                    'id': request_id,
                    'call_id': call_id,
                    'name': name,
                    'args': list(args),
                }
            )
            reply = await channel.receive()
            if (
                reply is None
                or reply.get('type') != 'call_result'
                or reply.get('call_id') != call_id
            ):
                raise _ProviderFailed(call_id)
            if not reply.get('ok'):
                raise _ProviderFailed(call_id)
            return reply.get('value')

        return call

    schema = {
        name: models.PromptVariable.model_validate(spec)
        for name, spec in message['schema'].items()
    }
    providers = {name: provider(name) for name in message['providers']}
    try:
        rendered = await rendering.render_sources_local(
            schema, message['variables'], providers, message['sources']
        )
    except _ProviderFailed as e:
        return {
            'type': 'error',
            'id': request_id,
            'message': 'A provider call failed',
            'provider_call': e.call_id,
        }
    except rendering.RenderError as e:
        return {'type': 'error', 'id': request_id, 'message': str(e)}
    return {'type': 'result', 'id': request_id, 'rendered': rendered}


async def _serve(channel: _Channel) -> None:
    channel.send({'type': 'ready', 'pid': os.getpid()})
    while True:
        message = await channel.receive()
        if message is None:
            return
        if message.get('type') != 'render':
            raise ValueError(f'unexpected message {message.get("type")!r}')
        try:
            reply = await _render(channel, message)
        except MemoryError:
            # The state of this process is not trusted after this; say
            # why and stop, and the parent starts a fresh worker.
            channel.send(
                {
                    'type': 'error',
                    'id': message.get('id'),
                    'message': 'The render used more memory than allowed',
                    'fatal': True,
                }
            )
            return
        except Exception:  # noqa: BLE001 - reported; the worker goes on
            traceback.print_exc(file=sys.stderr)
            reply = {
                'type': 'error',
                'id': message.get('id'),
                'message': 'The render failed',
            }
        channel.send(reply)


async def _main() -> None:
    # Keep the protocol on a private copy of stdout, and send anything
    # else written to fd 1 to stderr, so a stray print cannot corrupt
    # the protocol.
    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    out = os.fdopen(protocol_fd, 'wb', buffering=0)
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=64 * 1024 * 1024)
    await loop.connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer
    )
    _limit_resources()
    await _serve(_Channel(reader, typing.cast('typing.BinaryIO', out)))


if __name__ == '__main__':
    asyncio.run(_main())
