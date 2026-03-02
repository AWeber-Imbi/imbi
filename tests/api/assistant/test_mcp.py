"""Tests for assistant MCP module."""

import os
import unittest
from unittest import mock

from imbi_api.assistant import mcp, settings


class MCPManagerTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for MCPManager."""

    async def test_initialize_no_configs(self) -> None:
        """Test initialize with no server configs."""
        manager = mcp.MCPManager([])
        await manager.initialize()
        self.assertFalse(manager._initialized)

    async def test_initialize_with_configs(self) -> None:
        """Test initialize with server configs (stub)."""
        configs = [{'name': 'test-server', 'url': 'http://localhost'}]
        manager = mcp.MCPManager(configs)
        await manager.initialize()
        self.assertTrue(manager._initialized)

    async def test_aclose(self) -> None:
        """Test closing the MCP manager."""
        manager = mcp.MCPManager([{'name': 'test'}])
        await manager.initialize()
        self.assertTrue(manager._initialized)
        await manager.aclose()
        self.assertFalse(manager._initialized)

    def test_get_tools_returns_empty(self) -> None:
        """Test get_tools returns empty list (stub)."""
        manager = mcp.MCPManager([])
        result = manager.get_tools()
        self.assertEqual(result, [])

    async def test_execute_tool_returns_not_implemented(self) -> None:
        """Test execute_tool returns stub message."""
        manager = mcp.MCPManager([])
        result = await manager.execute_tool(
            'server', 'tool_name', {'key': 'value'}
        )
        self.assertIn('not yet implemented', result)
        self.assertIn('tool_name', result)


class CreateMCPManagerTestCase(unittest.TestCase):
    """Test cases for create_mcp_manager factory."""

    def setUp(self) -> None:
        settings._assistant_settings = None
        self.addCleanup(setattr, settings, '_assistant_settings', None)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_create_mcp_manager_default(self) -> None:
        """Test creating MCPManager with default settings."""
        manager = mcp.create_mcp_manager()
        self.assertIsInstance(manager, mcp.MCPManager)
        self.assertEqual(manager._configs, [])
