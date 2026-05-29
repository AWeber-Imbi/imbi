from unittest import mock

import httpx

from imbi_slackbot import mcp, settings
from tests import helpers

_SPEC = {
    'openapi': '3.1.0',
    'info': {'title': 'Imbi', 'version': '1'},
    'paths': {
        '/projects': {
            'get': {
                'operationId': 'list_projects',
                'responses': {'200': {'description': 'ok'}},
            }
        }
    },
}


class FakeResponse:
    def json(self) -> dict:
        return _SPEC

    def raise_for_status(self) -> None:
        return None


class ConversionTests(helpers.TestCase):
    def test_tool_with_schema(self) -> None:
        tool = mock.Mock(
            name='t', description='d', inputSchema={'type': 'object'}
        )
        tool.name = 'list'
        result = mcp._mcp_tool_to_anthropic(tool)
        self.assertEqual('list', result['name'])
        self.assertEqual({'type': 'object'}, result['input_schema'])

    def test_tool_without_schema(self) -> None:
        tool = mock.Mock(spec=['name', 'description'])
        tool.name = 'list'
        tool.description = None
        result = mcp._mcp_tool_to_anthropic(tool)
        self.assertEqual('', result['description'])
        self.assertEqual({}, result['input_schema'])


class ManagerTests(helpers.TestCase):
    def setUp(self) -> None:
        super().setUp()
        settings._slackbot_settings = None

    def tearDown(self) -> None:
        settings._slackbot_settings = None
        super().tearDown()

    async def test_initialize_without_api_url(self) -> None:
        with self.override_environment(IMBI_INTERNAL_API_URL=''):
            manager = mcp.MCPManager()
            await manager.initialize()
        self.assertFalse(manager.is_initialized)

    async def test_execute_success(self) -> None:
        manager = mcp.MCPManager()
        manager._http_client = httpx.AsyncClient()
        block = mock.Mock()
        block.text = 'hello'
        result = mock.Mock(content=[block], is_error=False)
        manager._client = mock.Mock(
            call_tool=mock.AsyncMock(return_value=result)
        )
        try:
            body, is_error = await manager.execute_tool('t', {'a': 1}, 'tok')
        finally:
            await manager._http_client.aclose()
        self.assertEqual('hello', body)
        self.assertFalse(is_error)

    async def test_execute_tool_reports_error_result(self) -> None:
        manager = mcp.MCPManager()
        manager._http_client = httpx.AsyncClient()
        block = mock.Mock()
        block.text = 'bad'
        result = mock.Mock(content=[block], is_error=True)
        manager._client = mock.Mock(
            call_tool=mock.AsyncMock(return_value=result)
        )
        try:
            body, is_error = await manager.execute_tool('t', {}, None)
        finally:
            await manager._http_client.aclose()
        self.assertTrue(is_error)
        self.assertIn('returned an error', body)

    async def test_execute_when_not_initialized(self) -> None:
        manager = mcp.MCPManager()
        body, is_error = await manager.execute_tool('x', {})
        self.assertTrue(is_error)
        self.assertFalse(manager.is_initialized)
        self.assertEqual([], manager.get_tools())
        self.assertEqual([], manager.get_tool_names())

    async def test_initialize_and_execute(self) -> None:
        with self.override_environment(
            IMBI_INTERNAL_API_URL='http://127.0.0.1:9',
        ):
            with mock.patch.object(
                httpx.AsyncClient, 'get', return_value=FakeResponse()
            ):
                manager = mcp.MCPManager()
                await manager.initialize()
            try:
                self.assertTrue(manager.is_initialized)
                self.assertIn('list_projects', manager.get_tool_names())
                # The dead API URL forces the call into the error path.
                body, is_error = await manager.execute_tool(
                    'list_projects', {}, 'tok'
                )
                self.assertTrue(is_error)
            finally:
                await manager.aclose()
        self.assertFalse(manager.is_initialized)


class ModuleTests(helpers.TestCase):
    async def asyncTearDown(self) -> None:
        await mcp.aclose()
        await super().asyncTearDown()

    def test_get_manager_raises_when_unset(self) -> None:
        mcp._manager = None
        with self.assertRaises(RuntimeError):
            mcp.get_manager()

    async def test_initialize_failure_yields_empty_manager(self) -> None:
        with mock.patch.object(
            mcp.MCPManager,
            'initialize',
            side_effect=RuntimeError('boom'),
        ):
            await mcp.initialize()
        manager = mcp.get_manager()
        self.assertFalse(manager.is_initialized)
