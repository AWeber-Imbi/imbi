"""Auto-generate MCP tools from the Imbi API OpenAPI spec.

Uses FastMCP to create an in-process MCP server from the API's
OpenAPI specification, then exposes tools in Anthropic format
for the assistant's Claude integration.

"""

from __future__ import annotations

import json
import logging
import typing

import fastmcp
import httpx
from fastmcp.server.providers.openapi import MCPType, RouteMap

from imbi_assistant import settings

if typing.TYPE_CHECKING:
    from fastmcp.utilities.openapi import HTTPRoute

LOGGER = logging.getLogger(__name__)

REFRESH_TOOL_NAME = 'refresh_openapi_spec'

REFRESH_TOOL: dict[str, typing.Any] = {
    'name': REFRESH_TOOL_NAME,
    'description': (
        'Re-fetch the Imbi API OpenAPI specification and reconnect to '
        'every configured external MCP server, rebuilding the full tool '
        'list from both sources. Use this when a tool you expect to '
        'exist is missing, or when a new API version or MCP server has '
        'been deployed.'
    ),
    'input_schema': {
        'type': 'object',
        'properties': {},
    },
}

# OpenAPI operation extension imbi-api stamps on endpoints that must not
# be exposed to AI. Its presence (set to ``False``) hides the operation
# regardless of path or method — the API owns which endpoints are
# sensitive (e.g. project Configuration / SSM Parameter Store).
_AI_TOOL_EXTENSION = 'x-imbi-ai-tool'

# Endpoints that should not be exposed as tools.
_EXCLUDED_ROUTE_MAPS = [
    RouteMap(pattern=r'^/auth/', mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r'^/mfa/', mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r'^/status/?$', mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r'.*/thumbnail/?$', mcp_type=MCPType.EXCLUDE),
]


def _exclude_non_ai_tools(
    route: HTTPRoute, _mcp_type: MCPType
) -> MCPType | None:
    """Exclude operations imbi-api flagged as off-limits for AI.

    Returns ``MCPType.EXCLUDE`` when the operation carries
    ``x-imbi-ai-tool: false`` in the OpenAPI spec, else ``None`` to
    leave the route map decision unchanged.
    """
    if route.extensions.get(_AI_TOOL_EXTENSION) is False:
        return MCPType.EXCLUDE
    return None


def _mcp_tool_to_anthropic(
    tool: typing.Any,
) -> dict[str, typing.Any]:
    """Convert an MCP Tool object to Anthropic tool format.

    Args:
        tool: An MCP Tool from ``client.list_tools()``.

    Returns:
        Dict with ``name``, ``description``, and
        ``input_schema`` keys.

    """
    schema: dict[str, typing.Any] = (
        tool.inputSchema if hasattr(tool, 'inputSchema') else {}
    )
    return {
        'name': tool.name,
        'description': tool.description or '',
        'input_schema': schema,
    }


