"""Tests for service account management endpoints."""

import datetime
import unittest
from unittest import mock

import psycopg.errors
from fastapi import testclient
from imbi_common import graph

from imbi_api import app, models
from imbi_api.auth import password


class ServiceAccountsEndpointsTestCase(unittest.TestCase):
    """Test service account endpoint functionality."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        from imbi_api.auth import permissions

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

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)

        self.now = datetime.datetime.now(datetime.UTC)

        self.sa_data = models.ServiceAccount(
            slug='test-bot',
            display_name='Test Bot',
            description='A test service account',
            is_active=True,
            created_at=self.now,
        )

    def test_create_service_account_success(self) -> None:
        """Test successful service account creation."""
        self.mock_db.create.return_value = self.sa_data
        self.mock_db.execute.return_value = [
            {
                'org_name': 'Acme Corp',
                'org_slug': 'acme-corp',
                'role': 'deployer',
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/service-accounts',
                json={
                    'slug': 'test-bot',
                    'display_name': 'Test Bot',
                    'description': 'A test service account',
                    'organization_slug': 'acme-corp',
                    'role_slug': 'deployer',
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
        self.assertEqual(len(data['organizations']), 1)
        self.assertEqual(
            data['organizations'][0]['organization_slug'],
            'acme-corp',
        )

    def test_create_service_account_duplicate(self) -> None:
        """Test creating duplicate service account."""
        self.mock_db.create.side_effect = psycopg.errors.UniqueViolation(
            'Duplicate'
        )

        response = self.client.post(
            '/service-accounts',
            json={
                'slug': 'test-bot',
                'display_name': 'Test Bot',
                'organization_slug': 'acme-corp',
                'role_slug': 'deployer',
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

    def test_list_service_accounts(self) -> None:
        """Test listing service accounts returns list."""
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
        self.mock_db.match.return_value = mock_accounts

        response = self.client.get('/service-accounts')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['slug'], 'bot-alpha')
        self.assertEqual(data[1]['slug'], 'bot-beta')
        self.assertFalse(data[1]['is_active'])

    def test_get_service_account(self) -> None:
        """Test getting a service account with memberships."""
        self.mock_db.match.return_value = [self.sa_data]
        self.mock_db.execute.return_value = [
            {
                'org_name': 'Acme Corp',
                'org_slug': 'acme-corp',
                'role': 'deployer',
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/service-accounts/test-bot',
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
        """Test getting nonexistent SA returns 404."""
        self.mock_db.match.return_value = []

        response = self.client.get(
            '/service-accounts/nonexistent',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_delete_service_account(self) -> None:
        """Test deleting a service account returns 204."""
        self.mock_db.execute.return_value = [{'deleted': 1}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(
                '/service-accounts/test-bot',
            )

        self.assertEqual(response.status_code, 204)

    def test_delete_service_account_not_found(self) -> None:
        """Test deleting nonexistent SA returns 404."""
        self.mock_db.execute.return_value = [{'deleted': 0}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(
                '/service-accounts/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_add_to_organization(self) -> None:
        """Test adding service account to org returns 204."""
        self.mock_db.execute.return_value = [
            {'s': {}, 'o': {}, 'r': {}},
        ]

        response = self.client.post(
            '/service-accounts/test-bot/organizations',
            json={
                'organization_slug': 'acme-corp',
                'role_slug': 'deployer',
            },
        )

        self.assertEqual(response.status_code, 204)

    def test_create_service_account_rollback_on_missing_org_or_role(
        self,
    ) -> None:
        """Test SA node is deleted when org/role not found."""
        self.mock_db.merge.return_value = self.sa_data
        # First execute (membership) returns empty,
        # second (rollback delete) returns
        self.mock_db.execute.side_effect = [
            [],  # membership query
            [{'n': 'true'}],  # rollback delete
        ]

        response = self.client.post(
            '/service-accounts',
            json={
                'slug': 'orphan-bot',
                'display_name': 'Orphan Bot',
                'organization_slug': 'nonexistent-org',
                'role_slug': 'deployer',
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn(
            'nonexistent-org',
            response.json()['detail'],
        )
        # Verify rollback execute was called
        self.assertEqual(self.mock_db.execute.call_count, 2)

    def test_create_service_account_rollback_detail_includes_role(
        self,
    ) -> None:
        """Test that the 404 detail mentions the role slug."""
        self.mock_db.merge.return_value = self.sa_data
        self.mock_db.execute.side_effect = [
            [],  # membership query
            [{'n': 'true'}],  # rollback delete
        ]

        response = self.client.post(
            '/service-accounts',
            json={
                'slug': 'orphan-bot',
                'display_name': 'Orphan Bot',
                'organization_slug': 'acme-corp',
                'role_slug': 'nonexistent-role',
            },
        )

        self.assertEqual(response.status_code, 404)
        detail = response.json()['detail']
        self.assertIn('nonexistent-role', detail)
        self.assertIn('acme-corp', detail)

    def test_create_service_account_missing_org(self) -> None:
        """Test creating SA without org_slug returns 422."""
        response = self.client.post(
            '/service-accounts',
            json={
                'slug': 'test-bot',
                'display_name': 'Test Bot',
                'role_slug': 'deployer',
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_remove_from_organization(self) -> None:
        """Test removing service account from org."""
        self.mock_db.execute.return_value = [{'deleted': 1}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(
                '/service-accounts/test-bot/organizations/acme-corp',
            )

        self.assertEqual(response.status_code, 204)

    def test_patch_service_account_display_name(self) -> None:
        """Test patching only the display name."""
        import datetime as dt

        from imbi_api import models as api_models

        existing = api_models.ServiceAccount(
            slug='my-sa',
            display_name='Old Name',
            description='A service account',
            is_active=True,
            created_at=dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
        )
        self.mock_db.match.return_value = [existing]
        self.mock_db.merge.return_value = None

        response = self.client.patch(
            '/service-accounts/my-sa',
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
        self.mock_db.merge.assert_called_once()

    def test_patch_service_account_not_found(self) -> None:
        """Test patching a non-existent service account returns 404."""
        self.mock_db.match.return_value = []

        response = self.client.patch(
            '/service-accounts/nonexistent',
            json=[
                {
                    'op': 'replace',
                    'path': '/display_name',
                    'value': 'X',
                }
            ],
        )

        self.assertEqual(response.status_code, 404)

    def test_patch_service_account_slug_change_raises_400(self) -> None:
        """Test patching slug to a different value raises 400."""
        import datetime as dt

        from imbi_api import models as api_models

        existing = api_models.ServiceAccount(
            slug='my-sa',
            display_name='SA',
            is_active=True,
            created_at=dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
        )
        self.mock_db.match.return_value = [existing]

        response = self.client.patch(
            '/service-accounts/my-sa',
            json=[
                {
                    'op': 'replace',
                    'path': '/slug',
                    'value': 'other-sa',
                }
            ],
        )

        self.assertEqual(response.status_code, 400)

    def test_update_organization_role_success(self) -> None:
        """PATCH updates the SA's membership role."""
        self.mock_db.execute.side_effect = [
            [{'slug': 'deployer'}],
            [{'role': 'deployer'}],
        ]

        response = self.client.patch(
            '/service-accounts/test-bot/organizations/acme-corp',
            json=[
                {
                    'op': 'replace',
                    'path': '/role_slug',
                    'value': 'deployer',
                },
            ],
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.mock_db.execute.call_count, 2)

    def test_update_organization_role_missing_role(self) -> None:
        """PATCH returns 404 when the target role does not exist."""
        self.mock_db.execute.side_effect = [[]]

        response = self.client.patch(
            '/service-accounts/test-bot/organizations/acme-corp',
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
        """PATCH returns 404 when SA is not a member of the org."""
        self.mock_db.execute.side_effect = [
            [{'slug': 'deployer'}],
            [],
        ]

        response = self.client.patch(
            '/service-accounts/test-bot/organizations/other-org',
            json=[
                {
                    'op': 'replace',
                    'path': '/role_slug',
                    'value': 'deployer',
                },
            ],
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not a member', response.json()['detail'])

    def test_update_organization_role_malformed_patch(self) -> None:
        """PATCH with wrong path returns 400 without touching graph."""
        response = self.client.patch(
            '/service-accounts/test-bot/organizations/acme-corp',
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
