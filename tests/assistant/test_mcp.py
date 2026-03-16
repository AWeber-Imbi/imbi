"""Tests for assistant MCP module."""

import os
import unittest
from unittest import mock

from imbi_assistant import mcp, settings


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
            {'IMBI_ASSISTANT_API_URL': ''},
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
        result = await manager.execute_tool('test', {})
        self.assertIn('not initialized', result)

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
                'IMBI_ASSISTANT_API_URL': 'http://api:8000',
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
    async def test_execute_tool_success(
        self,
        mock_from_openapi: mock.MagicMock,
        mock_mcp_client_cls: mock.MagicMock,
        mock_httpx_cls: mock.MagicMock,
    ) -> None:
        with mock.patch.dict(
            os.environ,
            {
                'IMBI_ASSISTANT_API_URL': 'http://api:8000',
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
            mock_client.call_tool.return_value = [result_block]
            mock_mcp_client_cls.return_value = mock_client

            manager = mcp.MCPManager()
            await manager.initialize()

            result = await manager.execute_tool(
                'get_projects',
                {},
                auth_token='test-token',
            )
            self.assertIn('projects', result)
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
                'IMBI_ASSISTANT_API_URL': 'http://api:8000',
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

            result = await manager.execute_tool(
                'bad_tool',
                {},
            )
            self.assertIn('failed', result)

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
        {'IMBI_ASSISTANT_API_URL': ''},
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
        {'IMBI_ASSISTANT_API_URL': ''},
        clear=True,
    )
    async def test_aclose_clears_manager(self) -> None:
        await mcp.initialize()
        await mcp.aclose()
        self.assertIsNone(mcp._manager)

    @mock.patch.dict(
        os.environ,
        {'IMBI_ASSISTANT_API_URL': 'http://bad:9999'},
        clear=True,
    )
    async def test_initialize_handles_connection_error(
        self,
    ) -> None:
        await mcp.initialize()
        manager = mcp.get_manager()
        self.assertFalse(manager.is_initialized)
        await mcp.aclose()
