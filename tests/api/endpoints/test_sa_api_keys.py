"""Tests for service account API key management endpoints."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common.auth import core

from imbi_api import app, models, settings
from imbi_api.auth import password


class SAAPIKeysEndpointsTestCase(unittest.TestCase):
    """Test service account API key endpoint functionality."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.app = app.create_app()
        self.client = testclient.TestClient(self.app)

        self.test_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,
            password_hash=password.hash_password('testpassword123'),
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

    def _create_mock_run(
        self,
        sa_data: dict | None = None,
        api_key_data: dict | None = None,
    ):
        """Create a mock run side effect for SA API key tests.

        Args:
            sa_data: Dict to return for ServiceAccount lookup
                queries. None means SA not found.
            api_key_data: Dict to return for APIKey queries.
                None means key not found.

        """

        def mock_run_side_effect(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(
                return_value=mock_result,
            )
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()

            # SA lookup: MATCH (s:ServiceAccount ...) RETURN s
            if (
                'ServiceAccount' in query
                and 'RETURN s' in query
                and 'APIKey' not in query
            ):
                if sa_data is not None:
                    mock_result.data = mock.AsyncMock(
                        return_value=[{'s': sa_data}],
                    )
                else:
                    mock_result.data = mock.AsyncMock(
                        return_value=[],
                    )
            # APIKey creation (has CREATE and APIKey)
            elif 'APIKey' in query and 'CREATE' in query:
                mock_result.data = mock.AsyncMock(return_value=[])
            # APIKey revoke: SET k.revoked
            elif 'APIKey' in query and 'SET k.revoked' in query:
                if api_key_data is not None:
                    mock_result.data = mock.AsyncMock(
                        return_value=[{'k': api_key_data}],
                    )
                else:
                    mock_result.data = mock.AsyncMock(
                        return_value=[],
                    )
            # APIKey rotate update: SET k.key_hash
            elif 'APIKey' in query and 'SET k.key_hash' in query:
                mock_result.data = mock.AsyncMock(return_value=[])
            # APIKey fetch/list: RETURN k
            elif 'APIKey' in query and 'RETURN k' in query:
                if api_key_data is not None:
                    mock_result.data = mock.AsyncMock(
                        return_value=[{'k': api_key_data}],
                    )
                else:
                    mock_result.data = mock.AsyncMock(
                        return_value=[],
                    )
            # Auth: token revocation check
            elif 'TokenMetadata' in query and 'revoked' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'revoked': False}],
                )
            # Auth: user lookup
            elif 'User' in query and 'email' in query:
                user_dict = self.test_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'u': user_dict}],
                )
            # Auth: permissions
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': []}],
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        return mock_run_side_effect

    def test_create_sa_api_key_success(self) -> None:
        """Test successful SA API key creation returns 201."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(
                    sa_data=self.sa_data,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot/api-keys',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
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
            self.assertEqual(data['description'], 'A test API key')
            self.assertIsNone(data['expires_at'])

            # Verify key format
            self.assertTrue(data['key_id'].startswith('ik_'))
            self.assertTrue(
                data['key_secret'].startswith(data['key_id']),
            )
            self.assertGreater(
                len(data['key_secret']),
                len(data['key_id']) + 10,
            )

    def test_create_sa_api_key_sa_not_found(self) -> None:
        """Test SA API key creation with missing SA returns 404."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(sa_data=None),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/nonexistent/api-keys',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
                json={'name': 'Test Key'},
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'Service account not found',
                response.json()['detail'],
            )

    def test_create_sa_api_key_expiration_exceeds_max(self) -> None:
        """Test SA API key creation with excessive expiration."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(
                    sa_data=self.sa_data,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot/api-keys',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
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
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(
                    sa_data=self.sa_data,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot/api-keys',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
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
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(
                    sa_data=self.sa_data,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get(
                '/service-accounts/test-bot/api-keys',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), [])

    def test_list_sa_api_keys_with_keys(self) -> None:
        """Test listing SA API keys with populated results."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

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

        def mock_run_list(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(
                return_value=mock_result,
            )
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            if 'APIKey' in query and 'RETURN k' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=api_keys_data,
                )
            elif 'TokenMetadata' in query and 'revoked' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'revoked': False}],
                )
            elif 'User' in query and 'email' in query:
                user_dict = self.test_user.model_dump(
                    mode='json',
                )
                mock_result.data = mock.AsyncMock(
                    return_value=[{'u': user_dict}],
                )
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': []}],
                )
            else:
                mock_result.data = mock.AsyncMock(
                    return_value=[],
                )

            return mock_result

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=mock_run_list,
            ),
            mock.patch(
                'imbi_common.neo4j.convert_neo4j_types',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get(
                '/service-accounts/test-bot/api-keys',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
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
        """Test successful SA API key revocation returns 204."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        api_key_data = {
            'key_id': 'ik_test123',
            'name': 'Test Key',
            'revoked': False,
        }

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(
                    sa_data=self.sa_data,
                    api_key_data=api_key_data,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.delete(
                '/service-accounts/test-bot/api-keys/ik_test123',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 204)

    def test_revoke_sa_api_key_not_found(self) -> None:
        """Test revoking nonexistent SA API key returns 404."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(
                    sa_data=self.sa_data,
                    api_key_data=None,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.delete(
                '/service-accounts/test-bot/api-keys/ik_nonexistent',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'not found',
                response.json()['detail'],
            )

    def test_rotate_sa_api_key_success(self) -> None:
        """Test successful SA API key rotation."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        api_key_data = {
            'key_id': 'ik_test123',
            'name': 'Test Key',
            'description': 'Test description',
            'scopes': ['read:projects'],
            'expires_at': (self.now + datetime.timedelta(days=30)).isoformat(),
            'revoked': False,
        }

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(
                    sa_data=self.sa_data,
                    api_key_data=api_key_data,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot/api-keys/ik_test123/rotate',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()

            # Key ID stays the same
            self.assertEqual(data['key_id'], 'ik_test123')
            # New secret is returned
            self.assertTrue(
                data['key_secret'].startswith('ik_test123_'),
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
        """Test rotating nonexistent SA API key returns 404."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(
                    sa_data=self.sa_data,
                    api_key_data=None,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot/api-keys/ik_nonexistent/rotate',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'not found',
                response.json()['detail'],
            )

    def test_rotate_sa_api_key_revoked(self) -> None:
        """Test rotating revoked SA API key returns 400."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        api_key_data = {
            'key_id': 'ik_revoked',
            'name': 'Revoked Key',
            'revoked': True,
        }

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(
                    sa_data=self.sa_data,
                    api_key_data=api_key_data,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot/api-keys/ik_revoked/rotate',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn(
                'revoked',
                response.json()['detail'],
            )
