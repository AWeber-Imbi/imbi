"""Imbi MCP server.

Exposes Imbi API functionality as MCP tools, forwarding the
client's JWT for authorization so that the MCP server can only
perform actions the authenticated user is permitted to do.
"""

import fastmcp

import imbi_mcp

mcp = fastmcp.FastMCP(
    'Imbi',
    version=imbi_mcp.version,
)
