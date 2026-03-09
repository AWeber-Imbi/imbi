"""Tests for client credentials CRUD endpoints."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common.auth import core

from imbi_api import app, models, settings
from imbi_api.auth import password


class ClientCredentialsEndpointsTestCase(unittest.TestCase):
    """Test client credentials endpoint functionality."""

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

    def _create_mock_run(
        self,
        sa_exists: bool = True,
        credential_data: dict | None = None,
        credential_list: list[dict] | None = None,
    ):
        """Create a mock run side effect for client credential tests.

        Args:
            sa_exists: Whether the service account lookup should
                return a result.
            credential_data: Single credential record for
                ownership/fetch queries.
            credential_list: List of credential records for list
                queries.

        """

        def mock_run_side_effect(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(
                return_value=mock_result,
            )
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()

            # Service account lookup
            if (
                'ServiceAccount' in query
                and 'ClientCredential' not in query
                and 'RETURN s' in query
            ):
                if sa_exists:
                    mock_result.data = mock.AsyncMock(
                        return_value=[
                            {
                                's': {
                                    'slug': 'test-bot',
                                    'display_name': 'Test Bot',
                                    'is_active': True,
                                },
                            }
                        ],
                    )
                else:
                    mock_result.data = mock.AsyncMock(
                        return_value=[],
                    )
            # OWNED_BY relationship creation
            elif 'OWNED_BY' in query and 'CREATE' in query:
                mock_result.data = mock.AsyncMock(return_value=[])
            # Credential ownership verification / list
            elif 'ClientCredential' in query and 'OWNED_BY' in query:
                if credential_list is not None:
                    mock_result.data = mock.AsyncMock(
                        return_value=credential_list,
                    )
                elif credential_data is not None:
                    mock_result.data = mock.AsyncMock(
                        return_value=[{'c': credential_data}],
                    )
                else:
                    mock_result.data = mock.AsyncMock(
                        return_value=[],
                    )
            # Credential update (revoke / rotate)
            elif 'ClientCredential' in query and 'SET' in query:
                mock_result.data = mock.AsyncMock(return_value=[])
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

    def test_create_client_credential(self) -> None:
        """Test creating a client credential returns 201."""
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
                side_effect=self._create_mock_run(),
            ),
            mock.patch('imbi_common.neo4j.create_node'),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot/client-credentials',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
                json={
                    'name': 'Deploy Credential',
                    'description': 'For CI/CD pipelines',
                },
            )

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertIn('client_id', data)
            self.assertIn('client_secret', data)
            self.assertTrue(data['client_id'].startswith('cc_'))
            self.assertEqual(data['name'], 'Deploy Credential')
            self.assertEqual(
                data['description'],
                'For CI/CD pipelines',
            )
            self.assertIsNone(data['expires_at'])

    def test_list_client_credentials(self) -> None:
        """Test listing client credentials returns list."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        credential_list = [
            {
                'c': {
                    'client_id': 'cc_abc123',
                    'name': 'Cred 1',
                    'description': 'First credential',
                    'scopes': [],
                    'created_at': self.now.isoformat(),
                    'expires_at': None,
                    'last_used': None,
                    'last_rotated': None,
                    'revoked': False,
                    'revoked_at': None,
                },
            },
            {
                'c': {
                    'client_id': 'cc_def456',
                    'name': 'Cred 2',
                    'description': None,
                    'scopes': ['read:projects'],
                    'created_at': self.now.isoformat(),
                    'expires_at': None,
                    'last_used': None,
                    'last_rotated': None,
                    'revoked': False,
                    'revoked_at': None,
                },
            },
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(
                    credential_list=credential_list,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get(
                '/service-accounts/test-bot/client-credentials',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]['client_id'], 'cc_abc123')
            self.assertEqual(data[0]['name'], 'Cred 1')
            self.assertEqual(data[1]['client_id'], 'cc_def456')
            self.assertEqual(
                data[1]['scopes'],
                ['read:projects'],
            )

    def test_revoke_client_credential(self) -> None:
        """Test revoking a client credential returns 204."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        credential_data = {
            'client_id': 'cc_abc123',
            'name': 'Cred 1',
            'revoked': False,
        }

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(
                    credential_data=credential_data,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.delete(
                '/service-accounts/test-bot/client-credentials/cc_abc123',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 204)

    def test_revoke_not_found(self) -> None:
        """Test revoking nonexistent credential returns 404."""
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
                    credential_data=None,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.delete(
                '/service-accounts/test-bot/client-credentials/cc_nonexistent',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn('not found', response.json()['detail'])

    def test_rotate_client_credential(self) -> None:
        """Test rotating a credential returns new secret."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        credential_data = {
            'client_id': 'cc_abc123',
            'name': 'Cred 1',
            'description': 'Deploy credential',
            'scopes': ['read:projects'],
            'expires_at': None,
            'revoked': False,
        }

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(
                    credential_data=credential_data,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot'
                '/client-credentials/cc_abc123/rotate',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['client_id'], 'cc_abc123')
            self.assertIn('client_secret', data)
            self.assertEqual(data['name'], 'Cred 1')
            self.assertEqual(
                data['description'],
                'Deploy credential',
            )
            self.assertEqual(
                data['scopes'],
                ['read:projects'],
            )

    def test_rotate_revoked_credential(self) -> None:
        """Test rotating a revoked credential returns 400."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        credential_data = {
            'client_id': 'cc_revoked',
            'name': 'Revoked Cred',
            'revoked': True,
        }

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(
                    credential_data=credential_data,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot'
                '/client-credentials/cc_revoked/rotate',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn('revoked', response.json()['detail'])
