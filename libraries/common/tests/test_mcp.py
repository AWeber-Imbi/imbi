"""Tests for the shared AI-toolset exclusion policy."""

from __future__ import annotations

import json
import logging
import time
import typing
import unittest
import unittest.mock

import fastmcp
import httpx
import starlette.middleware
from fastmcp.server.providers.openapi import MCPType
from fastmcp.utilities.openapi import HTTPRoute

from imbi.common import access_log, cache, mcp


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
    """Unit tests for :func:`imbi.common.mcp.excluded_route_maps`."""

    def test_all_maps_exclude(self) -> None:
        """Every map removes the matched route."""
        for route_map in mcp.excluded_route_maps(_spec()):
            self.assertEqual(MCPType.EXCLUDE, route_map.mcp_type)

    def test_covers_sensitive_prefixes(self) -> None:
        """Auth, MFA, status, and thumbnail paths are all covered."""
        patterns = {
            route_map.pattern for route_map in mcp.excluded_route_maps(_spec())
        }
        self.assertEqual(
            {
                r'^/auth/',
                r'^/mfa/',
                r'^/status/?$',
                r'.*/thumbnail/?$',
            },
            patterns,
        )

    def test_patterns_anchor_at_the_mount_prefix(self) -> None:
        """A prefixed deployment gets prefixed patterns."""
        patterns = {
            route_map.pattern
            for route_map in mcp.excluded_route_maps(_spec(prefix='/api'))
        }
        self.assertEqual(
            {
                r'^/api/auth/',
                r'^/api/mfa/',
                r'^/api/status/?$',
                r'.*/thumbnail/?$',
            },
            patterns,
        )


class MountPrefixTestCase(unittest.TestCase):
    """Unit tests for :func:`imbi.common.mcp.mount_prefix`."""

    def test_root_mounted_spec(self) -> None:
        """An unprefixed spec yields an empty prefix."""
        self.assertEqual('', mcp.mount_prefix(_spec()))

    def test_prefixed_spec(self) -> None:
        """The prefix comes from the profile path's spec entry."""
        self.assertEqual('/api', mcp.mount_prefix(_spec(prefix='/api')))

    def test_multi_segment_prefix(self) -> None:
        """Multi-segment prefixes are returned whole."""
        self.assertEqual(
            '/imbi/api', mcp.mount_prefix(_spec(prefix='/imbi/api'))
        )

    def test_missing_profile_path_raises(self) -> None:
        """Without the anchor path the prefix cannot be resolved."""
        with self.assertRaises(ValueError):
            mcp.mount_prefix(_openapi_spec({}))

    def test_ambiguous_profile_path_raises(self) -> None:
        """Two candidate anchors are ambiguous, so resolution fails."""
        spec = _openapi_spec(
            {
                f'/api{mcp.PROFILE_PATH}': {'get': OK},
                f'/v2{mcp.PROFILE_PATH}': {'get': OK},
            }
        )
        with self.assertRaises(ValueError):
            mcp.mount_prefix(spec)


#: Boilerplate ``responses`` block every test operation needs.
OK = {'responses': {'200': {'description': 'OK'}}}


def _openapi_spec(paths: dict[str, object]) -> dict[str, object]:
    """Wrap ``paths`` in a minimal OpenAPI envelope."""
    return {
        'openapi': '3.1.0',
        'info': {'title': 'Imbi', 'version': '1.0.0'},
        'paths': paths,
    }


def _spec(prefix: str = '') -> dict[str, object]:
    """Minimal OpenAPI spec exercising each exclusion path.

    ``prefix`` mimics the path the API is mounted under (the path
    component of ``IMBI_API_URL``), which every generated spec path
    carries.
    """
    return _openapi_spec(
        {
            f'{prefix}/projects/': {
                'get': {'operationId': 'list_projects', **OK}
            },
            f'{prefix}/users/me': {
                'get': {'operationId': 'get_current_user_profile', **OK}
            },
            f'{prefix}/auth/login': {'post': {'operationId': 'login', **OK}},
            f'{prefix}/configuration/{{key}}': {
                'put': {
                    'operationId': 'set_configuration_value',
                    'x-imbi-ai-tool': False,
                    **OK,
                }
            },
        }
    )


