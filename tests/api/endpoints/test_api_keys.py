"""Tests for API key management endpoints."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient

from imbi import app, models, settings
from imbi.auth import core


class APIKeysEndpointsTestCase(unittest.TestCase):
    """Test API keys endpoint functionality."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.app = app.create_app()
        self.client = testclient.TestClient(self.app)

        # Create test user
        self.test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=core.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
            api_key_max_lifetime_days=365,
        )

    def _create_mock_run(self, api_key_data: dict | None = None):
        """Create mock_run_side_effect for API keys tests."""

        def mock_run_side_effect(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()

            # APIKey queries (most specific first)
            if 'APIKey' in query and 'RETURN k' in query:
                if api_key_data:
                    mock_result.data = mock.AsyncMock(
                        return_value=[{'k': api_key_data}]
                    )
                else:
                    mock_result.data = mock.AsyncMock(return_value=[])
            # Auth queries
            elif 'TokenMetadata' in query and 'revoked' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'revoked': False}]
                )
            elif 'User' in query and 'email' in query:
                user_dict = self.test_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'u': user_dict}]
                )
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': []}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        return mock_run_side_effect

    def test_create_api_key_success(self) -> None:
        """Test successful API key creation."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run', side_effect=self._create_mock_run(None)
            ),
            mock.patch('imbi.neo4j.create_node'),
            mock.patch('imbi.neo4j.create_relationship'),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/api-keys',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'name': 'Test Key', 'description': 'Test API key'},
            )

            self.assertEqual(response.status_code, 201)
            data = response.json()

            # Verify response structure
            self.assertIn('key_id', data)
            self.assertIn('key_secret', data)
            self.assertEqual(data['name'], 'Test Key')
            self.assertEqual(data['description'], 'Test API key')
            self.assertIsNone(data['expires_at'])

            # Verify key format
            self.assertTrue(data['key_id'].startswith('ik_'))
            self.assertTrue(data['key_secret'].startswith(data['key_id']))
            # Full key should be: key_id + '_' + secret
            # Verify it's longer than just the key_id (has secret appended)
            self.assertGreater(
                len(data['key_secret']), len(data['key_id']) + 10
            )

    def test_create_api_key_with_expiration(self) -> None:
        """Test API key creation with expiration."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run', side_effect=self._create_mock_run(None)
            ),
            mock.patch('imbi.neo4j.create_node'),
            mock.patch('imbi.neo4j.create_relationship'),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/api-keys',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'name': 'Expiring Key', 'expires_in_days': 30},
            )

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertIsNotNone(data['expires_at'])

    def test_create_api_key_with_scopes(self) -> None:
        """Test API key creation with scopes."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run', side_effect=self._create_mock_run(None)
            ),
            mock.patch('imbi.neo4j.create_node'),
            mock.patch('imbi.neo4j.create_relationship'),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/api-keys',
                headers={'Authorization': f'Bearer {access_token}'},
                json={
                    'name': 'Scoped Key',
                    'scopes': ['read:projects', 'write:projects'],
                },
            )

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertEqual(
                data['scopes'], ['read:projects', 'write:projects']
            )

    def test_create_api_key_expiration_exceeds_max(self) -> None:
        """Test API key creation with expiration exceeding maximum."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run', side_effect=self._create_mock_run(None)
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/api-keys',
                headers={'Authorization': f'Bearer {access_token}'},
                json={'name': 'Long Key', 'expires_in_days': 999},
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn(
                'maximum allowed lifetime', response.json()['detail']
            )

    def test_list_api_keys_empty(self) -> None:
        """Test listing API keys when user has none."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run', side_effect=self._create_mock_run(None)
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get(
                '/api-keys',
                headers={'Authorization': f'Bearer {access_token}'},
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data, [])

    def test_list_api_keys_with_keys(self) -> None:
        """Test listing API keys with multiple keys."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        api_keys_data = [
            {
                'k': {
                    'key_id': 'ik_test1',
                    'name': 'Key 1',
                    'description': 'First key',
                    'scopes': [],
                    'created_at': datetime.datetime.now(datetime.UTC),
                    'expires_at': None,
                    'last_used': None,
                    'last_rotated': None,
                    'revoked': False,
                }
            },
            {
                'k': {
                    'key_id': 'ik_test2',
                    'name': 'Key 2',
                    'description': None,
                    'scopes': ['read:projects'],
                    'created_at': datetime.datetime.now(datetime.UTC),
                    'expires_at': datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(days=30),
                    'last_used': datetime.datetime.now(datetime.UTC),
                    'last_rotated': None,
                    'revoked': False,
                }
            },
        ]

        def mock_run_list(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            if 'APIKey' in query and 'RETURN k' in query:
                mock_result.data = mock.AsyncMock(return_value=api_keys_data)
            elif 'TokenMetadata' in query and 'revoked' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'revoked': False}]
                )
            elif 'User' in query and 'email' in query:
                user_dict = self.test_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'u': user_dict}]
                )
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': []}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch('imbi.neo4j.run', side_effect=mock_run_list),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get(
                '/api-keys',
                headers={'Authorization': f'Bearer {access_token}'},
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]['key_id'], 'ik_test1')
            self.assertEqual(data[0]['name'], 'Key 1')
            self.assertEqual(data[1]['key_id'], 'ik_test2')
            self.assertEqual(data[1]['scopes'], ['read:projects'])

    def test_revoke_api_key_success(self) -> None:
        """Test successful API key revocation."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        api_key_data = {
            'key_id': 'ik_test123',
            'name': 'Test Key',
            'revoked': False,
        }

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run',
                side_effect=self._create_mock_run(api_key_data),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.delete(
                '/api-keys/ik_test123',
                headers={'Authorization': f'Bearer {access_token}'},
            )

            self.assertEqual(response.status_code, 204)

    def test_revoke_api_key_not_found(self) -> None:
        """Test revoking non-existent API key."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run', side_effect=self._create_mock_run(None)
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.delete(
                '/api-keys/ik_nonexistent',
                headers={'Authorization': f'Bearer {access_token}'},
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn('not found', response.json()['detail'])

    def test_rotate_api_key_success(self) -> None:
        """Test successful API key rotation."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        api_key_data = {
            'key_id': 'ik_test123',
            'name': 'Test Key',
            'description': 'Test description',
            'scopes': ['read:projects'],
            'expires_at': datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(days=30),
            'revoked': False,
        }

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run',
                side_effect=self._create_mock_run(api_key_data),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/api-keys/ik_test123/rotate',
                headers={'Authorization': f'Bearer {access_token}'},
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()

            # Verify key_id stays the same
            self.assertEqual(data['key_id'], 'ik_test123')
            # Verify new secret is returned
            self.assertTrue(data['key_secret'].startswith('ik_test123_'))
            # Verify metadata is preserved
            self.assertEqual(data['name'], 'Test Key')
            self.assertEqual(data['description'], 'Test description')
            self.assertEqual(data['scopes'], ['read:projects'])

    def test_rotate_api_key_not_found(self) -> None:
        """Test rotating non-existent API key."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run', side_effect=self._create_mock_run(None)
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/api-keys/ik_nonexistent/rotate',
                headers={'Authorization': f'Bearer {access_token}'},
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn('not found', response.json()['detail'])

    def test_rotate_revoked_api_key(self) -> None:
        """Test rotating revoked API key."""
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        api_key_data = {
            'key_id': 'ik_revoked',
            'name': 'Revoked Key',
            'revoked': True,
        }

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.neo4j.run',
                side_effect=self._create_mock_run(api_key_data),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/api-keys/ik_revoked/rotate',
                headers={'Authorization': f'Bearer {access_token}'},
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn('revoked', response.json()['detail'])
