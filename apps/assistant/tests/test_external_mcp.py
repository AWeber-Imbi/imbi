"""Tests for the external MCP server manager."""

import asyncio
import collections.abc
import contextlib
import json
import unittest
from unittest import mock

import anyio
import httpx

from imbi.assistant import external_mcp
from imbi.common import models as common_models


def _make_server(**overrides: object) -> common_models.MCPServer:
    """Build an MCPServer node with sensible defaults."""
    data: dict[str, object] = {
        'name': 'Example',
        'slug': 'example',
        'url': 'https://mcp.example.com/mcp',
    }
    data.update(overrides)
    return common_models.MCPServer(**data)


def _make_tool(
    name: str,
    description: str | None = 'A tool',
    schema: dict | None = None,
) -> mock.MagicMock:
    """Build a mock MCP Tool object."""
    tool = mock.MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = schema if schema is not None else {'type': 'object'}
    return tool


class BuildAuthTestCase(unittest.TestCase):
    """Test cases for _build_auth."""

    def test_none_auth(self) -> None:
        server = _make_server(auth_type='none')
        headers, http_auth = external_mcp._build_auth(server)
        self.assertIsNone(headers)
        self.assertIsNone(http_auth)

    @mock.patch('imbi.assistant.external_mcp.decrypt_config_value')
    def test_static_auth(self, mock_decrypt: mock.MagicMock) -> None:
        mock_decrypt.return_value = 'secret-token'
        server = _make_server(
            auth_type='static',
            static_header='X-API-Key',
            static_value_encrypted='ciphertext',
        )
        headers, http_auth = external_mcp._build_auth(server)
        self.assertEqual(headers, {'X-API-Key': 'secret-token'})
        self.assertIsNone(http_auth)
        mock_decrypt.assert_called_once_with('ciphertext')

    @mock.patch('imbi.assistant.external_mcp.decrypt_config_value')
    def test_static_auth_missing_value(
        self, mock_decrypt: mock.MagicMock
    ) -> None:
        mock_decrypt.return_value = None
        server = _make_server(
            auth_type='static',
            static_header='X-API-Key',
            static_value_encrypted='bad',
        )
        headers, http_auth = external_mcp._build_auth(server)
        self.assertIsNone(headers)
        self.assertIsNone(http_auth)

    @mock.patch('imbi.assistant.external_mcp.decrypt_config_value')
    def test_oauth_auth(self, mock_decrypt: mock.MagicMock) -> None:
        mock_decrypt.return_value = 'client-secret'
        server = _make_server(
            auth_type='oauth_client_credentials',
            oauth_token_url='https://auth.example.com/token',
            oauth_client_id='client-id',
            oauth_client_secret_encrypted='ciphertext',
            oauth_scope='read',
        )
        headers, http_auth = external_mcp._build_auth(server)
        self.assertIsNone(headers)
        assert isinstance(http_auth, external_mcp.OAuthClientCredentialsAuth)
        # The HttpUrl token URL must be coerced to a plain string.
        self.assertIsInstance(http_auth._token_url, str)
        self.assertEqual(http_auth._token_url, str(server.oauth_token_url))
        mock_decrypt.assert_called_once_with('ciphertext')

    @mock.patch('imbi.assistant.external_mcp.decrypt_config_value')
    def test_oauth_auth_missing_secret(
        self, mock_decrypt: mock.MagicMock
    ) -> None:
        mock_decrypt.return_value = None
        server = _make_server(
            auth_type='oauth_client_credentials',
            oauth_token_url='https://auth.example.com/token',
            oauth_client_id='client-id',
            oauth_client_secret_encrypted='bad',
        )
        headers, http_auth = external_mcp._build_auth(server)
        self.assertIsNone(headers)
        self.assertIsNone(http_auth)


class OAuthClientCredentialsAuthTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for the OAuth client-credentials httpx auth."""

    async def test_fetches_and_caches_token(self) -> None:
        auth = external_mcp.OAuthClientCredentialsAuth(
            token_url='https://auth.example.com/token',
            client_id='id',
            client_secret='secret',
            scope='read',
        )

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            'access_token': 'tok-123',
            'expires_in': 3600,
        }
        mock_response.raise_for_status = mock.MagicMock()

        mock_client = mock.AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client

        with mock.patch(
            'imbi.assistant.external_mcp.httpx.AsyncClient',
            return_value=mock_client,
        ):
            request = httpx.Request('GET', 'https://mcp.example.com')
            flow = auth.async_auth_flow(request)
            sent = await flow.__anext__()
            self.assertEqual(sent.headers['Authorization'], 'Bearer tok-123')
            with self.assertRaises(StopAsyncIteration):
                await flow.__anext__()

        # Posted with scope and client credentials.
        posted = mock_client.post.call_args.kwargs['data']
        self.assertEqual(posted['grant_type'], 'client_credentials')
        self.assertEqual(posted['scope'], 'read')
        # Token is cached; not expired on a fresh fetch.
        self.assertFalse(auth._is_expired())


class ConnectAndRegisterTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for connecting to servers and registering tools."""

    @staticmethod
    def _patch_session(
        manager: external_mcp.ExternalMCPManager,
        tools: list,
    ) -> mock.AsyncMock:
        session = mock.AsyncMock()
        list_result = mock.MagicMock()
        list_result.tools = tools
        session.list_tools.return_value = list_result

        async def fake_open(server: object) -> mock.AsyncMock:
            manager._sessions[server.slug] = session  # type: ignore
            return session

        manager._open_session = fake_open  # type: ignore
        return session

    async def test_namespacing_and_ignored_tools(self) -> None:
        manager = external_mcp.ExternalMCPManager()
        server = _make_server(
            slug='svc',
            ignored_tools=['hidden'],
        )
        self._patch_session(
            manager,
            [_make_tool('listed'), _make_tool('hidden')],
        )
        await manager._connect_server(server)
        self.assertEqual(manager.get_tool_names(), ['mcp_svc_listed'])
        self.assertTrue(manager.has_tool('mcp_svc_listed'))
        self.assertFalse(manager.has_tool('mcp_svc_hidden'))
        tool = manager.get_tools()[0]
        self.assertEqual(tool['description'], 'A tool')
        self.assertEqual(tool['input_schema'], {'type': 'object'})

    async def test_tool_prefix_override(self) -> None:
        manager = external_mcp.ExternalMCPManager()
        server = _make_server(slug='svc', tool_prefix='custom')
        self._patch_session(manager, [_make_tool('thing')])
        await manager._connect_server(server)
        self.assertEqual(manager.get_tool_names(), ['mcp_custom_thing'])

    async def test_invalid_name_sanitized(self) -> None:
        manager = external_mcp.ExternalMCPManager()
        server = _make_server(slug='svc')
        self._patch_session(manager, [_make_tool('weird name!')])
        await manager._connect_server(server)
        self.assertEqual(manager.get_tool_names(), ['mcp_svc_weird_name_'])

    async def test_collision_skipped(self) -> None:
        manager = external_mcp.ExternalMCPManager()
        server = _make_server(slug='svc')
        self._patch_session(manager, [_make_tool('dup'), _make_tool('dup')])
        await manager._connect_server(server)
        self.assertEqual(manager.get_tool_names(), ['mcp_svc_dup'])

    async def test_overlong_name_truncated(self) -> None:
        manager = external_mcp.ExternalMCPManager()
        server = _make_server(slug='svc')
        # A name long enough to blow past the 128-char limit must be
        # truncated to a valid length rather than registered as-is.
        self._patch_session(manager, [_make_tool('x' * 200)])
        await manager._connect_server(server)
        names = manager.get_tool_names()
        self.assertEqual(len(names), 1)
        self.assertEqual(len(names[0]), 128)

    async def test_connect_failure_is_resilient(self) -> None:
        manager = external_mcp.ExternalMCPManager()
        server = _make_server(slug='svc')

        async def fail(_server: object) -> object:
            raise RuntimeError('boom')

        manager._open_session = fail  # type: ignore
        await manager._connect_server(server)
        self.assertEqual(manager.get_tool_names(), [])

    async def test_connect_propagates_cancellation(self) -> None:
        manager = external_mcp.ExternalMCPManager()
        server = _make_server(slug='svc')

        async def cancel(_server: object) -> object:
            raise asyncio.CancelledError

        manager._open_session = cancel  # type: ignore
        with self.assertRaises(asyncio.CancelledError):
            await manager._connect_server(server)

    async def test_initialize_reads_servers(self) -> None:
        manager = external_mcp.ExternalMCPManager()
        server = _make_server(slug='svc')
        self._patch_session(manager, [_make_tool('thing')])
        db = mock.AsyncMock()
        with mock.patch(
            'imbi.assistant.external_mcp.age_ops.get_enabled_mcp_servers',
            return_value=[server],
        ):
            await manager.initialize(db)
        self.assertTrue(manager.is_initialized)
        self.assertEqual(manager.get_tool_names(), ['mcp_svc_thing'])


class ExecuteToolTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for ExternalMCPManager.execute_tool."""

    async def test_unknown_tool(self) -> None:
        manager = external_mcp.ExternalMCPManager()
        content, is_error = await manager.execute_tool('mcp_x_y', {})
        self.assertIn('Unknown MCP tool', content)
        self.assertTrue(is_error)

    async def test_session_missing(self) -> None:
        manager = external_mcp.ExternalMCPManager()
        manager._tool_routes['mcp_x_y'] = ('gone', 'y')
        content, is_error = await manager.execute_tool('mcp_x_y', {})
        self.assertIn('not connected', content)
        self.assertTrue(is_error)

    async def test_success(self) -> None:
        manager = external_mcp.ExternalMCPManager()
        session = mock.AsyncMock()
        block = mock.MagicMock()
        block.text = '{"ok": true}'
        call_result = mock.MagicMock()
        call_result.content = [block]
        call_result.isError = False
        session.call_tool.return_value = call_result
        manager._sessions['svc'] = session
        manager._tool_routes['mcp_svc_thing'] = ('svc', 'thing')
        content, is_error = await manager.execute_tool(
            'mcp_svc_thing', {'a': 1}
        )
        self.assertEqual(content, '{"ok": true}')
        self.assertFalse(is_error)
        session.call_tool.assert_awaited_once_with('thing', {'a': 1})

    async def test_tool_returns_error(self) -> None:
        manager = external_mcp.ExternalMCPManager()
        session = mock.AsyncMock()
        block = mock.MagicMock()
        block.text = 'kaboom'
        call_result = mock.MagicMock()
        call_result.content = [block]
        call_result.isError = True
        session.call_tool.return_value = call_result
        manager._sessions['svc'] = session
        manager._tool_routes['mcp_svc_thing'] = ('svc', 'thing')
        content, is_error = await manager.execute_tool('mcp_svc_thing', {})
        payload = json.loads(content)
        self.assertIn('error', payload)
        self.assertEqual(payload['detail'], 'kaboom')
        self.assertTrue(is_error)

    async def test_call_raises(self) -> None:
        manager = external_mcp.ExternalMCPManager()
        session = mock.AsyncMock()
        session.call_tool.side_effect = RuntimeError('down')
        manager._sessions['svc'] = session
        manager._tool_routes['mcp_svc_thing'] = ('svc', 'thing')
        content, is_error = await manager.execute_tool('mcp_svc_thing', {})
        self.assertIn('failed', content)
        self.assertTrue(is_error)
        # Exception message preserved in detail for the model.
        payload = json.loads(content)
        self.assertEqual(payload['detail'], 'down')


class ReconnectTestCase(unittest.IsolatedAsyncioTestCase):
    """A call to a server whose session is gone reopens it once."""

    def setUp(self) -> None:
        self.manager = external_mcp.ExternalMCPManager()
        self.manager._servers['svc'] = _make_server(slug='svc')
        self.manager._tool_routes['mcp_svc_thing'] = ('svc', 'thing')
        self.session = mock.AsyncMock()
        block = mock.MagicMock()
        block.text = 'ok'
        self.session.call_tool.return_value = mock.MagicMock(
            content=[block], isError=False
        )

    async def test_reconnects_and_retries_call(self) -> None:
        self.manager._open_session = mock.AsyncMock(  # type: ignore
            return_value=self.session
        )
        content, is_error = await self.manager.execute_tool(
            'mcp_svc_thing', {}
        )
        self.assertEqual((content, is_error), ('ok', False))
        self.session.call_tool.assert_awaited_once_with('thing', {})

    async def test_failed_reconnect_waits_before_next_attempt(self) -> None:
        opener = mock.AsyncMock(side_effect=RuntimeError('502'))
        self.manager._open_session = opener  # type: ignore
        for _ in range(2):
            content, is_error = await self.manager.execute_tool(
                'mcp_svc_thing', {}
            )
            self.assertIn('not connected', content)
            self.assertTrue(is_error)
        opener.assert_awaited_once()

        # After the delay, the next call tries again.
        self.manager._reconnect_after['svc'] = 0.0
        opener.side_effect = None
        opener.return_value = self.session
        content, is_error = await self.manager.execute_tool(
            'mcp_svc_thing', {}
        )
        self.assertEqual((content, is_error), ('ok', False))
        self.assertEqual(opener.await_count, 2)

    async def test_queued_reconnect_skips_after_aclose(self) -> None:
        opener = mock.AsyncMock(return_value=self.session)
        self.manager._open_session = opener  # type: ignore
        lock = self.manager._reconnect_locks.setdefault('svc', asyncio.Lock())
        await lock.acquire()
        pending = asyncio.create_task(self.manager._reconnect('svc'))
        await asyncio.sleep(0)
        await self.manager.aclose()
        lock.release()
        self.assertIsNone(await pending)
        opener.assert_not_awaited()


class _FakeClientSession:
    """Stand-in for ``mcp.ClientSession`` used as a context manager."""

    def __init__(self, *_args: object) -> None:
        self.initialize = mock.AsyncMock()
        result = mock.MagicMock()
        result.tools = [_make_tool('search')]
        self.list_tools = mock.AsyncMock(return_value=result)

    async def __aenter__(self) -> '_FakeClientSession':
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class OpenSessionTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for _open_session transport wiring."""

    async def _run(self, server: common_models.MCPServer) -> None:
        manager = external_mcp.ExternalMCPManager()
        transport = mock.MagicMock()
        transport.__aenter__.return_value = (
            mock.MagicMock(),
            mock.MagicMock(),
            mock.MagicMock(),
        )
        with (
            mock.patch(
                'imbi.assistant.external_mcp.streamable_http.'
                'streamable_http_client',
                return_value=transport,
            ) as mock_client_ctx,
            mock.patch(
                'imbi.assistant.external_mcp.mcp.ClientSession',
                _FakeClientSession,
            ),
        ):
            result = await manager._open_session(server)
            self.assertIsInstance(result, _FakeClientSession)
            result.initialize.assert_awaited_once()  # type: ignore
            self.assertIn(server.slug, manager._sessions)
            await manager.aclose()
        transport.__aexit__.assert_awaited_once()
        # The HttpUrl must be coerced to a plain string for the client.
        passed_url = mock_client_ctx.call_args.args[0]
        self.assertIsInstance(passed_url, str)
        self.assertEqual(passed_url, str(server.url))

    @mock.patch(
        'imbi.assistant.external_mcp.create_mcp_http_client',
    )
    async def test_verify_ssl(self, mock_factory: mock.MagicMock) -> None:
        await self._run(_make_server(verify_ssl=True))
        mock_factory.assert_called_once()

    @mock.patch('imbi.assistant.external_mcp.httpx.AsyncClient')
    async def test_no_verify_ssl(self, mock_client: mock.MagicMock) -> None:
        await self._run(_make_server(verify_ssl=False))
        mock_client.assert_called_once()

    async def test_initialize_failure_propagates(self) -> None:
        manager = external_mcp.ExternalMCPManager()
        transport = mock.MagicMock()
        transport.__aenter__.side_effect = httpx.ConnectError('refused')
        with mock.patch(
            'imbi.assistant.external_mcp.streamable_http.'
            'streamable_http_client',
            return_value=transport,
        ):
            with self.assertRaises(httpx.ConnectError):
                await manager._open_session(_make_server())
        self.assertEqual(manager._sessions, {})


