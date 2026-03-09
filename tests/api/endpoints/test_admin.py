"""Tests for admin settings endpoint."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common.auth import core

from imbi_api import app, models, settings
from imbi_api.auth import password


class AdminSettingsEndpointTestCase(unittest.TestCase):
    """Test cases for GET /admin/settings endpoint."""

    def setUp(self) -> None:
        """Set up test client, auth settings, and test user."""
        self.test_app = app.create_app()
        self.client = testclient.TestClient(self.test_app)

        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
            api_key_max_lifetime_days=365,
        )
        self.test_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,
            password_hash=password.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

    def _mock_neo4j_run(self) -> mock.AsyncMock:
        """Build a side_effect list for neo4j.run auth queries.

        Returns three async-context-manager mocks:
        1. TokenMetadata (revoked check)
        2. User lookup
        3. Permission / GRANTS query
        """
        mock_token = mock.AsyncMock()
        mock_token.data.return_value = [{'revoked': False}]
        mock_token.__aenter__.return_value = mock_token
        mock_token.__aexit__.return_value = None

        mock_user = mock.AsyncMock()
        mock_user.data.return_value = [
            {
                'u': {
                    'email': self.test_user.email,
                    'display_name': (self.test_user.display_name),
                    'password_hash': (self.test_user.password_hash),
                    'is_active': True,
                    'is_admin': True,
                    'is_service_account': False,
                    'created_at': self.test_user.created_at,
                }
            }
        ]
        mock_user.__aenter__.return_value = mock_user
        mock_user.__aexit__.return_value = None

        mock_perms = mock.AsyncMock()
        mock_perms.data.return_value = [{'permissions': []}]
        mock_perms.__aenter__.return_value = mock_perms
        mock_perms.__aexit__.return_value = None

        return mock.AsyncMock(side_effect=[mock_token, mock_user, mock_perms])

    def test_get_admin_settings_success(self) -> None:
        """Test GET /admin/settings returns expected keys."""

        async def empty_generator():
            return
            yield

        with (
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._mock_neo4j_run().side_effect,
            ),
            mock.patch(
                'imbi_api.settings.get_auth_settings',
                return_value=self.auth_settings,
            ),
            mock.patch(
                'imbi_common.neo4j.fetch_nodes',
                return_value=empty_generator(),
            ),
        ):
            response = self.client.get(
                '/admin/settings',
                headers={
                    'Authorization': f'Bearer {self.token}',
                },
            )

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

        async def perm_generator():
            yield perm_read
            yield perm_write

        with (
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._mock_neo4j_run().side_effect,
            ),
            mock.patch(
                'imbi_api.settings.get_auth_settings',
                return_value=self.auth_settings,
            ),
            mock.patch(
                'imbi_common.neo4j.fetch_nodes',
                return_value=perm_generator(),
            ) as mock_fetch,
        ):
            response = self.client.get(
                '/admin/settings',
                headers={
                    'Authorization': f'Bearer {self.token}',
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['permissions']), 2)
        self.assertEqual(data['permissions'][0]['name'], 'blueprint:read')
        self.assertEqual(data['permissions'][0]['resource_type'], 'blueprint')
        self.assertEqual(data['permissions'][0]['action'], 'read')
        self.assertEqual(data['permissions'][1]['name'], 'blueprint:write')
        mock_fetch.assert_called_once_with(models.Permission, order_by='name')

    def test_get_admin_settings_unauthenticated(self) -> None:
        """Test request without auth header is rejected."""
        response = self.client.get('/admin/settings')
        self.assertIn(response.status_code, (401, 403))
