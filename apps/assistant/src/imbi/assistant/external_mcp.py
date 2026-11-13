"""Connect to external MCP servers over streamable HTTP.

Reads :class:`~imbi.common.models.MCPServer` nodes from the graph,
opens a streamable-HTTP MCP session per enabled server, discovers
their tools, and exposes them in Anthropic tool format for the
assistant's Claude integration.

This is additive to :mod:`imbi.assistant.mcp` (which builds tools
from the Imbi OpenAPI spec); the two managers run side by side.

"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import typing

import httpx
import mcp
from mcp import types as mcp_types
from mcp.client import streamable_http
from mcp.shared._httpx_utils import create_mcp_http_client

from imbi.assistant import age_ops
from imbi.common.auth.encryption import decrypt_config_value

if typing.TYPE_CHECKING:
    import collections.abc

    from imbi.common import graph
    from imbi.common import models as common_models

LOGGER = logging.getLogger(__name__)

_VALID_TOOL_NAME_RE = re.compile(r'^[a-zA-Z0-9_-]{1,128}$')

_MAX_TOOL_NAME_LEN = 128

_OAUTH_EXPIRY_BUFFER = 60.0

_OAUTH_TOKEN_TIMEOUT = 10.0

# ponytail: fixed delay between reconnect attempts to a server that is
# down; make it exponential if a fixed delay is too slow or too noisy.
_RECONNECT_DELAY = 60.0


class OAuthClientCredentialsAuth(httpx.Auth):
    """httpx Auth that fetches and caches OAuth client-credentials tokens.

    Transparently refreshes the access token shortly before it
    expires so requests do not fail at the last second.

    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str | None = None,
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    def _is_expired(self) -> bool:
        return (
            self._access_token is None
            or time.monotonic() >= self._expires_at - _OAUTH_EXPIRY_BUFFER
        )

    async def _fetch_token(self) -> None:
        data: dict[str, str] = {
            'grant_type': 'client_credentials',
            'client_id': self._client_id,
            'client_secret': self._client_secret,
        }
        if self._scope:
            data['scope'] = self._scope
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_OAUTH_TOKEN_TIMEOUT)
        ) as client:
            response = await client.post(self._token_url, data=data)
            response.raise_for_status()
            body = response.json()
        self._access_token = body['access_token']
        expires_in = int(body.get('expires_in', 3600))
        self._expires_at = time.monotonic() + expires_in
        LOGGER.debug(
            'Fetched OAuth token for client %s (expires in %ds)',
            self._client_id,
            expires_in,
        )

    async def async_auth_flow(
        self,
        request: httpx.Request,
    ) -> collections.abc.AsyncGenerator[httpx.Request, httpx.Response]:
        async with self._lock:
            if self._is_expired():
                await self._fetch_token()
        request.headers['Authorization'] = f'Bearer {self._access_token}'
        yield request


def _build_auth(
    server: common_models.MCPServer,
) -> tuple[dict[str, str] | None, httpx.Auth | None]:
    """Build the headers and httpx auth for a server.

    Decrypts any ``*_encrypted`` secrets at connect time.

    Returns:
        Tuple of (static headers or None, httpx.Auth or None).

    """
    if server.auth_type == 'static':
        value = decrypt_config_value(server.static_value_encrypted)
        if server.static_header and value is not None:
            return {server.static_header: value}, None
        LOGGER.warning(
            'Static auth for MCP server %r is missing a header or value',
            server.slug,
        )
        return None, None
    if server.auth_type == 'oauth_client_credentials':
        secret = decrypt_config_value(server.oauth_client_secret_encrypted)
        if (
            server.oauth_token_url
            and server.oauth_client_id
            and secret is not None
        ):
            return None, OAuthClientCredentialsAuth(
                token_url=str(server.oauth_token_url),
                client_id=server.oauth_client_id,
                client_secret=secret,
                scope=server.oauth_scope,
            )
        LOGGER.warning(
            'OAuth auth for MCP server %r is missing configuration',
            server.slug,
        )
        return None, None
    return None, None


def _tool_prefix(server: common_models.MCPServer) -> str:
    """Resolve the namespace prefix for a server's tools."""
    return server.tool_prefix or server.slug


def _mcp_tool_to_anthropic(
    tool: mcp_types.Tool,
    registered_name: str,
) -> dict[str, typing.Any]:
    """Convert an MCP Tool to Anthropic tool format."""
    return {
        'name': registered_name,
        'description': tool.description or '',
        'input_schema': tool.inputSchema or {},
    }


