"""The safeguards of text and MCP tool calls from outside Imbi (plan
P7 and section 6.7), shared by the Imbi relay and the plugin relay.

Each relayed call has a time limit and ends when the task stops. A
result of the Imbi relay also has a size limit and goes to the model
inside ``<untrusted>`` tags (:func:`reply`).
"""

import asyncio
import collections
import hashlib
import json
import re
import time
import typing

import httpx
from mcp import types
from mcp.shared import exceptions as mcp_exceptions

if typing.TYPE_CHECKING:
    from collections import abc

CALL_TIMEOUT = 120.0
#: The most result text, in characters, that the model gets from the
#: Imbi relay.
RESULT_LIMIT = 256 * 1024
#: The CLI's limit on an MCP tool name.
TOOL_NAME = re.compile(r'[A-Za-z0-9_-]{1,64}')
#: The errors of an MCP client session whose server is not reached or
#: dropped the session.
ERRORS = (httpx.HTTPError, OSError, ExceptionGroup, mcp_exceptions.McpError)
_UNTRUSTED_TAG = re.compile(r'<\s*/?\s*untrusted', re.IGNORECASE)

type Body = dict[str, typing.Any]


class Stopped(Exception):
    """The task stopped during the call."""


def escape(text: str) -> str:
    """``text`` with each untrusted tag, in any case and spacing,
    escaped, so it can neither close an untrusted block nor open a
    nested one."""
    return _UNTRUSTED_TAG.sub(lambda match: '&lt;' + match.group(0)[1:], text)


def untrusted(text: str, source: str) -> str:
    """Wrap text from outside Imbi's people in an untrusted block
    (plan section 6.7), with :func:`escape`."""
    return f'<untrusted source="{source}">\n{escape(text)}\n</untrusted>'


def digest(arguments: typing.Any) -> str:
    canonical = json.dumps(arguments, sort_keys=True, separators=(',', ':'))
    return 'sha256:' + hashlib.sha256(canonical.encode()).hexdigest()


def reason(error: BaseException) -> str:
    """A safe reason: an outbound check's code, or the error type. An
    error group (from the MCP client's task group) gives its first
    error."""
    inner: tuple[BaseException, ...] = getattr(error, 'exceptions', ())
    if inner:
        return reason(inner[0])
    code: object = getattr(error, 'reason', None)
    return code if isinstance(code, str) else type(error).__name__


def text(result: types.CallToolResult | None) -> str:
    if result is None:
        return ''
    parts: list[str] = []
    for block in result.content:
        if isinstance(block, types.TextContent):
            parts.append(block.text)
        else:
            parts.append(json.dumps(block.model_dump(mode='json')))
    if not parts and result.structuredContent is not None:
        parts.append(json.dumps(result.structuredContent))
    return '\n'.join(parts)


def reply(value: str, source: str, *, ok: bool) -> Body:
    """The tool result for the model: ``value`` cut to
    :data:`RESULT_LIMIT`, in an untrusted block."""
    if len(value) > RESULT_LIMIT:
        value = value[:RESULT_LIMIT] + '\n[result truncated]'
    result: Body = {
        'content': [{'type': 'text', 'text': untrusted(value, source)}]
    }
    if not ok:
        result['is_error'] = True
    return result


async def until_stopped[T](
    call: abc.Awaitable[T], stopped: abc.Callable[[], bool]
) -> T:
    """``call``, unless the task stops first or :data:`CALL_TIMEOUT`
    passes.

    Raises:
        Stopped: The task stopped.
        TimeoutError: The time is out.

    """
    task = asyncio.ensure_future(call)
    deadline = time.monotonic() + CALL_TIMEOUT
    try:
        while not task.done():
            if stopped():
                raise Stopped
            if time.monotonic() >= deadline:
                raise TimeoutError
            await asyncio.wait({task}, timeout=1)
        return task.result()
    finally:
        if not task.done():
            task.cancel()


class Audits:
    """The audit fields of the relayed calls of one server, for their
    ``tool.called`` events (plan P7): one per call, in call order.

    Args:
        prefix: The CLI name of the server's tools, ``mcp__<server>__``.

    """

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.queues: dict[tuple[str, str], collections.deque[Body]] = (
            collections.defaultdict(collections.deque)
        )

    def add(self, tool: str, arguments: typing.Any, fields: Body) -> None:
        self.queues[(tool, digest(arguments))].append(fields)

    def take(self, name: str, arguments: typing.Any) -> Body | None:
        """The audit fields of the oldest call of the CLI tool ``name``
        with ``arguments``, if it is a tool of this server."""
        if not name.startswith(self.prefix):
            return None
        queue = self.queues.get(
            (name.removeprefix(self.prefix), digest(arguments))
        )
        return queue.popleft() if queue else None
