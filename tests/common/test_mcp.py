"""Tests for the shared AI-toolset exclusion policy."""

from __future__ import annotations

import json
import unittest

import fastmcp
import httpx
from fastmcp.server.providers.openapi import MCPType
from fastmcp.utilities.openapi import HTTPRoute

from imbi.common import mcp


class ExcludeNonAiToolsTestCase(unittest.TestCase):
    """Unit tests for :func:`imbi.common.mcp.exclude_non_ai_tools`."""

    def test_excludes_flagged_route(self) -> None:
        """A route flagged ``x-imbi-ai-tool: false`` is excluded."""
        route = HTTPRoute(
            path='/configuration/{key}',
            method='PUT',
            extensions={mcp.AI_TOOL_EXTENSION: False},
        )
        self.assertEqual(
            MCPType.EXCLUDE,
            mcp.exclude_non_ai_tools(route, MCPType.TOOL),
        )

    def test_keeps_unflagged_route(self) -> None:
        """A route without the extension is left unchanged."""
        route = HTTPRoute(path='/projects/', method='GET')
        self.assertIsNone(mcp.exclude_non_ai_tools(route, MCPType.TOOL))

    def test_keeps_explicitly_allowed_route(self) -> None:
        """An explicit ``x-imbi-ai-tool: true`` is not excluded."""
        route = HTTPRoute(
            path='/projects/',
            method='GET',
            extensions={mcp.AI_TOOL_EXTENSION: True},
        )
        self.assertIsNone(mcp.exclude_non_ai_tools(route, MCPType.TOOL))


class ExcludedRouteMapsTestCase(unittest.TestCase):
    """Unit tests for :data:`imbi.common.mcp.EXCLUDED_ROUTE_MAPS`."""

    def test_all_maps_exclude(self) -> None:
        """Every static map removes the matched route."""
        for route_map in mcp.EXCLUDED_ROUTE_MAPS:
            self.assertEqual(MCPType.EXCLUDE, route_map.mcp_type)

    def test_covers_sensitive_prefixes(self) -> None:
        """Auth, MFA, status, and thumbnail paths are all covered."""
        patterns = {route_map.pattern for route_map in mcp.EXCLUDED_ROUTE_MAPS}
        self.assertEqual(
            {
                r'^/auth/',
                r'^/mfa/',
                r'^/status/?$',
                r'.*/thumbnail/?$',
            },
            patterns,
        )


def _spec() -> dict[str, object]:
    """Minimal OpenAPI spec exercising each exclusion path."""
    ok = {'responses': {'200': {'description': 'OK'}}}
    return {
        'openapi': '3.1.0',
        'info': {'title': 'Imbi', 'version': '1.0.0'},
        'paths': {
            '/projects/': {'get': {'operationId': 'list_projects', **ok}},
            '/auth/login': {'post': {'operationId': 'login', **ok}},
            '/configuration/{key}': {
                'put': {
                    'operationId': 'set_configuration_value',
                    'x-imbi-ai-tool': False,
                    **ok,
                }
            },
        },
    }


class FromOpenapiExclusionTests(unittest.IsolatedAsyncioTestCase):
    """End-to-end: the policy excludes the right tools via fastmcp."""

    async def test_policy_excludes_expected_tools(self) -> None:
        """A real server build drops auth and AI-flagged operations."""
        client = httpx.AsyncClient(base_url='http://localhost:8000')
        try:
            server = fastmcp.FastMCP.from_openapi(
                openapi_spec=_spec(),
                client=client,
                name='Imbi',
                route_maps=list(mcp.EXCLUDED_ROUTE_MAPS),
                route_map_fn=mcp.exclude_non_ai_tools,
            )
            async with fastmcp.Client(server) as connected:
                names = {tool.name for tool in await connected.list_tools()}
        finally:
            await client.aclose()

        self.assertIn('list_projects', names)
        self.assertNotIn('login', names)
        self.assertNotIn('set_configuration_value', names)

    async def test_serializable_spec_round_trips(self) -> None:
        """The spec used in tests is valid JSON (guards typos)."""
        self.assertIn('x-imbi-ai-tool', json.dumps(_spec()))
