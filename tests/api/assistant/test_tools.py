"""Tests for assistant tools module."""

import datetime
import unittest
from unittest import mock

from imbi_api import models
from imbi_api.assistant import tools
from imbi_api.auth import permissions


def _make_auth(
    is_admin: bool = False,
    perms: set[str] | None = None,
) -> permissions.AuthContext:
    """Create a test AuthContext."""
    user = models.User(
        email='test@example.com',
        display_name='Test User',
        is_admin=is_admin,
        created_at=datetime.datetime.now(datetime.UTC),
    )
    return permissions.AuthContext(
        user=user,
        auth_method='jwt',
        permissions=perms or set(),
    )


class ToolDefinitionTestCase(unittest.TestCase):
    """Test cases for ToolDefinition."""

    def test_tool_definition_fields(self) -> None:
        """Test ToolDefinition NamedTuple fields."""
        handler = mock.AsyncMock(return_value='result')
        td = tools.ToolDefinition(
            required_permission='test:read',
            schema={'name': 'test_tool'},
            handler=handler,
        )
        self.assertEqual(td.required_permission, 'test:read')
        self.assertEqual(td.schema['name'], 'test_tool')
        self.assertIs(td.handler, handler)


class GetToolsForUserTestCase(unittest.TestCase):
    """Test cases for get_tools_for_user."""

    def test_admin_gets_all_tools(self) -> None:
        """Test that admin user gets all tools."""
        schemas, names = tools.get_tools_for_user(
            user_permissions=set(), is_admin=True
        )
        self.assertEqual(len(schemas), len(tools.TOOLS))
        self.assertEqual(len(names), len(tools.TOOLS))

    def test_user_with_no_permissions(self) -> None:
        """Test user with no permissions gets no tools."""
        schemas, names = tools.get_tools_for_user(
            user_permissions=set(), is_admin=False
        )
        self.assertEqual(len(schemas), 0)
        self.assertEqual(len(names), 0)

    def test_user_with_specific_permission(self) -> None:
        """Test user gets tools matching their permissions."""
        _schemas, names = tools.get_tools_for_user(
            user_permissions={'project:read'}, is_admin=False
        )
        self.assertIn('list_projects', names)
        self.assertIn('get_project', names)
        # Should not have team tools
        self.assertNotIn('list_teams', names)

    def test_user_with_multiple_permissions(self) -> None:
        """Test user with multiple permissions."""
        _schemas, names = tools.get_tools_for_user(
            user_permissions={'project:read', 'team:read', 'user:read'},
            is_admin=False,
        )
        self.assertIn('list_projects', names)
        self.assertIn('list_teams', names)
        self.assertIn('list_users', names)

    def test_schemas_match_names(self) -> None:
        """Test that returned schemas and names correspond."""
        schemas, names = tools.get_tools_for_user(
            user_permissions=set(), is_admin=True
        )
        for schema, name in zip(schemas, names, strict=True):
            self.assertEqual(schema['name'], name)


class ExecuteToolTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for execute_tool."""

    async def test_unknown_tool(self) -> None:
        """Test executing an unknown tool."""
        auth = _make_auth(is_admin=True)
        result = await tools.execute_tool('nonexistent_tool', {}, auth)
        self.assertIn('Unknown tool', result)

    async def test_permission_denied(self) -> None:
        """Test executing tool without permission."""
        auth = _make_auth(perms=set())
        result = await tools.execute_tool('list_projects', {}, auth)
        self.assertIn('Permission denied', result)

    async def test_admin_bypasses_permission(self) -> None:
        """Test that admin can execute any tool."""
        auth = _make_auth(is_admin=True)
        with mock.patch(
            'imbi_common.neo4j.run',
        ) as mock_run:
            mock_ctx = mock.AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.data.return_value = []
            mock_run.return_value = mock_ctx

            result = await tools.execute_tool('list_projects', {}, auth)
            self.assertIn('No projects found', result)

    async def test_handler_exception(self) -> None:
        """Test handler exception is caught."""
        auth = _make_auth(is_admin=True)
        with mock.patch.dict(
            tools.TOOLS,
            {
                'test_tool': tools.ToolDefinition(
                    required_permission='test:read',
                    schema={'name': 'test_tool'},
                    handler=mock.AsyncMock(side_effect=RuntimeError('boom')),
                ),
            },
        ):
            result = await tools.execute_tool('test_tool', {}, auth)
            self.assertIn('Error executing tool', result)


class HandleListProjectsTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for _handle_list_projects."""

    async def test_no_projects(self) -> None:
        """Test listing with no projects found."""
        auth = _make_auth(is_admin=True)
        with mock.patch('imbi_common.neo4j.run') as mock_run:
            mock_ctx = mock.AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.data.return_value = []
            mock_run.return_value = mock_ctx

            result = await tools._handle_list_projects({}, auth)
            self.assertEqual(result, 'No projects found.')

    async def test_with_projects(self) -> None:
        """Test listing projects."""
        auth = _make_auth(is_admin=True)
        with mock.patch('imbi_common.neo4j.run') as mock_run:
            mock_ctx = mock.AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.data.return_value = [
                {
                    'name': 'My Project',
                    'slug': 'my-project',
                    'description': 'A test project',
                    'team': 'Platform',
                    'project_type': 'API',
                },
            ]
            mock_run.return_value = mock_ctx

            result = await tools._handle_list_projects({}, auth)
            self.assertIn('My Project', result)
            self.assertIn('Platform', result)
            self.assertIn('API', result)

    async def test_with_name_filter(self) -> None:
        """Test listing projects with name filter."""
        auth = _make_auth(is_admin=True)
        with mock.patch('imbi_common.neo4j.run') as mock_run:
            mock_ctx = mock.AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.data.return_value = []
            mock_run.return_value = mock_ctx

            await tools._handle_list_projects(
                {'name_filter': 'test', 'limit': 10}, auth
            )
            # Verify keyword arguments passed to neo4j.run
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args.kwargs
            self.assertEqual(call_kwargs['name_filter'], 'test')
            self.assertEqual(call_kwargs['limit'], 10)

    async def test_limit_capped(self) -> None:
        """Test that limit is capped at 100."""
        auth = _make_auth(is_admin=True)
        with mock.patch('imbi_common.neo4j.run') as mock_run:
            mock_ctx = mock.AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.data.return_value = []
            mock_run.return_value = mock_ctx

            await tools._handle_list_projects({'limit': 500}, auth)
            # The limit param should be capped at 100
            call_kwargs = mock_run.call_args.kwargs
            self.assertEqual(call_kwargs['limit'], 100)


class HandleGetProjectTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for _handle_get_project."""

    async def test_no_slug(self) -> None:
        """Test get_project with no slug."""
        auth = _make_auth(is_admin=True)
        result = await tools._handle_get_project({}, auth)
        self.assertIn('slug is required', result)

    async def test_project_not_found(self) -> None:
        """Test get_project with nonexistent project."""
        auth = _make_auth(is_admin=True)
        with mock.patch('imbi_common.neo4j.run') as mock_run:
            mock_ctx = mock.AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.data.return_value = []
            mock_run.return_value = mock_ctx

            result = await tools._handle_get_project({'slug': 'missing'}, auth)
            self.assertIn('not found', result)

    async def test_project_found(self) -> None:
        """Test get_project with existing project."""
        auth = _make_auth(is_admin=True)
        with (
            mock.patch('imbi_common.neo4j.run') as mock_run,
            mock.patch('imbi_common.neo4j.convert_neo4j_types') as mock_conv,
        ):
            mock_ctx = mock.AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.data.return_value = [
                {
                    'p': {
                        'name': 'Test',
                        'slug': 'test',
                        'description': 'A project',
                    },
                    'team': 'Platform',
                    'project_type': 'API',
                    'environments': ['staging', 'production'],
                },
            ]
            mock_run.return_value = mock_ctx
            mock_conv.return_value = {
                'name': 'Test',
                'slug': 'test',
                'description': 'A project',
            }

            result = await tools._handle_get_project({'slug': 'test'}, auth)
            self.assertIn('Test', result)
            self.assertIn('Platform', result)


class HandleListBlueprintsTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for _handle_list_blueprints."""

    async def test_no_blueprints(self) -> None:
        """Test listing with no blueprints found."""
        auth = _make_auth(is_admin=True)
        with mock.patch('imbi_common.neo4j.run') as mock_run:
            mock_ctx = mock.AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.data.return_value = []
            mock_run.return_value = mock_ctx

            result = await tools._handle_list_blueprints({}, auth)
            self.assertEqual(result, 'No blueprints found.')

    async def test_with_blueprints(self) -> None:
        """Test listing blueprints."""
        auth = _make_auth(is_admin=True)
        with mock.patch('imbi_common.neo4j.run') as mock_run:
            mock_ctx = mock.AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.data.return_value = [
                {
                    'name': 'Default API',
                    'slug': 'default-api',
                    'type': 'Project',
                    'description': 'Default API blueprint',
                    'enabled': True,
                },
            ]
            mock_run.return_value = mock_ctx

            result = await tools._handle_list_blueprints({}, auth)
            self.assertIn('Default API', result)
            self.assertIn('enabled', result)

    async def test_with_type_filter(self) -> None:
        """Test listing blueprints with type filter."""
        auth = _make_auth(is_admin=True)
        with mock.patch('imbi_common.neo4j.run') as mock_run:
            mock_ctx = mock.AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.data.return_value = []
            mock_run.return_value = mock_ctx

            await tools._handle_list_blueprints({'type': 'Team'}, auth)
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args.kwargs
            self.assertEqual(call_kwargs['type'], 'Team')


class HandleListTeamsTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for _handle_list_teams."""

    async def test_no_teams(self) -> None:
        """Test listing with no teams found."""
        auth = _make_auth(is_admin=True)
        with mock.patch('imbi_common.neo4j.run') as mock_run:
            mock_ctx = mock.AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.data.return_value = []
            mock_run.return_value = mock_ctx

            result = await tools._handle_list_teams({}, auth)
            self.assertEqual(result, 'No teams found.')

    async def test_with_teams(self) -> None:
        """Test listing teams."""
        auth = _make_auth(is_admin=True)
        with mock.patch('imbi_common.neo4j.run') as mock_run:
            mock_ctx = mock.AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.data.return_value = [
                {
                    'name': 'Platform',
                    'slug': 'platform',
                    'description': 'Platform team',
                    'organization': 'Engineering',
                },
            ]
            mock_run.return_value = mock_ctx

            result = await tools._handle_list_teams({}, auth)
            self.assertIn('Platform', result)
            self.assertIn('Engineering', result)


class HandleListUsersTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for _handle_list_users."""

    async def test_no_users(self) -> None:
        """Test listing with no users found."""
        auth = _make_auth(is_admin=True)
        with mock.patch('imbi_common.neo4j.run') as mock_run:
            mock_ctx = mock.AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.data.return_value = []
            mock_run.return_value = mock_ctx

            result = await tools._handle_list_users({}, auth)
            self.assertEqual(result, 'No users found.')

    async def test_with_users(self) -> None:
        """Test listing users."""
        auth = _make_auth(is_admin=True)
        with mock.patch('imbi_common.neo4j.run') as mock_run:
            mock_ctx = mock.AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.data.return_value = [
                {
                    'email': 'admin@example.com',
                    'display_name': 'Admin User',
                    'is_admin': True,
                    'is_active': True,
                },
                {
                    'email': 'user@example.com',
                    'display_name': 'Regular User',
                    'is_admin': False,
                    'is_active': True,
                },
            ]
            mock_run.return_value = mock_ctx

            result = await tools._handle_list_users({}, auth)
            self.assertIn('Admin User', result)
            self.assertIn('[admin]', result)
            self.assertIn('Regular User', result)

    async def test_inactive_users(self) -> None:
        """Test listing inactive users."""
        auth = _make_auth(is_admin=True)
        with mock.patch('imbi_common.neo4j.run') as mock_run:
            mock_ctx = mock.AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.data.return_value = [
                {
                    'email': 'inactive@example.com',
                    'display_name': 'Inactive User',
                    'is_admin': False,
                    'is_active': False,
                },
            ]
            mock_run.return_value = mock_ctx

            result = await tools._handle_list_users(
                {'active_only': False}, auth
            )
            self.assertIn('(inactive)', result)


class ToolRegistryTestCase(unittest.TestCase):
    """Test cases for the TOOLS registry."""

    def test_all_tools_have_required_fields(self) -> None:
        """Test that all registered tools have required fields."""
        for name, tool_def in tools.TOOLS.items():
            self.assertIsNotNone(
                tool_def.required_permission,
                f'Tool {name} missing permission',
            )
            self.assertIn(
                'name',
                tool_def.schema,
                f'Tool {name} schema missing name',
            )
            self.assertIn(
                'input_schema',
                tool_def.schema,
                f'Tool {name} schema missing input_schema',
            )
            self.assertIsNotNone(
                tool_def.handler,
                f'Tool {name} missing handler',
            )

    def test_expected_tools_registered(self) -> None:
        """Test that expected tools are in the registry."""
        expected = {
            'list_projects',
            'get_project',
            'list_blueprints',
            'list_teams',
            'list_users',
        }
        self.assertEqual(set(tools.TOOLS.keys()), expected)