class MCPManager:
    """Manages an in-process FastMCP server built from the Imbi
    API OpenAPI spec and provides tool definitions and execution
    for the assistant.

    """

    def __init__(self) -> None:
        self._server: fastmcp.FastMCP | None = None
        self._client: fastmcp.Client[typing.Any] | None = None
        self._tools: list[dict[str, typing.Any]] = []
        self._http_client: httpx.AsyncClient | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Fetch the OpenAPI spec and build tools."""
        assistant_settings = settings.get_assistant_settings()
        api_url = assistant_settings.api_url
        if not api_url:
            LOGGER.info('No API URL configured; MCP tools disabled')
            return

        spec_url = f'{api_url.rstrip("/")}/openapi.json'
        LOGGER.info('Fetching OpenAPI spec from %s', spec_url)

        async with httpx.AsyncClient(timeout=30) as tmp:
            response = await tmp.get(spec_url)
            response.raise_for_status()
            spec = response.json()

        self._http_client = httpx.AsyncClient(
            base_url=api_url,
            timeout=30,
        )

        self._server = fastmcp.FastMCP.from_openapi(
            openapi_spec=spec,
            client=self._http_client,
            name='Imbi',
            route_maps=list(_EXCLUDED_ROUTE_MAPS),
            route_map_fn=_exclude_non_ai_tools,
        )

        self._client = fastmcp.Client(self._server)
        await self._client.__aenter__()  # type: ignore[no-untyped-call]

        mcp_tools = await self._client.list_tools()
        self._tools = [_mcp_tool_to_anthropic(t) for t in mcp_tools]
        self._initialized = True
        LOGGER.info(
            'Loaded %d tools from OpenAPI spec',
            len(self._tools),
        )

    async def aclose(self) -> None:
        """Close the MCP client and HTTP client."""
        if self._client is not None:
            await self._client.__aexit__(None, None, None)  # type: ignore[no-untyped-call]  # pyright: ignore[reportUnknownMemberType]
            self._client = None
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
        self._server = None
        self._tools = []
        self._initialized = False

    def get_tools(self) -> list[dict[str, typing.Any]]:
        """Return Anthropic-compatible tool definitions."""
        return list(self._tools)

    def get_tool_names(self) -> list[str]:
        """Return the names of all available tools."""
        return [t['name'] for t in self._tools]

    async def execute_tool(
        self,
        tool_name: str,
        tool_input: dict[str, typing.Any],
        auth_token: str | None = None,
    ) -> tuple[str, bool]:
        """Execute a tool via the MCP client.

        Args:
            tool_name: The tool name.
            tool_input: The input parameters from Claude.
            auth_token: Bearer token to forward to the API.

        Returns:
            Tuple of (content, is_error). ``content`` is a JSON or text
            string suitable for an Anthropic ``tool_result`` block;
            ``is_error`` flags whether the call failed so the caller can
            set ``is_error: true`` on the tool_result block. The Claude
            API only treats a tool result as an error when that flag is
            set, so failures must surface here.

        """
        if not self._client or not self._http_client:
            return json.dumps({'error': 'MCP tools not initialized'}), True

        # Inject the caller's auth token for this request.
        if auth_token:
            self._http_client.headers['authorization'] = f'Bearer {auth_token}'
        try:
            result = await self._client.call_tool(
                tool_name,
                tool_input,
            )
            # call_tool returns a CallToolResult with .content
            parts: list[str] = []
            for block in result.content:
                text = getattr(block, 'text', None)
                if text is not None:
                    parts.append(text)
            body = '\n'.join(parts) if parts else '{}'
            if result.is_error:
                LOGGER.warning(
                    'Tool returned error: %s: %s',
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
                'Tool execution failed: %s',
                tool_name,
            )
            # Preserve the exception message (e.g. the 4xx/5xx body from
            # fastmcp's ToolError) so the model can correct its call.
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
        finally:
            # Clear the auth header after the request.
            self._http_client.headers.pop('authorization', None)

    async def reinitialize(self) -> tuple[bool, int]:
        """Re-fetch the OpenAPI spec and rebuild the tool list.

        Builds a replacement in a temporary manager first; only swaps
        in the new state if initialization succeeds, so a transient
        fetch/init failure leaves the existing tools in place.

        Returns:
            Tuple of (success, tool_count).

        """
        replacement = MCPManager()
        try:
            await replacement.initialize()
        except Exception:
            LOGGER.exception('Failed to reinitialize MCP tools')
            await replacement.aclose()
            return False, 0

        if not replacement._initialized:
            # API URL not configured; keep existing state.
            await replacement.aclose()
            return False, 0

        # Swap in the new state, then close the old client/transport.
        old_client = self._client
        old_http_client = self._http_client
        self._server = replacement._server
        self._client = replacement._client
        self._http_client = replacement._http_client
        self._tools = replacement._tools
        self._initialized = replacement._initialized
        # Detach so `replacement.aclose()` (if ever called) is a no-op.
        replacement._server = None
        replacement._client = None
        replacement._http_client = None
        replacement._tools = []
        replacement._initialized = False

        try:
            if old_client is not None:
                await old_client.__aexit__(None, None, None)  # type: ignore[no-untyped-call]  # pyright: ignore[reportUnknownMemberType]
        finally:
            if old_http_client is not None:
                await old_http_client.aclose()

        return self._initialized, len(self._tools)

    @property
    def is_initialized(self) -> bool:
        """Whether the manager has been initialized."""
        return self._initialized


# --- Module-level singleton ---

_manager: MCPManager | None = None


async def initialize() -> None:
    """Initialize the module-level MCP manager."""
    global _manager
    if _manager is not None:
        await _manager.aclose()
    _manager = MCPManager()
    try:
        await _manager.initialize()
    except Exception:
        LOGGER.exception('Failed to initialize MCP tools')
        _manager = MCPManager()


async def aclose() -> None:
    """Close the module-level MCP manager."""
    global _manager
    if _manager is not None:
        await _manager.aclose()
        _manager = None


def get_server_tools() -> list[dict[str, typing.Any]]:
    """Return server-side tool definitions in Anthropic format."""
    return [REFRESH_TOOL]


def is_server_tool(name: str) -> bool:
    """Check if a tool name is a server-side assistant tool."""
    return name == REFRESH_TOOL_NAME


def get_manager() -> MCPManager:
    """Get the MCP manager singleton.

    Returns:
        The initialized MCPManager.

    Raises:
        RuntimeError: If not yet initialized.

    """
    if _manager is None:
        raise RuntimeError('MCP manager not initialized')
    return _manager
