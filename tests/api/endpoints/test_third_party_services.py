"""Tests for third-party service CRUD endpoints."""

import datetime
import json
import unittest
from unittest import mock

import psycopg.errors
from fastapi import testclient
from imbi_common import graph

from imbi_api import app, models


class ThirdPartyServiceEndpointsTestCase(unittest.TestCase):
    """Test cases for ThirdPartyService CRUD endpoints."""

    def setUp(self) -> None:
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
                'third_party_service:create',
                'third_party_service:read',
                'third_party_service:update',
                'third_party_service:delete',
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

        self.service_data = {
            'name': 'Stripe',
            'slug': 'stripe',
            'description': 'Payment processing',
            'vendor': 'Stripe Inc',
            'service_url': 'https://stripe.com',
            'category': 'payments',
            'status': 'active',
            'links': {},
            'identifiers': {},
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
            'team': None,
        }

        self.service_update_json = {
            'name': 'Stripe',
            'slug': 'stripe',
            'vendor': 'Stripe Inc',
            'description': 'Payment processing',
            'service_url': 'https://stripe.com',
            'category': 'payments',
            'status': 'active',
        }

    # -- Create --

    def test_create_success(self) -> None:
        self.mock_db.execute.return_value = [
            {'service': self.service_data},
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/organizations/engineering/third-party-services/',
                json={
                    'name': 'Stripe',
                    'slug': 'stripe',
                    'vendor': 'Stripe Inc',
                },
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['slug'], 'stripe')
        self.assertEqual(data['name'], 'Stripe')

    def test_create_with_team(self) -> None:
        svc = dict(self.service_data)
        svc['team'] = {'name': 'Backend', 'slug': 'backend'}

        self.mock_db.execute.return_value = [{'service': svc}]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/organizations/engineering/third-party-services/',
                json={
                    'name': 'Stripe',
                    'slug': 'stripe',
                    'vendor': 'Stripe Inc',
                    'team_slug': 'backend',
                },
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['team']['slug'], 'backend')

    def test_create_missing_vendor(self) -> None:
        response = self.client.post(
            '/organizations/engineering/third-party-services/',
            json={
                'name': 'Stripe',
                'slug': 'stripe',
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_create_missing_name(self) -> None:
        response = self.client.post(
            '/organizations/engineering/third-party-services/',
            json={
                'slug': 'stripe',
                'vendor': 'Stripe Inc',
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_create_missing_slug(self) -> None:
        response = self.client.post(
            '/organizations/engineering/third-party-services/',
            json={
                'name': 'Stripe',
                'vendor': 'Stripe Inc',
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_create_invalid_status(self) -> None:
        response = self.client.post(
            '/organizations/engineering/third-party-services/',
            json={
                'name': 'Stripe',
                'slug': 'stripe',
                'vendor': 'Stripe Inc',
                'status': 'bogus',
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_create_duplicate_slug(self) -> None:
        self.mock_db.execute.side_effect = psycopg.errors.UniqueViolation()
        response = self.client.post(
            '/organizations/engineering/third-party-services/',
            json={
                'name': 'Stripe',
                'slug': 'stripe',
                'vendor': 'Stripe Inc',
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            'already exists',
            response.json()['detail'],
        )

    def test_create_org_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/organizations/nonexistent/third-party-services/',
                json={
                    'name': 'Stripe',
                    'slug': 'stripe',
                    'vendor': 'Stripe Inc',
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_create_team_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/organizations/engineering/third-party-services/',
                json={
                    'name': 'Stripe',
                    'slug': 'stripe',
                    'vendor': 'Stripe Inc',
                    'team_slug': 'nonexistent',
                },
            )

        self.assertEqual(response.status_code, 404)
        detail = response.json()['detail']
        self.assertIn('not found', detail)
        self.assertIn('team', detail)

    # -- List --

    def test_list_services(self) -> None:
        self.mock_db.execute.return_value = [
            {'service': self.service_data},
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/third-party-services/',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['slug'], 'stripe')

    def test_list_services_empty(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/third-party-services/',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_deserializes_json_fields(self) -> None:
        svc = dict(self.service_data)
        svc['links'] = json.dumps(
            {'docs': 'https://docs.stripe.com'},
        )
        svc['identifiers'] = json.dumps(
            {'account_id': 'acct_123'},
        )

        self.mock_db.execute.return_value = [{'service': svc}]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/third-party-services/',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()[0]
        self.assertEqual(
            data['links'],
            {'docs': 'https://docs.stripe.com'},
        )
        self.assertEqual(
            data['identifiers'],
            {'account_id': 'acct_123'},
        )

    # -- Get --

    def test_get_service(self) -> None:
        self.mock_db.execute.return_value = [
            {'service': self.service_data},
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/third-party-services/stripe',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'stripe')
        self.assertEqual(data['vendor'], 'Stripe Inc')

    def test_get_service_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/third-party-services/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    # -- Update --

    def test_update_service(self) -> None:
        updated = dict(self.service_data)
        updated['description'] = 'Updated description'

        self.mock_db.execute.side_effect = [
            [{'service': self.service_data}],
            [{'service': updated}],
        ]

        payload = dict(self.service_update_json)
        payload['description'] = 'Updated description'

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                '/organizations/engineering/third-party-services/stripe',
                json=payload,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['description'],
            'Updated description',
        )

    def test_update_service_with_team(self) -> None:
        updated = dict(self.service_data)
        updated['team'] = {
            'name': 'Backend',
            'slug': 'backend',
        }

        self.mock_db.execute.side_effect = [
            [{'service': self.service_data}],
            [{'service': updated}],
        ]

        payload = dict(self.service_update_json)
        payload['team_slug'] = 'backend'

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                '/organizations/engineering/third-party-services/stripe',
                json=payload,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['team']['slug'],
            'backend',
        )

    def test_update_missing_required_field(self) -> None:
        """Omitting a required field returns 422."""
        response = self.client.put(
            '/organizations/engineering/third-party-services/stripe',
            json={
                'name': 'Stripe',
                'vendor': 'Stripe Inc',
                # Missing slug, status
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_update_service_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                '/organizations/engineering/third-party-services/nonexistent',
                json=self.service_update_json,
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_update_invalid_status(self) -> None:
        payload = dict(self.service_update_json)
        payload['status'] = 'bogus'

        response = self.client.put(
            '/organizations/engineering/third-party-services/stripe',
            json=payload,
        )

        self.assertEqual(response.status_code, 422)

    def test_update_slug_conflict(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'service': self.service_data}],
            psycopg.errors.UniqueViolation(),
        ]

        payload = dict(self.service_update_json)
        payload['slug'] = 'existing-slug'

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                '/organizations/engineering/third-party-services/stripe',
                json=payload,
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            'already exists',
            response.json()['detail'],
        )

    def test_update_concurrent_delete(self) -> None:
        """Service deleted between fetch and update."""
        self.mock_db.execute.side_effect = [
            [{'service': self.service_data}],
            [],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                '/organizations/engineering/third-party-services/stripe',
                json=self.service_update_json,
            )

        self.assertEqual(response.status_code, 404)

    # -- Patch --

    def test_patch_third_party_service_name(self) -> None:
        """Test patching only the third-party service name."""
        existing_service_record = {
            'service': {
                'name': 'GitHub',
                'slug': 'github',
                'vendor': 'GitHub Inc.',
                'category': 'source_control',
                'status': 'active',
                'links': '{}',
                'identifiers': '{}',
                'organization': {'name': 'Engineering', 'slug': 'engineering'},
                'team': None,
            }
        }
        updated_service_record = {
            'service': {
                'name': 'GitHub Enterprise',
                'slug': 'github',
                'vendor': 'GitHub Inc.',
                'category': 'source_control',
                'status': 'active',
                'links': '{}',
                'identifiers': '{}',
                'organization': {'name': 'Engineering', 'slug': 'engineering'},
                'team': None,
            }
        }
        self.mock_db.execute.side_effect = [
            [existing_service_record],
            [updated_service_record],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/third-party-services/github',
                json=[
                    {
                        'op': 'replace',
                        'path': '/name',
                        'value': 'GitHub Enterprise',
                    }
                ],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'GitHub Enterprise')

    def test_patch_third_party_service_not_found(self) -> None:
        """Test patching non-existent third-party service returns 404."""
        self.mock_db.execute.return_value = []

        response = self.client.patch(
            '/organizations/engineering/third-party-services/nonexistent',
            json=[{'op': 'replace', 'path': '/name', 'value': 'X'}],
        )

        self.assertEqual(response.status_code, 404)

    # -- Delete --

    def test_delete_service(self) -> None:
        self.mock_db.execute.return_value = [{'deleted': 1}]
        response = self.client.delete(
            '/organizations/engineering/third-party-services/stripe',
        )

        self.assertEqual(response.status_code, 204)

    def test_delete_service_not_found(self) -> None:
        self.mock_db.execute.return_value = [{'deleted': 0}]
        response = self.client.delete(
            '/organizations/engineering/third-party-services/nonexistent',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])


class ServiceWebhooksEndpointsTestCase(unittest.TestCase):
    """Test cases for list_service_webhooks endpoint."""

    def setUp(self) -> None:
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
            permissions={'webhook:read'},
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

        self.base_url = (
            '/organizations/engineering/third-party-services/github/webhooks/'
        )

    def test_list_service_webhooks(self) -> None:
        record = {
            'webhook': {
                'name': 'GitHub PR Events',
                'slug': 'gh-pr-events',
                'description': 'PR webhooks',
                'icon': None,
                'notification_path': '/webhooks/gh-pr',
            },
            'tps': {
                'name': 'GitHub',
                'slug': 'github',
            },
            'identifier_selector': '$.repository.full_name',
            'rules': [],
        }

        self.mock_db.execute.return_value = [record]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self.base_url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['slug'], 'gh-pr-events')
        self.assertEqual(
            data[0]['name'],
            'GitHub PR Events',
        )
        self.assertEqual(
            data[0]['notification_path'],
            '/webhooks/gh-pr',
        )
        self.assertEqual(
            data[0]['third_party_service']['slug'],
            'github',
        )
        self.assertEqual(
            data[0]['identifier_selector'],
            '$.repository.full_name',
        )

    def test_list_service_webhooks_empty(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self.base_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_service_webhooks_multiple(self) -> None:
        records = [
            {
                'webhook': {
                    'name': 'First',
                    'slug': 'first',
                    'notification_path': '/webhooks/first',
                },
                'tps': {
                    'name': 'GitHub',
                    'slug': 'github',
                },
                'identifier_selector': None,
                'rules': [],
            },
            {
                'webhook': {
                    'name': 'Second',
                    'slug': 'second',
                    'notification_path': '/webhooks/second',
                },
                'tps': {
                    'name': 'GitHub',
                    'slug': 'github',
                },
                'identifier_selector': None,
                'rules': [],
            },
        ]

        self.mock_db.execute.return_value = records
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self.base_url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['slug'], 'first')
        self.assertEqual(data[1]['slug'], 'second')

    def test_list_service_webhooks_with_rules(self) -> None:
        record = {
            'webhook': {
                'name': 'GitHub Events',
                'slug': 'gh-events',
                'notification_path': '/webhooks/gh',
            },
            'tps': {
                'name': 'GitHub',
                'slug': 'github',
            },
            'identifier_selector': None,
            'rules': [
                {
                    'filter_expression': ('$.action == "opened"'),
                    'handler': 'pr.handler',
                    'handler_config': '{"notify": true}',
                },
                {
                    'filter_expression': ('$.action == "closed"'),
                    'handler': 'close.handler',
                    'handler_config': '{}',
                },
            ],
        }

        self.mock_db.execute.return_value = [record]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self.base_url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        rules = data[0]['rules']
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0]['handler'], 'pr.handler')
        self.assertEqual(
            rules[0]['handler_config'],
            {'notify': True},
        )
        self.assertEqual(
            rules[1]['handler'],
            'close.handler',
        )

    def test_list_service_webhooks_null_rules_filtered(
        self,
    ) -> None:
        record = {
            'webhook': {
                'name': 'GitHub Events',
                'slug': 'gh-events',
                'notification_path': '/webhooks/gh',
            },
            'tps': {
                'name': 'GitHub',
                'slug': 'github',
            },
            'identifier_selector': None,
            'rules': [None],
        }

        self.mock_db.execute.return_value = [record]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self.base_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['rules'], [])

    def test_list_service_webhooks_malformed_config(
        self,
    ) -> None:
        record = {
            'webhook': {
                'name': 'GitHub Events',
                'slug': 'gh-events',
                'notification_path': '/webhooks/gh',
            },
            'tps': {
                'name': 'GitHub',
                'slug': 'github',
            },
            'identifier_selector': None,
            'rules': [
                {
                    'filter_expression': '$.action',
                    'handler': 'my.handler',
                    'handler_config': '{bad json',
                },
            ],
        }

        self.mock_db.execute.return_value = [record]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self.base_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()[0]['rules'][0]['handler_config'],
            {},
        )

    def test_list_service_webhooks_without_tps(self) -> None:
        record = {
            'webhook': {
                'name': 'GitHub Events',
                'slug': 'gh-events',
                'notification_path': '/webhooks/gh',
            },
            'tps': None,
            'identifier_selector': None,
            'rules': [],
        }

        self.mock_db.execute.return_value = [record]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self.base_url)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(
            response.json()[0]['third_party_service'],
        )


class ServiceApplicationEndpointsTestCase(unittest.TestCase):
    """Test cases for ServiceApplication CRUD endpoints."""

    def setUp(self) -> None:
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
                'third_party_service:create',
                'third_party_service:read',
                'third_party_service:update',
                'third_party_service:delete',
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

        self.app_data = {
            'slug': 'my-app',
            'name': 'My App',
            'description': 'Test app',
            'app_type': 'github_app',
            'application_url': 'https://example.com',
            'client_id': 'client-123',
            'client_secret': 'encrypted-secret',
            'scopes': json.dumps(['repo', 'user']),
            'webhook_secret': 'encrypted-webhook',
            'private_key': None,
            'signing_secret': None,
            'settings': json.dumps({}),
            'status': 'active',
        }

        self.app_create_json = {
            'slug': 'my-app',
            'name': 'My App',
            'description': 'Test app',
            'app_type': 'github_app',
            'client_id': 'client-123',
            'client_secret': 'super-secret',
            'scopes': ['repo', 'user'],
            'webhook_secret': 'wh-secret',
        }

        self.app_update_json = {
            'slug': 'my-app',
            'name': 'My App',
            'description': 'Test app',
            'app_type': 'github_app',
            'client_id': 'client-123',
            'scopes': ['repo', 'user'],
        }

        self.mock_encryptor = mock.MagicMock()
        self.mock_encryptor.encrypt.side_effect = lambda v: f'enc:{v}'
        self.mock_encryptor.decrypt.side_effect = lambda v: v.removeprefix(
            'enc:'
        )

    def _patch_encryption(self):
        return mock.patch(
            'imbi_common.auth.encryption.TokenEncryption.get_instance',
            return_value=self.mock_encryptor,
        )

    # -- List applications --

    def test_list_applications(self) -> None:
        self.mock_db.execute.return_value = [
            {'app': self.app_data},
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['slug'], 'my-app')
        # Secrets should be stripped from the response
        self.assertNotIn('client_secret', data[0])
        self.assertNotIn('webhook_secret', data[0])

    def test_list_applications_empty(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_applications_deserializes_json(self) -> None:
        app_data = dict(self.app_data)
        app_data['scopes'] = json.dumps(['read', 'write'])
        app_data['settings'] = json.dumps({'debug': True})

        self.mock_db.execute.return_value = [
            {'app': app_data},
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()[0]
        self.assertEqual(data['scopes'], ['read', 'write'])
        self.assertEqual(data['settings'], {'debug': True})

    # -- Create application --

    def test_create_application(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'cnt': 0}],
            [{'app': self.app_data}],
        ]

        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.post(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/',
                json=self.app_create_json,
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['slug'], 'my-app')
        self.assertNotIn('client_secret', data)

    def test_create_application_duplicate(self) -> None:
        self.mock_db.execute.return_value = [{'cnt': 1}]

        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.post(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/',
                json=self.app_create_json,
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            'already exists',
            response.json()['detail'],
        )

    def test_create_application_service_not_found(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'cnt': 0}],
            [],
        ]

        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.post(
                '/organizations/engineering'
                '/third-party-services/nonexistent'
                '/applications/',
                json=self.app_create_json,
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_create_application_encrypts_secrets(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'cnt': 0}],
            [{'app': self.app_data}],
        ]

        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.post(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/',
                json=self.app_create_json,
            )

        self.assertEqual(response.status_code, 201)
        # Verify encrypt was called for secrets
        encrypt_calls = [
            c.args[0] for c in self.mock_encryptor.encrypt.call_args_list
        ]
        self.assertIn('super-secret', encrypt_calls)
        self.assertIn('wh-secret', encrypt_calls)

    def test_create_application_with_all_secrets(self) -> None:
        """All optional secret fields are encrypted."""
        payload = dict(self.app_create_json)
        payload['private_key'] = 'pk-data'
        payload['signing_secret'] = 'sig-data'

        app_data = dict(self.app_data)
        app_data['private_key'] = 'enc:pk-data'
        app_data['signing_secret'] = 'enc:sig-data'

        self.mock_db.execute.side_effect = [
            [{'cnt': 0}],
            [{'app': app_data}],
        ]

        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.post(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/',
                json=payload,
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        # All secrets should be stripped from the response
        self.assertNotIn('client_secret', data)
        self.assertNotIn('private_key', data)
        self.assertNotIn('signing_secret', data)

    # -- Get application --

    def test_get_application(self) -> None:
        self.mock_db.execute.return_value = [
            {'app': self.app_data},
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/my-app',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'my-app')
        self.assertNotIn('client_secret', data)

    def test_get_application_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_get_secrets_admin(self) -> None:
        app_data = dict(self.app_data)
        app_data['client_secret'] = 'enc:real-secret'
        app_data['webhook_secret'] = 'enc:real-webhook'

        self.mock_db.execute.return_value = [
            {'app': app_data},
        ]
        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.get(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/my-app/secrets',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['client_secret'], 'real-secret')
        self.assertEqual(
            data['webhook_secret'],
            'real-webhook',
        )

    def test_get_secrets_non_admin(self) -> None:
        from imbi_api.auth import permissions

        non_admin = models.User(
            email='user@example.com',
            display_name='Regular User',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=non_admin,
            session_id='test-session',
            auth_method='jwt',
            permissions={'third_party_service:read'},
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db.execute.return_value = [
            {'app': self.app_data},
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/my-app/secrets',
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn('Admin', response.json()['detail'])

    # -- Update application --

    def test_update_application(self) -> None:
        updated_app = dict(self.app_data)
        updated_app['name'] = 'Updated App'

        self.mock_db.execute.side_effect = [
            [{'app': self.app_data}],
            [{'app': updated_app}],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            payload = dict(self.app_update_json)
            payload['name'] = 'Updated App'
            response = self.client.put(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/my-app',
                json=payload,
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name'], 'Updated App')
        self.assertNotIn('client_secret', data)

    def test_update_preserves_existing_secrets(self) -> None:
        """Update carries forward existing encrypted values."""
        self.mock_db.execute.side_effect = [
            [{'app': self.app_data}],
            [{'app': self.app_data}],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/my-app',
                json=self.app_update_json,
            )

        self.assertEqual(response.status_code, 200)
        # Verify existing encrypted values were preserved
        # (props are now expanded as individual scalar params)
        update_call = self.mock_db.execute.call_args_list[1]
        params = update_call.args[1]
        self.assertEqual(
            params['client_secret'],
            self.app_data['client_secret'],
        )
        self.assertEqual(
            params['webhook_secret'],
            self.app_data['webhook_secret'],
        )

    def test_update_application_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/nonexistent',
                json=self.app_update_json,
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_update_application_concurrent_delete(self) -> None:
        """App deleted between fetch and update."""
        self.mock_db.execute.side_effect = [
            [{'app': self.app_data}],
            [],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/my-app',
                json=self.app_update_json,
            )

        self.assertEqual(response.status_code, 404)

    # -- Delete application --

    def test_delete_application(self) -> None:
        self.mock_db.execute.return_value = [{'deleted': 1}]
        response = self.client.delete(
            '/organizations/engineering'
            '/third-party-services/stripe'
            '/applications/my-app',
        )

        self.assertEqual(response.status_code, 204)

    def test_delete_application_not_found(self) -> None:
        self.mock_db.execute.return_value = [{'deleted': 0}]
        response = self.client.delete(
            '/organizations/engineering'
            '/third-party-services/stripe'
            '/applications/nonexistent',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    # -- Deserialization edge cases --

    def test_list_applications_null_json_fields(self) -> None:
        """None values in JSON fields use defaults."""
        app_data = dict(self.app_data)
        app_data['scopes'] = None
        app_data['settings'] = None

        self.mock_db.execute.return_value = [
            {'app': app_data},
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()[0]
        self.assertEqual(data['scopes'], [])
        self.assertEqual(data['settings'], {})

    def test_list_applications_malformed_json_fields(
        self,
    ) -> None:
        """Malformed JSON strings in fields use defaults."""
        app_data = dict(self.app_data)
        app_data['scopes'] = '{not valid json'
        app_data['settings'] = '{also broken'

        self.mock_db.execute.return_value = [
            {'app': app_data},
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()[0]
        self.assertEqual(data['scopes'], [])
        self.assertEqual(data['settings'], {})

    # -- Update application secrets --

    def test_update_secrets(self) -> None:
        updated_app = dict(self.app_data)
        updated_app['client_secret'] = 'enc:new-secret'

        self.mock_db.execute.side_effect = [
            [{'app': self.app_data}],
            [{'app': updated_app}],
        ]

        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.put(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/my-app/secrets',
                json={'client_secret': 'new-secret'},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['client_secret'], 'new-secret')

    def test_update_secrets_preserves_unchanged(self) -> None:
        """Fields not provided keep existing values."""
        updated_app = dict(self.app_data)
        updated_app['webhook_secret'] = 'enc:new-webhook'

        self.mock_db.execute.side_effect = [
            [{'app': self.app_data}],
            [{'app': updated_app}],
        ]

        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.put(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/my-app/secrets',
                json={'webhook_secret': 'new-webhook'},
            )

        self.assertEqual(response.status_code, 200)
        # Existing client_secret should be preserved
        update_call = self.mock_db.execute.call_args_list[1]
        self.assertEqual(
            update_call.args[1]['client_secret'],
            self.app_data['client_secret'],
        )

    def test_update_secrets_non_admin(self) -> None:
        from imbi_api.auth import permissions

        non_admin = models.User(
            email='user@example.com',
            display_name='Regular User',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=non_admin,
            session_id='test-session',
            auth_method='jwt',
            permissions={'third_party_service:update'},
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db.execute.return_value = [
            {'app': self.app_data},
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/my-app/secrets',
                json={'client_secret': 'new-secret'},
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn('Admin', response.json()['detail'])

    def test_update_secrets_empty_body_rejected(self) -> None:
        """At least one secret field must be provided."""
        response = self.client.put(
            '/organizations/engineering'
            '/third-party-services/stripe'
            '/applications/my-app/secrets',
            json={},
        )
        self.assertEqual(response.status_code, 422)

    def test_update_secrets_not_found(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'app': self.app_data}],
            [],
        ]

        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.put(
                '/organizations/engineering'
                '/third-party-services/stripe'
                '/applications/missing/secrets',
                json={'client_secret': 'new-secret'},
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])