class ExternalMCPManager:
    """Manages streamable-HTTP connections to external MCP servers
    and exposes their tools to the assistant.

    """

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task[None]] = []
        self._sessions: dict[str, mcp.ClientSession] = {}
        self._tools: list[dict[str, typing.Any]] = []
        # registered tool name -> (server slug, original tool name)
        self._tool_routes: dict[str, tuple[str, str]] = {}
        # server slug -> config, kept to reopen a failed session
        self._servers: dict[str, common_models.MCPServer] = {}
        # server slug -> monotonic time before which no reconnect runs
        self._reconnect_after: dict[str, float] = {}
        self._reconnect_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self, db: graph.Graph) -> None:
        """Connect to every enabled MCP server and discover tools.

        Per-server connect failures are logged and skipped so a single
        bad server cannot prevent startup.

        Args:
            db: Open graph connection used to read MCPServer nodes.

        """
        servers = await age_ops.get_enabled_mcp_servers(db)
        for server in servers:
            await self._connect_server(server)
        self._initialized = True
        LOGGER.info(
            'External MCP initialization complete: %d servers, %d tools',
            len(self._sessions),
            len(self._tools),
        )

    async def _connect_server(
        self,
        server: common_models.MCPServer,
    ) -> None:
        """Connect to a single server and register its tools."""
        LOGGER.info(
            'Connecting to external MCP server %r at %s',
            server.slug,
            server.url,
        )
        try:
            session = await asyncio.wait_for(
                self._open_session(server),
                timeout=float(server.timeout),
            )
            result = await session.list_tools()
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            LOGGER.error(
                'Failed to connect to MCP server %r: %s',
                server.slug,
                err,
            )
            return
        if self._sessions.get(server.slug) is not session:
            LOGGER.warning(
                'MCP server %r session closed during tool discovery',
                server.slug,
            )
            return
        self._servers[server.slug] = server
        prefix = _tool_prefix(server)
        for tool in result.tools:
            self._register_tool(server, tool, prefix)

    async def _open_session(
        self,
        server: common_models.MCPServer,
    ) -> mcp.ClientSession:
        """Open and initialize a streamable-HTTP session."""
        headers, http_auth = _build_auth(server)
        timeout = httpx.Timeout(float(server.timeout))
        if server.verify_ssl:
            http_client = create_mcp_http_client(headers, timeout, http_auth)
        else:
            LOGGER.warning(
                'SSL verification disabled for MCP server %r',
                server.slug,
            )
            http_client = httpx.AsyncClient(
                headers=headers,
                timeout=timeout,
                auth=http_auth,
                follow_redirects=True,
                verify=False,  # noqa: S501
            )

        self._tasks = [task for task in self._tasks if not task.done()]
        loop = asyncio.get_running_loop()
        ready: asyncio.Future[mcp.ClientSession] = loop.create_future()
        task = asyncio.create_task(
            self._run_session(server, http_client, ready),
            name=f'external-mcp-{server.slug}',
        )
        self._tasks.append(task)
        try:
            return await ready
        except BaseException:
            task.cancel()
            raise

    async def _run_session(
        self,
        server: common_models.MCPServer,
        http_client: httpx.AsyncClient,
        ready: asyncio.Future[mcp.ClientSession],
    ) -> None:
        """Hold one server's client contexts open in a dedicated task.

        The MCP client runs its I/O in an anyio task group. When a child
        task fails (for example on an HTTP 502), the group cancels the
        task that entered it. That task must be this one, not the caller,
        so a failure stops only this server and never the app lifespan.

        """
        try:
            async with (
                http_client,
                streamable_http.streamable_http_client(
                    str(server.url),
                    http_client=http_client,
                ) as (read_stream, write_stream, _),
                mcp.ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                self._sessions[server.slug] = session
                ready.set_result(session)
                await asyncio.get_running_loop().create_future()
        except Exception as err:  # noqa: BLE001
            if ready.done():
                LOGGER.error(
                    'External MCP server %r session failed: %r',
                    server.slug,
                    err,
                )
            else:
                ready.set_exception(err)
        finally:
            self._sessions.pop(server.slug, None)
            if not ready.done():
                ready.cancel()

    def _register_tool(
        self,
        server: common_models.MCPServer,
        tool: mcp_types.Tool,
        prefix: str,
    ) -> None:
        """Register a discovered tool, honoring ignored_tools."""
        if tool.name in server.ignored_tools:
            LOGGER.debug(
                'Ignoring MCP tool %s.%s (in ignored_tools)',
                server.slug,
                tool.name,
            )
            return
        registered_name = f'mcp_{prefix}_{tool.name}'
        if not _VALID_TOOL_NAME_RE.match(registered_name):
            sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', registered_name)
            sanitized = sanitized[:_MAX_TOOL_NAME_LEN]
            LOGGER.warning(
                'Sanitizing invalid MCP tool name %r -> %r (server %r)',
                registered_name,
                sanitized,
                server.slug,
            )
            registered_name = sanitized
        if not _VALID_TOOL_NAME_RE.match(registered_name):
            LOGGER.warning(
                'Skipping MCP tool with unusable name %r from server %r',
                registered_name,
                server.slug,
            )
            return
        if registered_name in self._tool_routes:
            LOGGER.warning(
                'Tool name collision %r; skipping from server %r',
                registered_name,
                server.slug,
            )
            return
        self._tool_routes[registered_name] = (server.slug, tool.name)
        self._tools.append(_mcp_tool_to_anthropic(tool, registered_name))

    async def aclose(self) -> None:
        """Close all server connections."""
        for task in self._tasks:
            task.cancel()
        # Each session task logs its own failure; teardown errors here
        # must not escape into the caller's (lifespan) unwind.
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        self._sessions.clear()
        self._tool_routes.clear()
        self._servers.clear()
        self._reconnect_after.clear()
        self._tools = []
        self._initialized = False

    def get_tools(self) -> list[dict[str, typing.Any]]:
        """Return Anthropic-compatible tool definitions."""
        return list(self._tools)

    def get_tool_names(self) -> list[str]:
        """Return the names of all registered tools."""
        return [t['name'] for t in self._tools]

    def has_tool(self, name: str) -> bool:
        """Return whether this manager owns the named tool."""
        return name in self._tool_routes

    async def execute_tool(
        self,
        tool_name: str,
        tool_input: dict[str, typing.Any],
    ) -> tuple[str, bool]:
        """Route a tool call to the owning server's session.

        Args:
            tool_name: The registered (namespaced) tool name.
            tool_input: The input parameters from Claude.

        Returns:
            Tuple of (content, is_error). ``content`` is a string
            suitable for an Anthropic ``tool_result`` block; ``is_error``
            flags whether the call failed so the caller can set
            ``is_error: true`` on the tool_result block.

        """
        route = self._tool_routes.get(tool_name)
        if route is None:
            return (
                json.dumps({'error': f'Unknown MCP tool: {tool_name}'}),
                True,
            )
        server_slug, original_name = route
        session = self._sessions.get(server_slug) or await self._reconnect(
            server_slug
        )
        if session is None:
            return (
                json.dumps({'error': f'Server {server_slug} not connected'}),
                True,
            )
        try:
            result = await session.call_tool(original_name, tool_input)
            parts: list[str] = []
            for block in result.content:
                text = getattr(block, 'text', None)
                if text is not None:
                    parts.append(text)
            body = '\n'.join(parts) if parts else '{}'
            if result.isError:
                LOGGER.warning(
                    'External MCP tool returned error: %s: %s',
                    tool_name,
                    body,
                )
                return (
                    json.dumps(
                        {
                            'error': f'Tool {tool_name} returned an error',
                            'detail': body,
                        }
                    ),
                    True,
                )
        except Exception as exc:
            LOGGER.exception(
                'External MCP tool execution failed: %s',
                tool_name,
            )
            # Preserve the exception message so the model can react.
            return (
                json.dumps(
                    {
                        'error': f'Tool execution failed: {tool_name}',
                        'detail': str(exc),
                    }
                ),
                True,
            )
        else:
            return body, False

    async def _reconnect(self, server_slug: str) -> mcp.ClientSession | None:
        """Reopen a failed server session, at most once per delay.

        Returns:
            The new session, or None if the server is still down or the
            delay since the last failed attempt has not passed.

        """
        server = self._servers.get(server_slug)
        if server is None:
            return None
        async with self._reconnect_lock:
            # Another call can have reconnected while this one waited.
            session = self._sessions.get(server_slug)
            if session is not None:
                return session
            if time.monotonic() < self._reconnect_after.get(server_slug, 0.0):
                return None
            LOGGER.info('Reconnecting to MCP server %r', server_slug)
            try:
                return await asyncio.wait_for(
                    self._open_session(server),
                    timeout=float(server.timeout),
                )
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                LOGGER.warning(
                    'Failed to reconnect to MCP server %r: %s',
                    server_slug,
                    err,
                )
                self._reconnect_after[server_slug] = (
                    time.monotonic() + _RECONNECT_DELAY
                )
                return None

    @property
    def is_initialized(self) -> bool:
        """Whether the manager has been initialized."""
        return self._initialized


# --- Module-level singleton ---

_manager: ExternalMCPManager | None = None


async def initialize(db: graph.Graph) -> None:
    """Initialize the module-level external MCP manager."""
    global _manager
    if _manager is not None:
        await _manager.aclose()
    _manager = ExternalMCPManager()
    try:
        await _manager.initialize(db)
    except Exception:
        LOGGER.exception('Failed to initialize external MCP servers')
        _manager = ExternalMCPManager()


async def ensure_manager() -> None:
    """Install an empty manager if none exists.

    Used when graph initialization fails at startup so request
    handling can still resolve a manager.
    """
    global _manager
    if _manager is None:
        _manager = ExternalMCPManager()


async def reinitialize(db: graph.Graph) -> tuple[bool, int]:
    """Rebuild connections from the current graph state.

    Returns:
        Tuple of (success, tool_count).

    """
    await initialize(db)
    manager = get_manager()
    return manager.is_initialized, len(manager.get_tools())


async def aclose() -> None:
    """Close the module-level external MCP manager."""
    global _manager
    if _manager is not None:
        await _manager.aclose()
        _manager = None


def get_manager() -> ExternalMCPManager:
    """Get the external MCP manager singleton.

    Returns:
        The initialized ExternalMCPManager.

    Raises:
        RuntimeError: If not yet initialized.

    """
    if _manager is None:
        raise RuntimeError('External MCP manager not initialized')
    return _manager
