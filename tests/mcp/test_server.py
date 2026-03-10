import json
import unittest
from unittest import mock

import fastmcp
import httpx

import imbi_mcp
from imbi_mcp import server


def _minimal_openapi_spec() -> dict:  # type: ignore[type-arg]
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
        },
    }


class CreateServerTests(unittest.TestCase):
    def setUp(self) -> None:
        spec = _minimal_openapi_spec()
        self.mock_response = httpx.Response(
            200,
            content=json.dumps(spec).encode(),
            headers={'content-type': 'application/json'},
            request=httpx.Request(
                'GET', 'http://localhost:8000/openapi.json'
            ),
        )

    @mock.patch('imbi_mcp.server.httpx.get')
    def test_returns_fastmcp_instance(
        self, mock_get: mock.Mock
    ) -> None:
        mock_get.return_value = self.mock_response
        mcp = server.create_server('http://localhost:8000')
        self.assertIsInstance(mcp, fastmcp.FastMCP)

    @mock.patch('imbi_mcp.server.httpx.get')
    def test_server_name(self, mock_get: mock.Mock) -> None:
        mock_get.return_value = self.mock_response
        mcp = server.create_server('http://localhost:8000')
        self.assertEqual('Imbi', mcp.name)

    @mock.patch('imbi_mcp.server.httpx.get')
    def test_server_version(
        self, mock_get: mock.Mock
    ) -> None:
        mock_get.return_value = self.mock_response
        mcp = server.create_server('http://localhost:8000')
        self.assertEqual(imbi_mcp.version, mcp.version)

    @mock.patch('imbi_mcp.server.httpx.get')
    def test_fetches_spec_from_api_url(
        self, mock_get: mock.Mock
    ) -> None:
        mock_get.return_value = self.mock_response
        server.create_server('http://example:9000')
        mock_get.assert_called_once_with(
            'http://example:9000/openapi.json', timeout=30
        )

    @mock.patch('imbi_mcp.server.httpx.get')
    def test_strips_trailing_slash(
        self, mock_get: mock.Mock
    ) -> None:
        mock_get.return_value = self.mock_response
        server.create_server('http://example:9000/')
        mock_get.assert_called_once_with(
            'http://example:9000/openapi.json', timeout=30
        )


class InjectAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_injects_authorization_header(self) -> None:
        request = httpx.Request('GET', 'http://localhost/')
        with mock.patch(
            'imbi_mcp.server.get_http_headers',
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
            'imbi_mcp.server.get_http_headers',
            return_value={},
        ):
            await server._inject_auth(request)
        self.assertNotIn('authorization', request.headers)

    async def test_calls_get_http_headers_with_include(
        self,
    ) -> None:
        request = httpx.Request('GET', 'http://localhost/')
        with mock.patch(
            'imbi_mcp.server.get_http_headers',
            return_value={},
        ) as mock_fn:
            await server._inject_auth(request)
        mock_fn.assert_called_once_with(
            include={'authorization'}
        )
