"""Imbi MCP server.

Exposes Imbi API functionality as MCP tools. JWT forwarding
and authorization are planned for a future iteration.
"""

import fastmcp

import imbi_mcp

mcp = fastmcp.FastMCP(
    'Imbi',
    version=imbi_mcp.version,
)
