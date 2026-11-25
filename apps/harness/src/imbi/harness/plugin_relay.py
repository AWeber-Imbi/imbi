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
opens a new session. Each call has the safeguards of the Imbi relay
(:mod:`imbi.harness.safeguards`); a result has each secret value
removed, and a result and a tool description reach the model as
untrusted text.
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

import claude_agent_sdk as sdk
import httpx
from mcp import types
from mcp.client import session as mcp_session
from mcp.client import sse, streamable_http

from imbi.harness import outbound, safeguards

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

type Body = dict[str, typing.Any]


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
    if config.get('type') not in TYPES:
        return 'it is not an http or sse server'
    try:
        url = outbound.check_url(str(config.get('url') or ''))
        pinned = outbound.check_url(str(origin or ''))
    except outbound.Refused:
        return 'its URL or the origin of its secrets is not an https URL'
    if outbound.origin(url) != outbound.origin(pinned):
        return (
            f'its URL is no longer at {origin}, the origin that its '
            'secrets were picked for. Pick the secrets again to confirm '
            'the new URL'
        )
    return None


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
            mcp_session.ClientSession
        ],
    ) -> None:
        self.ready: asyncio.Future[mcp_session.ClientSession] = (
            asyncio.get_running_loop().create_future()
        )
        self.closing = asyncio.Event()
        self.task = asyncio.create_task(self._hold(opened))

    async def _hold(
        self,
        opened: contextlib.AbstractAsyncContextManager[
            mcp_session.ClientSession
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

    def alive(self) -> bool:
        return not self.task.done()

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
        scrub: Removes each secret value from a text.
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
        scrub: abc.Callable[[str], str],
        stopped: abc.Callable[[], bool],
        notice: abc.Callable[[str], None],
    ) -> None:
        self.name = f'plugin:{plugin}:{name}'
        self.prefix = cli_name(plugin, name)
        self.url = str(config['url'])
        self.sse = config['type'] == 'sse'
        self.auth = auth
        self.proxy_env = proxy_env
        self.scrub = scrub
        self.stopped = stopped
        self.notice = notice
        self.tools: dict[str, _Tool] = {}
        self.audits = safeguards.Audits(f'{self.prefix}__')
        self.held: _Held | None = None
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
    async def _open(self) -> abc.AsyncGenerator[mcp_session.ClientSession]:
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
            yield session

    async def _session(self) -> _Held:
        """The open session, or a new one when there is none.

        Raises:
            Unavailable: The session closed while it opened.

        """
        async with self.lock:
            if self.held is None or not self.held.alive():
                self.held = _Held(self._open())
            held = self.held
        try:
            await asyncio.shield(held.ready)
        except asyncio.CancelledError:
            if held.ready.cancelled():
                raise Unavailable('session_closed') from None
            raise
        return held

    async def _drop(self, held: _Held | None) -> None:
        async with self.lock:
            if self.held is held:
                self.held = None
        if held is not None:
            await held.close()

    async def start(self) -> list[str]:
        """Open the session and list the tools. Return their names.

        Raises:
            Unavailable: The session did not open, or the tools were not
                listed in time.

        """
        try:
            async with asyncio.timeout(LIST_TIMEOUT):
                listed = await self._list(
                    (await self._session()).ready.result()
                )
        except (TimeoutError, Unavailable, *safeguards.ERRORS) as error:
            await self._drop(self.held)
            raise Unavailable(safeguards.reason(error)) from error
        for tool in listed:
            if not safeguards.TOOL_NAME.fullmatch(tool.name):
                continue
            hints = tool.annotations
            self.tools[tool.name] = _Tool(
                name=tool.name,
                description=safeguards.untrusted(
                    tool.description or tool.name, f'mcp:{self.name}'
                ),
                schema=tool.inputSchema,
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
        await self._drop(self.held)

    def writes(self) -> set[str]:
        """The CLI names of the tools that are not read only."""
        return {
            f'{self.prefix}__{tool.name}'
            for tool in self.tools.values()
            if not tool.read_only
        }

    def sdk_tools(self) -> list[sdk.SdkMcpTool[typing.Any]]:
        def make(tool: _Tool) -> sdk.SdkMcpTool[typing.Any]:
            # The CLI runs tools with readOnlyHint in parallel (#899).
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
        """Relay one call; return the tool result for the model."""
        started = time.monotonic()
        try:
            result = await safeguards.until_stopped(
                self._call(name, args), self.stopped
            )
        except Unavailable:
            status = 'error'
            text = f'The MCP server {self.name} is not available'
        except TimeoutError:
            status, text = 'timeout', 'The MCP call timed out'
        except safeguards.Stopped:
            status, text = 'stopped', 'The task stopped'
        else:
            status = 'error' if result.isError else 'ok'
            text = self.scrub(safeguards.text(result))
        self.audits.add(
            name,
            args,
            {
                'server': self.name,
                'input_digest': safeguards.digest(args),
                'status': status,
                'latency_ms': int((time.monotonic() - started) * 1000),
                'bytes_in': len(json.dumps(args)),
                'bytes_out': len(text),
            },
        )
        return safeguards.reply(text, f'mcp:{self.name}', ok=status == 'ok')

    async def _call(self, name: str, arguments: Body) -> types.CallToolResult:
        """One call in the open session. A failure closes the session,
        and the next call opens a new one.

        Raises:
            Unavailable: The session did not open, or the call failed.

        """
        held: _Held | None = None
        try:
            held = await self._session()
            return await held.ready.result().call_tool(
                name,
                arguments,
                read_timeout_seconds=datetime.timedelta(
                    seconds=safeguards.CALL_TIMEOUT + 10
                ),
            )
        except (Unavailable, *safeguards.ERRORS) as error:
            reason = safeguards.reason(error)
            LOGGER.warning('MCP session of %s failed: %s', self.name, reason)
            if not self.dropped:
                self.dropped = True
                self.notice(
                    f'The relay lost the session of the MCP server '
                    f'{self.name}, or could not open one ({reason}). The '
                    'call failed, and the next call opens a new session.'
                )
            await self._drop(held or self.held)
            raise Unavailable(reason) from error
