"""Tests for admin settings endpoint."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common import graph

from imbi_api import app, models, settings
from imbi_api.auth import password, permissions


class AdminSettingsEndpointTestCase(unittest.TestCase):
    """Test cases for GET /admin/settings endpoint."""

    def setUp(self) -> None:
        """Set up test client, auth settings, and test user."""
        self.test_app = app.create_app()

        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
            api_key_max_lifetime_days=365,
        )
        self.test_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,
            password_hash=password.hash_password(
                'testpassword123',
            ),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.admin_context = permissions.AuthContext(
            user=self.test_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user():
            return self.admin_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)

    def test_get_admin_settings_success(self) -> None:
        """Test GET /admin/settings returns expected keys."""
        self.mock_db.match.return_value = []

        response = self.client.get('/admin/settings')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['permissions'], [])
        self.assertEqual(
            data['oauth_provider_types'],
            ['google', 'github', 'oidc'],
        )
        self.assertEqual(data['auth_methods'], ['jwt', 'api_key'])
        self.assertEqual(data['auth_types'], ['oauth', 'password'])

    def test_get_admin_settings_with_permissions(self) -> None:
        """Test response includes Permission objects."""
        perm_read = models.Permission(
            name='blueprint:read',
            resource_type='blueprint',
            action='read',
            description='Read blueprints',
        )
        perm_write = models.Permission(
            name='blueprint:write',
            resource_type='blueprint',
            action='write',
            description='Write blueprints',
        )
        self.mock_db.match.return_value = [
            perm_read,
            perm_write,
        ]

        response = self.client.get('/admin/settings')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['permissions']), 2)
        self.assertEqual(data['permissions'][0]['name'], 'blueprint:read')
        self.assertEqual(
            data['permissions'][0]['resource_type'],
            'blueprint',
        )
        self.assertEqual(data['permissions'][0]['action'], 'read')
        self.assertEqual(data['permissions'][1]['name'], 'blueprint:write')
        self.mock_db.match.assert_called_once_with(
            models.Permission, order_by='name'
        )

    def test_get_admin_settings_unauthenticated(self) -> None:
        """Test request without auth header is rejected."""
        # Remove auth override only; keep graph DI override
        del self.test_app.dependency_overrides[permissions.get_current_user]
        unauth_client = testclient.TestClient(self.test_app)

        response = unauth_client.get('/admin/settings')
        self.assertIn(response.status_code, (401, 403))

        # Restore overrides
        async def mock_get_current_user():
            return self.admin_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )
