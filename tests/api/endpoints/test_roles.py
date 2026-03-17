"""Tests for role CRUD endpoints"""

import datetime
import unittest
from unittest import mock

from fastapi import testclient

from imbi_api import app, models


class RoleEndpointsTestCase(unittest.TestCase):
    """Test cases for role CRUD endpoints."""

    def setUp(self) -> None:
        """Set up test app with admin authentication."""
        from imbi_api.auth import permissions

        self.test_app = app.create_app()

        self.admin_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_context = permissions.AuthContext(
            user=self.admin_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user():
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
        with mock.patch(
            'imbi_common.neo4j.create_node',
        ) as mock_create:
            mock_create.return_value = models.Role(
                name='New Role',
                slug='new-role',
                description='A new role',
                priority=100,
                is_system=False,
            )

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

        with mock.patch(
            'imbi_common.neo4j.create_node',
        ) as mock_create:
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
            self.assertIn(
                'already exists',
                response.json()['detail'],
            )

    def test_list_roles(self) -> None:
        """Test listing all roles with relationships."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                'role': {
                    'name': 'Test Role',
                    'slug': 'test-role',
                    'description': 'A test role',
                    'priority': 100,
                    'is_system': False,
                },
                'permission_count': 5,
                'user_count': 3,
            },
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.get('/roles/')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['name'], 'Test Role')
            self.assertEqual(data[0]['slug'], 'test-role')
            rels = data[0]['relationships']
            self.assertEqual(
                rels['permissions']['count'],
                5,
            )
            self.assertEqual(
                rels['users']['count'],
                3,
            )

    def test_get_role_success(self) -> None:
        """Test getting a specific role."""
        mock_perm_result = mock.AsyncMock()
        mock_perm_result.data.return_value = []
        mock_perm_result.__aenter__.return_value = mock_perm_result
        mock_perm_result.__aexit__.return_value = None

        mock_parent_result = mock.AsyncMock()
        mock_parent_result.data.return_value = []
        mock_parent_result.__aenter__.return_value = mock_parent_result
        mock_parent_result.__aexit__.return_value = None

        mock_count_result = mock.AsyncMock()
        mock_count_result.data.return_value = [
            {'user_count': 2},
        ]
        mock_count_result.__aenter__.return_value = mock_count_result
        mock_count_result.__aexit__.return_value = None

        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node',
                return_value=self.test_role,
            ),
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[
                    mock_perm_result,
                    mock_parent_result,
                    mock_count_result,
                ],
            ) as mock_run,
        ):
            response = self.client.get('/roles/test-role')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['name'], 'Test Role')
            self.assertEqual(data['slug'], 'test-role')
            self.assertIn('relationships', data)
            rels = data['relationships']
            self.assertEqual(
                rels['permissions']['count'],
                0,
            )
            self.assertEqual(
                rels['users']['count'],
                2,
            )

            # Verify Cypher queries were executed for
            # permissions, parent role, and user count
            self.assertEqual(mock_run.call_count, 3)

    def test_get_role_not_found(self) -> None:
        """Test getting non-existent role returns 404."""
        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=None,
        ):
            response = self.client.get('/roles/nonexistent')

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'not found',
                response.json()['detail'],
            )

    def test_update_role_success(self) -> None:
        """Test updating a role."""
        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node',
                return_value=None,
            ),
            mock.patch(
                'imbi_common.neo4j.upsert',
            ) as mock_upsert,
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

    def test_update_role_slug_rename(self) -> None:
        """Test updating role with different slug renames it."""
        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node',
                return_value=None,
            ),
            mock.patch(
                'imbi_common.neo4j.upsert',
            ) as mock_upsert,
        ):
            response = self.client.put(
                '/roles/test-role',
                json={
                    'name': 'Test',
                    'slug': 'new-slug',
                    'priority': 100,
                },
            )

            self.assertEqual(response.status_code, 200)
            mock_upsert.assert_called_once()
            call_args = mock_upsert.call_args
            self.assertEqual(call_args[0][0].slug, 'new-slug')
            self.assertEqual(
                call_args[0][1],
                {'slug': 'test-role'},
            )

    def test_update_system_role_denied(self) -> None:
        """Test updating system role is denied."""
        system_role = models.Role(
            name='System Role',
            slug='system-role',
            priority=0,
            is_system=True,
        )

        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=system_role,
        ):
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
                'Cannot modify system role',
                response.json()['detail'],
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
            mock.patch(
                'imbi_common.neo4j.fetch_node',
                return_value=non_system_role,
            ),
            mock.patch(
                'imbi_common.neo4j.delete_node',
                return_value=True,
            ),
        ):
            response = self.client.delete('/roles/non-system')

            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b'')

    def test_delete_role_not_found(self) -> None:
        """Test deleting non-existent role returns 404."""
        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=None,
        ):
            response = self.client.delete(
                '/roles/nonexistent',
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'not found',
                response.json()['detail'],
            )

    def test_delete_system_role_denied(self) -> None:
        """Test deleting system role is denied."""
        system_role = models.Role(
            name='System Role',
            slug='system-role',
            priority=0,
            is_system=True,
        )

        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=system_role,
        ):
            response = self.client.delete(
                '/roles/system-role',
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn(
                'Cannot delete system role',
                response.json()['detail'],
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
                'imbi_common.neo4j.fetch_node',
                side_effect=[role, permission],
            ),
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=mock_result,
            ),
        ):
            response = self.client.post(
                '/roles/test-role/permissions',
                json={'permission_name': 'blueprint:read'},
            )

            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b'')

    def test_grant_permission_role_not_found(self) -> None:
        """Test granting permission when role doesn't exist."""
        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=None,
        ):
            response = self.client.post(
                '/roles/nonexistent/permissions',
                json={'permission_name': 'blueprint:read'},
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'not found',
                response.json()['detail'],
            )

    def test_grant_permission_permission_not_found(self) -> None:
        """Test granting non-existent permission."""
        role = self.test_role

        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            side_effect=[role, None],
        ):
            response = self.client.post(
                '/roles/test-role/permissions',
                json={'permission_name': 'nonexistent:perm'},
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'Permission',
                response.json()['detail'],
            )

    def test_revoke_permission_success(self) -> None:
        """Test revoking permission from role."""
        role = self.test_role

        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'deleted': 1}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node',
                return_value=role,
            ),
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=mock_result,
            ),
        ):
            response = self.client.delete(
                '/roles/test-role/permissions/blueprint:read'
            )

            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b'')

    def test_revoke_permission_role_not_found(self) -> None:
        """Test revoking permission when role doesn't exist."""
        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=None,
        ):
            response = self.client.delete(
                '/roles/nonexistent/permissions/blueprint:read'
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'not found',
                response.json()['detail'],
            )

    def test_list_role_users_success(self) -> None:
        """Test listing users assigned a role via org membership."""
        with mock.patch(
            'imbi_common.neo4j.query',
        ) as mock_query:
            mock_query.return_value = [
                {
                    'r': {
                        'name': 'Test Role',
                        'slug': 'test-role',
                    },
                    'users': [
                        {
                            'email': 'user1@example.com',
                            'display_name': 'User 1',
                            'is_active': True,
                            'is_admin': False,
                            'is_service_account': False,
                            'created_at': '2026-01-01T00:00:00+00:00',
                        },
                    ],
                },
            ]

            response = self.client.get('/roles/test-role/users')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 1)
            self.assertEqual(
                data[0]['email'],
                'user1@example.com',
            )

    def test_list_role_users_not_found(self) -> None:
        """Test listing users for non-existent role returns 404."""
        with mock.patch(
            'imbi_common.neo4j.query',
        ) as mock_query:
            mock_query.return_value = [{'r': None, 'users': []}]

            response = self.client.get(
                '/roles/nonexistent/users',
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'not found',
                response.json()['detail'],
            )

    def test_list_role_users_empty(self) -> None:
        """Test listing users when role exists but has no users."""
        with mock.patch(
            'imbi_common.neo4j.query',
        ) as mock_query:
            mock_query.return_value = [
                {
                    'r': {
                        'name': 'Empty Role',
                        'slug': 'empty-role',
                    },
                    'users': [],
                },
            ]

            response = self.client.get('/roles/empty-role/users')

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), [])

    def test_list_role_service_accounts_success(self) -> None:
        """Test listing service accounts assigned a role."""
        with mock.patch(
            'imbi_common.neo4j.query',
        ) as mock_query:
            mock_query.return_value = [
                {
                    'r': {
                        'name': 'Test Role',
                        'slug': 'test-role',
                    },
                    'service_accounts': [
                        {
                            'slug': 'deploy-bot',
                            'display_name': 'Deploy Bot',
                            'is_active': True,
                            'created_at': '2026-01-01T00:00:00+00:00',
                        },
                    ],
                },
            ]

            response = self.client.get(
                '/roles/test-role/service-accounts',
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['slug'], 'deploy-bot')

    def test_list_role_service_accounts_not_found(self) -> None:
        """Test listing SAs for non-existent role returns 404."""
        with mock.patch(
            'imbi_common.neo4j.query',
        ) as mock_query:
            mock_query.return_value = [
                {'r': None, 'service_accounts': []},
            ]

            response = self.client.get(
                '/roles/nonexistent/service-accounts',
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'not found',
                response.json()['detail'],
            )

    def test_list_role_service_accounts_empty(self) -> None:
        """Test listing SAs when role has none assigned."""
        with mock.patch(
            'imbi_common.neo4j.query',
        ) as mock_query:
            mock_query.return_value = [
                {
                    'r': {
                        'name': 'Empty Role',
                        'slug': 'empty-role',
                    },
                    'service_accounts': [],
                },
            ]

            response = self.client.get(
                '/roles/empty-role/service-accounts',
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), [])

    def test_revoke_permission_not_granted(self) -> None:
        """Test revoking ungranted permission returns 404."""
        role = self.test_role

        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'deleted': 0}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node',
                return_value=role,
            ),
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=mock_result,
            ),
        ):
            response = self.client.delete(
                '/roles/test-role/permissions/blueprint:write'
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'not granted',
                response.json()['detail'],
            )
