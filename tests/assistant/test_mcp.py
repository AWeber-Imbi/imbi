"""Tests for assistant MCP module."""

import json
import os
import unittest
from unittest import mock

from fastmcp.server.providers.openapi import MCPType
from fastmcp.utilities.openapi import HTTPRoute

from imbi_assistant import mcp, settings


class ExcludeNonAiToolsTestCase(unittest.TestCase):
    """Test cases for _exclude_non_ai_tools."""

    def test_excludes_flagged_route(self) -> None:
        route = HTTPRoute(
            path='/configuration/{key}',
            method='PUT',
            extensions={'x-imbi-ai-tool': False},
        )
        self.assertEqual(
            MCPType.EXCLUDE,
            mcp._exclude_non_ai_tools(route, MCPType.TOOL),
        )

    def test_keeps_unflagged_route(self) -> None:
        route = HTTPRoute(path='/projects/', method='GET')
        self.assertIsNone(
            mcp._exclude_non_ai_tools(route, MCPType.TOOL),
        )


class MCPToolToAnthropicTestCase(unittest.TestCase):
    """Test cases for _mcp_tool_to_anthropic."""

    def test_converts_tool_with_input_schema(self) -> None:
        tool = mock.MagicMock()
        tool.name = 'list_projects'
        tool.description = 'List all projects'
        tool.inputSchema = {
            'type': 'object',
            'properties': {'limit': {'type': 'integer'}},
        }
        result = mcp._mcp_tool_to_anthropic(tool)
        self.assertEqual(result['name'], 'list_projects')
        self.assertEqual(result['description'], 'List all projects')
        self.assertEqual(
            result['input_schema']['type'],
            'object',
        )

    def test_converts_tool_without_input_schema(self) -> None:
        tool = mock.MagicMock(spec=['name', 'description'])
        tool.name = 'get_status'
        tool.description = None
        result = mcp._mcp_tool_to_anthropic(tool)
        self.assertEqual(result['name'], 'get_status')
        self.assertEqual(result['description'], '')
        self.assertEqual(result['input_schema'], {})


class MCPManagerTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for MCPManager."""

    def setUp(self) -> None:
        settings._assistant_settings = None
        self.addCleanup(
            setattr,
            settings,
            '_assistant_settings',
            None,
        )

    async def test_initialize_no_api_url(self) -> None:
        with mock.patch.dict(
            os.environ,
            {'IMBI_INTERNAL_API_URL': ''},
            clear=True,
        ):
            manager = mcp.MCPManager()
            await manager.initialize()
            self.assertFalse(manager.is_initialized)

    async def test_get_tools_empty_before_init(self) -> None:
        manager = mcp.MCPManager()
        self.assertEqual(manager.get_tools(), [])

    async def test_get_tool_names_empty(self) -> None:
        manager = mcp.MCPManager()
        self.assertEqual(manager.get_tool_names(), [])

    async def test_execute_tool_not_initialized(self) -> None:
        manager = mcp.MCPManager()
        content, is_error = await manager.execute_tool('test', {})
        self.assertIn('not initialized', content)
        self.assertTrue(is_error)

    async def test_aclose_idempotent(self) -> None:
        manager = mcp.MCPManager()
        await manager.aclose()
        self.assertFalse(manager.is_initialized)

    @mock.patch('imbi_assistant.mcp.httpx.AsyncClient')
    @mock.patch('imbi_assistant.mcp.fastmcp.Client')
    @mock.patch('imbi_assistant.mcp.fastmcp.FastMCP.from_openapi')
    async def test_initialize_success(
        self,
        mock_from_openapi: mock.MagicMock,
        mock_mcp_client_cls: mock.MagicMock,
        mock_httpx_cls: mock.MagicMock,
    ) -> None:
        with mock.patch.dict(
            os.environ,
            {
                'IMBI_INTERNAL_API_URL': 'http://api:8000',
            },
            clear=True,
        ):
            # Mock the httpx fetch of the OpenAPI spec.
            mock_tmp = mock.AsyncMock()
            mock_response = mock.MagicMock()
            mock_response.json.return_value = {
                'openapi': '3.1.0',
                'paths': {},
            }
            mock_tmp.get.return_value = mock_response
            mock_tmp.__aenter__ = mock.AsyncMock(
                return_value=mock_tmp,
            )
            mock_tmp.__aexit__ = mock.AsyncMock(
                return_value=None,
            )
            mock_httpx_cls.return_value = mock_tmp

            mock_server = mock.MagicMock()
            mock_from_openapi.return_value = mock_server

            mock_tool = mock.MagicMock()
            mock_tool.name = 'get_projects'
            mock_tool.description = 'Get projects'
            mock_tool.inputSchema = {
                'type': 'object',
                'properties': {},
            }

            mock_client = mock.AsyncMock()
            mock_client.list_tools.return_value = [mock_tool]
            mock_client.__aenter__ = mock.AsyncMock(
                return_value=mock_client,
            )
            mock_client.__aexit__ = mock.AsyncMock(
                return_value=None,
            )
            mock_mcp_client_cls.return_value = mock_client

            manager = mcp.MCPManager()
            await manager.initialize()

            self.assertTrue(manager.is_initialized)
            self.assertEqual(len(manager.get_tools()), 1)
            self.assertEqual(
                manager.get_tool_names(),
                ['get_projects'],
            )

            await manager.aclose()
            self.assertFalse(manager.is_initialized)

    @mock.patch('imbi_assistant.mcp.httpx.AsyncClient')
    @mock.patch('imbi_assistant.mcp.fastmcp.Client')
    @mock.patch('imbi_assistant.mcp.fastmcp.FastMCP.from_openapi')
    async def test_initialize_passes_ai_exclusion_hook(
        self,
        mock_from_openapi: mock.MagicMock,
        mock_mcp_client_cls: mock.MagicMock,
        mock_httpx_cls: mock.MagicMock,
    ) -> None:
        with mock.patch.dict(
            os.environ,
            {'IMBI_INTERNAL_API_URL': 'http://api:8000'},
            clear=True,
        ):
            mock_tmp = mock.AsyncMock()
            mock_response = mock.MagicMock()
            mock_response.json.return_value = {
                'openapi': '3.1.0',
                'paths': {},
            }
            mock_tmp.get.return_value = mock_response
            mock_tmp.__aenter__ = mock.AsyncMock(return_value=mock_tmp)
            mock_tmp.__aexit__ = mock.AsyncMock(return_value=None)
            mock_httpx_cls.return_value = mock_tmp

            mock_from_openapi.return_value = mock.MagicMock()
            mock_client = mock.AsyncMock()
            mock_client.list_tools.return_value = []
            mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = mock.AsyncMock(return_value=None)
            mock_mcp_client_cls.return_value = mock_client

            manager = mcp.MCPManager()
            await manager.initialize()

            _, kwargs = mock_from_openapi.call_args
            self.assertIs(
                kwargs['route_map_fn'],
                mcp._exclude_non_ai_tools,
            )

            await manager.aclose()

    @mock.patch('imbi_assistant.mcp.httpx.AsyncClient')
    @mock.patch('imbi_assistant.mcp.fastmcp.Client')
    @mock.patch('imbi_assistant.mcp.fastmcp.FastMCP.from_openapi')
    async def test_execute_tool_success(
        self,
        mock_from_openapi: mock.MagicMock,
        mock_mcp_client_cls: mock.MagicMock,
        mock_httpx_cls: mock.MagicMock,
    ) -> None:
        with mock.patch.dict(
            os.environ,
            {
                'IMBI_INTERNAL_API_URL': 'http://api:8000',
            },
            clear=True,
        ):
            mock_tmp = mock.AsyncMock()
            mock_response = mock.MagicMock()
            mock_response.json.return_value = {
                'openapi': '3.1.0',
                'paths': {},
            }
            mock_tmp.get.return_value = mock_response
            mock_tmp.__aenter__ = mock.AsyncMock(
                return_value=mock_tmp,
            )
            mock_tmp.__aexit__ = mock.AsyncMock(
                return_value=None,
            )
            mock_httpx_cls.return_value = mock_tmp

            mock_from_openapi.return_value = mock.MagicMock()

            mock_client = mock.AsyncMock()
            mock_client.list_tools.return_value = []
            mock_client.__aenter__ = mock.AsyncMock(
                return_value=mock_client,
            )
            mock_client.__aexit__ = mock.AsyncMock(
                return_value=None,
            )

            result_block = mock.MagicMock()
            result_block.text = '{"projects": []}'
            call_result = mock.MagicMock()
            call_result.content = [result_block]
            call_result.is_error = False
            mock_client.call_tool.return_value = call_result
            mock_mcp_client_cls.return_value = mock_client

            manager = mcp.MCPManager()
            await manager.initialize()

            content, is_error = await manager.execute_tool(
                'get_projects',
                {},
                auth_token='test-token',
            )
            self.assertIn('projects', content)
            self.assertFalse(is_error)
            mock_client.call_tool.assert_called_once_with(
                'get_projects',
                {},
            )

            await manager.aclose()

    @mock.patch('imbi_assistant.mcp.httpx.AsyncClient')
    @mock.patch('imbi_assistant.mcp.fastmcp.Client')
    @mock.patch('imbi_assistant.mcp.fastmcp.FastMCP.from_openapi')
    async def test_execute_tool_error(
        self,
        mock_from_openapi: mock.MagicMock,
        mock_mcp_client_cls: mock.MagicMock,
        mock_httpx_cls: mock.MagicMock,
    ) -> None:
        with mock.patch.dict(
            os.environ,
            {
                'IMBI_INTERNAL_API_URL': 'http://api:8000',
            },
            clear=True,
        ):
            mock_tmp = mock.AsyncMock()
            mock_response = mock.MagicMock()
            mock_response.json.return_value = {
                'openapi': '3.1.0',
                'paths': {},
            }
            mock_tmp.get.return_value = mock_response
            mock_tmp.__aenter__ = mock.AsyncMock(
                return_value=mock_tmp,
            )
            mock_tmp.__aexit__ = mock.AsyncMock(
                return_value=None,
            )
            mock_httpx_cls.return_value = mock_tmp

            mock_from_openapi.return_value = mock.MagicMock()

            mock_client = mock.AsyncMock()
            mock_client.list_tools.return_value = []
            mock_client.__aenter__ = mock.AsyncMock(
                return_value=mock_client,
            )
            mock_client.__aexit__ = mock.AsyncMock(
                return_value=None,
            )
            mock_client.call_tool.side_effect = RuntimeError(
                'Connection refused',
            )
            mock_mcp_client_cls.return_value = mock_client

            manager = mcp.MCPManager()
            await manager.initialize()

            content, is_error = await manager.execute_tool(
                'bad_tool',
                {},
            )
            self.assertIn('failed', content)
            self.assertTrue(is_error)
            # The exception message must survive into ``detail`` so the
            # model can correct its call on retry.
            payload = json.loads(content)
            self.assertEqual(payload['detail'], 'Connection refused')

            await manager.aclose()

    @mock.patch('imbi_assistant.mcp.httpx.AsyncClient')
    @mock.patch('imbi_assistant.mcp.fastmcp.Client')
    @mock.patch('imbi_assistant.mcp.fastmcp.FastMCP.from_openapi')
    async def test_execute_tool_4xx_detail_propagates(
        self,
        mock_from_openapi: mock.MagicMock,
        mock_mcp_client_cls: mock.MagicMock,
        mock_httpx_cls: mock.MagicMock,
    ) -> None:
        """A 400 with a validation detail must survive into ``detail``
        with ``is_error=True`` so the LLM can see why the call failed
        and self-correct on the next turn.
        """
        with mock.patch.dict(
            os.environ,
            {'IMBI_INTERNAL_API_URL': 'http://api:8000'},
            clear=True,
        ):
            mock_tmp = mock.AsyncMock()
            mock_response = mock.MagicMock()
            mock_response.json.return_value = {
                'openapi': '3.1.0',
                'paths': {},
            }
            mock_tmp.get.return_value = mock_response
            mock_tmp.__aenter__ = mock.AsyncMock(return_value=mock_tmp)
            mock_tmp.__aexit__ = mock.AsyncMock(return_value=None)
            mock_httpx_cls.return_value = mock_tmp

            mock_from_openapi.return_value = mock.MagicMock()

            mock_client = mock.AsyncMock()
            mock_client.list_tools.return_value = []
            mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = mock.AsyncMock(return_value=None)
            # fastmcp surfaces a 4xx by raising ToolError with the
            # backend's error body in the message. RuntimeError stands
            # in here to avoid importing fastmcp internals.
            detail_msg = (
                "Error calling tool 'patch_project': HTTP error 400: "
                "Bad Request - {'detail': 'Validation error: "
                "[{\\'loc\\': (\\'ci_deploy_status\\',), \\'input\\': "
                "\\'Pass\\'}]'}"
            )
            mock_client.call_tool.side_effect = RuntimeError(detail_msg)
            mock_mcp_client_cls.return_value = mock_client

            manager = mcp.MCPManager()
            await manager.initialize()

            content, is_error = await manager.execute_tool(
                'patch_project',
                {},
            )

            self.assertTrue(is_error)
            payload = json.loads(content)
            self.assertEqual(payload['detail'], detail_msg)
            # Sanity: the validation specifics make it through unmangled
            # so the model sees what to fix.
            self.assertIn('ci_deploy_status', payload['detail'])
            self.assertIn('Pass', payload['detail'])

            await manager.aclose()


class ModuleLevelFunctionsTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for module-level initialize/aclose/get_manager."""

    def setUp(self) -> None:
        self._original = mcp._manager
        mcp._manager = None
        settings._assistant_settings = None

    def tearDown(self) -> None:
        mcp._manager = self._original
        settings._assistant_settings = None

    @mock.patch.dict(
        os.environ,
        {'IMBI_INTERNAL_API_URL': ''},
        clear=True,
    )
    async def test_initialize_and_get_manager(self) -> None:
        await mcp.initialize()
        manager = mcp.get_manager()
        self.assertIsInstance(manager, mcp.MCPManager)
        await mcp.aclose()

    async def test_get_manager_raises_before_init(self) -> None:
        with self.assertRaises(RuntimeError):
            mcp.get_manager()

    @mock.patch.dict(
        os.environ,
        {'IMBI_INTERNAL_API_URL': ''},
        clear=True,
    )
    async def test_aclose_clears_manager(self) -> None:
        await mcp.initialize()
        await mcp.aclose()
        self.assertIsNone(mcp._manager)

    @mock.patch.dict(
        os.environ,
        {'IMBI_INTERNAL_API_URL': 'http://bad:9999'},
        clear=True,
    )
    async def test_initialize_handles_connection_error(
        self,
    ) -> None:
        await mcp.initialize()
        manager = mcp.get_manager()
        self.assertFalse(manager.is_initialized)
        await mcp.aclose()


