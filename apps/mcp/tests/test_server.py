import json
import typing
import unittest
from unittest import mock

import fastmcp
import httpx
import jwt
from fastmcp.server.auth.auth import AccessToken, RemoteAuthProvider
from fastmcp.server.providers.openapi import MCPType
from starlette import testclient as starlette_testclient

import imbi.mcp
from imbi.mcp import server


def _minimal_openapi_spec() -> dict[str, object]:
    return {
        'openapi': '3.1.0',
        'info': {'title': 'Imbi', 'version': '2.0.0a0'},
        'paths': {
            '/projects/': {
                'get': {
                    'operationId': 'list_projects',
                    'summary': 'List projects',
                    'responses': {
                        '200': {'description': 'OK'},
                    },
                },
            },
            '/auth/login': {
                'post': {
                    'operationId': 'login',
                    'summary': 'Login',
                    'responses': {
                        '200': {'description': 'OK'},
                    },
                },
            },
            '/status': {
                'get': {
                    'operationId': 'status',
                    'summary': 'Status',
                    'responses': {
                        '200': {'description': 'OK'},
                    },
                },
            },
            '/organizations/{org_slug}/projects/{id}/configuration/{key}': {
                'put': {
                    'operationId': 'set_configuration_value',
                    'summary': 'Set configuration value',
                    'x-imbi-ai-tool': False,
                    'responses': {
                        '200': {'description': 'OK'},
                    },
                },
            },
        },
    }


class CreateServerTests(unittest.TestCase):
    def setUp(self) -> None:
        spec = _minimal_openapi_spec()
        self.mock_response = httpx.Response(
            200,
            content=json.dumps(spec).encode(),
            headers={'content-type': 'application/json'},
            request=httpx.Request('GET', 'http://localhost:8000/openapi.json'),
        )

    @mock.patch('imbi.mcp.server.httpx.get')
    def test_returns_fastmcp_instance(self, mock_get: mock.Mock) -> None:
        mock_get.return_value = self.mock_response
        mcp = server.create_server('http://localhost:8000')
        self.assertIsInstance(mcp, fastmcp.FastMCP)

    @mock.patch('imbi.mcp.server.httpx.get')
    def test_server_name(self, mock_get: mock.Mock) -> None:
        mock_get.return_value = self.mock_response
        mcp = server.create_server('http://localhost:8000')
        self.assertEqual('Imbi', mcp.name)

    @mock.patch('imbi.mcp.server.httpx.get')
    def test_server_version(self, mock_get: mock.Mock) -> None:
        mock_get.return_value = self.mock_response
        mcp = server.create_server('http://localhost:8000')
        self.assertEqual(imbi.mcp.version, mcp.version)

    @mock.patch('imbi.mcp.server.httpx.get')
    def test_status_custom_route(self, mock_get: mock.Mock) -> None:
        mock_get.return_value = self.mock_response
        mcp = server.create_server('http://localhost:8000')
        with starlette_testclient.TestClient(mcp.http_app()) as client:
            response = client.get('/status')
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                'service': 'imbi-mcp',
                'status': 'ok',
                'version': imbi.mcp.version,
            },
            response.json(),
        )

    @mock.patch('imbi.mcp.server.httpx.get')
    def test_status_custom_route_with_auth_enabled(
        self, mock_get: mock.Mock
    ) -> None:
        mock_get.return_value = self.mock_response
        mcp = server.create_server(
            'http://localhost:8000',
            public_url='https://host/mcp',
            auth_server_url='https://host',
        )
        with starlette_testclient.TestClient(mcp.http_app()) as client:
            response = client.get('/status')
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                'service': 'imbi-mcp',
                'status': 'ok',
                'version': imbi.mcp.version,
            },
            response.json(),
        )

    @mock.patch('imbi.mcp.server.httpx.get')
    def test_fetches_spec_from_api_url(self, mock_get: mock.Mock) -> None:
        mock_get.return_value = self.mock_response
        server.create_server('http://example:9000')
        mock_get.assert_called_once_with(
            'http://example:9000/openapi.json', timeout=30
        )

    @mock.patch('imbi.mcp.server.httpx.get')
    def test_strips_trailing_slash(self, mock_get: mock.Mock) -> None:
        mock_get.return_value = self.mock_response
        server.create_server('http://example:9000/')
        mock_get.assert_called_once_with(
            'http://example:9000/openapi.json', timeout=30
        )

    @mock.patch('imbi.mcp.server.httpx.get')
    @mock.patch('fastmcp.FastMCP.from_openapi')
    def test_route_maps_exclude_auth_and_status(
        self, mock_from_openapi: mock.Mock, mock_get: mock.Mock
    ) -> None:
        mock_get.return_value = self.mock_response
        mock_from_openapi.return_value = fastmcp.FastMCP(name='stub')
        server.create_server('http://example:9000')
        _, kwargs = mock_from_openapi.call_args
        route_maps = kwargs['route_maps']
        excluded = [rm for rm in route_maps if rm.mcp_type == MCPType.EXCLUDE]
        patterns = [rm.pattern for rm in excluded]
        self.assertIn(r'^/auth/', patterns)
        self.assertIn(r'^/mfa/', patterns)
        self.assertIn(r'^/status/?$', patterns)
        self.assertIn(r'.*/thumbnail/?$', patterns)

    @mock.patch('imbi.mcp.server.httpx.get')
    @mock.patch('fastmcp.FastMCP.from_openapi')
    def test_route_maps_classify_get_as_resources(
        self, mock_from_openapi: mock.Mock, mock_get: mock.Mock
    ) -> None:
        mock_get.return_value = self.mock_response
        mock_from_openapi.return_value = fastmcp.FastMCP(name='stub')
        server.create_server('http://example:9000')
        _, kwargs = mock_from_openapi.call_args
        route_maps = kwargs['route_maps']
        resource_maps = [
            rm
            for rm in route_maps
            if rm.mcp_type in (MCPType.RESOURCE, MCPType.RESOURCE_TEMPLATE)
        ]
        self.assertTrue(
            all('GET' in rm.methods for rm in resource_maps),
            'All resource route maps should specify GET method',
        )


