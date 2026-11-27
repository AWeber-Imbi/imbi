"""Connect to external MCP servers over streamable HTTP.

Reads :class:`~imbi.common.models.MCPServer` nodes from the graph,
opens a streamable-HTTP MCP session per enabled server, discovers
their tools, and exposes them in Anthropic tool format for the
Claude integrations of the assistant and the Slack bot.

An MCP server belongs to one organization. Each organization has its
own :class:`ExternalMCPManager`, made on the first turn in that
organization (:func:`get_manager`), so a turn sees only the servers of
its own organization.

This is additive to each service's ``mcp`` module (which builds tools
from the Imbi OpenAPI spec); the two managers run side by side.

"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import re
import time
import typing

import httpx2
import mcp
import pydantic
from mcp import types as mcp_types
from mcp.client import streamable_http
from mcp.shared._httpx_utils import create_mcp_http_client

from imbi.common import api, graph
from imbi.common import models as common_models
from imbi.common.auth.encryption import decrypt_config_value

if typing.TYPE_CHECKING:
    import collections.abc

LOGGER = logging.getLogger(__name__)

_VALID_TOOL_NAME_RE = re.compile(r'^[a-zA-Z0-9_-]{1,128}$')

_MAX_TOOL_NAME_LEN = 128

_OAUTH_EXPIRY_BUFFER = 60.0

_OAUTH_TOKEN_TIMEOUT = 10.0

# ponytail: fixed delay between reconnect attempts to a server that is
# down; make it exponential if a fixed delay is too slow or too noisy.
_RECONNECT_DELAY = 60.0


async def get_enabled_mcp_servers(
    db: graph.Graph,
    org_id: str,
) -> list[common_models.MCPServer]:
    """Return the enabled external MCP server nodes of an organization."""
    query = """
    MATCH (s:MCPServer {{enabled: true, org_id: {org_id}}})
    RETURN s
    """
    records = await db.execute(query, {'org_id': org_id}, ['s'])
    servers: list[common_models.MCPServer] = []
    for record in records:
        data = graph.parse_agtype(record['s'])
        try:
            servers.append(common_models.MCPServer(**data))
        except pydantic.ValidationError as err:
            LOGGER.warning('Skipping invalid MCPServer row: %s', err)
    return servers


class OAuthClientCredentialsAuth(httpx2.Auth):
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
        async with httpx2.AsyncClient(
            timeout=httpx2.Timeout(_OAUTH_TOKEN_TIMEOUT)
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
        request: httpx2.Request,
    ) -> collections.abc.AsyncGenerator[httpx2.Request, httpx2.Response]:
        async with self._lock:
            if self._is_expired():
                await self._fetch_token()
        request.headers['Authorization'] = f'Bearer {self._access_token}'
        yield request


#: Gets the values of a server's secret references (``static_value``,
#: ``oauth_client_secret``) from imbi-api. The service sets it at start.
CredentialResolver = typing.Callable[
    [common_models.MCPServer],
    typing.Awaitable[dict[str, str | None]],
]
_credential_resolver: CredentialResolver | None = None


def _destination(
    server: common_models.MCPServer,
) -> tuple[str, str | None, str, bool]:
    """Where a connection sends a secret, and how: imbi-api gives the
    secret only when these are the saved values."""
    return (
        str(server.url),
        str(server.oauth_token_url) if server.oauth_token_url else None,
        server.auth_type,
        server.verify_ssl,
    )


def set_credential_resolver(resolver: CredentialResolver | None) -> None:
    """Set how a connection gets the secrets of a server's references."""
    global _credential_resolver
    _credential_resolver = resolver


def install_credential_resolver(api_url: str, api_token: str) -> None:
    """Get the secrets of the servers' bindings from imbi-api with the
    API key of this service's account (``POST
    /mcp-servers/{id}/credentials``). With no key, servers that use a
    binding connect without the secret."""
    if not api_token:
        LOGGER.info(
            'No API token: MCP servers that use a secret binding cannot '
            'get the secret'
        )
        set_credential_resolver(None)
        return

    async def resolve(
        server: common_models.MCPServer,
    ) -> dict[str, str | None]:
        async with api.Imbi(
            base_url=api_url, token=api_token, timeout=float(server.timeout)
        ) as client:
            # The URLs this connection uses: imbi-api refuses the secret
            # when they are not the saved ones.
            url, token_url, auth_type, verify_ssl = _destination(server)
            response = await client.post(
                f'/mcp-servers/{server.id}/credentials',
                json={
                    'url': url,
                    'oauth_token_url': token_url,
                    'auth_type': auth_type,
                    'verify_ssl': verify_ssl,
                },
            )
        response.raise_for_status()
        return typing.cast('dict[str, str | None]', response.json())

    set_credential_resolver(resolve)