class ServerToolHelpersTestCase(unittest.TestCase):
    """Test cases for the server-tool helper functions."""

    def test_is_server_tool_true(self) -> None:
        self.assertTrue(mcp.is_server_tool(mcp.REFRESH_TOOL_NAME))

    def test_is_server_tool_false(self) -> None:
        self.assertFalse(mcp.is_server_tool('some_api_tool'))

    def test_get_server_tools_includes_refresh(self) -> None:
        tools = mcp.get_server_tools()
        names = [t['name'] for t in tools]
        self.assertIn(mcp.REFRESH_TOOL_NAME, names)


class ReinitializeTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for MCPManager.reinitialize."""

    def setUp(self) -> None:
        settings._assistant_settings = None
        self.addCleanup(
            setattr,
            settings,
            '_assistant_settings',
            None,
        )

    async def test_reinitialize_preserves_state_on_failure(
        self,
    ) -> None:
        """A failing reinit leaves existing tools intact and cleans
        up any replacement resources that were partially assigned
        before the exception.
        """
        manager = mcp.MCPManager()
        manager._tools = [{'name': 'existing_tool'}]
        manager._initialized = True

        replacement_client = mock.AsyncMock()
        replacement_client.__aexit__ = mock.AsyncMock(return_value=None)
        replacement_http = mock.AsyncMock()

        async def failing_initialize(self: mcp.MCPManager) -> None:
            # Mimic initialize() that assigns transport handles, then
            # fails before completing.
            self._client = replacement_client
            self._http_client = replacement_http
            raise RuntimeError('boom')

        with mock.patch.object(
            mcp.MCPManager,
            'initialize',
            failing_initialize,
        ):
            success, count = await manager.reinitialize()

        self.assertFalse(success)
        self.assertEqual(count, 0)
        # Existing tools are still there.
        self.assertTrue(manager.is_initialized)
        self.assertEqual(manager.get_tool_names(), ['existing_tool'])
        # Replacement transport was cleaned up via aclose().
        replacement_client.__aexit__.assert_awaited_once()
        replacement_http.aclose.assert_awaited_once()

    async def test_reinitialize_preserves_state_when_no_api_url(
        self,
    ) -> None:
        """If the replacement reports not initialized, keep state."""
        manager = mcp.MCPManager()
        manager._tools = [{'name': 'existing_tool'}]
        manager._initialized = True

        async def fake_initialize(_self: mcp.MCPManager) -> None:
            # Mimic the no-API-URL early return: leaves _initialized
            # False on the replacement.
            return None

        with mock.patch.object(
            mcp.MCPManager,
            'initialize',
            fake_initialize,
        ):
            success, count = await manager.reinitialize()

        self.assertFalse(success)
        self.assertEqual(count, 0)
        self.assertTrue(manager.is_initialized)
        self.assertEqual(manager.get_tool_names(), ['existing_tool'])

    async def test_reinitialize_swaps_state_on_success(self) -> None:
        """A successful reinit swaps in the new tools and closes old."""
        manager = mcp.MCPManager()
        old_client = mock.AsyncMock()
        old_client.__aexit__ = mock.AsyncMock(return_value=None)
        old_http = mock.AsyncMock()
        manager._client = old_client
        manager._http_client = old_http
        manager._tools = [{'name': 'old_tool'}]
        manager._initialized = True

        async def fake_initialize(self: mcp.MCPManager) -> None:
            self._tools = [{'name': 'new_tool'}]
            self._initialized = True

        with mock.patch.object(
            mcp.MCPManager,
            'initialize',
            fake_initialize,
        ):
            success, count = await manager.reinitialize()

        self.assertTrue(success)
        self.assertEqual(count, 1)
        self.assertEqual(manager.get_tool_names(), ['new_tool'])
        old_client.__aexit__.assert_awaited_once()
        old_http.aclose.assert_awaited_once()