class CreateServerExcludesConfigTests(unittest.IsolatedAsyncioTestCase):
    @mock.patch('imbi.mcp.server.httpx.get')
    async def test_flagged_endpoint_not_exposed(
        self, mock_get: mock.Mock
    ) -> None:
        spec = _minimal_openapi_spec()
        mock_get.return_value = httpx.Response(
            200,
            content=json.dumps(spec).encode(),
            headers={'content-type': 'application/json'},
            request=httpx.Request('GET', 'http://localhost:8000/openapi.json'),
        )
        mcp = server.create_server('http://localhost:8000')
        async with fastmcp.Client(mcp) as client:
            tools = await client.list_tools()
            resources = await client.list_resources()
        names = {t.name for t in tools}
        self.assertNotIn('set_configuration_value', names)
        # A non-flagged GET still becomes a resource, proving the spec
        # was processed rather than wholesale rejected.
        self.assertTrue(resources)


class InjectAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_injects_authorization_header(self) -> None:
        request = httpx.Request('GET', 'http://localhost/')
        with mock.patch(
            'imbi.mcp.server.get_http_headers',
            return_value={'authorization': 'Bearer test-jwt'},
        ):
            await server._inject_auth(request)
        self.assertEqual(
            'Bearer test-jwt',
            request.headers.get('authorization'),
        )

    async def test_no_header_when_absent(self) -> None:
        request = httpx.Request('GET', 'http://localhost/')
        with mock.patch(
            'imbi.mcp.server.get_http_headers',
            return_value={},
        ):
            await server._inject_auth(request)
        self.assertNotIn('authorization', request.headers)

    async def test_calls_get_http_headers_with_include(
        self,
    ) -> None:
        request = httpx.Request('GET', 'http://localhost/')
        with mock.patch(
            'imbi.mcp.server.get_http_headers',
            return_value={},
        ) as mock_fn:
            await server._inject_auth(request)
        mock_fn.assert_called_once_with(include={'authorization'})


class ImbiTokenVerifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_key_accepted_and_forwarded(self) -> None:
        verifier = server.ImbiTokenVerifier()
        token = await verifier.verify_token('ik_abc_secret')
        self.assertIsNotNone(token)
        token = typing.cast('AccessToken', token)
        self.assertEqual('ik_abc_secret', token.token)
        self.assertEqual('api-key', token.client_id)

    async def test_valid_access_jwt(self) -> None:
        claims = {
            'type': 'access',
            'sub': 'user@example.com',
            'scope': 'read write',
            'exp': 1234567890,
        }
        with mock.patch(
            'imbi.mcp.server.core.verify_token', return_value=claims
        ):
            token = await server.ImbiTokenVerifier().verify_token('jwt')
        self.assertIsNotNone(token)
        token = typing.cast('AccessToken', token)
        self.assertEqual('user@example.com', token.client_id)
        self.assertEqual(['read', 'write'], token.scopes)
        self.assertEqual(1234567890, token.expires_at)

    async def test_invalid_jwt_returns_none(self) -> None:
        with mock.patch(
            'imbi.mcp.server.core.verify_token',
            side_effect=jwt.InvalidTokenError('bad'),
        ):
            token = await server.ImbiTokenVerifier().verify_token('jwt')
        self.assertIsNone(token)

    async def test_non_access_token_rejected(self) -> None:
        with mock.patch(
            'imbi.mcp.server.core.verify_token',
            return_value={'type': 'refresh', 'sub': 'user@example.com'},
        ):
            token = await server.ImbiTokenVerifier().verify_token('jwt')
        self.assertIsNone(token)


class BuildAuthTests(unittest.TestCase):
    def test_none_when_unconfigured(self) -> None:
        self.assertIsNone(server._build_auth(None, None))
        self.assertIsNone(server._build_auth('https://host/mcp', None))
        self.assertIsNone(server._build_auth(None, 'https://host'))

    def test_provider_when_configured(self) -> None:
        provider = server._build_auth('https://host/mcp', 'https://host')
        self.assertIsInstance(provider, RemoteAuthProvider)


class CreateServerAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        spec = _minimal_openapi_spec()
        self.mock_response = httpx.Response(
            200,
            content=json.dumps(spec).encode(),
            headers={'content-type': 'application/json'},
            request=httpx.Request('GET', 'http://localhost:8000/openapi.json'),
        )

    @mock.patch('imbi.mcp.server.httpx.get')
    def test_auth_disabled_by_default(self, mock_get: mock.Mock) -> None:
        mock_get.return_value = self.mock_response
        mcp = server.create_server('http://localhost:8000')
        self.assertIsNone(mcp.auth)

    @mock.patch('imbi.mcp.server.httpx.get')
    def test_auth_enabled_when_configured(self, mock_get: mock.Mock) -> None:
        mock_get.return_value = self.mock_response
        mcp = server.create_server(
            'http://localhost:8000',
            public_url='https://host/mcp',
            auth_server_url='https://host',
        )
        self.assertIsInstance(mcp.auth, RemoteAuthProvider)
