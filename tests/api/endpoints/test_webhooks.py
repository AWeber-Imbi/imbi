"""Tests for webhook and project services endpoints."""

import copy
import datetime
import json
import typing
import unittest
from unittest import mock

import psycopg.errors
from fastapi import testclient
from imbi_common import graph

from imbi_api import app, models


class _WebhookDetails(typing.TypedDict):
    name: str
    slug: str
    description: typing.NotRequired[str]
    icon: typing.NotRequired[str | None]
    notification_path: str
    secret: typing.NotRequired[str]


class _WebhookRule(typing.TypedDict):
    filter_expression: str
    handler: str
    handler_config: str


class _WebhookRecord(typing.TypedDict):
    webhook: _WebhookDetails
    tps: typing.NotRequired[dict[str, str] | None]
    identifier_selector: typing.NotRequired[str | None]
    rules: list[_WebhookRule | None]


class WebhookEndpointsTestCase(unittest.TestCase):
    """Test cases for Webhook CRUD endpoints."""

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
                'webhook:create',
                'webhook:read',
                'webhook:update',
                'webhook:delete',
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

        self.webhook_record: _WebhookRecord = {
            'webhook': {
                'name': 'GitHub Events',
                'slug': 'github-events',
                'description': 'Receives GitHub webhooks',
                'icon': None,
                'notification_path': '/webhooks/github',
                'secret': 'enc:my-secret',
            },
            'tps': None,
            'identifier_selector': None,
            'rules': [],
        }

        self.webhook_create_json: _WebhookDetails = {
            'name': 'GitHub Events',
            'slug': 'github-events',
            'notification_path': '/webhooks/github',
            'secret': 'my-secret',
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

    # -- Create --

    def test_create_success(self) -> None:
        self.mock_db.execute.return_value = [self.webhook_record]
        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.post(
                '/organizations/engineering/webhooks/',
                json=self.webhook_create_json,
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['slug'], 'github-events')
        self.assertEqual(data['name'], 'GitHub Events')
        self.assertEqual(
            data['notification_path'],
            '/webhooks/github',
        )

    def test_create_with_rules(self) -> None:
        record = copy.deepcopy(self.webhook_record)
        record['rules'] = [
            {
                'filter_expression': '$.action == "opened"',
                'handler': 'my.handler',
                'handler_config': '{"key": "value"}',
            },
        ]

        self.mock_db.execute.return_value = [record]
        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            payload = dict(self.webhook_create_json)
            payload['rules'] = [
                {
                    'filter_expression': '$.action == "opened"',
                    'handler': 'my.handler',
                    'handler_config': {'key': 'value'},
                },
            ]
            response = self.client.post(
                '/organizations/engineering/webhooks/',
                json=payload,
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(len(data['rules']), 1)
        self.assertEqual(
            data['rules'][0]['handler'],
            'my.handler',
        )

    def test_create_with_third_party_service(self) -> None:
        record = copy.deepcopy(self.webhook_record)
        record['tps'] = {
            'name': 'GitHub',
            'slug': 'github',
        }
        record['identifier_selector'] = '$.repository.full_name'

        self.mock_db.execute.return_value = [record]
        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            payload = dict(self.webhook_create_json)
            payload['third_party_service_slug'] = 'github'
            payload['identifier_selector'] = '$.repository.full_name'
            response = self.client.post(
                '/organizations/engineering/webhooks/',
                json=payload,
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIsNotNone(data['third_party_service'])
        self.assertEqual(
            data['third_party_service']['slug'],
            'github',
        )

    def test_create_duplicate_slug(self) -> None:
        self.mock_db.execute.side_effect = psycopg.errors.UniqueViolation()
        with self._patch_encryption():
            response = self.client.post(
                '/organizations/engineering/webhooks/',
                json=self.webhook_create_json,
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

    def test_create_org_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.post(
                '/organizations/nonexistent/webhooks/',
                json=self.webhook_create_json,
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_create_third_party_service_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            payload = dict(self.webhook_create_json)
            payload['third_party_service_slug'] = 'nonexistent'
            payload['identifier_selector'] = '$.repository.full_name'
            response = self.client.post(
                '/organizations/engineering/webhooks/',
                json=payload,
            )

        self.assertEqual(response.status_code, 404)
        detail = response.json()['detail']
        self.assertIn('not found', detail)
        self.assertIn('nonexistent', detail)

    def test_create_missing_name(self) -> None:
        response = self.client.post(
            '/organizations/engineering/webhooks/',
            json={
                'slug': 'test',
                'notification_path': '/test',
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_create_missing_slug(self) -> None:
        response = self.client.post(
            '/organizations/engineering/webhooks/',
            json={
                'name': 'Test',
                'notification_path': '/test',
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_create_invalid_notification_path(self) -> None:
        response = self.client.post(
            '/organizations/engineering/webhooks/',
            json={
                'name': 'Test',
                'slug': 'test',
                'notification_path': 'no-leading-slash',
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_create_invalid_slug_pattern(self) -> None:
        response = self.client.post(
            '/organizations/engineering/webhooks/',
            json={
                'name': 'Test',
                'slug': 'Bad-Slug',
                'notification_path': '/test',
            },
        )
        self.assertEqual(response.status_code, 422)

    # -- List --

    def test_list_webhooks(self) -> None:
        self.mock_db.execute.return_value = [self.webhook_record]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/webhooks/',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['slug'], 'github-events')

    def test_list_webhooks_empty(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/webhooks/',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    # -- Get --

    def test_get_webhook(self) -> None:
        self.mock_db.execute.return_value = [self.webhook_record]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/webhooks/github-events',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'github-events')
        self.assertEqual(
            data['notification_path'],
            '/webhooks/github',
        )

    def test_get_webhook_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/webhooks/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    # -- Patch --

    def test_patch_webhook_description(self) -> None:
        """Test patching only the webhook description."""
        existing_record = {
            'webhook': {
                'name': 'Deploy Hook',
                'slug': 'deploy',
                'description': 'Old',
                'notification_path': '/deploy',
                'secret': None,
            },
            'tps': None,
            'identifier_selector': None,
            'rules': [],
        }
        updated_record = {
            'webhook': {
                'name': 'Deploy Hook',
                'slug': 'deploy',
                'description': 'New desc',
                'notification_path': '/deploy',
                'secret': None,
            },
            'tps': None,
            'identifier_selector': None,
            'rules': [],
        }
        self.mock_db.execute.side_effect = [
            [existing_record],
            [updated_record],
            [updated_record],
        ]

        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.patch(
                '/organizations/engineering/webhooks/deploy',
                json=[
                    {
                        'op': 'replace',
                        'path': '/description',
                        'value': 'New desc',
                    }
                ],
            )

        self.assertEqual(response.status_code, 200)

    def test_patch_webhook_not_found(self) -> None:
        """Test patching non-existent webhook returns 404."""
        self.mock_db.execute.return_value = []

        response = self.client.patch(
            '/organizations/engineering/webhooks/nonexistent',
            json=[{'op': 'replace', 'path': '/description', 'value': 'X'}],
        )

        self.assertEqual(response.status_code, 404)

    def test_patch_webhook_with_tps(self) -> None:
        """Test patching a webhook that has a third-party service link."""
        existing_record = {
            'webhook': {
                'name': 'GitHub Hook',
                'slug': 'github-hook',
                'description': 'Old desc',
                'notification_path': '/github',
                'secret': None,
            },
            'tps': {'slug': 'github', 'name': 'GitHub'},
            'identifier_selector': '$.repo',
            'rules': [],
        }
        updated_record = {
            'webhook': {
                'name': 'GitHub Hook',
                'slug': 'github-hook',
                'description': 'New desc',
                'notification_path': '/github',
                'secret': None,
            },
            'tps': {'slug': 'github', 'name': 'GitHub'},
            'identifier_selector': '$.repo',
            'rules': [],
        }

        self.mock_db.execute.side_effect = [
            [existing_record],
            [updated_record],
            [updated_record],
        ]

        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.patch(
                '/organizations/engineering/webhooks/github-hook',
                json=[
                    {
                        'op': 'replace',
                        'path': '/description',
                        'value': 'New desc',
                    }
                ],
            )

        self.assertEqual(response.status_code, 200)

    def test_patch_webhook_encrypt_new_secret(self) -> None:
        """Test patching a webhook's secret encrypts the new value."""
        existing_record = {
            'webhook': {
                'name': 'Deploy Hook',
                'slug': 'deploy',
                'description': 'A hook',
                'notification_path': '/deploy',
                'secret': None,
            },
            'tps': None,
            'identifier_selector': None,
            'rules': [],
        }
        updated_record = dict(existing_record)

        self.mock_db.execute.side_effect = [
            [existing_record],
            [updated_record],
            [updated_record],
        ]

        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.patch(
                '/organizations/engineering/webhooks/deploy',
                json=[
                    {'op': 'replace', 'path': '/secret', 'value': 'my-secret'}
                ],
            )

        self.assertEqual(response.status_code, 200)
        self.mock_encryptor.encrypt.assert_called_once_with('my-secret')

    def test_patch_webhook_clear_secret(self) -> None:
        """Test patching secret to null clears the encrypted secret."""
        existing_record = {
            'webhook': {
                'name': 'Deploy Hook',
                'slug': 'deploy',
                'description': 'A hook',
                'notification_path': '/deploy',
                'secret': 'enc:old-secret',
            },
            'tps': None,
            'identifier_selector': None,
            'rules': [],
        }
        updated_record = {
            'webhook': {
                'name': 'Deploy Hook',
                'slug': 'deploy',
                'description': 'A hook',
                'notification_path': '/deploy',
                'secret': None,
            },
            'tps': None,
            'identifier_selector': None,
            'rules': [],
        }

        self.mock_db.execute.side_effect = [
            [existing_record],
            [updated_record],
            [updated_record],
        ]

        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.patch(
                '/organizations/engineering/webhooks/deploy',
                json=[{'op': 'replace', 'path': '/secret', 'value': None}],
            )

        self.assertEqual(response.status_code, 200)
        self.mock_encryptor.encrypt.assert_not_called()

    def test_patch_webhook_with_rules(self) -> None:
        """Test patching a webhook that has rules stored as a JSON string."""
        existing_record = {
            'webhook': {
                'name': 'Deploy Hook',
                'slug': 'deploy',
                'description': 'Old',
                'notification_path': '/deploy',
                'secret': None,
            },
            'tps': None,
            'identifier_selector': None,
            'rules': json.dumps(
                [
                    {
                        'filter_expression': '$.action == "push"',
                        'handler': 'my.handler',
                        'handler_config': '{}',
                    }
                ]
            ),
        }
        updated_record = {
            'webhook': {
                'name': 'Deploy Hook',
                'slug': 'deploy',
                'description': 'New',
                'notification_path': '/deploy',
                'secret': None,
            },
            'tps': None,
            'identifier_selector': None,
            'rules': [],
        }

        self.mock_db.execute.side_effect = [
            [existing_record],
            [updated_record],
            [updated_record],
        ]

        with (
            self._patch_encryption(),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.patch(
                '/organizations/engineering/webhooks/deploy',
                json=[
                    {'op': 'replace', 'path': '/description', 'value': 'New'}
                ],
            )

        self.assertEqual(response.status_code, 200)

    # -- Delete --

    def test_delete_webhook(self) -> None:
        self.mock_db.execute.return_value = [{'deleted': 1}]
        response = self.client.delete(
            '/organizations/engineering/webhooks/github-events',
        )

        self.assertEqual(response.status_code, 204)

    def test_delete_webhook_not_found(self) -> None:
        self.mock_db.execute.return_value = [{'deleted': 0}]
        response = self.client.delete(
            '/organizations/engineering/webhooks/nonexistent',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    # -- Response building edge cases --

    def test_rules_with_malformed_handler_config(self) -> None:
        record = copy.deepcopy(self.webhook_record)
        record['rules'] = [
            {
                'filter_expression': '$.action',
                'handler': 'my.handler',
                'handler_config': '{not valid json',
            },
        ]

        self.mock_db.execute.return_value = [record]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/webhooks/github-events',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['rules']), 1)
        self.assertEqual(
            data['rules'][0]['handler_config'],
            {},
        )

    def test_rules_with_null_entries_filtered(self) -> None:
        record = copy.deepcopy(self.webhook_record)
        record['rules'] = [None]

        self.mock_db.execute.return_value = [record]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/webhooks/github-events',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['rules'], [])

    def test_rules_with_list_handler_config(self) -> None:
        record = copy.deepcopy(self.webhook_record)
        record['rules'] = [
            {
                'filter_expression': '$.action',
                'handler': 'my.handler',
                'handler_config': json.dumps(['step1', 'step2']),
            },
        ]

        self.mock_db.execute.return_value = [record]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/webhooks/github-events',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['rules'][0]['handler_config'],
            ['step1', 'step2'],
        )


class ProjectServicesEndpointsTestCase(unittest.TestCase):
    """Test cases for Project EXISTS_IN service endpoints."""

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
                'project:read',
                'project:write',
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

        self.service_record: dict[str, str | None] = {
            'service_slug': 'github',
            'service_name': 'GitHub',
            'identifier': 'org/repo',
            'canonical_link': 'https://github.com/org/repo',
        }

    # -- List --

    def test_list_project_services(self) -> None:
        self.mock_db.execute.return_value = [
            self.service_record,
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/projects/my-project/services/',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(
            data[0]['third_party_service_slug'],
            'github',
        )
        self.assertEqual(data[0]['identifier'], 'org/repo')

    def test_list_project_services_empty(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/projects/my-project/services/',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_without_canonical_link(self) -> None:
        record = copy.deepcopy(self.service_record)
        record['canonical_link'] = None

        self.mock_db.execute.return_value = [record]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/projects/my-project/services/',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNone(data[0]['canonical_link'])

    # -- Create --

    def test_create_project_service(self) -> None:
        self.mock_db.execute.return_value = [
            self.service_record,
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/organizations/engineering/projects/my-project/services/',
                json={
                    'third_party_service_slug': 'github',
                    'identifier': 'org/repo',
                    'canonical_link': ('https://github.com/org/repo'),
                },
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(
            data['third_party_service_slug'],
            'github',
        )
        self.assertEqual(data['identifier'], 'org/repo')

    def test_create_project_service_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/organizations/engineering/projects/my-project/services/',
                json={
                    'third_party_service_slug': 'nonexistent',
                    'identifier': 'org/repo',
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_create_missing_identifier(self) -> None:
        response = self.client.post(
            '/organizations/engineering/projects/my-project/services/',
            json={
                'third_party_service_slug': 'github',
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_create_empty_identifier_rejected(self) -> None:
        response = self.client.post(
            '/organizations/engineering/projects/my-project/services/',
            json={
                'third_party_service_slug': 'github',
                'identifier': '',
            },
        )
        self.assertEqual(response.status_code, 422)

    # -- Delete --

    def test_delete_project_service(self) -> None:
        self.mock_db.execute.return_value = [{'deleted': 1}]
        response = self.client.delete(
            '/organizations/engineering/projects/my-project/services/github',
        )

        self.assertEqual(response.status_code, 204)

    def test_delete_project_service_not_found(self) -> None:
        self.mock_db.execute.return_value = [{'deleted': 0}]
        response = self.client.delete(
            '/organizations/engineering'
            '/projects/my-project/services/nonexistent',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])