class SessionIsolationTestCase(unittest.IsolatedAsyncioTestCase):
    """A failing MCP client child task must not cancel the caller (#287)."""

    async def test_child_failure_does_not_cancel_lifespan_task(self) -> None:
        fail = anyio.Event()

        async def bad_gateway() -> None:
            await fail.wait()
            request = httpx.Request('POST', 'https://mcp.example.com/mcp')
            raise httpx.HTTPStatusError(
                '502 Bad Gateway',
                request=request,
                response=httpx.Response(502, request=request),
            )

        @contextlib.asynccontextmanager
        async def fake_transport(
            *_args: object, **_kwargs: object
        ) -> collections.abc.AsyncGenerator[tuple[object, object, object]]:
            # Mirrors streamable_http_client: a task group whose child
            # raises from handle_request_async on a 502.
            async with anyio.create_task_group() as tg:
                tg.start_soon(bad_gateway)
                try:
                    yield mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
                finally:
                    tg.cancel_scope.cancel()

        manager = external_mcp.ExternalMCPManager()

        with (
            mock.patch(
                'imbi.assistant.external_mcp.age_ops.get_enabled_mcp_servers',
                mock.AsyncMock(return_value=[_make_server()]),
            ),
            mock.patch(
                'imbi.assistant.external_mcp.streamable_http.'
                'streamable_http_client',
                fake_transport,
            ),
            mock.patch(
                'imbi.assistant.external_mcp.mcp.ClientSession',
                _FakeClientSession,
            ),
            self.assertLogs('imbi.assistant.external_mcp', 'ERROR'),
        ):
            # This test task stands in for the ASGI lifespan task. Before
            # the fix, the failing child cancelled it here.
            await manager.initialize(mock.MagicMock())
            self.assertTrue(manager.has_tool('mcp_example_search'))
            fail.set()
            await asyncio.wait_for(
                asyncio.gather(*manager._tasks, return_exceptions=True),
                timeout=5,
            )
            # The failed server degrades on its own; its tools stay
            # registered so a later call can reconnect.
            self.assertNotIn('example', manager._sessions)
            self.assertTrue(manager.has_tool('mcp_example_search'))
            await manager.aclose()


class AcloseTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for aclose."""

    async def test_aclose_resets_state(self) -> None:
        manager = external_mcp.ExternalMCPManager()
        manager._tool_routes['x'] = ('s', 't')
        manager._tools = [{'name': 'x'}]
        manager._sessions['s'] = mock.AsyncMock()
        manager._initialized = True
        await manager.aclose()
        self.assertEqual(manager.get_tools(), [])
        self.assertFalse(manager.is_initialized)
        self.assertFalse(manager.has_tool('x'))

    async def test_aclose_suppresses_teardown_errors(self) -> None:
        async def broken() -> None:
            try:
                await asyncio.sleep(3600)
            finally:
                raise ExceptionGroup('teardown', [RuntimeError('scope')])

        manager = external_mcp.ExternalMCPManager()
        task = asyncio.create_task(broken())
        await asyncio.sleep(0)
        manager._tasks.append(task)
        await manager.aclose()
        self.assertFalse(manager.is_initialized)


class ModuleLevelTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for module-level singleton helpers."""

    def setUp(self) -> None:
        self._original = external_mcp._manager
        external_mcp._manager = None

    def tearDown(self) -> None:
        external_mcp._manager = self._original

    async def test_get_manager_raises_before_init(self) -> None:
        with self.assertRaises(RuntimeError):
            external_mcp.get_manager()

    async def test_initialize_and_get_manager(self) -> None:
        db = mock.AsyncMock()
        with mock.patch(
            'imbi.assistant.external_mcp.age_ops.get_enabled_mcp_servers',
            return_value=[],
        ):
            await external_mcp.initialize(db)
        manager = external_mcp.get_manager()
        self.assertIsInstance(manager, external_mcp.ExternalMCPManager)
        self.assertTrue(manager.is_initialized)
        await external_mcp.aclose()
        self.assertIsNone(external_mcp._manager)

    async def test_initialize_handles_failure(self) -> None:
        db = mock.AsyncMock()
        with mock.patch.object(
            external_mcp.ExternalMCPManager,
            'initialize',
            side_effect=RuntimeError('boom'),
        ):
            await external_mcp.initialize(db)
        # A fresh, empty manager is installed on failure.
        manager = external_mcp.get_manager()
        self.assertFalse(manager.is_initialized)

    async def test_reinitialize(self) -> None:
        db = mock.AsyncMock()
        with mock.patch(
            'imbi.assistant.external_mcp.age_ops.get_enabled_mcp_servers',
            return_value=[],
        ):
            await external_mcp.initialize(db)
            success, count = await external_mcp.reinitialize(db)
        self.assertTrue(success)
        self.assertEqual(count, 0)
        await external_mcp.aclose()
