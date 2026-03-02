"""MCP client manager stub for future implementation."""

import logging
import typing

from imbi_api.assistant import settings

LOGGER = logging.getLogger(__name__)


class MCPManager:
    """Manages connections to external MCP servers.

    This is a stub for future implementation. MCP tools will
    be merged with native Imbi tools in the tool list.

    """

    def __init__(
        self,
        server_configs: list[dict[str, typing.Any]],
    ) -> None:
        self._configs = server_configs
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize connections to MCP servers."""
        if not self._configs:
            LOGGER.debug('No MCP servers configured')
            return
        LOGGER.info(
            'MCP server support is stubbed; %d server(s) configured '
            'but not connected',
            len(self._configs),
        )
        self._initialized = True

    async def aclose(self) -> None:
        """Close all MCP server connections."""
        self._initialized = False

    def get_tools(self) -> list[dict[str, typing.Any]]:
        """Get tool schemas from all connected MCP servers.

        Returns:
            Empty list (stub implementation).

        """
        return []

    async def execute_tool(
        self,
        server_name: str,
        tool_name: str,
        tool_input: dict[str, typing.Any],
    ) -> str:
        """Execute a tool on an MCP server.

        Returns:
            Error message (stub implementation).

        """
        return f'MCP tool execution not yet implemented: {tool_name}'


def create_mcp_manager() -> MCPManager:
    """Create an MCPManager from settings."""
    assistant_settings = settings.get_assistant_settings()
    return MCPManager(assistant_settings.mcp_servers)
