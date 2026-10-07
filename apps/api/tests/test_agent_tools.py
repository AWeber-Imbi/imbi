"""Tests for the agent tool catalog."""

import asyncio
import json
import typing
import unittest
from unittest import mock

import httpx
from mcp import types as mcp_types

from imbi.api import agent_tools
from imbi.common import graph, models


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


def _server(slug: str, **overrides: typing.Any) -> models.MCPServer:
    return models.MCPServer(
        name=slug.title(),
        slug=slug,
        url='https://mcp.example.com/mcp',  # type: ignore[arg-type]
        **overrides,
    )


def _mcp_tool(
    name: str, annotations: mcp_types.ToolAnnotations | None = None
) -> mcp_types.Tool:
    return mcp_types.Tool(
        name=name,
        description=f'{name} description',
        inputSchema={'type': 'object'},
        annotations=annotations,
    )


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
    def setUp(self) -> None:
        self.db = mock.AsyncMock(spec=graph.Graph)
        self.servers = [
            _server('github', ignored_tools=['delete_repo']),
            _server('sentry'),
        ]
        self.db.match.return_value = self.servers
        self.listed: dict[str, list[mcp_types.Tool] | Exception] = {
            'github': [
                _mcp_tool(
                    'read_file', mcp_types.ToolAnnotations(readOnlyHint=True)
                ),
                _mcp_tool(
                    'create_pr', mcp_types.ToolAnnotations(readOnlyHint=False)
                ),
                _mcp_tool(
                    'delete_repo',
                    mcp_types.ToolAnnotations(destructiveHint=True),
                ),
            ],
            'sentry': ConnectionError(
                'connection refused: http://10.0.0.5:8080/mcp?token=s3cret'
            ),
        }

        async def list_tools(
            server: models.MCPServer, timeout_s: float | None = None
        ) -> list[mcp_types.Tool]:
            result = self.listed[server.slug]
            if isinstance(result, Exception):
                raise result
            return result

        patcher = mock.patch.object(
            agent_tools.mcp_test, 'list_tools', side_effect=list_tools
        )
        self.list_tools = patcher.start()
        self.addCleanup(patcher.stop)

    def _group(
        self, catalog: agent_tools.AgentToolCatalog, slug: str
    ) -> agent_tools.AgentToolGroup:
        (group,) = [g for g in catalog.groups if g.server.slug == slug]
        return group

    async def test_build_catalog(self) -> None:
        catalog = await agent_tools.build_catalog(self.db, SPEC)
        self.db.match.assert_awaited_once_with(
            models.MCPServer, {'enabled': True}, order_by='name'
        )
        self.assertEqual(
            [g.server.slug for g in catalog.groups],
            ['imbi', 'github', 'sentry'],
        )

        github = self._group(catalog, 'github')
        self.assertEqual(github.server.transport, 'mcp/http')
        self.assertEqual(github.server.name, 'Github')
        self.assertIsNone(github.error)
        # ``delete_repo`` is in ignored_tools.
        self.assertEqual(
            [(t.key, t.capability) for t in github.tools],
            [('github.create_pr', 'write'), ('github.read_file', 'read')],
        )
        self.assertEqual(github.tools[1].description, 'read_file description')

        sentry = self._group(catalog, 'sentry')
        self.assertEqual(sentry.tools, [])
        self.assertEqual(sentry.error, 'unreachable')

    async def test_imbi_group(self) -> None:
        group = self._group(
            await agent_tools.build_catalog(self.db, SPEC), 'imbi'
        )
        self.assertEqual(group.server.transport, 'internal')
        self.assertIsNone(group.error)
        tools = {t.key: t for t in group.tools}
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

    async def test_imbi_group_error(self) -> None:
        group = self._group(
            await agent_tools.build_catalog(self.db, {'paths': {}}), 'imbi'
        )
        self.assertEqual(group.tools, [])
        self.assertIsNotNone(group.error)

    async def test_server_timeout(self) -> None:
        async def slow(
            server: models.MCPServer, timeout_s: float | None = None
        ) -> list[mcp_types.Tool]:
            await asyncio.sleep(1)
            return []

        self.list_tools.side_effect = slow
        self.db.match.return_value = [_server('slow', timeout=0)]
        catalog = await agent_tools.build_catalog(self.db, SPEC)
        group = self._group(catalog, 'slow')
        self.assertEqual(group.error, 'timeout')

    async def test_server_timeout_is_capped(self) -> None:
        self.db.match.return_value = [_server('github', timeout=60)]
        await agent_tools.build_catalog(self.db, SPEC)
        self.assertEqual(
            self.list_tools.await_args.args[1],
            agent_tools.SERVER_TIMEOUT_SECONDS,
        )

    async def test_error_codes(self) -> None:
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
                self.listed['sentry'] = err
                catalog = await agent_tools.build_catalog(self.db, SPEC)
                self.assertEqual(
                    self._group(catalog, 'sentry').error, expected
                )

    async def test_error_text_is_not_in_the_catalog(self) -> None:
        with self.assertLogs(agent_tools.LOGGER, 'WARNING') as logs:
            catalog = await agent_tools.build_catalog(self.db, SPEC)
        self.assertNotIn('s3cret', catalog.model_dump_json())
        self.assertNotIn('10.0.0.5', catalog.model_dump_json())
        # The full error goes to the log, with the server slug.
        self.assertIn("'sentry'", logs.output[0])
        self.assertIn('s3cret', logs.output[0])

    async def test_cache_holds_only_codes(self) -> None:
        client = mock.AsyncMock()
        client.get.return_value = None
        await agent_tools.get_catalog(self.db, client, lambda: SPEC)
        stored = client.set.await_args.args[1]
        self.assertNotIn('s3cret', stored)
        self.assertNotIn('connection refused', stored)
        self.assertIn('"error":"unreachable"', stored)


class CacheTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = mock.AsyncMock(spec=graph.Graph)
        self.valkey = mock.AsyncMock()
        self.catalog = agent_tools.AgentToolCatalog(
            groups=[
                agent_tools.AgentToolGroup(
                    server=agent_tools.AgentToolServer(
                        slug='imbi', name='Imbi', transport='internal'
                    )
                )
            ],
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
        result = await agent_tools.get_catalog(self.db, self.valkey, self.spec)
        self.assertEqual(result, self.catalog)
        self.build.assert_not_awaited()
        self.spec.assert_not_called()
        self.valkey.set.assert_not_awaited()

    async def test_cache_miss_stores(self) -> None:
        self.valkey.get.return_value = None
        result = await agent_tools.get_catalog(self.db, self.valkey, self.spec)
        self.assertEqual(result, self.catalog)
        self.build.assert_awaited_once_with(self.db, SPEC)
        self.valkey.set.assert_awaited_once_with(
            agent_tools.CACHE_KEY,
            self.catalog.model_dump_json(),
            ex=agent_tools.CACHE_TTL_SECONDS,
        )

    async def test_refresh_skips_cache(self) -> None:
        result = await agent_tools.get_catalog(
            self.db, self.valkey, self.spec, refresh=True
        )
        self.assertEqual(result, self.catalog)
        self.valkey.get.assert_not_awaited()
        self.build.assert_awaited_once()
        self.valkey.set.assert_awaited_once()

    async def test_entry_with_error_text_is_replaced(self) -> None:
        # An entry from an earlier release can hold the error text.
        entry = json.loads(self.catalog.model_dump_json())
        entry['groups'][0]['error'] = 'connection refused: 10.0.0.5'
        self.valkey.get.return_value = json.dumps(entry).encode()
        result = await agent_tools.get_catalog(self.db, self.valkey, self.spec)
        self.assertEqual(result, self.catalog)
        self.build.assert_awaited_once()
        self.valkey.set.assert_awaited_once()

    async def test_malformed_entry_is_replaced(self) -> None:
        self.valkey.get.return_value = b'{"groups": 1}'
        await agent_tools.get_catalog(self.db, self.valkey, self.spec)
        self.build.assert_awaited_once()
        self.valkey.set.assert_awaited_once()

    async def test_valkey_errors_are_ignored(self) -> None:
        self.valkey.get.side_effect = ConnectionError('down')
        self.valkey.set.side_effect = ConnectionError('down')
        result = await agent_tools.get_catalog(self.db, self.valkey, self.spec)
        self.assertEqual(result, self.catalog)

    async def test_without_valkey(self) -> None:
        result = await agent_tools.get_catalog(self.db, None, self.spec)
        self.assertEqual(result, self.catalog)
        self.build.assert_awaited_once()
