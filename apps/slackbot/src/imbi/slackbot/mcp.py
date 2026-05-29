"""Auto-generate MCP tools from the Imbi API OpenAPI spec.

Uses FastMCP to create an in-process MCP server from the API's
OpenAPI specification, then exposes tools in Anthropic format for the
bot's Claude integration. The set of exposed operations is governed by
the shared :mod:`imbi_common.mcp` policy.

"""

from __future__ import annotations

import json
import logging
import typing

import fastmcp
import httpx
from imbi_common.mcp import EXCLUDED_ROUTE_MAPS, exclude_non_ai_tools

from imbi_slackbot import settings

LOGGER = logging.getLogger(__name__)


def _mcp_tool_to_anthropic(
    tool: typing.Any,
) -> dict[str, typing.Any]:
    """Convert an MCP Tool object to Anthropic tool format.

    Args:
        tool: An MCP Tool from ``client.list_tools()``.

    Returns:
        Dict with ``name``, ``description``, and ``input_schema`` keys.

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
    """Manages an in-process FastMCP server built from the Imbi API
    OpenAPI spec and provides tool definitions and execution.

    """

    def __init__(self) -> None:
        self._server: fastmcp.FastMCP | None = None
        self._client: fastmcp.Client[typing.Any] | None = None
        self._tools: list[dict[str, typing.Any]] = []
        self._http_client: httpx.AsyncClient | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Fetch the OpenAPI spec and build tools."""
        slackbot_settings = settings.get_slackbot_settings()
        api_url = slackbot_settings.api_url
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
            route_maps=list(EXCLUDED_ROUTE_MAPS),
            route_map_fn=exclude_non_ai_tools,
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
            ``is_error`` flags whether the call failed.

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
        # Close any partially-opened client and leave the empty manager
        # in place; callers degrade to a tool-less prompt.
        await _manager.aclose()


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