async def _referenced_secrets(
    server: common_models.MCPServer,
) -> dict[str, str | None]:
    """Return the values of a server's secret references. With no
    resolver or on a failure, log it and return none: the connection
    then fails as with a missing secret."""
    if not (server.static_value_ref or server.oauth_client_secret_ref):
        return {}
    if _credential_resolver is None:
        LOGGER.warning(
            'MCP server %r uses a secret binding, but this service has no '
            'API token to get it',
            server.slug,
        )
        return {}
    try:
        return await _credential_resolver(server)
    except Exception:
        LOGGER.exception(
            'Could not get the secrets of MCP server %r', server.slug
        )
        return {}


async def _build_auth(
    server: common_models.MCPServer,
) -> tuple[dict[str, str] | None, httpx2.Auth | None]:
    """Build the headers and httpx auth for a server.

    Decrypts any ``*_encrypted`` secrets, and gets the values of any
    secret references, at connect time.

    Returns:
        Tuple of (static headers or None, httpx2.Auth or None).

    """
    referenced = await _referenced_secrets(server)
    if server.auth_type == 'static':
        value = (
            referenced.get('static_value')
            if server.static_value_ref
            else decrypt_config_value(server.static_value_encrypted)
        )
        if server.static_header and value is not None:
            return {server.static_header: value}, None
        LOGGER.warning(
            'Static auth for MCP server %r is missing a header or value',
            server.slug,
        )
        return None, None
    if server.auth_type == 'oauth_client_credentials':
        secret = (
            referenced.get('oauth_client_secret')
            if server.oauth_client_secret_ref
            else decrypt_config_value(server.oauth_client_secret_encrypted)
        )
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
        'input_schema': tool.input_schema or {},
    }


