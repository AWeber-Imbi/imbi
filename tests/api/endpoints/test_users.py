"""Tests for user CRUD endpoints"""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common import graph

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

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
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
        self.mock_db.match.return_value = []
        self.mock_db.create.return_value = mock.AsyncMock()
        self.mock_db.execute.return_value = [
            {
                'org_name': 'Default',
                'org_slug': 'default',
                'role': 'developer',
            },
        ]

        with mock.patch(
            'imbi_api.auth.password.hash_password',
        ) as mock_hash:
            mock_hash.return_value = '$argon2id$hashed'

            with mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ):
                response = self.client.post(
                    '/users/',
                    json={
                        'email': 'new@example.com',
                        'display_name': 'New User',
                        'password': 'SecurePass123!@#',
                        'is_active': True,
                        'is_admin': False,
                        'is_service_account': False,
                        'organization_slug': 'default',
                        'role_slug': 'developer',
                    },
                )

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertEqual(data['email'], 'new@example.com')
            self.assertNotIn('password_hash', data)
            self.assertEqual(len(data['organizations']), 1)
            self.assertEqual(
                data['organizations'][0]['organization_slug'],
                'default',
            )
            mock_hash.assert_called_once_with('SecurePass123!@#')

    def test_create_user_oauth_only(self) -> None:
        """Test creating user without password (OAuth-only)."""
        self.mock_db.match.return_value = []
        self.mock_db.create.return_value = mock.AsyncMock()
        self.mock_db.execute.return_value = [
            {
                'org_name': 'Default',
                'org_slug': 'default',
                'role': 'developer',
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/users/',
                json={
                    'email': 'oauth@example.com',
                    'display_name': 'OAuth User',
                    'password': None,
                    'organization_slug': 'default',
                    'role_slug': 'developer',
                },
            )

        self.assertEqual(response.status_code, 201)

    def test_create_user_duplicate_username(self) -> None:
        """Test creating user with duplicate username."""
        self.mock_db.match.return_value = [self.test_user]

        response = self.client.post(
            '/users/',
            json={
                'email': 'dup@example.com',
                'display_name': 'Duplicate User',
                'organization_slug': 'default',
                'role_slug': 'developer',
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

    def test_create_user_missing_org_slug(self) -> None:
        """Test creating user without organization_slug."""
        response = self.client.post(
            '/users/',
            json={
                'email': 'new@example.com',
                'display_name': 'New User',
                'role_slug': 'developer',
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_create_user_missing_role_slug(self) -> None:
        """Test creating user without role_slug returns 422."""
        response = self.client.post(
            '/users/',
            json={
                'email': 'new@example.com',
                'display_name': 'New User',
                'organization_slug': 'default',
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_create_user_invalid_org_rollback(self) -> None:
        """Test user is deleted when org/role not found."""
        self.mock_db.match.return_value = []
        self.mock_db.create.return_value = mock.AsyncMock()
        self.mock_db.execute.return_value = []
        self.mock_db.delete.return_value = None

        response = self.client.post(
            '/users/',
            json={
                'email': 'new@example.com',
                'display_name': 'New User',
                'organization_slug': 'nonexistent',
                'role_slug': 'developer',
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])
        # Verify: match (existence), create, execute (membership),
        # delete (rollback)
        self.mock_db.match.assert_called_once()
        self.mock_db.create.assert_called_once()
        self.mock_db.execute.assert_called_once()
        self.mock_db.delete.assert_called_once()

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
        self.mock_db.match.return_value = mock_users

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
        self.mock_db.match.return_value = mock_users

        response = self.client.get(
            '/users/?is_active=true',
        )

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
        self.mock_db.match.return_value = mock_users

        response = self.client.get('/users/?is_admin=true')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertTrue(data[0]['is_admin'])

    def test_get_user_success(self) -> None:
        """Test retrieving a single user with memberships."""
        mock_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.mock_db.match.return_value = [mock_user]
        self.mock_db.execute.return_value = [
            {
                'org_name': 'Default',
                'org_slug': 'default',
                'role': 'developer',
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/users/test@example.com',
            )

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
        self.mock_db.match.return_value = []

        response = self.client.get(
            '/users/nonexistent@example.com',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_delete_user_success(self) -> None:
        """Test deleting a user."""
        self.mock_db.execute.return_value = [{'n': 'true'}]

        response = self.client.delete(
            '/users/test@example.com',
        )

        self.assertEqual(response.status_code, 204)

    def test_delete_user_cannot_delete_self(self) -> None:
        """Test user cannot delete their own account."""
        self.auth_context.user.email = 'test@example.com'

        response = self.client.delete(
            '/users/test@example.com',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('delete', response.json()['detail'])

        self.auth_context.user.email = 'admin@example.com'

    def test_delete_user_not_found(self) -> None:
        """Test deleting non-existent user."""
        self.mock_db.execute.return_value = []

        response = self.client.delete(
            '/users/nonexistent@example.com',
        )

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
        self.mock_db.match.return_value = [mock_user]
        self.mock_db.merge.return_value = None

        with (
            mock.patch(
                'imbi_api.auth.password.verify_password',
                return_value=True,
            ),
            mock.patch(
                'imbi_api.auth.password.hash_password',
            ) as mock_hash,
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
            self.mock_db.merge.assert_called_once()

        self.auth_context.user.email = 'admin@example.com'
        self.auth_context.user.is_admin = True

    def test_change_password_admin_force_change(
        self,
    ) -> None:
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
        self.mock_db.match.return_value = [mock_user]
        self.mock_db.merge.return_value = None

        with mock.patch(
            'imbi_api.auth.password.hash_password',
        ) as mock_hash:
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
        """Test password change with incorrect current."""
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
        self.mock_db.match.return_value = [mock_user]

        with mock.patch(
            'imbi_api.auth.password.verify_password',
            return_value=False,
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
        """Test non-admin cannot change another password."""
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

    def test_patch_user_display_name(self) -> None:
        """Test patching only the user's display name."""
        existing_user = models.User(
            email='dev@example.com',
            display_name='Old Name',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
        )
        self.mock_db.match.return_value = [existing_user]
        self.mock_db.merge.return_value = None

        response = self.client.patch(
            '/users/dev%40example.com',
            json=[
                {
                    'op': 'replace',
                    'path': '/display_name',
                    'value': 'New Name',
                }
            ],
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['display_name'], 'New Name')

    def test_patch_user_not_found(self) -> None:
        """Test patching non-existent user returns 404."""
        self.mock_db.match.return_value = []

        response = self.client.patch(
            '/users/nobody%40example.com',
            json=[
                {
                    'op': 'replace',
                    'path': '/display_name',
                    'value': 'X',
                }
            ],
        )

        self.assertEqual(response.status_code, 404)

    def test_patch_user_non_admin_cannot_grant_admin(
        self,
    ) -> None:
        """Test that non-admin cannot patch is_admin to True."""
        self.auth_context.user.is_admin = False

        existing_user = models.User(
            email='dev@example.com',
            display_name='Dev',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
        )
        self.mock_db.match.return_value = [existing_user]

        response = self.client.patch(
            '/users/dev%40example.com',
            json=[
                {
                    'op': 'replace',
                    'path': '/is_admin',
                    'value': True,
                }
            ],
        )

        self.assertEqual(response.status_code, 403)

        self.auth_context.user.is_admin = True

    def test_patch_user_non_admin_cannot_modify_admin(self) -> None:
        """Non-admins cannot patch admin users."""
        self.auth_context.user.is_admin = False

        admin_user = models.User(
            email='admin@example.com',
            display_name='Admin',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
        )
        self.mock_db.match.return_value = [admin_user]

        response = self.client.patch(
            '/users/admin%40example.com',
            json=[
                {
                    'op': 'replace',
                    'path': '/display_name',
                    'value': 'Renamed',
                },
            ],
        )

        self.assertEqual(response.status_code, 403)

        self.auth_context.user.is_admin = True

    def test_patch_user_cannot_deactivate_self(self) -> None:
        """Users cannot deactivate themselves via PATCH."""
        self.auth_context.user.email = 'test@example.com'

        existing_user = models.User(
            email='test@example.com',
            display_name='Test',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.mock_db.match.return_value = [existing_user]

        response = self.client.patch(
            '/users/test%40example.com',
            json=[
                {
                    'op': 'replace',
                    'path': '/is_active',
                    'value': False,
                },
            ],
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('deactivate', response.json()['detail'])

        self.auth_context.user.email = 'admin@example.com'

    def test_patch_user_service_account_cannot_be_admin(self) -> None:
        """Setting is_service_account + is_admin on a user returns 400."""
        existing_user = models.User(
            email='u@example.com',
            display_name='U',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.mock_db.match.return_value = [existing_user]

        response = self.client.patch(
            '/users/u%40example.com',
            json=[
                {
                    'op': 'replace',
                    'path': '/is_service_account',
                    'value': True,
                },
            ],
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('admins', response.json()['detail'])

    def test_patch_user_service_account_clears_password(self) -> None:
        """Becoming a service account clears the password hash."""
        existing_user = models.User(
            email='svc@example.com',
            display_name='Svc',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.mock_db.match.return_value = [existing_user]
        self.mock_db.merge.return_value = None

        response = self.client.patch(
            '/users/svc%40example.com',
            json=[
                {
                    'op': 'replace',
                    'path': '/is_service_account',
                    'value': True,
                },
            ],
        )

        self.assertEqual(response.status_code, 200)
        merged_user = self.mock_db.merge.call_args.args[0]
        self.assertIsNone(merged_user.password_hash)


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

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)

    def test_add_to_organization_success(self) -> None:
        """Test adding a user to an organization."""
        self.mock_db.execute.return_value = [
            {'u': {}, 'o': {}, 'r': {}},
        ]

        response = self.client.post(
            '/users/test@example.com/organizations',
            json={
                'organization_slug': 'default',
                'role_slug': 'developer',
            },
        )

        self.assertEqual(response.status_code, 204)

    def test_add_to_organization_missing_fields(
        self,
    ) -> None:
        """Test adding to org with missing required fields."""
        response = self.client.post(
            '/users/test@example.com/organizations',
            json={'organization_slug': 'default'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('required', response.json()['detail'])

    def test_add_to_organization_not_found(self) -> None:
        """Test adding to non-existent org/user/role."""
        self.mock_db.execute.return_value = []

        response = self.client.post(
            '/users/test@example.com/organizations',
            json={
                'organization_slug': 'nonexistent',
                'role_slug': 'developer',
            },
        )

        self.assertEqual(response.status_code, 404)

    def test_remove_from_organization_success(self) -> None:
        """Test removing a user from an organization."""
        self.mock_db.execute.return_value = [{'m': 'true'}]

        response = self.client.delete(
            '/users/test@example.com/organizations/default'
        )

        self.assertEqual(response.status_code, 204)

    def test_remove_from_organization_not_member(
        self,
    ) -> None:
        """Test removing user from org they're not in."""
        self.mock_db.execute.return_value = []

        response = self.client.delete(
            '/users/test@example.com/organizations/other-org'
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn(
            'not a member',
            response.json()['detail'],
        )

    def test_update_organization_role_success(self) -> None:
        """PATCH updates the membership role."""
        self.mock_db.execute.side_effect = [
            [{'slug': 'admin'}],
            [{'role': 'admin'}],
        ]

        response = self.client.patch(
            '/users/test@example.com/organizations/default',
            json=[
                {
                    'op': 'replace',
                    'path': '/role_slug',
                    'value': 'admin',
                },
            ],
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.mock_db.execute.call_count, 2)

    def test_update_organization_role_missing_role(self) -> None:
        """PATCH returns 404 when the target role does not exist."""
        self.mock_db.execute.side_effect = [[]]

        response = self.client.patch(
            '/users/test@example.com/organizations/default',
            json=[
                {
                    'op': 'replace',
                    'path': '/role_slug',
                    'value': 'ghost',
                },
            ],
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('Role', response.json()['detail'])

    def test_update_organization_role_missing_membership(
        self,
    ) -> None:
        """PATCH returns 404 when the user is not a member."""
        self.mock_db.execute.side_effect = [
            [{'slug': 'admin'}],
            [],
        ]

        response = self.client.patch(
            '/users/test@example.com/organizations/other-org',
            json=[
                {
                    'op': 'replace',
                    'path': '/role_slug',
                    'value': 'admin',
                },
            ],
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not a member', response.json()['detail'])

    def test_update_organization_role_malformed_patch(self) -> None:
        """PATCH with wrong path returns 400 without touching graph."""
        response = self.client.patch(
            '/users/test@example.com/organizations/default',
            json=[
                {
                    'op': 'replace',
                    'path': '/display_name',
                    'value': 'nope',
                },
            ],
        )

        self.assertEqual(response.status_code, 400)
        self.mock_db.execute.assert_not_awaited()


class ServiceAccountGuardRailsTestCase(unittest.TestCase):
    """Test guardrails for invalid service account operations."""

    def setUp(self) -> None:
        """Set up test app with admin authentication context."""
        from imbi_api.auth import permissions

        self.test_app = app.create_app()

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

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)

    def test_create_service_account_with_password_blocked(
        self,
    ) -> None:
        """POST /users with is_service_account+password = 400."""
        response = self.client.post(
            '/users/',
            json={
                'email': 'sa@example.com',
                'display_name': 'SA With Password',
                'password': 'SecurePass123!@#',
                'is_active': True,
                'is_admin': False,
                'is_service_account': True,
                'organization_slug': 'default',
                'role_slug': 'developer',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'Service accounts cannot have passwords',
            response.json()['detail'],
        )

    def test_create_service_account_as_admin_blocked(
        self,
    ) -> None:
        """POST /users with is_service_account+is_admin = 400."""
        response = self.client.post(
            '/users/',
            json={
                'email': 'sa-admin@example.com',
                'display_name': 'SA Admin',
                'is_active': True,
                'is_admin': True,
                'is_service_account': True,
                'organization_slug': 'default',
                'role_slug': 'developer',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'Service accounts cannot be admins',
            response.json()['detail'],
        )

    def test_change_password_for_service_account_blocked(
        self,
    ) -> None:
        """POST /users/{email}/password for SA returns 400."""
        sa_user = models.User(
            email='sa@example.com',
            display_name='SA User',
            is_active=True,
            is_admin=False,
            is_service_account=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.mock_db.match.return_value = [sa_user]

        response = self.client.post(
            '/users/sa@example.com/password',
            json={
                'new_password': 'NewSecure123!@#',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'Service accounts cannot have passwords',
            response.json()['detail'],
        )
