"""The relay of plugin MCP servers (ADR 0031).

A plugin MCP server whose header variables the agent maps to secrets
is removed from the CLI's copy of the plugin. The runner connects to
it instead, with the secrets in its memory only, and gives its tools to
the CLI as an in-process server named ``plugin:<plugin>:<server>``. The
CLI names them ``mcp__plugin_<plugin>_<server>__<tool>``, as it would
name the tools of the plugin's own server, so allow rules, the tool
policy, and the ``PreToolUse`` hook treat them as the plugin's tools.

Each server keeps one MCP session for the life of the task. When the
server drops it, the call that fails returns an error and is not sent
again, because the state of the old session is gone; the next call
opens a new session. Each call has the time limit and the stop of the
Imbi relay (:mod:`imbi.harness.safeguards`). The tool descriptions,
schemas and results reach the model as the server sent them, as they
would from a server that the CLI connects to, with each secret value
removed.
"""

import asyncio
import contextlib
import dataclasses
import datetime
import json
import logging
import re
import time
import typing

import anyio
import claude_agent_sdk as sdk
import httpx
from anyio.streams import memory
from mcp import types
from mcp.client import session as mcp_session
from mcp.client import sse, streamable_http
from mcp.shared import exceptions as mcp_exceptions
from mcp.shared import message

from imbi.harness import outbound, redact, safeguards

if typing.TYPE_CHECKING:
    from collections import abc

LOGGER = logging.getLogger(__name__)

#: The longest time to open a session and list the tools at start.
LIST_TIMEOUT = 30.0
#: The longest wait for a session to end.
CLOSE_TIMEOUT = 10.0
#: The server types that the relay can connect to.
TYPES = frozenset({'http', 'sse'})
_NOT_NAME = re.compile(r'[^A-Za-z0-9_-]')
_SESSION_TERMINATED = 32600
type Body = dict[str, typing.Any]
type _Write = memory.MemoryObjectSendStream[message.SessionMessage]


def cli_name(plugin: str, server: str) -> str:
    """``mcp__plugin_<plugin>_<server>``: the CLI's name of a plugin
    server in its tool names, with each character outside
    ``[A-Za-z0-9_-]`` as ``_``."""
    return _NOT_NAME.sub('_', f'mcp__plugin_{plugin}_{server}')


def problem(config: Body, origin: str | None) -> str | None:
    """Why the relay must not send the secrets to a server, if it must
    not: it is not an ``http`` or ``sse`` server, or its URL is not an
    HTTPS URL at ``origin``, the origin that the person saw when they
    picked the secrets."""
    kind = config.get('type')
    if not isinstance(kind, str) or kind not in TYPES:
        return 'it is not an http or sse server'
    try:
        url = outbound.check_url(str(config.get('url') or ''))
    except outbound.Refused:
        return 'its URL is not an https URL'
    try:
        pinned = outbound.check_url(str(origin or ''))
    except outbound.Refused:
        return (
            "the agent's entry has no https origin for its secrets. Pick "
            'the secrets again'
        )
    if outbound.origin(url) != outbound.origin(pinned):
        return (
            f'its URL is no longer at {origin}, the origin that its '
            'secrets were picked for. Pick the secrets again to confirm '
            'the new URL'
        )
    return None


def _lost(error: BaseException) -> bool:
    """Whether ``error`` means that the session no longer works: the
    transport failed, or the server ended the session. Any other error
    belongs to one call."""
    if isinstance(error, mcp_exceptions.McpError):
        return error.error.code in {
            types.CONNECTION_CLOSED,
            _SESSION_TERMINATED,
        }
    return isinstance(
        error,
        (
            Unavailable,
            *safeguards.ERRORS,
            anyio.ClosedResourceError,
            anyio.BrokenResourceError,
        ),
    )


def _block(block: types.ContentBlock, redactor: redact.Redactor) -> Body:
    """``block`` with each secret value removed. An image whose data
    held one is a text notice instead, since its redacted data is not
    an image."""
    dumped = block.model_dump(mode='json', exclude_none=True)
    scrubbed = _fields(dumped, redactor)
    if dumped['type'] == 'image' and scrubbed['data'] != dumped['data']:
        return _text('The image held a secret value and was removed.')
    return scrubbed


def _fields(fields: Body, redactor: redact.Redactor) -> Body:
    """``fields`` of a content block with each secret value removed
    from their values. The field names, the ``type``, and the fields
    of an embedded resource stay, so the SDK still reads the block."""
    return {
        name: value
        if name == 'type'
        else _fields(value, redactor)
        if name == 'resource' and fields.get('type') == 'resource'
        else redactor.payload(value)
        for name, value in fields.items()
    }


def _text(text: str) -> Body:
    return {'type': 'text', 'text': text}


def _schema(schema: Body) -> Body:
    """An input schema that the SDK reads as a JSON schema: it reads
    one without ``type`` and ``properties`` as a map of parameter
    types."""
    return {'type': 'object', 'properties': {}, **schema}


