"""Tests for group CRUD endpoints"""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from neo4j import exceptions

from imbi_api import app, models


class GroupEndpointsTestCase(unittest.TestCase):
    """Test cases for group CRUD endpoints."""

    def setUp(self) -> None:
        """Set up test app with admin authentication context."""
        from imbi_api.auth import permissions

        self.test_app = app.create_app()

        # Create an admin user for authentication
        self.admin_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_context = permissions.AuthContext(
            user=self.admin_user,
            session_id='test-session',
            auth_method='jwt',
            permissions={
                'group:create',
                'group:read',
                'group:update',
                'group:delete',
            },
        )

        # Override the get_current_user dependency
        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.client = testclient.TestClient(self.test_app)

        self.test_group = models.Group(
            name='Engineering',
            slug='engineering',
            description='Engineering team',
        )

    def test_create_group_success(self) -> None:
        """Test successful group creation."""
        with mock.patch('imbi_common.neo4j.create_node') as mock_create:
            mock_create.return_value = self.test_group

            response = self.client.post(
                '/groups/',
                json={
                    'name': 'Engineering',
                    'slug': 'engineering',
                    'description': 'Engineering team',
                },
            )

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertEqual(data['slug'], 'engineering')
            self.assertEqual(data['name'], 'Engineering')

    def test_create_group_duplicate_slug(self) -> None:
        """Test creating group with duplicate slug."""
        with mock.patch('imbi_common.neo4j.create_node') as mock_create:
            mock_create.side_effect = exceptions.ConstraintError('Duplicate')

            response = self.client.post(
                '/groups/',
                json={
                    'name': 'Engineering',
                    'slug': 'engineering',
                    'description': 'Engineering team',
                },
            )

            self.assertEqual(response.status_code, 409)
            self.assertIn('already exists', response.json()['detail'])

    def test_list_groups(self) -> None:
        """Test listing all groups."""
        mock_groups = [
            models.Group(
                name=f'Group {i}',
                slug=f'group-{i}',
                description=f'Test group {i}',
            )
            for i in range(3)
        ]

        async def mock_fetch():
            for group in mock_groups:
                yield group

        with mock.patch(
            'imbi_common.neo4j.fetch_nodes', return_value=mock_fetch()
        ):
            response = self.client.get('/groups/')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 3)

    def test_get_group_success(self) -> None:
        """Test retrieving a single group with relationships."""
        mock_group = models.Group(
            name='Engineering',
            slug='engineering',
            description='Engineering team',
            parent=None,
            roles=[],
        )

        mock_roles_result = mock.AsyncMock()
        mock_roles_result.data.return_value = []
        mock_roles_ctx = mock.AsyncMock()
        mock_roles_ctx.__aenter__.return_value = mock_roles_result
        mock_roles_ctx.__aexit__.return_value = None

        mock_parent_result = mock.AsyncMock()
        mock_parent_result.data.return_value = []
        mock_parent_ctx = mock.AsyncMock()
        mock_parent_ctx.__aenter__.return_value = mock_parent_result
        mock_parent_ctx.__aexit__.return_value = None

        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node', return_value=mock_group
            ),
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[mock_roles_ctx, mock_parent_ctx],
            ),
        ):
            response = self.client.get('/groups/engineering')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['slug'], 'engineering')

    def test_get_group_not_found(self) -> None:
        """Test retrieving non-existent group."""
        with mock.patch('imbi_common.neo4j.fetch_node', return_value=None):
            response = self.client.get('/groups/nonexistent')

            self.assertEqual(response.status_code, 404)
            self.assertIn('not found', response.json()['detail'])

    def test_list_group_members_success(self) -> None:
        """Test listing members of a group."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                'g': {'name': 'Engineering', 'slug': 'engineering'},
                'members': [
                    {
                        'email': 'user1@example.com',
                        'display_name': 'User 1',
                        'is_active': True,
                        'is_admin': False,
                        'is_service_account': False,
                        'created_at': datetime.datetime.now(datetime.UTC),
                    },
                    {
                        'email': 'user2@example.com',
                        'display_name': 'User 2',
                        'is_active': True,
                        'is_admin': False,
                        'is_service_account': False,
                        'created_at': datetime.datetime.now(datetime.UTC),
                    },
                ],
            }
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            response = self.client.get('/groups/engineering/members')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 2)

    def test_list_group_members_group_not_found(self) -> None:
        """Test listing members of non-existent group."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = []
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            response = self.client.get('/groups/nonexistent/members')

            self.assertEqual(response.status_code, 404)

    def test_update_group_success(self) -> None:
        """Test updating an existing group."""
        existing_group = models.Group(
            name='Old Name',
            slug='engineering',
            description='Old description',
        )

        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node', return_value=existing_group
            ),
            mock.patch('imbi_common.neo4j.upsert') as mock_upsert,
        ):
            response = self.client.put(
                '/groups/engineering',
                json={
                    'name': 'New Name',
                    'slug': 'engineering',
                    'description': 'New description',
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['name'], 'New Name')
            mock_upsert.assert_called_once()

    def test_update_group_slug_mismatch(self) -> None:
        """Test updating group with mismatched slugs."""
        response = self.client.put(
            '/groups/engineering',
            json={
                'name': 'Engineering',
                'slug': 'different-slug',
                'description': 'Test',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('must match', response.json()['detail'])

    def test_update_group_not_found(self) -> None:
        """Test updating non-existent group."""
        with mock.patch('imbi_common.neo4j.fetch_node', return_value=None):
            response = self.client.put(
                '/groups/nonexistent',
                json={
                    'name': 'Test',
                    'slug': 'nonexistent',
                    'description': 'Test',
                },
            )

            self.assertEqual(response.status_code, 404)

    def test_delete_group_success(self) -> None:
        """Test deleting a group."""
        with mock.patch('imbi_common.neo4j.delete_node', return_value=True):
            response = self.client.delete('/groups/engineering')

            self.assertEqual(response.status_code, 204)

    def test_delete_group_not_found(self) -> None:
        """Test deleting non-existent group."""
        with mock.patch('imbi_common.neo4j.delete_node', return_value=False):
            response = self.client.delete('/groups/nonexistent')

            self.assertEqual(response.status_code, 404)

    def test_set_parent_group_success(self) -> None:
        """Test setting a parent group."""
        # Mock circular check (no circular reference)
        mock_circular_result = mock.AsyncMock()
        mock_circular_result.data.return_value = [{'circular': 0}]
        mock_circular_result.__aenter__.return_value = mock_circular_result
        mock_circular_result.__aexit__.return_value = None

        # Mock set parent
        mock_set_result = mock.AsyncMock()
        mock_set_result.data.return_value = [{'child': {}, 'parent': {}}]
        mock_set_result.__aenter__.return_value = mock_set_result
        mock_set_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            side_effect=[mock_circular_result, mock_set_result],
        ):
            response = self.client.post(
                '/groups/sub-team/parent',
                json={'parent_slug': 'engineering'},
            )

            self.assertEqual(response.status_code, 204)

    def test_set_parent_group_self_parent_prevented(self) -> None:
        """Test preventing group from being its own parent."""
        response = self.client.post(
            '/groups/engineering/parent',
            json={'parent_slug': 'engineering'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('own parent', response.json()['detail'])

    def test_set_parent_group_circular_prevented(self) -> None:
        """Test preventing circular parent relationships."""
        # Mock circular check (circular reference detected)
        mock_circular_result = mock.AsyncMock()
        mock_circular_result.data.return_value = [{'circular': 1}]
        mock_circular_result.__aenter__.return_value = mock_circular_result
        mock_circular_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run', return_value=mock_circular_result
        ):
            response = self.client.post(
                '/groups/engineering/parent',
                json={'parent_slug': 'sub-team'},
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn('circular', response.json()['detail'])

    def test_set_parent_group_not_found(self) -> None:
        """Test setting parent when group or parent doesn't exist."""
        # Mock circular check
        mock_circular_result = mock.AsyncMock()
        mock_circular_result.data.return_value = [{'circular': 0}]
        mock_circular_result.__aenter__.return_value = mock_circular_result
        mock_circular_result.__aexit__.return_value = None

        # Mock set parent (not found)
        mock_set_result = mock.AsyncMock()
        mock_set_result.data.return_value = []
        mock_set_result.__aenter__.return_value = mock_set_result
        mock_set_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            side_effect=[mock_circular_result, mock_set_result],
        ):
            response = self.client.post(
                '/groups/nonexistent/parent',
                json={'parent_slug': 'engineering'},
            )

            self.assertEqual(response.status_code, 404)

    def test_remove_parent_group_success(self) -> None:
        """Test removing parent group relationship."""
        mock_result = mock.AsyncMock()
        mock_result.consume.return_value = None
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            response = self.client.delete('/groups/sub-team/parent')

            self.assertEqual(response.status_code, 204)

    def test_assign_role_to_group_success(self) -> None:
        """Test assigning a role to a group."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'g': {}, 'r': {}}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            response = self.client.post(
                '/groups/engineering/roles',
                json={'role_slug': 'developer'},
            )

            self.assertEqual(response.status_code, 204)

    def test_assign_role_to_group_not_found(self) -> None:
        """Test assigning role to non-existent group."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = []
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            response = self.client.post(
                '/groups/nonexistent/roles',
                json={'role_slug': 'developer'},
            )

            self.assertEqual(response.status_code, 404)

    def test_unassign_role_from_group_success(self) -> None:
        """Test unassigning a role from a group."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'deleted': 1}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            response = self.client.delete(
                '/groups/engineering/roles/developer'
            )

            self.assertEqual(response.status_code, 204)

    def test_unassign_role_from_group_not_assigned(self) -> None:
        """Test unassigning role that group doesn't have."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'deleted': 0}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            response = self.client.delete('/groups/engineering/roles/admin')

            self.assertEqual(response.status_code, 404)
            self.assertIn('does not have', response.json()['detail'])
