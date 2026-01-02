"""Tests for role CRUD endpoints"""

import datetime
import unittest
from unittest import mock

from fastapi import testclient

from imbi import app, models


class RoleEndpointsTestCase(unittest.TestCase):
    """Test cases for role CRUD endpoints."""

    def setUp(self) -> None:
        """
        Prepare a FastAPI test app with an admin authentication context,
        override the current-user dependency, create a TestClient, and
        build a sample Role for use in tests.

        Sets the following attributes on self:
        - test_app: the FastAPI application instance used for testing.
        - admin_user: a User object with administrative privileges.
        - auth_context: an AuthContext for the admin_user used by the
            overridden dependency.
        - client: a TestClient bound to test_app for making HTTP
            requests.
        - test_role: a Role instance used as a sample role in tests.
        """
        from imbi.auth import permissions

        self.test_app = app.create_app()

        # Create an admin user for authentication
        self.admin_user = models.User(
            username='admin',
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,  # Admin has all permissions
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_context = permissions.AuthContext(
            user=self.admin_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),  # Admin bypasses permission checks
        )

        # Override the get_current_user dependency
        async def mock_get_current_user():
            """
            Provide the test instance's current authenticated user
            context for dependency injection.

            Returns:
                The test instance's `auth_context` object used as the
                    authenticated user in requests.
            """
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.client = testclient.TestClient(self.test_app)

        self.test_role = models.Role(
            name='Test Role',
            slug='test-role',
            description='A test role',
            priority=100,
            is_system=False,
        )

    def test_create_role_success(self) -> None:
        """Test successful role creation."""
        with mock.patch('imbi.neo4j.create_node') as mock_create:
            mock_node = {
                'name': 'New Role',
                'slug': 'new-role',
                'description': 'A new role',
                'priority': 100,
                'is_system': False,
            }
            mock_create.return_value = mock_node

            response = self.client.post(
                '/roles/',
                json={
                    'name': 'New Role',
                    'slug': 'new-role',
                    'description': 'A new role',
                    'priority': 100,
                    'is_system': False,
                },
            )

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertEqual(data['name'], 'New Role')
            self.assertEqual(data['slug'], 'new-role')
            mock_create.assert_called_once()

    def test_create_role_duplicate(self) -> None:
        """Test creating duplicate role returns 409."""
        import neo4j

        with mock.patch('imbi.neo4j.create_node') as mock_create:
            mock_create.side_effect = neo4j.exceptions.ConstraintError(
                'Constraint violation'
            )

            response = self.client.post(
                '/roles/',
                json={
                    'name': 'Duplicate',
                    'slug': 'duplicate',
                    'priority': 100,
                },
            )

            self.assertEqual(response.status_code, 409)
            self.assertIn('already exists', response.json()['detail'])

    def test_list_roles(self) -> None:
        """
        Verify that GET /roles/ returns a list containing the test role
        and that the backend fetch was called with ordering by
        "priority DESC".

        Asserts the response status is 200, the returned list contains
        exactly one role matching the test role's name and slug, and
        that the patched fetch_nodes received an `order_by` argument
        including "priority DESC".
        """

        async def role_generator():
            """
            Asynchronously yields the predefined test role instance for
            use in tests.

            Returns:
                async generator: Yields the `self.test_role` object.
            """
            yield self.test_role

        with mock.patch(
            'imbi.neo4j.fetch_nodes', return_value=role_generator()
        ) as mock_fetch:
            response = self.client.get('/roles/')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['name'], 'Test Role')
            self.assertEqual(data[0]['slug'], 'test-role')

            # Verify order_by was passed
            call_args = mock_fetch.call_args
            self.assertIn('priority DESC', call_args.kwargs['order_by'])

    def test_get_role_success(self) -> None:
        """Test getting a specific role."""
        with (
            mock.patch('imbi.neo4j.fetch_node', return_value=self.test_role),
            mock.patch('imbi.neo4j.refresh_relationship') as mock_refresh,
        ):
            response = self.client.get('/roles/test-role')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['name'], 'Test Role')
            self.assertEqual(data['slug'], 'test-role')

            # Verify relationships were loaded
            self.assertEqual(mock_refresh.call_count, 2)
            calls = [call[0][1] for call in mock_refresh.call_args_list]
            self.assertIn('permissions', calls)
            self.assertIn('parent_role', calls)

    def test_get_role_not_found(self) -> None:
        """Test getting non-existent role returns 404."""
        with mock.patch('imbi.neo4j.fetch_node', return_value=None):
            response = self.client.get('/roles/nonexistent')

            self.assertEqual(response.status_code, 404)
            self.assertIn('not found', response.json()['detail'])

    def test_update_role_success(self) -> None:
        """Test updating a role."""
        with (
            mock.patch('imbi.neo4j.fetch_node', return_value=None),
            mock.patch('imbi.neo4j.upsert') as mock_upsert,
        ):
            mock_upsert.return_value = 'element123'

            response = self.client.put(
                '/roles/test-role',
                json={
                    'name': 'Updated Role',
                    'slug': 'test-role',
                    'description': 'Updated description',
                    'priority': 200,
                    'is_system': False,
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['name'], 'Updated Role')
            self.assertEqual(data['priority'], 200)
            mock_upsert.assert_called_once()

    def test_update_role_slug_mismatch(self) -> None:
        """Test updating role with mismatched slug returns 400."""
        response = self.client.put(
            '/roles/test-role',
            json={
                'name': 'Test',
                'slug': 'wrong-slug',
                'priority': 100,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('must match', response.json()['detail'])

    def test_update_system_role_denied(self) -> None:
        """Test updating system role is denied."""
        system_role = models.Role(
            name='System Role',
            slug='system-role',
            priority=0,
            is_system=True,
        )

        with mock.patch('imbi.neo4j.fetch_node', return_value=system_role):
            response = self.client.put(
                '/roles/system-role',
                json={
                    'name': 'System Role',
                    'slug': 'system-role',
                    'priority': 100,
                    'is_system': True,
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn(
                'Cannot modify system role', response.json()['detail']
            )

    def test_delete_role_success(self) -> None:
        """Test deleting a role."""
        non_system_role = models.Role(
            name='Non-System Role',
            slug='non-system',
            priority=100,
            is_system=False,
        )

        with (
            mock.patch('imbi.neo4j.fetch_node', return_value=non_system_role),
            mock.patch('imbi.neo4j.delete_node', return_value=True),
        ):
            response = self.client.delete('/roles/non-system')

            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b'')

    def test_delete_role_not_found(self) -> None:
        """Test deleting non-existent role returns 404."""
        with mock.patch('imbi.neo4j.fetch_node', return_value=None):
            response = self.client.delete('/roles/nonexistent')

            self.assertEqual(response.status_code, 404)
            self.assertIn('not found', response.json()['detail'])

    def test_delete_system_role_denied(self) -> None:
        """Test deleting system role is denied."""
        system_role = models.Role(
            name='System Role',
            slug='system-role',
            priority=0,
            is_system=True,
        )

        with mock.patch('imbi.neo4j.fetch_node', return_value=system_role):
            response = self.client.delete('/roles/system-role')

            self.assertEqual(response.status_code, 400)
            self.assertIn(
                'Cannot delete system role', response.json()['detail']
            )

    def test_grant_permission_success(self) -> None:
        """Test granting permission to role."""
        role = self.test_role
        permission = models.Permission(
            name='blueprint:read',
            resource_type='blueprint',
            action='read',
            description='Read blueprints',
        )

        mock_result = mock.AsyncMock()
        mock_result.consume.return_value = None
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with (
            mock.patch(
                'imbi.neo4j.fetch_node', side_effect=[role, permission]
            ),
            mock.patch('imbi.neo4j.run', return_value=mock_result),
        ):
            response = self.client.post(
                '/roles/test-role/permissions',
                json={'permission_name': 'blueprint:read'},
            )

            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b'')

    def test_grant_permission_role_not_found(self) -> None:
        """Test granting permission when role doesn't exist."""
        with mock.patch('imbi.neo4j.fetch_node', return_value=None):
            response = self.client.post(
                '/roles/nonexistent/permissions',
                json={'permission_name': 'blueprint:read'},
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn('not found', response.json()['detail'])

    def test_grant_permission_permission_not_found(self) -> None:
        """Test granting non-existent permission."""
        role = self.test_role

        with mock.patch('imbi.neo4j.fetch_node', side_effect=[role, None]):
            response = self.client.post(
                '/roles/test-role/permissions',
                json={'permission_name': 'nonexistent:perm'},
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn('Permission', response.json()['detail'])

    def test_revoke_permission_success(self) -> None:
        """Test revoking permission from role."""
        role = self.test_role

        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'deleted': 1}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with (
            mock.patch('imbi.neo4j.fetch_node', return_value=role),
            mock.patch('imbi.neo4j.run', return_value=mock_result),
        ):
            response = self.client.delete(
                '/roles/test-role/permissions/blueprint:read'
            )

            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b'')

    def test_revoke_permission_role_not_found(self) -> None:
        """Test revoking permission when role doesn't exist."""
        with mock.patch('imbi.neo4j.fetch_node', return_value=None):
            response = self.client.delete(
                '/roles/nonexistent/permissions/blueprint:read'
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn('not found', response.json()['detail'])

    def test_revoke_permission_not_granted(self) -> None:
        """
        Verifies that attempting to revoke a permission not assigned to
        the role results in a 404 response containing "not granted".
        """
        role = self.test_role

        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'deleted': 0}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with (
            mock.patch('imbi.neo4j.fetch_node', return_value=role),
            mock.patch('imbi.neo4j.run', return_value=mock_result),
        ):
            response = self.client.delete(
                '/roles/test-role/permissions/blueprint:write'
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn('not granted', response.json()['detail'])