class Unavailable(Exception):
    """The relay could not open or keep a session. ``reason`` is
    safe."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclasses.dataclass(frozen=True)
class _Tool:
    name: str
    description: str
    schema: Body
    read_only: bool


class _Held:
    """An MCP session in a task of its own, so that any task can open
    and close it (an anyio task group must exit in the task that
    entered it)."""

    def __init__(
        self,
        opened: contextlib.AbstractAsyncContextManager[
            tuple[mcp_session.ClientSession, _Write]
        ],
    ) -> None:
        self.ready: asyncio.Future[
            tuple[mcp_session.ClientSession, _Write]
        ] = asyncio.get_running_loop().create_future()
        self.closing = asyncio.Event()
        self.task = asyncio.create_task(self._hold(opened))

    async def _hold(
        self,
        opened: contextlib.AbstractAsyncContextManager[
            tuple[mcp_session.ClientSession, _Write]
        ],
    ) -> None:
        try:
            async with opened as session:
                self.ready.set_result(session)
                await self.closing.wait()
        except Exception as error:  # noqa: BLE001 - ends the session
            if not self.ready.done():
                self.ready.set_exception(error)
            LOGGER.info('MCP session ended: %s', safeguards.reason(error))
        finally:
            self.ready.cancel()

    @property
    def session(self) -> mcp_session.ClientSession:
        return self.ready.result()[0]

    def alive(self) -> bool:
        """Whether the session can still send. The SSE client closes its
        write side after a failed request but keeps its event stream."""
        if self.task.done():
            return False
        if not self.ready.done():
            return True
        write = self.ready.result()[1]
        return write.statistics().open_send_streams > 0

    async def close(self) -> None:
        """Close the session; cancel it when the server does not answer
        the end of the session in :data:`CLOSE_TIMEOUT`."""
        self.closing.set()
        _, pending = await asyncio.wait({self.task}, timeout=CLOSE_TIMEOUT)
        for task in pending:
            task.cancel()


class Server:
    """Relays the tools of one plugin MCP server.

    Args:
        plugin: The plugin name that the CLI uses.
        name: The server name in the plugin.
        config: The server's definition in the pinned plugin, checked
            with :func:`problem`.
        auth: Fills the server's headers.
        proxy_env: The egress proxy environment of the CLI.
        redactor: Removes each secret value.
        stopped: Whether the task stopped.
        notice: Gives the task a warning.

    """

    def __init__(  # noqa: PLR0913 - keyword-only options
        self,
        plugin: str,
        name: str,
        config: Body,
        auth: httpx.Auth,
        *,
        proxy_env: abc.Mapping[str, str],
        redactor: redact.Redactor,
        stopped: abc.Callable[[], bool],
        notice: abc.Callable[[str], None],
    ) -> None:
        self.name = f'plugin:{plugin}:{name}'
        self.prefix = cli_name(plugin, name)
        self.url = str(config['url'])
        self.sse = config['type'] == 'sse'
        self.auth = auth
        self.proxy_env = proxy_env
        self.redactor = redactor
        self.stopped = stopped
        self.notice = notice
        self.tools: dict[str, _Tool] = {}
        self.audits = safeguards.Audits(f'{self.prefix}__')
        self.held: _Held | None = None
        self.retiring: set[asyncio.Task[None]] = set()
        self.lock = asyncio.Lock()
        self.dropped = False

    def _client(
        self,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        """An HTTP client to the server's origin only. It follows a
        redirect, but :class:`outbound.Transport` refuses another
        origin."""
        del headers, auth
        return httpx.AsyncClient(
            transport=outbound.Transport(self.url, self.proxy_env),
            auth=self.auth,
            follow_redirects=True,
            timeout=timeout
            or httpx.Timeout(safeguards.CALL_TIMEOUT + 10, connect=10),
        )

    @contextlib.asynccontextmanager
    async def _open(
        self,
    ) -> abc.AsyncGenerator[tuple[mcp_session.ClientSession, _Write]]:
        async with contextlib.AsyncExitStack() as stack:
            if self.sse:
                read, write = await stack.enter_async_context(
                    sse.sse_client(
                        self.url, timeout=10, httpx_client_factory=self._client
                    )
                )
            else:
                client = await stack.enter_async_context(self._client())
                read, write, _ = await stack.enter_async_context(
                    streamable_http.streamable_http_client(
                        self.url, http_client=client
                    )
                )
            session = await stack.enter_async_context(
                mcp_session.ClientSession(read, write)
            )
            await session.initialize()
            yield session, write

    async def _session(self) -> _Held:
        """The open session, or a new one when there is none or it no
        longer works.

        Raises:
            Unavailable: The session closed while it opened.

        """
        async with self.lock:
            if self.held is None or not self.held.alive():
                if self.held is not None:
                    self._retire(self.held)
                self.held = _Held(self._open())
            held = self.held
        try:
            await asyncio.shield(held.ready)
        except asyncio.CancelledError:
            if held.ready.cancelled():
                raise Unavailable('session_closed') from None
            raise
        return held

    def _retire(self, held: _Held) -> None:
        """Close a session that no longer works without making the call
        that replaces it wait; :meth:`close` waits for it."""
        closing = asyncio.create_task(held.close())
        self.retiring.add(closing)
        closing.add_done_callback(self.retiring.discard)

    async def _drop(self, held: _Held) -> None:
        """Close ``held``, and forget it when it is the current session.
        Another call can have opened a newer one."""
        async with self.lock:
            if self.held is held:
                self.held = None
        await held.close()

    async def start(self) -> list[str]:
        """Open the session and list the tools. Return their names.

        Raises:
            Unavailable: The session did not open, or the tools were not
                listed in time or were not valid.

        """
        try:
            async with asyncio.timeout(LIST_TIMEOUT):
                listed = await self._list((await self._session()).session)
        except Exception as error:
            await self.close()
            raise Unavailable(safeguards.reason(error)) from error
        for tool in listed:
            if not safeguards.TOOL_NAME.fullmatch(tool.name):
                continue
            hints = tool.annotations
            self.tools[tool.name] = _Tool(
                name=tool.name,
                description=self.redactor.text(tool.description or tool.name),
                schema=self.redactor.payload(_schema(tool.inputSchema)),
                read_only=bool(hints and hints.readOnlyHint),
            )
        return sorted(self.tools)

    @staticmethod
    async def _list(session: mcp_session.ClientSession) -> list[types.Tool]:
        tools: list[types.Tool] = []
        cursor: str | None = None
        while True:
            page = await session.list_tools(
                params=types.PaginatedRequestParams(cursor=cursor)
            )
            tools.extend(page.tools)
            if not (cursor := page.nextCursor):
                return tools

    async def close(self) -> None:
        """Close the session and each session that the relay
        replaced."""
        if self.held is not None:
            await self._drop(self.held)
        await asyncio.gather(*self.retiring)

    def writes(self) -> set[str]:
        """The CLI names of the tools that are not read only."""
        return {
            f'{self.prefix}__{tool.name}'
            for tool in self.tools.values()
            if not tool.read_only
        }

    def sdk_tools(self) -> list[sdk.SdkMcpTool[typing.Any]]:
        def make(tool: _Tool) -> sdk.SdkMcpTool[typing.Any]:
            hints = types.ToolAnnotations(readOnlyHint=True)

            @sdk.tool(
                tool.name,
                tool.description,
                tool.schema,
                annotations=hints if tool.read_only else None,
            )
            async def relayed(args: Body) -> Body:
                return await self.call(tool.name, args)

            return relayed

        return [make(tool) for tool in self.tools.values()]

    def take_audit(self, name: str, arguments: typing.Any) -> Body | None:
        return self.audits.take(name, arguments)

    async def call(self, name: str, args: Body) -> Body:
        """Relay one call; return the tool result for the model. Every
        failure is a scrubbed, audited error result."""
        started = time.monotonic()
        status = 'error'
        try:
            result = await safeguards.until_stopped(
                self._call(name, args), self.stopped
            )
        except Unavailable:
            content = [_text(f'The MCP server {self.name} is not available')]
        except TimeoutError:
            status, content = 'timeout', [_text('The MCP call timed out')]
        except safeguards.Stopped:
            status, content = 'stopped', [_text('The task stopped')]
        except Exception as error:  # noqa: BLE001 - the model gets an error
            LOGGER.warning(
                'MCP call to %s failed: %s', self.name, type(error).__name__
            )
            content = [
                _text(self.redactor.text(f'The MCP call failed: {error}'))
            ]
        else:
            status = 'error' if result.isError else 'ok'
            content = [
                _block(block, self.redactor) for block in result.content
            ]
        self.audits.add(
            name,
            args,
            {
                'server': self.name,
                'input_digest': safeguards.digest(args),
                'status': status,
                'latency_ms': int((time.monotonic() - started) * 1000),
                'bytes_in': len(json.dumps(args)),
                'bytes_out': len(json.dumps(content)),
            },
        )
        reply: Body = {'content': content}
        if status != 'ok':
            reply['is_error'] = True
        return reply

    async def _call(self, name: str, arguments: Body) -> types.CallToolResult:
        """One call in the open session. When the session no longer
        works, the call fails and the next call opens a new session.

        Raises:
            Unavailable: The session did not open, or it was lost.

        """
        held: _Held | None = None
        try:
            held = await self._session()
            return await held.session.call_tool(
                name,
                arguments,
                read_timeout_seconds=datetime.timedelta(
                    seconds=safeguards.CALL_TIMEOUT + 10
                ),
            )
        except Exception as error:
            if not _lost(error):
                raise
            await self._lose(held, safeguards.reason(error))
            raise Unavailable(safeguards.reason(error)) from error

    async def _lose(self, held: _Held | None, reason: str) -> None:
        """Warn once that a session was lost or did not open, and close
        the session of the call. A session that did not open is closed
        already."""
        LOGGER.warning('MCP session of %s failed: %s', self.name, reason)
        if not self.dropped:
            self.dropped = True
            self.notice(
                f'The relay lost the session of the MCP server {self.name}, '
                f'or could not open one ({reason}). The call failed, and '
                'the next call opens a new session.'
            )
        if held is not None:
            await self._drop(held)
