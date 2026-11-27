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
"""

import contextlib
import dataclasses
import json
import logging
import time
import typing
import uuid

import claude_agent_sdk as sdk
import httpx2
import jwt
from mcp import types
from mcp.client import session as mcp_session
from mcp.client import streamable_http

from imbi.harness import policy, safeguards

if typing.TYPE_CHECKING:
    from collections import abc

LOGGER = logging.getLogger(__name__)

#: The name of the relayed server for the CLI (``mcp__imbi_api__``).
SERVER = 'imbi_api'
#: The server part of the tool map key of a relayed tool.
KEY = 'imbi'
_IDEMPOTENCY_KEYS = ('Idempotency-Key', 'idempotency_key')

type Body = dict[str, typing.Any]


def mapped(tool_map: Body) -> set[str]:
    """The Imbi tools in a tool map: ``imbi.<tool>`` keys. They never
    include the harness's own tools."""
    return {
        name
        for name in (
            k.removeprefix(f'{KEY}.')
            for k in tool_map
            if k.startswith(f'{KEY}.')
        )
        if name not in policy.HARNESS_TOOLS
    }


class Bearer(httpx2.Auth):
    """The current token on each request: a renewed token applies at
    once."""

    def __init__(self, token: abc.Callable[[], str]) -> None:
        self.token = token

    def auth_flow(
        self, request: httpx2.Request
    ) -> abc.Generator[httpx2.Request, httpx2.Response]:
        request.headers['Authorization'] = f'Bearer {self.token()}'
        yield request


class Unavailable(Exception):
    """The relay could not reach ``apps/mcp``."""


@dataclasses.dataclass
class _Tool:
    name: str
    description: str
    schema: Body
    read_only: bool
    idempotency_key: str | None


class Relay:
    """Relays the agent's mapped tools of one MCP server."""

    def __init__(
        self,
        url: str,
        auth: httpx2.Auth | None,
        tool_map: Body,
        *,
        stopped: abc.Callable[[], bool] = lambda: False,
    ) -> None:
        self.url = url
        self.auth = auth
        self.mapped = mapped(tool_map)
        self.stopped = stopped
        self.tools: dict[str, _Tool] = {}
        self.audits = safeguards.Audits(f'mcp__{SERVER}__')

    @contextlib.asynccontextmanager
    async def _session(
        self,
    ) -> abc.AsyncGenerator[mcp_session.ClientSession]:
        # The SDK follows a redirect only on the same origin, so the
        # token goes to the configured origin only.
        async with (
            httpx2.AsyncClient(
                auth=self.auth,
                # Past the call deadline, so that the deadline decides.
                timeout=httpx2.Timeout(
                    safeguards.CALL_TIMEOUT + 10, connect=10
                ),
            ) as client,
            streamable_http.streamable_http_client(
                self.url, http_client=client
            ) as (read, write),
            mcp_session.ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session

    async def start(self) -> list[str]:
        """List the tools; keep the mapped ones. Return their names."""
        try:
            async with self._session() as session:
                listed = await session.list_tools()
        except safeguards.ERRORS as error:
            raise Unavailable(safeguards.reason(error)) from error
        for tool in listed.tools:
            if (
                tool.name not in self.mapped
                or not safeguards.TOOL_NAME.fullmatch(tool.name)
            ):
                continue
            properties: Body = tool.input_schema.get('properties') or {}
            annotations = tool.annotations
            description = tool.description or tool.name
            self.tools[tool.name] = _Tool(
                name=tool.name,
                description=description,
                schema=tool.input_schema,
                read_only=bool(annotations and annotations.read_only_hint),
                idempotency_key=next(
                    (k for k in _IDEMPOTENCY_KEYS if k in properties), None
                ),
            )
        return sorted(self.tools)

    def allowed_tools(self) -> list[str]:
        return [f'mcp__{SERVER}__{name}' for name in sorted(self.tools)]

    def writes(self) -> set[str]:
        """The CLI names of the tools that are not read only."""
        return {
            f'mcp__{SERVER}__{tool.name}'
            for tool in self.tools.values()
            if not tool.read_only
        }

    def sdk_tools(self) -> list[sdk.SdkMcpTool[typing.Any]]:
        def make(tool: _Tool) -> sdk.SdkMcpTool[typing.Any]:
            # The CLI runs tools with read_only_hint in parallel (#899).
            hints = types.ToolAnnotations(read_only_hint=True)

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
        if tool.idempotency_key is not None:
            arguments.setdefault(tool.idempotency_key, str(uuid.uuid4()))
        retries = 1 if tool.read_only or tool.idempotency_key else 0
        started = time.monotonic()
        status, result, jti = 'error', None, None
        try:
            for attempt in range(retries + 1):
                # The token of this attempt: a heartbeat can renew it
                # during the call.
                jti = self._jti()
                try:
                    result = await self._until_stopped(name, arguments)
                    status = 'error' if result.is_error else 'ok'
                    break
                except Unavailable:
                    if attempt == retries:
                        raise
        except Unavailable:
            text = f'The MCP server {SERVER} is not available'
        except TimeoutError:
            status, text = 'timeout', 'The Imbi call timed out'
        except safeguards.Stopped:
            status, text = 'stopped', 'The task stopped'
        else:
            text = safeguards.text(result)
        self.audits.add(
            name,
            args,
            {
                'server': SERVER,
                'input_digest': safeguards.digest(args),
                'token_jti': jti,
                'status': status,
                'latency_ms': int((time.monotonic() - started) * 1000),
                'bytes_in': len(json.dumps(arguments)),
                'bytes_out': len(text),
            },
        )
        return safeguards.reply(text, f'mcp:{SERVER}', ok=status == 'ok')

    async def _until_stopped(
        self, name: str, arguments: Body
    ) -> types.CallToolResult:
        """The call, unless the task stops first or the time is out."""
        return await safeguards.until_stopped(
            self._call(name, arguments), self.stopped
        )

    async def _call(self, name: str, arguments: Body) -> types.CallToolResult:
        try:
            async with self._session() as session:
                return await session.call_tool(
                    name,
                    arguments,
                    read_timeout_seconds=safeguards.CALL_TIMEOUT + 10,
                )
        except safeguards.ERRORS as error:
            raise Unavailable(safeguards.reason(error)) from error


def imbi(
    url: str,
    token: abc.Callable[[], str],
    tool_map: Body,
    *,
    stopped: abc.Callable[[], bool] = lambda: False,
) -> Relay:
    """The relay to ``apps/mcp``, with the agent API token."""
    return Relay(url, Bearer(token), tool_map, stopped=stopped)