class FromOpenapiExclusionTests(unittest.IsolatedAsyncioTestCase):
    """End-to-end: the policy excludes the right tools via fastmcp."""

    async def _tool_names(self, prefix: str = '') -> set[str]:
        """Build a server from the policy and list its tools."""
        spec = _spec(prefix)
        client = httpx.AsyncClient(base_url='http://localhost:8000')
        try:
            server = fastmcp.FastMCP.from_openapi(
                openapi_spec=spec,
                client=client,
                name='Imbi',
                route_maps=mcp.excluded_route_maps(spec),
                route_map_fn=mcp.exclude_non_ai_tools,
            )
            async with fastmcp.Client(server) as connected:
                return {tool.name for tool in await connected.list_tools()}
        finally:
            await client.aclose()

    async def test_policy_excludes_expected_tools(self) -> None:
        """A real server build drops auth and AI-flagged operations."""
        names = await self._tool_names()

        self.assertIn('list_projects', names)
        self.assertNotIn('login', names)
        self.assertNotIn('set_configuration_value', names)

    async def test_policy_excludes_expected_tools_when_prefixed(self) -> None:
        """The same holds when the API is mounted under a prefix."""
        names = await self._tool_names('/api')

        self.assertIn('list_projects', names)
        self.assertNotIn('login', names)
        self.assertNotIn('set_configuration_value', names)

    async def test_serializable_spec_round_trips(self) -> None:
        """The spec used in tests is valid JSON (guards typos)."""
        self.assertIn('x-imbi-ai-tool', json.dumps(_spec()))


def _permission_spec(prefix: str = '') -> dict[str, object]:
    """Spec whose operations carry ``x-imbi-permission``.

    ``prefix`` mounts every path under a deployment prefix, as imbi-api
    does when ``IMBI_API_URL`` carries a path. The profile operation is
    flagged off-limits for AI so it never joins the toolset -- it is
    here only because it is what :func:`imbi.common.mcp.mount_prefix`
    reads the prefix from.
    """
    return _openapi_spec(
        {
            f'{prefix}/users/me': {
                'get': {
                    'operationId': 'get_current_user_profile',
                    'x-imbi-ai-tool': False,
                    **OK,
                }
            },
            f'{prefix}/projects/': {
                'get': {
                    'operationId': 'list_projects',
                    'x-imbi-permission': ['project:read'],
                    **OK,
                },
                'post': {
                    'operationId': 'create_project',
                    'x-imbi-permission': ['project:write'],
                    **OK,
                },
            },
            f'{prefix}/graph/query': {
                'post': {
                    'operationId': 'graph_query',
                    'x-imbi-permission': ['admin'],
                    **OK,
                }
            },
            f'{prefix}/ungated': {'get': {'operationId': 'ungated_op', **OK}},
        }
    )


class PermissionFilterMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    """Per-caller filtering of ``tools/list``."""

    async def _tool_names(
        self,
        handler: typing.Callable[[httpx.Request], httpx.Response],
        prefix: str = '',
    ) -> set[str]:
        """Build a filtered server and list its tools.

        ``handler`` stands in for the API, answering the middleware's
        profile lookup. ``prefix`` mounts the spec under a deployment
        path prefix.
        """
        spec = _permission_spec(prefix)
        client = httpx.AsyncClient(
            base_url='http://localhost:8000',
            transport=httpx.MockTransport(handler),
        )
        try:
            server = fastmcp.FastMCP.from_openapi(
                openapi_spec=spec,
                client=client,
                name='Imbi',
                route_maps=mcp.excluded_route_maps(spec),
                route_map_fn=mcp.exclude_non_ai_tools,
                mcp_component_fn=mcp.copy_permissions_to_meta,
            )
            server.add_middleware(mcp.PermissionFilterMiddleware(client, spec))
            async with fastmcp.Client(server) as connected:
                return {tool.name for tool in await connected.list_tools()}
        finally:
            await client.aclose()

    @staticmethod
    def _profile(
        *, is_admin: bool, permissions: list[str]
    ) -> typing.Callable[[httpx.Request], httpx.Response]:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={'is_admin': is_admin, 'permissions': permissions},
            )

        return handler

    async def test_filters_tools_caller_cannot_invoke(self) -> None:
        """Only tools whose permissions the caller holds survive."""
        names = await self._tool_names(
            self._profile(is_admin=False, permissions=['project:read'])
        )
        self.assertEqual({'list_projects', 'ungated_op'}, names)

    async def test_profile_lookup_uses_the_mount_prefix(self) -> None:
        """The lookup targets the spec's path, not a bare ``/users/me``.

        imbi-api mounts its routers under the path of ``IMBI_API_URL``
        while the client's ``base_url`` has no path, so a hard-coded
        ``/users/me`` 404s and filtering silently fails open.
        """
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(request.url.path)
            return httpx.Response(
                200, json={'is_admin': False, 'permissions': ['project:read']}
            )

        names = await self._tool_names(handler, prefix='/api')

        self.assertEqual(['/api/users/me'], requested)
        self.assertEqual({'list_projects', 'ungated_op'}, names)

    async def test_admin_sees_every_tool(self) -> None:
        """Admins bypass filtering, matching the API's own bypass."""
        names = await self._tool_names(
            self._profile(is_admin=True, permissions=[])
        )
        self.assertEqual(
            {'list_projects', 'create_project', 'graph_query', 'ungated_op'},
            names,
        )

    async def test_admin_only_tool_hidden_from_non_admin(self) -> None:
        """The ``admin`` sentinel is never satisfied by a permission."""
        names = await self._tool_names(
            self._profile(is_admin=False, permissions=['admin'])
        )
        self.assertNotIn('graph_query', names)

    async def test_fails_open_on_profile_error(self) -> None:
        """A failed lookup returns the unfiltered list, not an empty one."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        with self.assertLogs('imbi.common.mcp', level='WARNING'):
            names = await self._tool_names(handler)
        self.assertEqual(
            {'list_projects', 'create_project', 'graph_query', 'ungated_op'},
            names,
        )

    async def test_fails_open_on_transport_error(self) -> None:
        """A connection failure also fails open."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError('boom')

        with self.assertLogs('imbi.common.mcp', level='WARNING'):
            names = await self._tool_names(handler)
        self.assertEqual(4, len(names))

    async def test_fails_open_on_non_object_profile(self) -> None:
        """Well-formed JSON that is not an object also fails open."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=['not', 'a', 'profile'])

        with self.assertLogs('imbi.common.mcp', level='WARNING'):
            names = await self._tool_names(handler)
        self.assertEqual(4, len(names))


class PermissionCacheTests(unittest.IsolatedAsyncioTestCase):
    """Profile caching in :class:`PermissionFilterMiddleware`."""

    def setUp(self) -> None:
        self.calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(request.headers.get('authorization', ''))
            return httpx.Response(
                200, json={'is_admin': False, 'permissions': ['project:read']}
            )

        self.client = httpx.AsyncClient(
            base_url='http://localhost:8000',
            transport=httpx.MockTransport(handler),
        )
        self.middleware = mcp.PermissionFilterMiddleware(
            self.client, _permission_spec()
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def _resolve(self, token: str | None) -> None:
        """Resolve permissions as though called with ``token``."""
        headers = {'authorization': token} if token else {}
        with unittest.mock.patch.object(
            mcp, 'get_http_headers', return_value=headers
        ):
            await self.middleware._caller_permissions()

    async def test_repeated_lookups_hit_the_cache(self) -> None:
        """The same credential resolves without a second request."""
        await self._resolve('Bearer token-a')
        await self._resolve('Bearer token-a')
        self.assertEqual(1, len(self.calls))

    async def test_distinct_credentials_are_not_shared(self) -> None:
        """A second caller must not inherit the first one's profile."""
        await self._resolve('Bearer token-a')
        await self._resolve('Bearer token-b')
        self.assertEqual(2, len(self.calls))

    async def test_expired_entry_is_refetched(self) -> None:
        """Past the TTL the profile is resolved again."""
        await self._resolve('Bearer token-a')
        with unittest.mock.patch.object(
            cache.time,
            'monotonic',
            return_value=time.monotonic()
            + mcp.PermissionFilterMiddleware.CACHE_TTL_SECONDS
            + 1,
        ):
            await self._resolve('Bearer token-a')
        self.assertEqual(2, len(self.calls))

    async def test_anonymous_callers_are_not_cached(self) -> None:
        """With no credential there is no key to cache under."""
        await self._resolve(None)
        await self._resolve(None)
        self.assertEqual(2, len(self.calls))

    async def test_cache_is_bounded(self) -> None:
        """The cache never grows past its maximum size."""
        limit = mcp.PermissionFilterMiddleware.CACHE_MAX_ENTRIES
        for index in range(limit + 10):
            await self._resolve(f'Bearer token-{index}')
        self.assertLessEqual(
            len(self.middleware._cache),
            limit,
        )


