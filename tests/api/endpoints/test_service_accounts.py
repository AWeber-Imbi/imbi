"""Tests for service account management endpoints."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common.auth import core
from neo4j import exceptions

from imbi_api import app, models, settings
from imbi_api.auth import password


class ServiceAccountsEndpointsTestCase(unittest.TestCase):
    """Test service account endpoint functionality."""

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

        self.sa_data = models.ServiceAccount(
            slug='test-bot',
            display_name='Test Bot',
            description='A test service account',
            is_active=True,
            created_at=self.now,
        )

    def _create_mock_run(
        self,
        sa_node: models.ServiceAccount | None = None,
        org_records: list[dict] | None = None,
        membership_records: list[dict] | None = None,
        deleted_count: int = 0,
    ):
        """Create a mock run side effect for service account tests.

        Args:
            sa_node: ServiceAccount to return for fetch queries.
            org_records: Records to return for org membership
                queries.
            membership_records: Records to return for MEMBER_OF +
                Organization + Role queries.
            deleted_count: Count to return for DELETE membership
                queries.

        """

        def mock_run_side_effect(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(
                return_value=mock_result,
            )
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()

            # Org membership lookup (get_service_account)
            if 'MEMBER_OF' in query and 'Organization' in query:
                if 'DELETE' in query:
                    mock_result.data = mock.AsyncMock(
                        return_value=[{'deleted': deleted_count}],
                    )
                elif 'MERGE' in query or 'Role' in query:
                    mock_result.data = mock.AsyncMock(
                        return_value=membership_records or [],
                    )
                else:
                    mock_result.data = mock.AsyncMock(
                        return_value=org_records or [],
                    )
            # Cleanup query for delete
            elif 'DETACH DELETE' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'deleted': 1}],
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

    def test_create_service_account_success(self) -> None:
        """Test successful service account creation returns 201."""
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
                '/service-accounts',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
                json={
                    'slug': 'test-bot',
                    'display_name': 'Test Bot',
                    'description': 'A test service account',
                },
            )

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertEqual(data['slug'], 'test-bot')
            self.assertEqual(data['display_name'], 'Test Bot')
            self.assertEqual(
                data['description'],
                'A test service account',
            )
            self.assertTrue(data['is_active'])
            self.assertIn('created_at', data)

    def test_create_service_account_duplicate(self) -> None:
        """Test creating duplicate service account returns 409."""
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
            mock.patch(
                'imbi_common.neo4j.create_node',
                side_effect=exceptions.ConstraintError('Duplicate'),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
                json={
                    'slug': 'test-bot',
                    'display_name': 'Test Bot',
                },
            )

            self.assertEqual(response.status_code, 409)
            self.assertIn('already exists', response.json()['detail'])

    def test_list_service_accounts(self) -> None:
        """Test listing service accounts returns list."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        mock_accounts = [
            models.ServiceAccount(
                slug='bot-alpha',
                display_name='Bot Alpha',
                is_active=True,
                created_at=self.now,
            ),
            models.ServiceAccount(
                slug='bot-beta',
                display_name='Bot Beta',
                description='Second bot',
                is_active=False,
                created_at=self.now,
            ),
        ]

        async def mock_fetch(*_args, **_kwargs):
            for account in mock_accounts:
                yield account

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(),
            ),
            mock.patch(
                'imbi_common.neo4j.fetch_nodes',
                return_value=mock_fetch(),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get(
                '/service-accounts',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]['slug'], 'bot-alpha')
            self.assertEqual(data[1]['slug'], 'bot-beta')
            self.assertFalse(data[1]['is_active'])

    def test_get_service_account(self) -> None:
        """Test getting a service account with org memberships."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        org_records = [
            {
                'org_name': 'Acme Corp',
                'org_slug': 'acme-corp',
                'role': 'deployer',
            },
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(
                    org_records=org_records,
                ),
            ),
            mock.patch(
                'imbi_common.neo4j.fetch_node',
                return_value=self.sa_data,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get(
                '/service-accounts/test-bot',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['slug'], 'test-bot')
            self.assertEqual(data['display_name'], 'Test Bot')
            self.assertEqual(len(data['organizations']), 1)
            self.assertEqual(
                data['organizations'][0]['organization_slug'],
                'acme-corp',
            )
            self.assertEqual(
                data['organizations'][0]['role'],
                'deployer',
            )

    def test_get_service_account_not_found(self) -> None:
        """Test getting nonexistent service account returns 404."""
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
            mock.patch(
                'imbi_common.neo4j.fetch_node',
                return_value=None,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get(
                '/service-accounts/nonexistent',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn('not found', response.json()['detail'])

    def test_update_service_account(self) -> None:
        """Test updating a service account returns updated data."""
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
            mock.patch(
                'imbi_common.neo4j.fetch_node',
                return_value=self.sa_data,
            ),
            mock.patch('imbi_common.neo4j.upsert'),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.put(
                '/service-accounts/test-bot',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
                json={
                    'slug': 'test-bot',
                    'display_name': 'Updated Bot',
                    'description': 'Updated description',
                    'is_active': False,
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['slug'], 'test-bot')
            self.assertEqual(data['display_name'], 'Updated Bot')
            self.assertEqual(
                data['description'],
                'Updated description',
            )
            self.assertFalse(data['is_active'])

    def test_update_service_account_slug_mismatch(self) -> None:
        """Test updating with mismatched slugs returns 400."""
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
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.put(
                '/service-accounts/test-bot',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
                json={
                    'slug': 'different-slug',
                    'display_name': 'Mismatched',
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn('must match', response.json()['detail'])

    def test_delete_service_account(self) -> None:
        """Test deleting a service account returns 204."""
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
            mock.patch(
                'imbi_common.neo4j.delete_node',
                return_value=True,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.delete(
                '/service-accounts/test-bot',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 204)

    def test_delete_service_account_not_found(self) -> None:
        """Test deleting nonexistent service account returns 404."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        def mock_run_not_found(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(
                return_value=mock_result,
            )
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()

            if 'DETACH DELETE' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'deleted': 0}],
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
                side_effect=mock_run_not_found,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.delete(
                '/service-accounts/nonexistent',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn('not found', response.json()['detail'])

    def test_add_to_organization(self) -> None:
        """Test adding service account to organization returns 204."""
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        membership_records = [
            {'s': {}, 'o': {}, 'r': {}},
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
            ) as mock_settings,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=self._create_mock_run(
                    membership_records=membership_records,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/service-accounts/test-bot/organizations',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
                json={
                    'organization_slug': 'acme-corp',
                    'role_slug': 'deployer',
                },
            )

            self.assertEqual(response.status_code, 204)

    def test_remove_from_organization(self) -> None:
        """Test removing service account from org returns 204."""
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
                    deleted_count=1,
                ),
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.delete(
                '/service-accounts/test-bot/organizations/acme-corp',
                headers={
                    'Authorization': f'Bearer {access_token}',
                },
            )

            self.assertEqual(response.status_code, 204)
