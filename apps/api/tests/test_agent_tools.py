"""Tests for the agent tool catalog."""

import json
import typing
import unittest
from unittest import mock

import httpx
from mcp import types as mcp_types

from imbi.api import agent_tools


def _operation(
    operation_id: str, **extra: typing.Any
) -> dict[str, typing.Any]:
    return {
        'operationId': operation_id,
        'summary': operation_id,
        'description': f'Do {operation_id}.\n\nMore text.',
        'responses': {'200': {'description': 'OK'}},
        **extra,
    }


SPEC: dict[str, typing.Any] = {
    'openapi': '3.1.0',
    'info': {'title': 'Imbi', 'version': '1'},
    'paths': {
        '/api/users/me': {'get': _operation('get_me')},
        '/api/projects': {
            'get': _operation('list_projects'),
            'post': _operation('create_project'),
        },
        '/api/projects/{id}': {
            'delete': {
                **_operation('delete_project'),
                'parameters': [
                    {
                        'name': 'id',
                        'in': 'path',
                        'required': True,
                        'schema': {'type': 'string'},
                    }
                ],
            },
        },
        '/api/secrets': {
            'get': _operation('list_secrets', **{'x-imbi-ai-tool': False})
        },
        '/api/auth/login': {'post': _operation('login')},
    },
}


class CapabilityTestCase(unittest.TestCase):
    def test_capability(self) -> None:
        a = mcp_types.ToolAnnotations
        for annotations, expected in (
            (None, 'unknown'),
            (a(title='Only a title'), 'unknown'),
            (a(readOnlyHint=True), 'read'),
            (a(readOnlyHint=True, destructiveHint=True), 'read'),
            (a(destructiveHint=True), 'destructive'),
            (a(readOnlyHint=False), 'write'),
            (a(readOnlyHint=False, destructiveHint=False), 'write'),
        ):
            with self.subTest(annotations=annotations):
                self.assertEqual(agent_tools.capability(annotations), expected)

    def test_summary(self) -> None:
        self.assertIsNone(agent_tools._summary(None))
        self.assertEqual(
            agent_tools._summary('  First\nline.\n\nSecond.'), 'First line.'
        )
        long = agent_tools._summary('x' * 400)
        assert long is not None
        self.assertEqual(len(long), agent_tools.DESCRIPTION_LENGTH)
        self.assertTrue(long.endswith('…'))


class CatalogTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_imbi_tools(self) -> None:
        catalog = await agent_tools.build_catalog(SPEC)
        self.assertIsNone(catalog.error)
        tools = {t.key: t for t in catalog.tools}
        # Excluded: the auth route and the x-imbi-ai-tool: false route.
        self.assertEqual(
            sorted(tools),
            [
                'imbi.create_project',
                'imbi.delete_project',
                'imbi.get_me',
                'imbi.list_projects',
            ],
        )
        self.assertEqual(tools['imbi.list_projects'].capability, 'read')
        self.assertEqual(tools['imbi.create_project'].capability, 'write')
        self.assertEqual(
            tools['imbi.delete_project'].capability, 'destructive'
        )

    async def test_error(self) -> None:
        with self.assertLogs(agent_tools.LOGGER, 'ERROR'):
            catalog = await agent_tools.build_catalog({'paths': {}})
        self.assertEqual(catalog.tools, [])
        self.assertIsNotNone(catalog.error)

    def test_error_codes(self) -> None:
        request = httpx.Request('POST', 'https://mcp.example.com/mcp')

        def status(code: int) -> httpx.HTTPStatusError:
            return httpx.HTTPStatusError(
                'bad token',
                request=request,
                response=httpx.Response(code, request=request),
            )

        wrapped = RuntimeError('session failed')
        wrapped.__cause__ = status(403)
        for err, expected in (
            (status(401), 'auth_failed'),
            (ExceptionGroup('task group', [status(401)]), 'auth_failed'),
            (wrapped, 'auth_failed'),
            (status(500), 'unreachable'),
            (httpx.ReadTimeout('slow', request=request), 'timeout'),
            (ExceptionGroup('task group', [ValueError('x')]), 'unreachable'),
        ):
            with self.subTest(err=err):
                self.assertEqual(agent_tools._error_code(err), expected)


class CacheTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.valkey = mock.AsyncMock()
        self.catalog = agent_tools.AgentToolCatalog(
            generated_at='2026-10-06T12:00:00Z',  # type: ignore[arg-type]
        )
        patcher = mock.patch.object(
            agent_tools, 'build_catalog', return_value=self.catalog
        )
        self.build = patcher.start()
        self.addCleanup(patcher.stop)
        self.spec = mock.Mock(return_value=SPEC)

    async def test_cache_hit(self) -> None:
        self.valkey.get.return_value = self.catalog.model_dump_json().encode()
        result = await agent_tools.get_catalog(self.valkey, self.spec)
        self.assertEqual(result, self.catalog)
        self.build.assert_not_awaited()
        self.spec.assert_not_called()
        self.valkey.set.assert_not_awaited()

    async def test_cache_miss_stores(self) -> None:
        self.valkey.get.return_value = None
        result = await agent_tools.get_catalog(self.valkey, self.spec)
        self.assertEqual(result, self.catalog)
        self.build.assert_awaited_once_with(SPEC)
        self.valkey.set.assert_awaited_once_with(
            agent_tools.CACHE_KEY,
            self.catalog.model_dump_json(),
            ex=agent_tools.CACHE_TTL_SECONDS,
        )

    async def test_refresh_skips_cache(self) -> None:
        result = await agent_tools.get_catalog(
            self.valkey, self.spec, refresh=True
        )
        self.assertEqual(result, self.catalog)
        self.valkey.get.assert_not_awaited()
        self.build.assert_awaited_once()
        self.valkey.set.assert_awaited_once()

    async def test_entry_with_error_text_is_replaced(self) -> None:
        # An entry from an earlier release can hold the error text.
        entry = json.loads(self.catalog.model_dump_json())
        entry['error'] = 'connection refused: 10.0.0.5'
        self.valkey.get.return_value = json.dumps(entry).encode()
        result = await agent_tools.get_catalog(self.valkey, self.spec)
        self.assertEqual(result, self.catalog)
        self.build.assert_awaited_once()
        self.valkey.set.assert_awaited_once()

    async def test_grouped_entry_is_replaced(self) -> None:
        # An entry from an earlier release has the tools in groups.
        self.valkey.get.return_value = (
            b'{"groups": [], "generated_at": "2026-10-06T12:00:00Z"}'
        )
        result = await agent_tools.get_catalog(self.valkey, self.spec)
        self.assertEqual(result, self.catalog)
        self.build.assert_awaited_once()

    async def test_malformed_entry_is_replaced(self) -> None:
        self.valkey.get.return_value = b'{"tools": 1}'
        await agent_tools.get_catalog(self.valkey, self.spec)
        self.build.assert_awaited_once()
        self.valkey.set.assert_awaited_once()

    async def test_valkey_errors_are_ignored(self) -> None:
        self.valkey.get.side_effect = ConnectionError('down')
        self.valkey.set.side_effect = ConnectionError('down')
        result = await agent_tools.get_catalog(self.valkey, self.spec)
        self.assertEqual(result, self.catalog)

    async def test_without_valkey(self) -> None:
        result = await agent_tools.get_catalog(None, self.spec)
        self.assertEqual(result, self.catalog)
        self.build.assert_awaited_once()
