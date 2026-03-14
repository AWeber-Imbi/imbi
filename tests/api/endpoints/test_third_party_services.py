"""Tests for third-party service CRUD endpoints."""

import datetime
import json
import unittest
from unittest import mock

from fastapi import testclient
from neo4j import exceptions

from imbi_api import app, models
from imbi_api.domain import models as domain_models


def _mock_neo4j_result(data):
    """Create a mock async context manager for neo4j.run()."""
    result = mock.AsyncMock()
    result.data.return_value = data
    result.__aenter__.return_value = result
    result.__aexit__.return_value = None
    return result


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

    # -- Create --

    def test_create_success(self) -> None:
        result = _mock_neo4j_result(
            [{'service': self.service_data}],
        )
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.post(
                '/third-party-services/',
                json={
                    'name': 'Stripe',
                    'slug': 'stripe',
                    'vendor': 'Stripe Inc',
                    'organization_slug': 'engineering',
                },
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['slug'], 'stripe')
        self.assertEqual(data['name'], 'Stripe')

    def test_create_with_team(self) -> None:
        svc = dict(self.service_data)
        svc['team'] = {'name': 'Backend', 'slug': 'backend'}

        result = _mock_neo4j_result([{'service': svc}])
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.post(
                '/third-party-services/',
                json={
                    'name': 'Stripe',
                    'slug': 'stripe',
                    'vendor': 'Stripe Inc',
                    'organization_slug': 'engineering',
                    'team_slug': 'backend',
                },
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['team']['slug'], 'backend')

    def test_create_missing_org_slug(self) -> None:
        response = self.client.post(
            '/third-party-services/',
            json={
                'name': 'Stripe',
                'slug': 'stripe',
                'vendor': 'Stripe Inc',
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'organization_slug',
            response.json()['detail'],
        )

    def test_create_missing_vendor(self) -> None:
        response = self.client.post(
            '/third-party-services/',
            json={
                'name': 'Stripe',
                'slug': 'stripe',
                'organization_slug': 'engineering',
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('vendor', response.json()['detail'])

    def test_create_missing_name(self) -> None:
        response = self.client.post(
            '/third-party-services/',
            json={
                'slug': 'stripe',
                'vendor': 'Stripe Inc',
                'organization_slug': 'engineering',
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('name', response.json()['detail'])

    def test_create_missing_slug(self) -> None:
        response = self.client.post(
            '/third-party-services/',
            json={
                'name': 'Stripe',
                'vendor': 'Stripe Inc',
                'organization_slug': 'engineering',
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('slug', response.json()['detail'])

    def test_create_invalid_status(self) -> None:
        response = self.client.post(
            '/third-party-services/',
            json={
                'name': 'Stripe',
                'slug': 'stripe',
                'vendor': 'Stripe Inc',
                'organization_slug': 'engineering',
                'status': 'bogus',
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Invalid status', response.json()['detail'])

    def test_create_duplicate_slug(self) -> None:
        with mock.patch(
            'imbi_common.neo4j.run',
            side_effect=exceptions.ConstraintError(),
        ):
            response = self.client.post(
                '/third-party-services/',
                json={
                    'name': 'Stripe',
                    'slug': 'stripe',
                    'vendor': 'Stripe Inc',
                    'organization_slug': 'engineering',
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

    def test_create_org_not_found(self) -> None:
        result = _mock_neo4j_result([])
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.post(
                '/third-party-services/',
                json={
                    'name': 'Stripe',
                    'slug': 'stripe',
                    'vendor': 'Stripe Inc',
                    'organization_slug': 'nonexistent',
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_create_team_not_found(self) -> None:
        result = _mock_neo4j_result([])
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.post(
                '/third-party-services/',
                json={
                    'name': 'Stripe',
                    'slug': 'stripe',
                    'vendor': 'Stripe Inc',
                    'organization_slug': 'engineering',
                    'team_slug': 'nonexistent',
                },
            )

        self.assertEqual(response.status_code, 404)
        detail = response.json()['detail']
        self.assertIn('not found', detail)
        self.assertIn('team', detail)

    # -- List --

    def test_list_services(self) -> None:
        result = _mock_neo4j_result(
            [{'service': self.service_data}],
        )
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.get('/third-party-services/')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['slug'], 'stripe')

    def test_list_services_empty(self) -> None:
        result = _mock_neo4j_result([])
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.get('/third-party-services/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_deserializes_json_fields(self) -> None:
        svc = dict(self.service_data)
        svc['links'] = json.dumps({'docs': 'https://docs.stripe.com'})
        svc['identifiers'] = json.dumps({'account_id': 'acct_123'})

        result = _mock_neo4j_result([{'service': svc}])
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.get('/third-party-services/')

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
        result = _mock_neo4j_result(
            [{'service': self.service_data}],
        )
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.get(
                '/third-party-services/stripe',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'stripe')
        self.assertEqual(data['vendor'], 'Stripe Inc')

    def test_get_service_not_found(self) -> None:
        result = _mock_neo4j_result([])
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.get(
                '/third-party-services/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    # -- Update --

    def test_update_service(self) -> None:
        updated = dict(self.service_data)
        updated['description'] = 'Updated description'

        fetch_result = _mock_neo4j_result(
            [{'service': self.service_data}],
        )
        update_result = _mock_neo4j_result(
            [{'service': updated}],
        )

        with mock.patch(
            'imbi_common.neo4j.run',
            side_effect=[fetch_result, update_result],
        ):
            response = self.client.put(
                '/third-party-services/stripe',
                json={
                    'name': 'Stripe',
                    'vendor': 'Stripe Inc',
                    'description': 'Updated description',
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['description'],
            'Updated description',
        )

    def test_update_service_with_team(self) -> None:
        updated = dict(self.service_data)
        updated['team'] = {'name': 'Backend', 'slug': 'backend'}

        fetch_result = _mock_neo4j_result(
            [{'service': self.service_data}],
        )
        update_result = _mock_neo4j_result(
            [{'service': updated}],
        )

        with mock.patch(
            'imbi_common.neo4j.run',
            side_effect=[fetch_result, update_result],
        ):
            response = self.client.put(
                '/third-party-services/stripe',
                json={
                    'name': 'Stripe',
                    'vendor': 'Stripe Inc',
                    'team_slug': 'backend',
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['team']['slug'],
            'backend',
        )

    def test_update_defaults_slug_from_url(self) -> None:
        """Slug defaults to URL path slug when not in body."""
        fetch_result = _mock_neo4j_result(
            [{'service': self.service_data}],
        )
        update_result = _mock_neo4j_result(
            [{'service': self.service_data}],
        )

        with mock.patch(
            'imbi_common.neo4j.run',
            side_effect=[fetch_result, update_result],
        ) as mock_run:
            response = self.client.put(
                '/third-party-services/stripe',
                json={
                    'name': 'Stripe',
                    'vendor': 'Stripe Inc',
                },
            )

        self.assertEqual(response.status_code, 200)
        # The update call should include the slug in props
        update_call = mock_run.call_args_list[1]
        self.assertEqual(
            update_call.kwargs['props']['slug'],
            'stripe',
        )

    def test_update_service_not_found(self) -> None:
        result = _mock_neo4j_result([])
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.put(
                '/third-party-services/nonexistent',
                json={
                    'name': 'Stripe',
                    'vendor': 'Stripe Inc',
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_update_invalid_status(self) -> None:
        fetch_result = _mock_neo4j_result(
            [{'service': self.service_data}],
        )

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=fetch_result,
        ):
            response = self.client.put(
                '/third-party-services/stripe',
                json={
                    'name': 'Stripe',
                    'vendor': 'Stripe Inc',
                    'status': 'bogus',
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn('Invalid status', response.json()['detail'])

    def test_update_slug_conflict(self) -> None:
        fetch_result = _mock_neo4j_result(
            [{'service': self.service_data}],
        )

        with mock.patch(
            'imbi_common.neo4j.run',
            side_effect=[
                fetch_result,
                exceptions.ConstraintError(),
            ],
        ):
            response = self.client.put(
                '/third-party-services/stripe',
                json={
                    'name': 'Stripe',
                    'slug': 'existing-slug',
                    'vendor': 'Stripe Inc',
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

    def test_update_concurrent_delete(self) -> None:
        """Service deleted between fetch and update."""
        fetch_result = _mock_neo4j_result(
            [{'service': self.service_data}],
        )
        empty_result = _mock_neo4j_result([])

        with mock.patch(
            'imbi_common.neo4j.run',
            side_effect=[fetch_result, empty_result],
        ):
            response = self.client.put(
                '/third-party-services/stripe',
                json={
                    'name': 'Stripe Updated',
                    'vendor': 'Stripe Inc',
                },
            )

        self.assertEqual(response.status_code, 404)

    # -- Delete --

    def test_delete_service(self) -> None:
        result = _mock_neo4j_result([{'deleted': 1}])
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.delete(
                '/third-party-services/stripe',
            )

        self.assertEqual(response.status_code, 204)

    def test_delete_service_not_found(self) -> None:
        result = _mock_neo4j_result([{'deleted': 0}])
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.delete(
                '/third-party-services/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])


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
        result = _mock_neo4j_result(
            [{'app': self.app_data}],
        )
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.get(
                '/third-party-services/stripe/applications/',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['slug'], 'my-app')
        # Secrets should be masked
        self.assertEqual(
            data[0]['client_secret'],
            domain_models.SECRET_MASK,
        )
        self.assertEqual(
            data[0]['webhook_secret'],
            domain_models.SECRET_MASK,
        )

    def test_list_applications_empty(self) -> None:
        result = _mock_neo4j_result([])
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.get(
                '/third-party-services/stripe/applications/',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_applications_deserializes_json(self) -> None:
        app_data = dict(self.app_data)
        app_data['scopes'] = json.dumps(['read', 'write'])
        app_data['settings'] = json.dumps({'debug': True})

        result = _mock_neo4j_result([{'app': app_data}])
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.get(
                '/third-party-services/stripe/applications/',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()[0]
        self.assertEqual(data['scopes'], ['read', 'write'])
        self.assertEqual(data['settings'], {'debug': True})

    # -- Create application --

    def test_create_application(self) -> None:
        check_result = _mock_neo4j_result([{'cnt': 0}])
        create_result = _mock_neo4j_result(
            [{'app': self.app_data}],
        )

        with (
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[check_result, create_result],
            ),
            self._patch_encryption(),
        ):
            response = self.client.post(
                '/third-party-services/stripe/applications/',
                json=self.app_create_json,
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['slug'], 'my-app')
        self.assertEqual(
            data['client_secret'],
            domain_models.SECRET_MASK,
        )

    def test_create_application_duplicate(self) -> None:
        check_result = _mock_neo4j_result([{'cnt': 1}])

        with (
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=check_result,
            ),
            self._patch_encryption(),
        ):
            response = self.client.post(
                '/third-party-services/stripe/applications/',
                json=self.app_create_json,
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

    def test_create_application_service_not_found(self) -> None:
        check_result = _mock_neo4j_result([{'cnt': 0}])
        create_result = _mock_neo4j_result([])

        with (
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[check_result, create_result],
            ),
            self._patch_encryption(),
        ):
            response = self.client.post(
                '/third-party-services/nonexistent/applications/',
                json=self.app_create_json,
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_create_application_encrypts_secrets(self) -> None:
        check_result = _mock_neo4j_result([{'cnt': 0}])
        create_result = _mock_neo4j_result(
            [{'app': self.app_data}],
        )

        with (
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[check_result, create_result],
            ),
            self._patch_encryption(),
        ):
            response = self.client.post(
                '/third-party-services/stripe/applications/',
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

        check_result = _mock_neo4j_result([{'cnt': 0}])

        app_data = dict(self.app_data)
        app_data['private_key'] = 'enc:pk-data'
        app_data['signing_secret'] = 'enc:sig-data'
        create_result = _mock_neo4j_result(
            [{'app': app_data}],
        )

        with (
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[check_result, create_result],
            ),
            self._patch_encryption(),
        ):
            response = self.client.post(
                '/third-party-services/stripe/applications/',
                json=payload,
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        # All secrets should be masked in response
        self.assertEqual(
            data['client_secret'],
            domain_models.SECRET_MASK,
        )
        self.assertEqual(
            data['private_key'],
            domain_models.SECRET_MASK,
        )
        self.assertEqual(
            data['signing_secret'],
            domain_models.SECRET_MASK,
        )

    # -- Get application --

    def test_get_application(self) -> None:
        result = _mock_neo4j_result(
            [{'app': self.app_data}],
        )
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.get(
                '/third-party-services/stripe/applications/my-app',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'my-app')
        self.assertEqual(
            data['client_secret'],
            domain_models.SECRET_MASK,
        )

    def test_get_application_not_found(self) -> None:
        result = _mock_neo4j_result([])
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.get(
                '/third-party-services/stripe/applications/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_get_application_reveal_secrets_admin(self) -> None:
        app_data = dict(self.app_data)
        app_data['client_secret'] = 'enc:real-secret'
        app_data['webhook_secret'] = 'enc:real-webhook'

        result = _mock_neo4j_result([{'app': app_data}])
        with (
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=result,
            ),
            self._patch_encryption(),
        ):
            response = self.client.get(
                '/third-party-services/stripe'
                '/applications/my-app'
                '?reveal_secrets=true',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['client_secret'], 'real-secret')
        self.assertEqual(data['webhook_secret'], 'real-webhook')

    def test_get_application_reveal_secrets_non_admin(self) -> None:
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

        response = self.client.get(
            '/third-party-services/stripe'
            '/applications/my-app'
            '?reveal_secrets=true',
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn('Admin', response.json()['detail'])

    # -- Update application --

    def test_update_application(self) -> None:
        fetch_result = _mock_neo4j_result(
            [{'app': self.app_data}],
        )
        updated_app = dict(self.app_data)
        updated_app['name'] = 'Updated App'
        update_result = _mock_neo4j_result(
            [{'app': updated_app}],
        )

        with (
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[fetch_result, update_result],
            ),
            self._patch_encryption(),
        ):
            payload = dict(self.app_create_json)
            payload['name'] = 'Updated App'
            response = self.client.put(
                '/third-party-services/stripe/applications/my-app',
                json=payload,
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name'], 'Updated App')
        self.assertEqual(
            data['client_secret'],
            domain_models.SECRET_MASK,
        )

    def test_update_application_masked_secret_preserved(
        self,
    ) -> None:
        """Sending SECRET_MASK preserves existing encrypted value."""
        fetch_result = _mock_neo4j_result(
            [{'app': self.app_data}],
        )
        update_result = _mock_neo4j_result(
            [{'app': self.app_data}],
        )

        with (
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[fetch_result, update_result],
            ) as mock_run,
            self._patch_encryption(),
        ):
            payload = dict(self.app_create_json)
            payload['client_secret'] = domain_models.SECRET_MASK
            payload['webhook_secret'] = domain_models.SECRET_MASK
            response = self.client.put(
                '/third-party-services/stripe/applications/my-app',
                json=payload,
            )

        self.assertEqual(response.status_code, 200)
        # Verify existing encrypted values were kept
        update_call = mock_run.call_args_list[1]
        props = update_call.kwargs['props']
        self.assertEqual(
            props['client_secret'],
            self.app_data['client_secret'],
        )
        self.assertEqual(
            props['webhook_secret'],
            self.app_data['webhook_secret'],
        )

    def test_update_application_not_found(self) -> None:
        result = _mock_neo4j_result([])
        with (
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=result,
            ),
            self._patch_encryption(),
        ):
            response = self.client.put(
                '/third-party-services/stripe/applications/nonexistent',
                json=self.app_create_json,
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_update_application_concurrent_delete(self) -> None:
        """App deleted between fetch and update."""
        fetch_result = _mock_neo4j_result(
            [{'app': self.app_data}],
        )
        empty_result = _mock_neo4j_result([])

        with (
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[fetch_result, empty_result],
            ),
            self._patch_encryption(),
        ):
            response = self.client.put(
                '/third-party-services/stripe/applications/my-app',
                json=self.app_create_json,
            )

        self.assertEqual(response.status_code, 404)

    # -- Delete application --

    def test_delete_application(self) -> None:
        result = _mock_neo4j_result([{'deleted': 1}])
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.delete(
                '/third-party-services/stripe/applications/my-app',
            )

        self.assertEqual(response.status_code, 204)

    def test_delete_application_not_found(self) -> None:
        result = _mock_neo4j_result([{'deleted': 0}])
        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=result,
        ):
            response = self.client.delete(
                '/third-party-services/stripe/applications/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])