class RequiredPermissionsTests(unittest.IsolatedAsyncioTestCase):
    """Unit tests for :func:`imbi.common.mcp.required_permissions`."""

    async def test_reads_permissions_recorded_on_meta(self) -> None:
        """``copy_permissions_to_meta`` makes permissions readable."""
        client = httpx.AsyncClient(base_url='http://localhost:8000')
        try:
            server = fastmcp.FastMCP.from_openapi(
                openapi_spec=_permission_spec(),
                client=client,
                name='Imbi',
                mcp_component_fn=mcp.copy_permissions_to_meta,
            )
            found = {
                tool.name: mcp.required_permissions(tool)
                for tool in await server.list_tools()
            }
        finally:
            await client.aclose()
        self.assertEqual(['project:read'], found['list_projects'])
        self.assertEqual(['admin'], found['graph_query'])
        self.assertEqual([], found['ungated_op'])

    async def test_meta_survives_the_mcp_protocol(self) -> None:
        """Permissions reach a connected client, not just the server.

        ``meta`` is a public field, so it is carried over the wire --
        this guards the coupling that reading a private ``_route``
        attribute previously created.
        """
        client = httpx.AsyncClient(base_url='http://localhost:8000')
        try:
            server = fastmcp.FastMCP.from_openapi(
                openapi_spec=_permission_spec(),
                client=client,
                name='Imbi',
                mcp_component_fn=mcp.copy_permissions_to_meta,
            )
            async with fastmcp.Client(server) as connected:
                tools = {
                    tool.name: tool for tool in await connected.list_tools()
                }
        finally:
            await client.aclose()
        self.assertEqual(
            ['project:read'],
            mcp.required_permissions(tools['list_projects']),
        )
        self.assertEqual([], mcp.required_permissions(tools['ungated_op']))

    def test_non_openapi_tool_has_no_permissions(self) -> None:
        """A tool with no recorded meta yields an empty list."""
        not_a_tool = typing.cast(typing.Any, object())
        self.assertEqual([], mcp.required_permissions(not_a_tool))


class _StubApp:
    """ASGI app that answers 200 with an empty body."""

    async def __call__(
        self,
        _scope: dict[str, typing.Any],
        _receive: typing.Any,
        send: typing.Any,
    ) -> None:
        await send(
            {'type': 'http.response.start', 'status': 200, 'headers': []}
        )
        await send({'type': 'http.response.body', 'body': b''})


async def _logged_principal(credential: bytes) -> str:
    """Return the principal the access log renders for ``credential``.

    Exercises the label cache through the middleware that reads it,
    rather than reaching into its internals.
    """

    async def receive() -> typing.Any:  # pragma: no cover - not awaited
        raise AssertionError('receive should not be called')

    async def send(_message: typing.Any) -> None:
        return None

    middleware = access_log.AccessLogMiddleware(
        _StubApp(), logger=logging.getLogger('imbi.common.tests.access')
    )
    scope: dict[str, typing.Any] = {
        'type': 'http',
        'http_version': '1.1',
        'method': 'POST',
        'path': '/mcp',
        'query_string': b'',
        'client': ('10.0.0.1', 0),
        'headers': [(b'authorization', credential)],
    }
    with unittest.TestCase().assertLogs(
        'imbi.common.tests.access', level=logging.INFO
    ) as logs:
        await middleware(scope, receive, send)
    return logs.records[0].getMessage().split(' - ', 1)[1].split(' "', 1)[0]


