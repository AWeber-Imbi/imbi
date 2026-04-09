"""Tests for service account API key management endpoints."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common import graph

from imbi_api import app, models, settings
from imbi_api.auth import password, permissions


class SAAPIKeysEndpointsTestCase(unittest.TestCase):
    """Test service account API key endpoint functionality."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.test_app = app.create_app()

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

        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
            api_key_max_lifetime_days=365,
        )

        self.now = datetime.datetime.now(datetime.UTC)

        self.sa_data = {
            'slug': 'test-bot',
            'display_name': 'Test Bot',
            'description': 'A test service account',
            'is_active': True,
            'created_at': self.now.isoformat(),
        }

        # Set up auth context
        self.auth_context = permissions.AuthContext(
            user=self.test_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        # Set up mock graph database
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)

    def test_create_sa_api_key_success(self) -> None:
        """Test successful SA API key creation returns 201."""
        # SA lookup returns the service account
        self.mock_db.execute.return_value = [
            {'s': self.sa_data},
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot/api-keys',
                json={
                    'name': 'Test Key',
                    'description': 'A test API key',
                },
            )

            self.assertEqual(response.status_code, 201)
            data = response.json()

            self.assertIn('key_id', data)
            self.assertIn('key_secret', data)
            self.assertEqual(data['name'], 'Test Key')
            self.assertEqual(
                data['description'],
                'A test API key',
            )
            self.assertIsNone(data['expires_at'])

            # Verify key format
            self.assertTrue(
                data['key_id'].startswith('ik_'),
            )
            self.assertTrue(
                data['key_secret'].startswith(
                    data['key_id'],
                ),
            )
            self.assertGreater(
                len(data['key_secret']),
                len(data['key_id']) + 10,
            )

    def test_create_sa_api_key_sa_not_found(self) -> None:
        """Test SA API key creation with missing SA."""
        self.mock_db.execute.return_value = []

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/nonexistent/api-keys',
                json={'name': 'Test Key'},
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'Service account not found',
                response.json()['detail'],
            )

    def test_create_sa_api_key_expiration_exceeds_max(
        self,
    ) -> None:
        """Test SA API key creation with excessive expiry."""
        self.mock_db.execute.return_value = [
            {'s': self.sa_data},
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot/api-keys',
                json={
                    'name': 'Long Key',
                    'expires_in_days': 999,
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn(
                'maximum allowed lifetime',
                response.json()['detail'],
            )

    def test_create_sa_api_key_with_expiration(self) -> None:
        """Test SA API key creation with valid expiration."""
        self.mock_db.execute.return_value = [
            {'s': self.sa_data},
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot/api-keys',
                json={
                    'name': 'Expiring Key',
                    'expires_in_days': 30,
                },
            )

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertIsNotNone(data['expires_at'])

    def test_list_sa_api_keys_empty(self) -> None:
        """Test listing SA API keys when none exist."""
        self.mock_db.execute.return_value = []

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get(
                '/service-accounts/test-bot/api-keys',
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), [])

    def test_list_sa_api_keys_with_keys(self) -> None:
        """Test listing SA API keys with results."""
        api_keys_data = [
            {
                'k': {
                    'key_id': 'ik_test1',
                    'name': 'Key 1',
                    'description': 'First key',
                    'scopes': [],
                    'created_at': self.now.isoformat(),
                    'expires_at': None,
                    'last_used': None,
                    'last_rotated': None,
                    'revoked': False,
                },
            },
            {
                'k': {
                    'key_id': 'ik_test2',
                    'name': 'Key 2',
                    'description': None,
                    'scopes': ['read:projects'],
                    'created_at': self.now.isoformat(),
                    'expires_at': (
                        self.now + datetime.timedelta(days=30)
                    ).isoformat(),
                    'last_used': self.now.isoformat(),
                    'last_rotated': None,
                    'revoked': False,
                },
            },
        ]

        self.mock_db.execute.return_value = api_keys_data

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get(
                '/service-accounts/test-bot/api-keys',
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]['key_id'], 'ik_test1')
            self.assertEqual(data[0]['name'], 'Key 1')
            self.assertEqual(data[1]['key_id'], 'ik_test2')
            self.assertEqual(
                data[1]['scopes'],
                ['read:projects'],
            )

    def test_revoke_sa_api_key_success(self) -> None:
        """Test successful SA API key revocation."""
        api_key_data = {
            'key_id': 'ik_test123',
            'name': 'Test Key',
            'revoked': False,
        }

        # First call: fetch key, second: revoke
        self.mock_db.execute.side_effect = [
            [{'k': api_key_data}],
            [],
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.delete(
                '/service-accounts/test-bot/api-keys/ik_test123',
            )

            self.assertEqual(response.status_code, 204)

    def test_revoke_sa_api_key_not_found(self) -> None:
        """Test revoking nonexistent SA API key returns 404."""
        self.mock_db.execute.return_value = []

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.delete(
                '/service-accounts/test-bot/api-keys/ik_nonexistent',
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'not found',
                response.json()['detail'],
            )

    def test_rotate_sa_api_key_success(self) -> None:
        """Test successful SA API key rotation."""
        api_key_data = {
            'key_id': 'ik_test123',
            'name': 'Test Key',
            'description': 'Test description',
            'scopes': ['read:projects'],
            'expires_at': (self.now + datetime.timedelta(days=30)).isoformat(),
            'revoked': False,
        }

        # First call: fetch key, second: update hash
        self.mock_db.execute.side_effect = [
            [{'k': api_key_data}],
            [{'k': api_key_data}],
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot/api-keys/ik_test123/rotate',
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()

            # Key ID stays the same
            self.assertEqual(
                data['key_id'],
                'ik_test123',
            )
            # New secret is returned
            self.assertTrue(
                data['key_secret'].startswith(
                    'ik_test123_',
                ),
            )
            # Metadata is preserved
            self.assertEqual(data['name'], 'Test Key')
            self.assertEqual(
                data['description'],
                'Test description',
            )
            self.assertEqual(
                data['scopes'],
                ['read:projects'],
            )

    def test_rotate_sa_api_key_not_found(self) -> None:
        """Test rotating nonexistent SA API key."""
        self.mock_db.execute.return_value = []

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot/api-keys/ik_nonexistent/rotate',
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'not found',
                response.json()['detail'],
            )

    def test_rotate_sa_api_key_revoked(self) -> None:
        """Test rotating revoked SA API key returns 400."""
        api_key_data = {
            'key_id': 'ik_revoked',
            'name': 'Revoked Key',
            'revoked': True,
        }

        self.mock_db.execute.return_value = [
            {'k': api_key_data},
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot/api-keys/ik_revoked/rotate',
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn(
                'revoked',
                response.json()['detail'],
            )
