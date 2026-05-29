"""Imbi MCP server.

Auto-generates MCP tools from the Imbi API's OpenAPI spec.

Authentication: the caller's ``Authorization`` header is always forwarded
to the API for per-user auth. When a public URL and authorization server
are configured, the server additionally becomes an OAuth 2.0 Resource
Server -- it verifies bearer tokens at the edge and advertises Protected
Resource Metadata so MCP clients can run a browser login flow. Without
that configuration it stays a transparent pass-through and leaves all
token validation to the API.
"""

from __future__ import annotations

import logging

import fastmcp
import httpx
import jwt
from fastmcp.server.auth.auth import (
    AccessToken,
    RemoteAuthProvider,
    TokenVerifier,
)
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.providers.openapi import MCPType, RouteMap
from imbi_common.auth import core
from pydantic import AnyHttpUrl

import imbi_mcp

logger = logging.getLogger(__name__)

# Endpoints that should not be exposed as MCP tools.
_EXCLUDED_ROUTE_MAPS = [
    RouteMap(pattern=r'^/auth/', mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r'^/mfa/', mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r'^/status/?$', mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r'.*/thumbnail/?$', mcp_type=MCPType.EXCLUDE),
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


class ImbiTokenVerifier(TokenVerifier):
    """Validate Imbi bearer credentials at the MCP edge.

    JWT access tokens are verified locally with the shared Imbi HS256
    secret (via ``imbi_common``). Opaque ``ik_`` API keys cannot be
    verified here -- only the API can -- so they are accepted and
    forwarded for the API to authorize (accept-and-forward). Anything
    else returns ``None``, which makes FastMCP answer ``401`` with a
    ``WWW-Authenticate`` challenge and kicks off OAuth discovery.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        if token.startswith('ik_'):
            return AccessToken(token=token, client_id='api-key', scopes=[])
        try:
            claims = core.verify_token(token)
        except jwt.InvalidTokenError:
            return None
        if claims.get('type') != 'access':
            return None
        scope = str(claims.get('scope') or '')
        return AccessToken(
            token=token,
            client_id=str(claims.get('sub', '')),
            scopes=scope.split(),
            expires_at=claims.get('exp'),
            claims=claims,
        )


def _build_auth(
    public_url: str | None, auth_server_url: str | None
) -> RemoteAuthProvider | None:
    """Build the OAuth Resource Server provider when configured.

    Both ``public_url`` (where this server is reachable, e.g.
    ``https://host/mcp``) and ``auth_server_url`` (the Imbi issuer, e.g.
    ``https://host``) are required to advertise discovery. When either is
    missing the server keeps its transparent pass-through behavior.
    """
    if not (public_url and auth_server_url):
        return None
    return RemoteAuthProvider(
        token_verifier=ImbiTokenVerifier(),
        authorization_servers=[AnyHttpUrl(auth_server_url)],
        base_url=public_url,
        resource_name='Imbi',
        scopes_supported=['imbi'],
    )


def create_server(
    api_url: str,
    *,
    public_url: str | None = None,
    auth_server_url: str | None = None,
) -> fastmcp.FastMCP:
    """Build a FastMCP server from the live Imbi API OpenAPI spec.

    Args:
        api_url: Base URL of the running Imbi API
            (e.g. ``http://localhost:8000``).
        public_url: Public URL where this MCP server is reachable
            (e.g. ``https://host/mcp``). Enables OAuth when set with
            ``auth_server_url``.
        auth_server_url: Imbi OAuth issuer URL (e.g. ``https://host``).
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
        auth=_build_auth(public_url, auth_server_url),
        route_maps=[
            *_EXCLUDED_ROUTE_MAPS,
            *_SEMANTIC_ROUTE_MAPS,
        ],
    )
