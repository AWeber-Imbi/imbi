"""Tests for client credentials CRUD endpoints."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common import graph

from imbi_api import app, models, settings
from imbi_api.auth import password, permissions


class ClientCredentialsEndpointsTestCase(unittest.TestCase):
    """Test client credentials endpoint functionality."""

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

    def test_create_client_credential(self) -> None:
        """Test creating a client credential returns 201."""
        # SA lookup returns a result
        # create_node mock not needed -- merge handles it
        self.mock_db.execute.return_value = [
            {
                's': {
                    'slug': 'test-bot',
                    'display_name': 'Test Bot',
                    'is_active': True,
                },
            },
        ]
        self.mock_db.merge.return_value = None

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
                '/service-accounts/test-bot/client-credentials',
                json={
                    'name': 'Deploy Credential',
                    'description': 'For CI/CD pipelines',
                },
            )

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertIn('client_id', data)
            self.assertIn('client_secret', data)
            self.assertTrue(
                data['client_id'].startswith('cc_'),
            )
            self.assertEqual(
                data['name'],
                'Deploy Credential',
            )
            self.assertEqual(
                data['description'],
                'For CI/CD pipelines',
            )
            self.assertIsNone(data['expires_at'])

    def test_list_client_credentials(self) -> None:
        """Test listing client credentials returns list."""
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

        self.mock_db.execute.return_value = credential_list

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
                '/service-accounts/test-bot/client-credentials',
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 2)
            self.assertEqual(
                data[0]['client_id'],
                'cc_abc123',
            )
            self.assertEqual(data[0]['name'], 'Cred 1')
            self.assertEqual(
                data[1]['client_id'],
                'cc_def456',
            )
            self.assertEqual(
                data[1]['scopes'],
                ['read:projects'],
            )

    def test_revoke_client_credential(self) -> None:
        """Test revoking a client credential returns 204."""
        credential_data = {
            'client_id': 'cc_abc123',
            'name': 'Cred 1',
            'revoked': False,
        }

        # First call: fetch credential, second: revoke
        self.mock_db.execute.side_effect = [
            [{'c': credential_data}],
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
                '/service-accounts/test-bot/client-credentials/cc_abc123',
            )

            self.assertEqual(response.status_code, 204)

    def test_revoke_not_found(self) -> None:
        """Test revoking nonexistent credential returns 404."""
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
                '/service-accounts/test-bot/client-credentials/cc_nonexistent',
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'not found',
                response.json()['detail'],
            )

    def test_rotate_client_credential(self) -> None:
        """Test rotating a credential returns new secret."""
        credential_data = {
            'client_id': 'cc_abc123',
            'name': 'Cred 1',
            'description': 'Deploy credential',
            'scopes': ['read:projects'],
            'expires_at': None,
            'revoked': False,
        }

        # First call: fetch, second: update
        self.mock_db.execute.side_effect = [
            [{'c': credential_data}],
            [{'c': credential_data}],
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
                '/service-accounts/test-bot'
                '/client-credentials/cc_abc123/rotate',
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(
                data['client_id'],
                'cc_abc123',
            )
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
        credential_data = {
            'client_id': 'cc_revoked',
            'name': 'Revoked Cred',
            'revoked': True,
        }

        self.mock_db.execute.return_value = [
            {'c': credential_data},
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
                '/service-accounts/test-bot'
                '/client-credentials/cc_revoked/rotate',
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn(
                'revoked',
                response.json()['detail'],
            )
