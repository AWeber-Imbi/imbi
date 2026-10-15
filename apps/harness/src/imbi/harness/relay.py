"""The Imbi relay (harness plan P7, H27).

The runner is the MCP client of ``apps/mcp``; the model gets the
relayed tools as an in-process MCP server, ``imbi_api``. So:

- The agent API token stays in the runner's memory: only the runner's
  HTTP client sends it, never the CLI, a child process, or a log.
- The model gets only the tools that ``apps/mcp`` lists for the token
  *and* that the agent's tool map has as ``imbi.<tool>`` (the key
  of the agent tool catalog, ``agent_tools.IMBI_SERVER_SLUG``). A new
  Imbi tool is off until an admin maps it. The API still checks the
  service account's permission on every call (H28).
- The tool policy hook sees each call as ``mcp__imbi_api__<tool>``,
  keyed ``imbi.<tool>``: approvals, rate limits, environments. The CLI
  name differs from the key because the harness's own in-process
  server is ``imbi``.
- Each call has a time limit, ends when the task stops, and has a size
  limit. Its result goes to the model inside ``<untrusted>`` tags.
- A read is tried again once after a connection error. A write is
  tried again only when the tool takes an idempotency key, with the
  same key.

Each call opens its own MCP session, so a renewed token (each runner
heartbeat) applies at once, a restart of ``apps/mcp`` costs one call,
and nothing stays open when the runner fences and exits.

A third-party MCP server of the agent uses the same relay, with its
own CLI name (:func:`server_name`), its credential from the secrets
broker, and the outbound checks of :mod:`imbi.harness.outbound`. Its
tool descriptions are untrusted too.
"""

import asyncio
import collections
import contextlib
import dataclasses
import datetime
import hashlib
import json
import logging
import re
import time
import typing
import uuid

import claude_agent_sdk as sdk
import httpx
import jwt
from mcp import types
from mcp.client import session as mcp_session
from mcp.client import streamable_http
from mcp.shared import exceptions as mcp_exceptions

from imbi.harness import policy

if typing.TYPE_CHECKING:
    from collections import abc

LOGGER = logging.getLogger(__name__)

#: The name of the relayed server for the CLI (``mcp__imbi_api__``).
SERVER = 'imbi_api'
#: The server part of the tool map key of a relayed tool.
KEY = 'imbi'
CALL_TIMEOUT = 120.0
#: The CLI's limit on an MCP tool name.
_TOOL_NAME = re.compile(r'[A-Za-z0-9_-]{1,64}')
_NOT_NAME = re.compile(r'[^a-z0-9_-]+')
#: The most result text, in characters, that the model gets.
RESULT_LIMIT = 256 * 1024
_IDEMPOTENCY_KEYS = ('Idempotency-Key', 'idempotency_key')
_UNTRUSTED_TAG = re.compile(r'<\s*/?\s*untrusted', re.IGNORECASE)

type Body = dict[str, typing.Any]


def untrusted(text: str, source: str) -> str:
    """Wrap text from outside Imbi's people in an untrusted block
    (plan section 6.7). A tag in the text, in any case and spacing,
    is escaped, so the text can neither close the block nor open a
    nested one."""
    text = _UNTRUSTED_TAG.sub(lambda m: '&lt;' + m.group(0)[1:], text)
    return f'<untrusted source="{source}">\n{text}\n</untrusted>'


def mapped(tool_map: Body, key: str = KEY) -> set[str]:
    """The tools of one server in a tool map: ``<key>.<tool>`` keys.
    The Imbi tools never include the harness's own tools."""
    return {
        name
        for name in (
            k.removeprefix(f'{key}.')
            for k in tool_map
            if k.startswith(f'{key}.')
        )
        if key != KEY or name not in policy.HARNESS_TOOLS
    }


def server_name(slug: str) -> str:
    """The CLI name of a third-party server: the slug in lower case,
    with each run of other characters as one ``_``. Never ``__``, which
    divides the server and the tool in a CLI tool name."""
    return re.sub('_{2,}', '_', _NOT_NAME.sub('_', slug.lower())).strip('_')


