"""Tests for user CRUD endpoints"""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from neo4j import exceptions

from imbi_api import app, models


class UserEndpointsTestCase(unittest.TestCase):
    """Test cases for user CRUD endpoints."""

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
                'user:create',
                'user:read',
                'user:update',
                'user:delete',
            },
        )

        # Override the get_current_user dependency
        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.client = testclient.TestClient(self.test_app)

        self.test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

    def test_create_user_success_with_password(self) -> None:
        """Test successful user creation with password."""
        with (
            mock.patch(
                'imbi_common.auth.core.hash_password',
            ) as mock_hash,
            mock.patch('imbi_common.neo4j.create_node') as mock_create,
        ):
            mock_hash.return_value = '$argon2id$hashed'
            mock_create.return_value = None

            response = self.client.post(
                '/users/',
                json={
                    'email': 'new@example.com',
                    'display_name': 'New User',
                    'password': 'SecurePass123!@#',
                    'is_active': True,
                    'is_admin': False,
                    'is_service_account': False,
                },
            )

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertEqual(data['email'], 'new@example.com')
            self.assertNotIn('password_hash', data)
            mock_hash.assert_called_once_with('SecurePass123!@#')

    def test_create_user_oauth_only(self) -> None:
        """Test creating user without password (OAuth-only)."""
        with mock.patch(
            'imbi_common.neo4j.create_node',
        ) as mock_create:
            mock_create.return_value = None

            response = self.client.post(
                '/users/',
                json={
                    'email': 'oauth@example.com',
                    'display_name': 'OAuth User',
                    'password': None,
                },
            )

            self.assertEqual(response.status_code, 201)

    def test_create_user_duplicate_username(self) -> None:
        """Test creating user with duplicate username."""
        with mock.patch(
            'imbi_common.neo4j.create_node',
        ) as mock_create:
            mock_create.side_effect = exceptions.ConstraintError('Duplicate')

            response = self.client.post(
                '/users/',
                json={
                    'email': 'dup@example.com',
                    'display_name': 'Duplicate User',
                },
            )

            self.assertEqual(response.status_code, 409)
            self.assertIn('already exists', response.json()['detail'])

    def test_list_users(self) -> None:
        """Test listing all users."""
        mock_users = [
            models.User(
                email=f'user{i}@example.com',
                display_name=f'User {i}',
                is_active=True,
                is_admin=False,
                is_service_account=False,
                created_at=datetime.datetime.now(datetime.UTC),
            )
            for i in range(3)
        ]

        async def mock_fetch():
            for user in mock_users:
                yield user

        with mock.patch(
            'imbi_common.neo4j.fetch_nodes',
            return_value=mock_fetch(),
        ):
            response = self.client.get('/users/')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 3)
            self.assertNotIn('password_hash', data[0])

    def test_list_users_filtered_active(self) -> None:
        """Test listing users filtered by active status."""
        mock_users = [
            models.User(
                email='active@example.com',
                display_name='Active User',
                is_active=True,
                is_admin=False,
                is_service_account=False,
                created_at=datetime.datetime.now(datetime.UTC),
            )
        ]

        async def mock_fetch():
            for user in mock_users:
                yield user

        with mock.patch(
            'imbi_common.neo4j.fetch_nodes',
            return_value=mock_fetch(),
        ):
            response = self.client.get('/users/?is_active=true')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 1)
            self.assertTrue(data[0]['is_active'])

    def test_list_users_filtered_admin(self) -> None:
        """Test listing users filtered by admin status."""
        mock_users = [
            models.User(
                email='admin2@example.com',
                display_name='Admin User 2',
                is_active=True,
                is_admin=True,
                is_service_account=False,
                created_at=datetime.datetime.now(datetime.UTC),
            )
        ]

        async def mock_fetch():
            for user in mock_users:
                yield user

        with mock.patch(
            'imbi_common.neo4j.fetch_nodes',
            return_value=mock_fetch(),
        ):
            response = self.client.get('/users/?is_admin=true')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 1)
            self.assertTrue(data[0]['is_admin'])

    def test_get_user_success(self) -> None:
        """Test retrieving a single user with org memberships."""
        mock_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        mock_org_result = mock.AsyncMock()
        mock_org_result.data.return_value = [
            {
                'org_name': 'Default',
                'org_slug': 'default',
                'role': 'developer',
            }
        ]
        mock_org_result.__aenter__.return_value = mock_org_result
        mock_org_result.__aexit__.return_value = None

        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node',
                return_value=mock_user,
            ),
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=mock_org_result,
            ),
        ):
            response = self.client.get('/users/test@example.com')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertNotIn('password_hash', data)
            self.assertEqual(len(data['organizations']), 1)
            self.assertEqual(
                data['organizations'][0]['organization_slug'],
                'default',
            )
            self.assertEqual(
                data['organizations'][0]['role'],
                'developer',
            )

    def test_get_user_not_found(self) -> None:
        """Test retrieving non-existent user."""
        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=None,
        ):
            response = self.client.get('/users/nonexistent@example.com')

            self.assertEqual(response.status_code, 404)
            self.assertIn('not found', response.json()['detail'])

    def test_update_user_success(self) -> None:
        """Test updating an existing user."""
        existing_user = models.User(
            email='test@example.com',
            display_name='Old Name',
            password_hash='$argon2id$oldhash',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime(
                2024,
                1,
                1,
                tzinfo=datetime.UTC,
            ),
        )

        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node',
                return_value=existing_user,
            ),
            mock.patch('imbi_common.neo4j.upsert') as mock_upsert,
        ):
            response = self.client.put(
                '/users/test@example.com',
                json={
                    'email': 'test@example.com',
                    'display_name': 'New Name',
                    'is_active': True,
                    'is_admin': False,
                    'is_service_account': False,
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['email'], 'test@example.com')
            self.assertEqual(data['display_name'], 'New Name')
            mock_upsert.assert_called_once()

    def test_update_user_email_mismatch(self) -> None:
        """Test updating user with mismatched email addresses."""
        response = self.client.put(
            '/users/test@example.com',
            json={
                'email': 'different@example.com',
                'display_name': 'Test',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('must match', response.json()['detail'])

    def test_update_user_non_admin_cannot_set_admin(self) -> None:
        """Test non-admin cannot grant admin privileges."""
        # Change auth context to non-admin
        self.auth_context.user.is_admin = False

        existing_user = models.User(
            email='test@example.com',
            display_name='Test',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=existing_user,
        ):
            response = self.client.put(
                '/users/test@example.com',
                json={
                    'email': 'test@example.com',
                    'display_name': 'Test',
                    'is_admin': True,  # Trying to elevate
                },
            )

            self.assertEqual(response.status_code, 403)
            self.assertIn('admin', response.json()['detail'].lower())

        # Restore admin status
        self.auth_context.user.is_admin = True

    def test_update_user_cannot_deactivate_self(self) -> None:
        """Test user cannot deactivate their own account."""
        self.auth_context.user.email = 'test@example.com'

        existing_user = models.User(
            email='test@example.com',
            display_name='Test',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=existing_user,
        ):
            response = self.client.put(
                '/users/test@example.com',
                json={
                    'email': 'test@example.com',
                    'display_name': 'Test',
                    'is_active': False,
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn('deactivate', response.json()['detail'])

        self.auth_context.user.email = 'admin@example.com'

    def test_update_user_not_found(self) -> None:
        """Test updating non-existent user."""
        with mock.patch(
            'imbi_common.neo4j.fetch_node',
            return_value=None,
        ):
            response = self.client.put(
                '/users/nonexistent@example.com',
                json={
                    'email': 'nonexistent@example.com',
                    'display_name': 'Test',
                },
            )

            self.assertEqual(response.status_code, 404)

    def test_delete_user_success(self) -> None:
        """Test deleting a user."""
        with mock.patch(
            'imbi_common.neo4j.delete_node',
            return_value=True,
        ):
            response = self.client.delete('/users/test@example.com')

            self.assertEqual(response.status_code, 204)

    def test_delete_user_cannot_delete_self(self) -> None:
        """Test user cannot delete their own account."""
        self.auth_context.user.email = 'test@example.com'

        response = self.client.delete('/users/test@example.com')

        self.assertEqual(response.status_code, 400)
        self.assertIn('delete', response.json()['detail'])

        self.auth_context.user.email = 'admin@example.com'

    def test_delete_user_not_found(self) -> None:
        """Test deleting non-existent user."""
        with mock.patch(
            'imbi_common.neo4j.delete_node',
            return_value=False,
        ):
            response = self.client.delete('/users/nonexistent@example.com')

            self.assertEqual(response.status_code, 404)

    def test_change_password_self_success(self) -> None:
        """Test user changing their own password."""
        self.auth_context.user.email = 'test@example.com'
        self.auth_context.user.is_admin = False

        mock_user = models.User(
            email='test@example.com',
            display_name='Test',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node',
                return_value=mock_user,
            ),
            mock.patch(
                'imbi_common.auth.core.verify_password',
                return_value=True,
            ),
            mock.patch(
                'imbi_common.auth.core.hash_password',
            ) as mock_hash,
            mock.patch('imbi_common.neo4j.upsert') as mock_upsert,
        ):
            mock_hash.return_value = '$argon2id$newhash'

            response = self.client.post(
                '/users/test@example.com/password',
                json={
                    'current_password': 'OldPass123!@#',
                    'new_password': 'NewSecure123!@#',
                },
            )

            self.assertEqual(response.status_code, 204)
            mock_hash.assert_called_once_with('NewSecure123!@#')
            mock_upsert.assert_called_once()

        self.auth_context.user.email = 'admin@example.com'
        self.auth_context.user.is_admin = True

    def test_change_password_admin_force_change(self) -> None:
        """Test admin changing another user's password."""
        mock_user = models.User(
            email='other@example.com',
            display_name='Other',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node',
                return_value=mock_user,
            ),
            mock.patch(
                'imbi_common.auth.core.hash_password',
            ) as mock_hash,
            mock.patch('imbi_common.neo4j.upsert'),
        ):
            mock_hash.return_value = '$argon2id$newhash'

            response = self.client.post(
                '/users/otheruser/password',
                json={
                    'new_password': 'AdminForced123!@#',
                },
            )

            self.assertEqual(response.status_code, 204)
            mock_hash.assert_called_once_with('AdminForced123!@#')

    def test_change_password_wrong_current(self) -> None:
        """Test password change with incorrect current password."""
        self.auth_context.user.email = 'test@example.com'
        self.auth_context.user.is_admin = False

        mock_user = models.User(
            email='test@example.com',
            display_name='Test',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node',
                return_value=mock_user,
            ),
            mock.patch(
                'imbi_common.auth.core.verify_password',
                return_value=False,
            ),
        ):
            response = self.client.post(
                '/users/test@example.com/password',
                json={
                    'current_password': 'WrongPass123!@#',
                    'new_password': 'NewSecure123!@#',
                },
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn(
                'incorrect',
                response.json()['detail'].lower(),
            )

        self.auth_context.user.email = 'admin@example.com'
        self.auth_context.user.is_admin = True

    def test_change_password_not_self_or_admin(self) -> None:
        """Test non-admin cannot change another user's password."""
        self.auth_context.user.is_admin = False
        self.auth_context.permissions = set()

        response = self.client.post(
            '/users/otheruser/password',
            json={'new_password': 'NewSecure123!@#'},
        )

        self.assertEqual(response.status_code, 403)

        self.auth_context.user.is_admin = True
        self.auth_context.permissions = {
            'user:create',
            'user:read',
            'user:update',
            'user:delete',
        }


class OrgMembershipEndpointsTestCase(unittest.TestCase):
    """Test org membership endpoints on users."""

    def setUp(self) -> None:
        """Set up test app with admin authentication context."""
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
            permissions={'user:update'},
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.client = testclient.TestClient(self.test_app)

    def test_add_to_organization_success(self) -> None:
        """Test adding a user to an organization."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'u': {}, 'o': {}, 'r': {}}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.post(
                '/users/test@example.com/organizations',
                json={
                    'organization_slug': 'default',
                    'role_slug': 'developer',
                },
            )

            self.assertEqual(response.status_code, 204)

    def test_add_to_organization_missing_fields(self) -> None:
        """Test adding to org with missing required fields."""
        response = self.client.post(
            '/users/test@example.com/organizations',
            json={'organization_slug': 'default'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('required', response.json()['detail'])

    def test_add_to_organization_not_found(self) -> None:
        """Test adding to non-existent org/user/role."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = []
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.post(
                '/users/test@example.com/organizations',
                json={
                    'organization_slug': 'nonexistent',
                    'role_slug': 'developer',
                },
            )

            self.assertEqual(response.status_code, 404)

    def test_update_organization_role_success(self) -> None:
        """Test changing a user's role in an organization."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'u': {}, 'o': {}, 'r': {}}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.put(
                '/users/test@example.com/organizations/default',
                json={'role_slug': 'admin'},
            )

            self.assertEqual(response.status_code, 204)

    def test_update_organization_role_missing_slug(self) -> None:
        """Test updating role without role_slug."""
        response = self.client.put(
            '/users/test@example.com/organizations/default',
            json={},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('required', response.json()['detail'])

    def test_update_organization_role_not_found(self) -> None:
        """Test updating role for non-existent membership."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = []
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.put(
                '/users/test@example.com/organizations/nonexistent',
                json={'role_slug': 'admin'},
            )

            self.assertEqual(response.status_code, 404)

    def test_remove_from_organization_success(self) -> None:
        """Test removing a user from an organization."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'deleted': 1}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.delete(
                '/users/test@example.com/organizations/default'
            )

            self.assertEqual(response.status_code, 204)

    def test_remove_from_organization_not_member(self) -> None:
        """Test removing user from org they're not in."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'deleted': 0}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.delete(
                '/users/test@example.com/organizations/other-org'
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'not a member',
                response.json()['detail'],
            )