class RememberApiKeyOwnerTestCase(unittest.IsolatedAsyncioTestCase):
    """The profile lookup labels an API key's owner for the access log."""

    def setUp(self) -> None:
        access_log.clear_api_key_principals()
        self.addCleanup(access_log.clear_api_key_principals)

    async def test_user_owned_key_logs_the_email(self) -> None:
        """A user-owned key renders the owner, not the opaque key id."""
        mcp._remember_api_key_owner(  # pyright: ignore[reportPrivateUsage]
            'Bearer ik_abc123_secret', {'email': 'gavinr@aweber.com'}
        )
        self.assertEqual(
            'gavinr@aweber.com',
            await _logged_principal(b'Bearer ik_abc123_secret'),
        )

    async def test_profile_without_email_is_ignored(self) -> None:
        """A profile with no email (service account) adds no label."""
        mcp._remember_api_key_owner(  # pyright: ignore[reportPrivateUsage]
            'Bearer ik_abc123_secret', {'is_admin': False}
        )
        self.assertEqual(
            'ik_abc123',
            await _logged_principal(b'Bearer ik_abc123_secret'),
        )

    async def test_jwt_credential_is_ignored(self) -> None:
        """A JWT caller needs no label; the cache stays untouched."""
        mcp._remember_api_key_owner(  # pyright: ignore[reportPrivateUsage]
            'Bearer header.payload.signature', {'email': 'a@b.com'}
        )
        self.assertEqual(
            'ik_abc123',
            await _logged_principal(b'Bearer ik_abc123_secret'),
        )

    async def test_missing_credential_is_ignored(self) -> None:
        """An unauthenticated lookup has no key to label."""
        mcp._remember_api_key_owner(  # pyright: ignore[reportPrivateUsage]
            None, {'email': 'a@b.com'}
        )
        self.assertEqual(
            'ik_abc123',
            await _logged_principal(b'Bearer ik_abc123_secret'),
        )

    async def test_labels_the_caller_from_the_profile_lookup(self) -> None:
        """PermissionFilterMiddleware's own lookup populates the label."""
        spec = _permission_spec()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    'email': 'gavinr@aweber.com',
                    'is_admin': False,
                    'permissions': ['project:read'],
                },
            )

        client = httpx.AsyncClient(
            base_url='http://localhost:8000',
            transport=httpx.MockTransport(handler),
        )
        try:
            server = fastmcp.FastMCP.from_openapi(
                openapi_spec=spec,
                client=client,
                name='Imbi',
                mcp_component_fn=mcp.copy_permissions_to_meta,
            )
            server.add_middleware(mcp.PermissionFilterMiddleware(client, spec))
            with unittest.mock.patch.object(
                mcp,
                'get_http_headers',
                return_value={'authorization': 'Bearer ik_abc123_secret'},
            ):
                async with fastmcp.Client(server) as connected:
                    await connected.list_tools()
        finally:
            await client.aclose()
        self.assertEqual(
            'gavinr@aweber.com',
            await _logged_principal(b'Bearer ik_abc123_secret'),
        )


class AccessLogContextMiddlewareTestCase(unittest.IsolatedAsyncioTestCase):
    """The invoked tool name reaches the HTTP access log line."""

    async def test_tool_name_is_logged(self) -> None:
        """A tool call renders as ``(tool:<name>)`` on the log line."""
        server = fastmcp.FastMCP(name='proto')

        @server.tool
        def ping(name: str) -> str:
            """Ping."""
            return f'hi {name}'

        server.add_middleware(mcp.AccessLogContextMiddleware())
        app = server.http_app(
            middleware=[
                starlette.middleware.Middleware(access_log.AccessLogMiddleware)
            ],
            stateless_http=True,
        )
        request = {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'tools/call',
            'params': {'name': 'ping', 'arguments': {'name': 'bob'}},
        }
        with self.assertLogs('imbi.common.access', level='INFO') as logs:
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url='http://mcp'
                ) as client:
                    response = await client.post(
                        '/mcp',
                        json=request,
                        headers={
                            'accept': 'application/json, text/event-stream',
                            'content-type': 'application/json',
                        },
                    )
        self.assertEqual(200, response.status_code)
        self.assertIn('(tool:ping)', logs.records[0].getMessage())

    async def test_no_http_request_is_a_noop(self) -> None:
        """Under stdio there is no request to annotate; the call runs."""
        middleware = mcp.AccessLogContextMiddleware()
        context = unittest.mock.Mock()
        called = False

        async def call_next(_context: typing.Any) -> str:
            nonlocal called
            called = True
            return 'ok'

        with unittest.mock.patch.object(
            mcp,
            'get_http_request',
            side_effect=RuntimeError('No active HTTP request found.'),
        ):
            self.assertEqual(
                'ok', await middleware.on_call_tool(context, call_next)
            )
        self.assertTrue(called)
