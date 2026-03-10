"""Imbi MCP server.

Auto-generates MCP tools from the Imbi API's OpenAPI spec.
Forwards the caller's Authorization header to the API for
per-user authentication.
"""

from __future__ import annotations

import logging

import fastmcp
import httpx
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.providers.openapi import MCPType, RouteMap

import imbi_mcp

logger = logging.getLogger(__name__)

# Endpoints that should not be exposed as MCP tools.
_EXCLUDED_ROUTE_MAPS = [
    RouteMap(pattern=r'^/auth/', mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r'^/mfa/', mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r'^/status$', mcp_type=MCPType.EXCLUDE),
    RouteMap(
        pattern=r'.*/thumbnail$', mcp_type=MCPType.EXCLUDE
    ),
]

# Read-only list endpoints → resources, parameterised GETs →
# resource templates, everything else → tools.
_SEMANTIC_ROUTE_MAPS = [
    RouteMap(
        methods=['GET'],
        pattern=r'.*\{.*\}.*',
        mcp_type=MCPType.RESOURCE_TEMPLATE,
    ),
    RouteMap(
        methods=['GET'],
        pattern=r'.*',
        mcp_type=MCPType.RESOURCE,
    ),
]


async def _inject_auth(request: httpx.Request) -> None:
    """Forward the MCP caller's Authorization header to the API."""
    headers = get_http_headers(include={'authorization'})
    auth = headers.get('authorization')
    if auth:
        request.headers['authorization'] = auth


def create_server(api_url: str) -> fastmcp.FastMCP:
    """Build a FastMCP server from the live Imbi API OpenAPI spec.

    Args:
        api_url: Base URL of the running Imbi API
            (e.g. ``http://localhost:8000``).
    """
    spec_url = f'{api_url.rstrip("/")}/openapi.json'
    logger.info('Fetching OpenAPI spec from %s', spec_url)
    response = httpx.get(spec_url, timeout=30)
    response.raise_for_status()
    spec = response.json()

    client = httpx.AsyncClient(
        base_url=api_url,
        timeout=30,
        event_hooks={'request': [_inject_auth]},
    )

    return fastmcp.FastMCP.from_openapi(
        openapi_spec=spec,
        client=client,
        name='Imbi',
        version=imbi_mcp.version,
        route_maps=[
            *_EXCLUDED_ROUTE_MAPS,
            *_SEMANTIC_ROUTE_MAPS,
        ],
    )