class ExternalMCPManager:
    """Manages streamable-HTTP connections to the external MCP servers
    of one organization and exposes their tools to a Claude integration.

    """

    def __init__(self, org_id: str) -> None:
        self._org_id = org_id
        self._tasks: list[asyncio.Task[None]] = []
        self._sessions: dict[str, mcp.ClientSession] = {}
        # server slug -> task that holds the latest session open
        self._session_tasks: dict[str, asyncio.Task[None]] = {}
        self._tools: list[dict[str, typing.Any]] = []
        # registered tool name -> (server slug, original tool name)
        self._tool_routes: dict[str, tuple[str, str]] = {}
        # server slug -> config, kept to reopen a failed session
        self._servers: dict[str, common_models.MCPServer] = {}
        # server slug -> monotonic time before which no reconnect runs
        self._reconnect_after: dict[str, float] = {}
        # server slug -> lock that serializes reconnects to that server
        self._reconnect_locks: dict[str, asyncio.Lock] = {}
        # slugs of connected servers that an admin disabled since connecting
        self._disabled: set[str] = set()
        # number of the newest sync_enabled read, so a slow, older read
        # cannot replace the result of a newer one
        self._sync_seq = 0
        # True in the context of a turn whose own enabled-server read
        # failed; other turns cannot clear it (fail closed per turn)
        self._read_failed: contextvars.ContextVar[bool] = (
            contextvars.ContextVar(
                f'external_mcp_read_failed_{id(self)}', default=False
            )
        )
        self._initialized = False

    async def initialize(self, db: graph.Graph) -> None:
        """Connect to every enabled MCP server of the organization and
        discover tools.

        Per-server connect failures are logged and skipped so a single
        bad server cannot stop the others.

        Args:
            db: Open graph connection used to read MCPServer nodes.

        """
        servers = await get_enabled_mcp_servers(db, self._org_id)
        # Connect in parallel, so the first turn waits for the slowest server,
        # not for the sum of all the timeouts.
        await asyncio.gather(*(self._connect_server(s) for s in servers))
        self._initialized = True
        LOGGER.info(
            'External MCP initialization complete for organization %s: '
            '%d servers, %d tools',
            self._org_id,
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
            session, result = await asyncio.wait_for(
                self._open_and_list(server),
                timeout=float(server.timeout),
            )
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

    async def _open_and_list(
        self,
        server: common_models.MCPServer,
    ) -> tuple[mcp.ClientSession, mcp_types.ListToolsResult]:
        """Open a session and discover its tools.

        If discovery fails or is cancelled (for example by the connect
        timeout), stop the session task so that its HTTP client closes.

        """
        session = await self._open_session(server)
        try:
            return session, await session.list_tools()
        except BaseException:
            task = self._session_tasks.pop(server.slug, None)
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            raise

    async def _open_session(
        self,
        server: common_models.MCPServer,
    ) -> mcp.ClientSession:
        """Open and initialize a streamable-HTTP session."""
        auth_headers, http_auth = await _build_auth(server)
        headers = server.request_headers(auth_headers)
        timeout = httpx2.Timeout(float(server.timeout))
        if server.verify_ssl:
            http_client = create_mcp_http_client(headers, timeout, http_auth)
        else:
            LOGGER.warning(
                'SSL verification disabled for MCP server %r',
                server.slug,
            )
            http_client = httpx2.AsyncClient(
                headers=headers,
                timeout=timeout,
                auth=http_auth,
                follow_redirects=True,
                verify=False,
            )

        self._tasks = [task for task in self._tasks if not task.done()]
        loop = asyncio.get_running_loop()
        ready: asyncio.Future[mcp.ClientSession] = loop.create_future()
        task = asyncio.create_task(
            self._run_session(server, http_client, ready),
            name=f'external-mcp-{server.slug}',
        )
        self._tasks.append(task)
        self._session_tasks[server.slug] = task
        try:
            return await ready
        except BaseException:
            task.cancel()
            raise

    async def _run_session(
        self,
        server: common_models.MCPServer,
        http_client: httpx2.AsyncClient,
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
                ) as (read_stream, write_stream),
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
        # Clear the servers first. A reconnect that gets its lock while
        # this method waits below then finds no server and opens nothing.
        self._servers.clear()
        for task in self._tasks:
            task.cancel()
        # Each session task logs its own failure; teardown errors here
        # must not escape into the caller's (lifespan) unwind.
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        self._session_tasks.clear()
        self._sessions.clear()
        self._tool_routes.clear()
        self._reconnect_after.clear()
        self._reconnect_locks.clear()
        self._disabled = set()
        self._tools = []
        self._initialized = False

    async def sync_enabled(self, db: graph.Graph | None) -> None:
        """Read the enabled flags again, so that a server that an admin
        disabled stops at once, without a restart.

        Call this once for each turn. If there is no graph or the read
        fails, all servers are disabled (fail closed). The failure also
        stays in the context of the calling turn, so a newer read that
        another turn starts cannot expose tools to this turn.

        """
        self._sync_seq += 1
        seq = self._sync_seq
        enabled: set[str] = set()
        failed = True
        if db is None:
            LOGGER.error('No graph to read the enabled MCP servers')
        else:
            try:
                servers = await get_enabled_mcp_servers(db, self._org_id)
            except Exception:
                LOGGER.exception('Failed to read the enabled MCP servers')
            else:
                # A server whose destination or TLS check changed after
                # it connected stops: its open session still uses the old
                # values. It comes back at the next reinitialize.
                enabled = {
                    s.slug
                    for s in servers
                    if s.slug not in self._servers
                    or _destination(s) == _destination(self._servers[s.slug])
                }
                failed = False
        self._read_failed.set(failed)
        if seq == self._sync_seq:
            self._disabled = set(self._servers) - enabled

    def _is_enabled(self, name: str) -> bool:
        if self._read_failed.get():
            return False
        route = self._tool_routes.get(name)
        return route is not None and route[0] not in self._disabled

    def get_tools(self) -> list[dict[str, typing.Any]]:
        """Return Anthropic-compatible tool definitions."""
        return [t for t in self._tools if self._is_enabled(t['name'])]

    def get_tool_names(self) -> list[str]:
        """Return the names of all registered tools."""
        return [t['name'] for t in self.get_tools()]

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
        if self._read_failed.get() or route[0] in self._disabled:
            return (
                json.dumps({'error': f'MCP server {route[0]} is disabled'}),
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
            if result.is_error:
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
        lock = self._reconnect_locks.setdefault(server_slug, asyncio.Lock())
        async with lock:
            # aclose() can have removed the server while this one waited.
            if self._servers.get(server_slug) is not server:
                return None
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


# --- Module-level managers, one for each organization ---

# ponytail: a manager stays open for the life of the process, also for
# an idle organization; evict idle managers if the number of
# organizations grows large.
_managers: dict[str, ExternalMCPManager] = {}
_locks: dict[str, asyncio.Lock] = {}


async def get_manager(db: graph.Graph, org_id: str) -> ExternalMCPManager:
    """Return the manager of an organization, connecting it first when
    this is the organization's first turn.

    A failure to read the servers gives an empty manager that is not
    kept, so the next turn tries again.

    """
    manager = _managers.get(org_id)
    if manager is not None:
        return manager
    async with _locks.setdefault(org_id, asyncio.Lock()):
        manager = _managers.get(org_id)
        if manager is not None:
            return manager
        manager = ExternalMCPManager(org_id)
        try:
            await manager.initialize(db)
        except asyncio.CancelledError:
            await manager.aclose()
            raise
        except Exception:
            LOGGER.exception(
                'Failed to initialize the MCP servers of organization %s',
                org_id,
            )
            await manager.aclose()
            return ExternalMCPManager(org_id)
        _managers[org_id] = manager
        return manager


async def reinitialize(db: graph.Graph, org_id: str) -> tuple[bool, int]:
    """Rebuild the connections of an organization from the graph.

    Returns:
        Tuple of (success, tool_count).

    """
    async with _locks.setdefault(org_id, asyncio.Lock()):
        old = _managers.pop(org_id, None)
    if old is not None:
        await old.aclose()
    manager = await get_manager(db, org_id)
    return manager.is_initialized, len(manager.get_tools())


@contextlib.asynccontextmanager
async def lifespan() -> collections.abc.AsyncGenerator[None]:
    """Close the connections of every organization at shutdown. The
    connections themselves open on each organization's first turn."""
    try:
        yield
    finally:
        await aclose()


async def aclose() -> None:
    """Close the managers of every organization."""
    managers = list(_managers.values())
    _managers.clear()
    _locks.clear()
    await asyncio.gather(
        *(m.aclose() for m in managers), return_exceptions=True
    )
