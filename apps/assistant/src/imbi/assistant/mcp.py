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

LOGGER = logging.getLogger(__name__)

# Endpoints that should not be exposed as tools.
_EXCLUDED_ROUTE_MAPS = [
    RouteMap(pattern=r'^/auth/', mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r'^/mfa/', mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r'^/status/?$', mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r'.*/thumbnail/?$', mcp_type=MCPType.EXCLUDE),
]


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
    schema = tool.inputSchema if hasattr(tool, 'inputSchema') else {}
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
        self._client: fastmcp.Client | None = None
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
        )

        self._client = fastmcp.Client(self._server)
        await self._client.__aenter__()

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
            await self._client.__aexit__(None, None, None)
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
    ) -> str:
        """Execute a tool via the MCP client.

        Args:
            tool_name: The tool name.
            tool_input: The input parameters from Claude.
            auth_token: Bearer token to forward to the API.

        Returns:
            JSON string of the tool result.

        """
        if not self._client or not self._http_client:
            return json.dumps({'error': 'MCP tools not initialized'})

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
                return json.dumps(
                    {
                        'error': f'Tool {tool_name} returned an error',
                        'detail': body,
                    }
                )
        except Exception:
            LOGGER.exception(
                'Tool execution failed: %s',
                tool_name,
            )
            return json.dumps(
                {
                    'error': f'Tool execution failed: {tool_name}',
                }
            )
        else:
            return body
        finally:
            # Clear the auth header after the request.
            self._http_client.headers.pop('authorization', None)

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