def digest(arguments: typing.Any) -> str:
    canonical = json.dumps(arguments, sort_keys=True, separators=(',', ':'))
    return 'sha256:' + hashlib.sha256(canonical.encode()).hexdigest()


class Bearer(httpx.Auth):
    """The current token on each request: a renewed token applies at
    once."""

    def __init__(self, token: abc.Callable[[], str]) -> None:
        self.token = token

    def auth_flow(
        self, request: httpx.Request
    ) -> abc.Generator[httpx.Request, httpx.Response]:
        request.headers['Authorization'] = f'Bearer {self.token()}'
        yield request


class Unavailable(Exception):
    """The relay could not reach ``apps/mcp``."""


class Stopped(Exception):
    """The task stopped during the call."""


@dataclasses.dataclass
class _Tool:
    name: str
    description: str
    schema: Body
    read_only: bool
    idempotency_key: str | None


class Relay:
    """Relays the agent's mapped tools of one MCP server."""

    def __init__(  # noqa: PLR0913 - keyword-only options
        self,
        url: str,
        auth: httpx.Auth | None,
        tool_map: Body,
        *,
        server: str = SERVER,
        key: str = KEY,
        ignored: abc.Iterable[str] = (),
        transport: httpx.AsyncBaseTransport | None = None,
        stopped: abc.Callable[[], bool] = lambda: False,
    ) -> None:
        self.url = url
        self.auth = auth
        self.server = server
        self.key = key
        self.mapped = mapped(tool_map, key) - set(ignored)
        self.transport = transport
        self.stopped = stopped
        self.tools: dict[str, _Tool] = {}
        self.audits: dict[tuple[str, str], collections.deque[Body]] = (
            collections.defaultdict(collections.deque)
        )

    @contextlib.asynccontextmanager
    async def _session(
        self,
    ) -> abc.AsyncGenerator[mcp_session.ClientSession]:
        # No redirects: the token goes to the configured origin only.
        async with (
            httpx.AsyncClient(
                auth=self.auth,
                transport=self.transport,
                follow_redirects=False,
                # Past the call deadline, so that the deadline decides.
                timeout=httpx.Timeout(CALL_TIMEOUT + 10, connect=10),
            ) as client,
            streamable_http.streamable_http_client(
                self.url, http_client=client
            ) as (read, write, _),
            mcp_session.ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session

    async def start(self) -> list[str]:
        """List the tools; keep the mapped ones. Return their names."""
        try:
            async with self._session() as session:
                listed = await session.list_tools()
        except (
            httpx.HTTPError,
            OSError,
            ExceptionGroup,
            mcp_exceptions.McpError,
        ) as err:
            raise Unavailable(_reason(err)) from err
        for tool in listed.tools:
            if tool.name not in self.mapped or not _TOOL_NAME.fullmatch(
                tool.name
            ):
                continue
            properties: Body = tool.inputSchema.get('properties') or {}
            annotations = tool.annotations
            description = tool.description or tool.name
            if self.server != SERVER:
                description = untrusted(description, f'mcp:{self.server}')
            self.tools[tool.name] = _Tool(
                name=tool.name,
                description=description,
                schema=tool.inputSchema,
                read_only=bool(annotations and annotations.readOnlyHint),
                idempotency_key=next(
                    (k for k in _IDEMPOTENCY_KEYS if k in properties), None
                ),
            )
        return sorted(self.tools)

    def allowed_tools(self) -> list[str]:
        return [f'mcp__{self.server}__{name}' for name in sorted(self.tools)]

    def sdk_tools(self) -> list[sdk.SdkMcpTool[typing.Any]]:
        def make(tool: _Tool) -> sdk.SdkMcpTool[typing.Any]:
            @sdk.tool(tool.name, tool.description, tool.schema)
            async def relayed(args: Body) -> Body:
                return await self.call(tool.name, args)

            return relayed

        return [make(tool) for tool in self.tools.values()]

    def take_audit(self, name: str, arguments: typing.Any) -> Body | None:
        """The audit fields of a relayed call, for its tool.called
        event (plan P7): one per call, in call order."""
        prefix = f'mcp__{self.server}__'
        if not name.startswith(prefix):
            return None
        queue = self.audits.get((name.removeprefix(prefix), digest(arguments)))
        return queue.popleft() if queue else None

    def _jti(self) -> str | None:
        """The ``jti`` of the agent API token; ``None`` for another
        server."""
        if not isinstance(self.auth, Bearer):
            return None
        try:
            claims = jwt.decode(
                self.auth.token(), options={'verify_signature': False}
            )
        except jwt.InvalidTokenError:
            return None
        return str(claims.get('jti') or '') or None

    async def call(self, name: str, args: Body) -> Body:
        """Relay one call; return the tool result for the model."""
        tool = self.tools[name]
        arguments = dict(args)
        input_digest = digest(args)
        if tool.idempotency_key is not None:
            arguments.setdefault(tool.idempotency_key, str(uuid.uuid4()))
        retries = 1 if tool.read_only or tool.idempotency_key else 0
        started = time.monotonic()
        status, result = 'error', None
        try:
            for attempt in range(retries + 1):
                try:
                    result = await self._until_stopped(name, arguments)
                    status = 'error' if result.isError else 'ok'
                    break
                except Unavailable:
                    if attempt == retries:
                        raise
        except Unavailable:
            text = f'The MCP server {self.server} is not available'
        except TimeoutError:
            status, text = 'timeout', 'The Imbi call timed out'
        except Stopped:
            status, text = 'stopped', 'The task stopped'
        else:
            text = _text(result)
        size = len(text)
        if size > RESULT_LIMIT:
            text = text[:RESULT_LIMIT] + '\n[result truncated]'
        self.audits[(name, input_digest)].append(
            {
                'server': self.server,
                'input_digest': input_digest,
                'token_jti': self._jti(),
                'status': status,
                'latency_ms': int((time.monotonic() - started) * 1000),
                'bytes_in': len(json.dumps(arguments)),
                'bytes_out': size,
            }
        )
        reply: Body = {
            'content': [
                {
                    'type': 'text',
                    'text': untrusted(text, f'mcp:{self.server}'),
                }
            ]
        }
        if status != 'ok':
            reply['is_error'] = True
        return reply

    async def _until_stopped(
        self, name: str, arguments: Body
    ) -> types.CallToolResult:
        """The call, unless the task stops first or the time is out."""

        async def call() -> types.CallToolResult:
            try:
                async with self._session() as session:
                    return await session.call_tool(
                        name,
                        arguments,
                        read_timeout_seconds=datetime.timedelta(
                            seconds=CALL_TIMEOUT + 10
                        ),
                    )
            except (
                httpx.HTTPError,
                OSError,
                ExceptionGroup,
                mcp_exceptions.McpError,
            ) as err:
                raise Unavailable(_reason(err)) from err

        task = asyncio.ensure_future(call())
        deadline = time.monotonic() + CALL_TIMEOUT
        try:
            while not task.done():
                if self.stopped():
                    raise Stopped
                if time.monotonic() >= deadline:
                    raise TimeoutError
                await asyncio.wait({task}, timeout=1)
            return task.result()
        finally:
            if not task.done():
                task.cancel()


def imbi(
    url: str,
    token: abc.Callable[[], str],
    tool_map: Body,
    *,
    stopped: abc.Callable[[], bool] = lambda: False,
) -> Relay:
    """The relay to ``apps/mcp``, with the agent API token."""
    return Relay(url, Bearer(token), tool_map, stopped=stopped)


def _reason(err: BaseException) -> str:
    """A safe reason: an outbound check's code, or the error type. An
    error group (from the MCP client's task group) gives its first
    error."""
    inner: tuple[BaseException, ...] = getattr(err, 'exceptions', ())
    if inner:
        return _reason(inner[0])
    reason: object = getattr(err, 'reason', None)
    return reason if isinstance(reason, str) else type(err).__name__


def _text(result: types.CallToolResult | None) -> str:
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
