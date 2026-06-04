"""Tests for service plugin CRUD endpoints."""

import datetime
import json
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common import graph

from imbi_api import models
from imbi_api.auth import password, permissions
from tests import support


class ServicePluginsEndpointTestCase(support.SharedAppTestCase):
    def setUp(self) -> None:
        self.test_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,
            password_hash=password.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.test_user,
            session_id='test-session',
            auth_method='jwt',
            permissions={
                'third_party_service:read',
                'third_party_service:update',
            },
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)

        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

    def test_list_plugins_empty(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_api.endpoints.service_plugins.list_plugins',
            return_value=[],
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/third-party-services/github/plugins/'
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_plugins_with_results(self) -> None:
        plugin_raw = json.dumps(
            {
                'id': 'abc123',
                'plugin_slug': 'ssm',
                'label': 'SSM Config',
                'options': '{}',
                'api_version': 1,
            }
        )
        svc_raw = json.dumps({'slug': 'github'})
        self.mock_db.execute.return_value = [
            {
                'plugin': plugin_raw,
                'svc': svc_raw,
            }
        ]
        with mock.patch(
            'imbi_api.endpoints.service_plugins.list_plugins',
            return_value=[],
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/third-party-services/github/plugins/'
                )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['plugin_slug'], 'ssm')
        self.assertEqual(data[0]['status'], 'unavailable')

    def test_create_plugin_slug_not_installed(self) -> None:
        from imbi_common.plugins.errors import PluginNotFoundError

        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_api.endpoints.service_plugins.get_plugin',
            side_effect=PluginNotFoundError('ssm'),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.post(
                    '/organizations/myorg/'
                    'third-party-services/github/plugins/',
                    json={
                        'plugin_slug': 'ssm',
                        'label': 'My SSM',
                        'options': {},
                    },
                )
        self.assertEqual(response.status_code, 400)

    def test_delete_plugin_conflict(self) -> None:
        self.mock_db.execute.return_value = [{'cnt': '2'}]
        with testclient.TestClient(self.test_app) as client:
            response = client.delete(
                '/organizations/myorg/'
                'third-party-services/github/plugins/abc123'
            )
        self.assertEqual(response.status_code, 409)

    def test_delete_plugin_not_found(self) -> None:
        self.mock_db.execute.return_value = [{'cnt': '0'}]

        def _side_effect(*args: object, **kwargs: object) -> list[dict]:
            call_count = self.mock_db.execute.call_count
            if call_count == 1:
                return [{'cnt': '0'}]
            return [{'deleted': '0'}]

        self.mock_db.execute.side_effect = _side_effect
        with testclient.TestClient(self.test_app) as client:
            response = client.delete(
                '/organizations/myorg/'
                'third-party-services/github/plugins/abc123'
            )
        self.assertEqual(response.status_code, 404)

    def test_list_plugins_active_status(self) -> None:
        from imbi_common.plugins.base import (
            ConfigurationPlugin,
            PluginManifest,
        )
        from imbi_common.plugins.registry import RegistryEntry

        class _Fake(ConfigurationPlugin):
            manifest = PluginManifest(
                slug='ssm', name='SSM', plugin_type='configuration'
            )

            async def list_keys(self, ctx, credentials):  # type: ignore[override]
                return []

            async def get_values(self, ctx, credentials, keys=None):  # type: ignore[override]
                return []

            async def set_value(self, ctx, credentials, key, value):  # type: ignore[override]
                raise NotImplementedError

            async def delete_key(self, ctx, credentials, key):  # type: ignore[override]
                return None

        entry = RegistryEntry(
            handler_cls=_Fake,
            manifest=_Fake.manifest,
            package_name='imbi-plugin-ssm',
            package_version='1.0.0',
        )
        plugin_raw = json.dumps(
            {
                'id': 'abc123',
                'plugin_slug': 'ssm',
                'label': 'SSM',
                'options': '{}',
                'api_version': 1,
            }
        )
        svc_raw = json.dumps({'slug': 'github'})
        self.mock_db.execute.return_value = [
            {'plugin': plugin_raw, 'svc': svc_raw}
        ]
        with mock.patch(
            'imbi_api.endpoints.service_plugins.list_plugins',
            return_value=[entry],
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/third-party-services/github/plugins/'
                )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data[0]['status'], 'active')

    def test_create_plugin_duplicate_label_returns_409(self) -> None:
        from imbi_common.plugins.base import (
            ConfigurationPlugin,
            PluginManifest,
        )
        from imbi_common.plugins.registry import RegistryEntry

        class _Fake(ConfigurationPlugin):
            manifest = PluginManifest(
                slug='ssm', name='SSM', plugin_type='configuration'
            )

            async def list_keys(self, ctx, credentials):  # type: ignore[override]
                return []

            async def get_values(self, ctx, credentials, keys=None):  # type: ignore[override]
                return []

            async def set_value(self, ctx, credentials, key, value):  # type: ignore[override]
                raise NotImplementedError

            async def delete_key(self, ctx, credentials, key):  # type: ignore[override]
                return None

        entry = RegistryEntry(
            handler_cls=_Fake,
            manifest=_Fake.manifest,
            package_name='imbi-plugin-ssm',
            package_version='1.0.0',
        )
        self.mock_db.execute.return_value = [{'cnt': '1'}]
        with mock.patch(
            'imbi_api.endpoints.service_plugins.get_plugin',
            return_value=entry,
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.post(
                    '/organizations/myorg/'
                    'third-party-services/github/plugins/',
                    json={
                        'plugin_slug': 'ssm',
                        'label': 'My SSM',
                        'options': {},
                    },
                )
        self.assertEqual(response.status_code, 409)

    def test_create_plugin_success(self) -> None:
        from imbi_common.plugins.base import (
            ConfigurationPlugin,
            PluginManifest,
        )
        from imbi_common.plugins.registry import RegistryEntry

        class _Fake(ConfigurationPlugin):
            manifest = PluginManifest(
                slug='ssm', name='SSM', plugin_type='configuration'
            )

            async def list_keys(self, ctx, credentials):  # type: ignore[override]
                return []

            async def get_values(self, ctx, credentials, keys=None):  # type: ignore[override]
                return []

            async def set_value(self, ctx, credentials, key, value):  # type: ignore[override]
                raise NotImplementedError

            async def delete_key(self, ctx, credentials, key):  # type: ignore[override]
                return None

        entry = RegistryEntry(
            handler_cls=_Fake,
            manifest=_Fake.manifest,
            package_name='imbi-plugin-ssm',
            package_version='1.0.0',
        )
        plugin_raw = json.dumps(
            {
                'id': 'newid',
                'plugin_slug': 'ssm',
                'label': 'My SSM',
                'options': '{}',
                'api_version': 1,
            }
        )
        svc_raw = json.dumps({'slug': 'github'})
        responses = [
            [{'cnt': '0'}],
            [{'plugin': plugin_raw, 'svc': svc_raw}],
        ]

        def _exec(*_a: object, **_k: object) -> list[dict]:
            return responses.pop(0)

        self.mock_db.execute.side_effect = _exec
        with (
            mock.patch(
                'imbi_api.endpoints.service_plugins.get_plugin',
                return_value=entry,
            ),
            mock.patch(
                'imbi_api.endpoints.service_plugins.list_plugins',
                return_value=[entry],
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.post(
                    '/organizations/myorg/'
                    'third-party-services/github/plugins/',
                    json={
                        'plugin_slug': 'ssm',
                        'label': 'My SSM',
                        'options': {},
                    },
                )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['id'], 'newid')

    def test_create_plugin_service_not_found(self) -> None:
        from imbi_common.plugins.base import (
            ConfigurationPlugin,
            PluginManifest,
        )
        from imbi_common.plugins.registry import RegistryEntry

        class _Fake(ConfigurationPlugin):
            manifest = PluginManifest(
                slug='ssm', name='SSM', plugin_type='configuration'
            )

            async def list_keys(self, ctx, credentials):  # type: ignore[override]
                return []

            async def get_values(self, ctx, credentials, keys=None):  # type: ignore[override]
                return []

            async def set_value(self, ctx, credentials, key, value):  # type: ignore[override]
                raise NotImplementedError

            async def delete_key(self, ctx, credentials, key):  # type: ignore[override]
                return None

        entry = RegistryEntry(
            handler_cls=_Fake,
            manifest=_Fake.manifest,
            package_name='imbi-plugin-ssm',
            package_version='1.0.0',
        )
        responses = [[{'cnt': '0'}], []]

        def _exec(*_a: object, **_k: object) -> list[dict]:
            return responses.pop(0)

        self.mock_db.execute.side_effect = _exec
        with mock.patch(
            'imbi_api.endpoints.service_plugins.get_plugin',
            return_value=entry,
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.post(
                    '/organizations/myorg/'
                    'third-party-services/github/plugins/',
                    json={
                        'plugin_slug': 'ssm',
                        'label': 'My SSM',
                        'options': {},
                    },
                )
        self.assertEqual(response.status_code, 404)

    def test_update_plugin_success(self) -> None:
        plugin_raw = json.dumps(
            {
                'id': 'abc123',
                'plugin_slug': 'ssm',
                'label': 'New Label',
                'options': '{}',
                'api_version': 1,
            }
        )
        svc_raw = json.dumps({'slug': 'github'})
        # PUT runs dup-label check, the update, then a final read that
        # includes the OPTIONAL MATCH for the linked ServiceApplication.
        self.mock_db.execute.side_effect = [
            [{'cnt': '0'}],  # dup-label check
            [{'plugin': plugin_raw, 'svc': svc_raw}],  # update
            [{'plugin': plugin_raw, 'svc': svc_raw, 'app': None}],  # re-read
        ]
        with mock.patch(
            'imbi_api.endpoints.service_plugins.list_plugins',
            return_value=[],
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.put(
                    '/organizations/myorg/'
                    'third-party-services/github/plugins/abc123',
                    json={'label': 'New Label', 'options': {}},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['label'], 'New Label')

    def test_update_plugin_not_found(self) -> None:
        # dup-label check returns 0, then update returns empty.
        self.mock_db.execute.side_effect = [[{'cnt': '0'}], []]
        with testclient.TestClient(self.test_app) as client:
            response = client.put(
                '/organizations/myorg/'
                'third-party-services/github/plugins/abc123',
                json={'label': 'New Label', 'options': {}},
            )
        self.assertEqual(response.status_code, 404)

    def test_update_plugin_used_as_login_requires_capable_manifest(
        self,
    ) -> None:
        """used_as_login=true is rejected when manifest.login_capable=false."""
        from imbi_common.plugins.base import (
            ConfigurationPlugin,
            PluginManifest,
        )
        from imbi_common.plugins.registry import RegistryEntry

        class _Fake(ConfigurationPlugin):
            manifest = PluginManifest(
                slug='ssm',
                name='SSM',
                plugin_type='configuration',
                login_capable=False,
            )

            async def list_keys(self, ctx, credentials):  # type: ignore[override]
                return []

            async def get_values(self, ctx, credentials, keys=None):  # type: ignore[override]
                return []

            async def set_value(self, ctx, credentials, key, value):  # type: ignore[override]
                raise NotImplementedError

            async def delete_key(self, ctx, credentials, key):  # type: ignore[override]
                return None

        entry = RegistryEntry(
            handler_cls=_Fake,
            manifest=_Fake.manifest,
            package_name='imbi-plugin-ssm',
            package_version='1.0.0',
        )
        # dup-label check (string '0'), then slug lookup
        self.mock_db.execute.side_effect = [
            [{'cnt': '0'}],
            [{'slug': '"ssm"'}],
        ]
        with mock.patch(
            'imbi_api.endpoints.service_plugins.get_plugin',
            return_value=entry,
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.put(
                    '/organizations/myorg/'
                    'third-party-services/github/plugins/abc123',
                    json={
                        'label': 'New Label',
                        'options': {},
                        'used_as_login': True,
                    },
                )
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'cannot be used as a login provider',
            response.json()['detail'],
        )

    def test_update_plugin_used_as_login_succeeds_when_capable(self) -> None:
        """used_as_login=true is accepted when manifest.login_capable=true."""
        from imbi_common.plugins.base import (
            IdentityCredentials,
            IdentityPlugin,
            IdentityProfile,
            PluginManifest,
        )
        from imbi_common.plugins.registry import RegistryEntry

        class _IdFake(IdentityPlugin):
            manifest = PluginManifest(
                slug='okta',
                name='Okta',
                plugin_type='identity',
                login_capable=True,
            )

            async def authorization_request(  # type: ignore[override]
                self, ctx, credentials, redirect_uri, scopes
            ):
                raise NotImplementedError

            async def exchange_code(  # type: ignore[override]
                self, ctx, credentials, code, redirect_uri, code_verifier
            ) -> tuple[IdentityProfile, IdentityCredentials]:
                raise NotImplementedError

            async def refresh(  # type: ignore[override]
                self, ctx, credentials, refresh_token
            ) -> IdentityCredentials:
                raise NotImplementedError

            async def revoke(  # type: ignore[override]
                self, ctx, credentials, access_token
            ) -> None:
                return None

        entry = RegistryEntry(
            handler_cls=_IdFake,
            manifest=_IdFake.manifest,
            package_name='imbi-plugin-okta',
            package_version='1.0.0',
        )
        plugin_raw = json.dumps(
            {
                'id': 'abc123',
                'plugin_slug': 'okta',
                'label': 'Okta Login',
                'options': '{}',
                'api_version': 1,
                'used_as_login': True,
                'login_capable': True,
            }
        )
        svc_raw = json.dumps({'slug': 'github'})
        # dup-label check, slug lookup, update, final OPTIONAL-MATCH read.
        self.mock_db.execute.side_effect = [
            [{'cnt': '0'}],
            [{'slug': '"okta"'}],
            [{'plugin': plugin_raw, 'svc': svc_raw}],
            [{'plugin': plugin_raw, 'svc': svc_raw, 'app': None}],
        ]
        with (
            mock.patch(
                'imbi_api.endpoints.service_plugins.get_plugin',
                return_value=entry,
            ),
            mock.patch(
                'imbi_api.endpoints.service_plugins.list_plugins',
                return_value=[entry],
            ),
            mock.patch(
                'imbi_api.auth.login_providers.invalidate_cache'
            ) as invalidate_mock,
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.put(
                    '/organizations/myorg/'
                    'third-party-services/github/plugins/abc123',
                    json={
                        'label': 'Okta Login',
                        'options': {},
                        'used_as_login': True,
                    },
                )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['used_as_login'])
        invalidate_mock.assert_called_once()

    def test_update_plugin_used_as_login_plugin_not_found(self) -> None:
        """used_as_login=true rejects when registry has no entry."""
        from imbi_common.plugins.errors import PluginNotFoundError

        # dup-label check, slug lookup
        self.mock_db.execute.side_effect = [
            [{'cnt': '0'}],
            [{'slug': '"missing"'}],
        ]
        with mock.patch(
            'imbi_api.endpoints.service_plugins.get_plugin',
            side_effect=PluginNotFoundError('missing'),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.put(
                    '/organizations/myorg/'
                    'third-party-services/github/plugins/abc123',
                    json={
                        'label': 'L',
                        'options': {},
                        'used_as_login': True,
                    },
                )
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'not loaded in the registry',
            response.json()['detail'],
        )

    def test_update_plugin_connects_users_to_invalidates_cache(self) -> None:
        """Setting connects_users_to busts the login-providers cache."""
        plugin_raw = json.dumps(
            {
                'id': 'abc123',
                'plugin_slug': 'okta',
                'label': 'Okta Login',
                'options': '{}',
                'api_version': 1,
                'connects_users_to': 'aweber.com',
            }
        )
        svc_raw = json.dumps({'slug': 'github'})
        self.mock_db.execute.side_effect = [
            [{'cnt': '0'}],
            [{'plugin': plugin_raw, 'svc': svc_raw}],
            [{'plugin': plugin_raw, 'svc': svc_raw, 'app': None}],
        ]
        with (
            mock.patch(
                'imbi_api.endpoints.service_plugins.list_plugins',
                return_value=[],
            ),
            mock.patch(
                'imbi_api.auth.login_providers.invalidate_cache'
            ) as invalidate_mock,
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.put(
                    '/organizations/myorg/'
                    'third-party-services/github/plugins/abc123',
                    json={
                        'label': 'Okta Login',
                        'options': {},
                        'connects_users_to': 'aweber.com',
                    },
                )
        self.assertEqual(response.status_code, 200)
        invalidate_mock.assert_called_once()

    def test_delete_plugin_force_skips_ref_check(self) -> None:
        # When force=true, only the delete query runs (no ref check).
        self.mock_db.execute.return_value = [{'deleted': '1'}]
        with testclient.TestClient(self.test_app) as client:
            response = client.delete(
                '/organizations/myorg/'
                'third-party-services/github/plugins/abc123?force=true'
            )
        self.assertEqual(response.status_code, 204)

    def test_delete_plugin_success(self) -> None:
        responses = [
            [{'cnt': '0'}],
            [{'deleted': '1'}],
        ]

        def _exec(*_a: object, **_k: object) -> list[dict]:
            return responses.pop(0)

        self.mock_db.execute.side_effect = _exec
        with testclient.TestClient(self.test_app) as client:
            response = client.delete(
                '/organizations/myorg/'
                'third-party-services/github/plugins/abc123'
            )
        self.assertEqual(response.status_code, 204)

    def _make_oauth2_entry(self):  # type: ignore[no-untyped-def]
        from imbi_common.plugins.base import (
            IdentityCredentials,
            IdentityPlugin,
            IdentityProfile,
            PluginManifest,
        )
        from imbi_common.plugins.registry import RegistryEntry

        class _GHFake(IdentityPlugin):
            manifest = PluginManifest(
                slug='github-oauth2',
                name='GitHub OAuth2',
                plugin_type='identity',
                auth_type='oauth2',
            )

            async def authorization_request(  # type: ignore[override]
                self, ctx, credentials, redirect_uri, scopes
            ):
                raise NotImplementedError

            async def exchange_code(  # type: ignore[override]
                self, ctx, credentials, code, redirect_uri, code_verifier
            ) -> tuple[IdentityProfile, IdentityCredentials]:
                raise NotImplementedError

            async def refresh(  # type: ignore[override]
                self, ctx, credentials, refresh_token
            ) -> IdentityCredentials:
                raise NotImplementedError

            async def revoke(  # type: ignore[override]
                self, ctx, credentials, access_token
            ) -> None:
                return None

        return RegistryEntry(
            handler_cls=_GHFake,
            manifest=_GHFake.manifest,
            package_name='imbi-plugin-github',
            package_version='1.0.0',
        )

    def _make_api_token_entry(self):  # type: ignore[no-untyped-def]
        from imbi_common.plugins.base import (
            ConfigurationPlugin,
            PluginManifest,
        )
        from imbi_common.plugins.registry import RegistryEntry

        class _Fake(ConfigurationPlugin):
            manifest = PluginManifest(
                slug='ssm', name='SSM', plugin_type='configuration'
            )

            async def list_keys(self, ctx, credentials):  # type: ignore[override]
                return []

            async def get_values(self, ctx, credentials, keys=None):  # type: ignore[override]
                return []

            async def set_value(self, ctx, credentials, key, value):  # type: ignore[override]
                raise NotImplementedError

            async def delete_key(self, ctx, credentials, key):  # type: ignore[override]
                return None

        return RegistryEntry(
            handler_cls=_Fake,
            manifest=_Fake.manifest,
            package_name='imbi-plugin-ssm',
            package_version='1.0.0',
        )

    def test_create_plugin_with_application_slug_success(self) -> None:
        entry = self._make_oauth2_entry()
        plugin_raw = json.dumps(
            {
                'id': 'newid',
                'plugin_slug': 'github-oauth2',
                'label': 'GitHub OAuth2',
                'options': '{}',
                'api_version': 1,
            }
        )
        svc_raw = json.dumps({'slug': 'github'})
        app_raw = json.dumps(
            {'slug': 'gh-oauth-app', 'name': 'GitHub OAuth App'}
        )
        responses = [
            [{'cnt': '0'}],  # dup-label
            [{'plugin': plugin_raw, 'svc': svc_raw, 'app': app_raw}],
        ]

        def _exec(*_a: object, **_k: object) -> list[dict]:
            return responses.pop(0)

        self.mock_db.execute.side_effect = _exec
        with (
            mock.patch(
                'imbi_api.endpoints.service_plugins.get_plugin',
                return_value=entry,
            ),
            mock.patch(
                'imbi_api.endpoints.service_plugins.list_plugins',
                return_value=[entry],
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.post(
                    '/organizations/myorg/'
                    'third-party-services/github/plugins/',
                    json={
                        'plugin_slug': 'github-oauth2',
                        'label': 'GitHub OAuth2',
                        'options': {},
                        'service_application_slug': 'gh-oauth-app',
                    },
                )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['application_slug'], 'gh-oauth-app')
        self.assertEqual(body['application_name'], 'GitHub OAuth App')

    def test_create_plugin_application_slug_rejected_for_api_token(
        self,
    ) -> None:
        entry = self._make_api_token_entry()
        # The pre-flight dup-label check still runs before the auth_type
        # rejection — supply the count even though the rejection comes
        # next.
        self.mock_db.execute.side_effect = [[{'cnt': '0'}]]
        with (
            mock.patch(
                'imbi_api.endpoints.service_plugins.get_plugin',
                return_value=entry,
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.post(
                    '/organizations/myorg/'
                    'third-party-services/github/plugins/',
                    json={
                        'plugin_slug': 'ssm',
                        'label': 'SSM',
                        'options': {},
                        'service_application_slug': 'something',
                    },
                )
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "auth_type='api_token'",
            response.json()['detail'],
        )

    def test_create_plugin_app_not_in_service_returns_400(self) -> None:
        entry = self._make_oauth2_entry()
        # dup-label=0, create returns nothing (no app match), svc-check
        # confirms the service exists.
        responses = [
            [{'cnt': '0'}],
            [],
            [{'cnt': '1'}],
        ]

        def _exec(*_a: object, **_k: object) -> list[dict]:
            return responses.pop(0)

        self.mock_db.execute.side_effect = _exec
        with mock.patch(
            'imbi_api.endpoints.service_plugins.get_plugin',
            return_value=entry,
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.post(
                    '/organizations/myorg/'
                    'third-party-services/github/plugins/',
                    json={
                        'plugin_slug': 'github-oauth2',
                        'label': 'GitHub OAuth2',
                        'options': {},
                        'service_application_slug': 'wrong-app',
                    },
                )
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'not registered to service',
            response.json()['detail'],
        )

    def test_update_plugin_sets_application_link(self) -> None:
        plugin_raw = json.dumps(
            {
                'id': 'abc123',
                'plugin_slug': 'github-oauth2',
                'label': 'L',
                'options': '{}',
                'api_version': 1,
            }
        )
        svc_raw = json.dumps({'slug': 'github'})
        app_raw = json.dumps(
            {'slug': 'gh-oauth-app', 'name': 'GitHub OAuth App'}
        )
        # dup-label, SET update, link delete, link create, final read.
        self.mock_db.execute.side_effect = [
            [{'cnt': '0'}],
            [{'plugin': plugin_raw, 'svc': svc_raw}],
            [],
            [{'slug': '"gh-oauth-app"'}],
            [{'plugin': plugin_raw, 'svc': svc_raw, 'app': app_raw}],
        ]
        with mock.patch(
            'imbi_api.endpoints.service_plugins.list_plugins',
            return_value=[],
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.put(
                    '/organizations/myorg/'
                    'third-party-services/github/plugins/abc123',
                    json={
                        'label': 'L',
                        'options': {},
                        'service_application_slug': 'gh-oauth-app',
                    },
                )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['application_slug'], 'gh-oauth-app')

    def test_update_plugin_clears_application_link(self) -> None:
        plugin_raw = json.dumps(
            {
                'id': 'abc123',
                'plugin_slug': 'github-oauth2',
                'label': 'L',
                'options': '{}',
                'api_version': 1,
            }
        )
        svc_raw = json.dumps({'slug': 'github'})
        # Update path with explicit ``null`` in the body: dup-label,
        # SET update, link delete (no create), final read.
        self.mock_db.execute.side_effect = [
            [{'cnt': '0'}],
            [{'plugin': plugin_raw, 'svc': svc_raw}],
            [],
            [{'plugin': plugin_raw, 'svc': svc_raw, 'app': None}],
        ]
        with mock.patch(
            'imbi_api.endpoints.service_plugins.list_plugins',
            return_value=[],
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.put(
                    '/organizations/myorg/'
                    'third-party-services/github/plugins/abc123',
                    json={
                        'label': 'L',
                        'options': {},
                        'service_application_slug': None,
                    },
                )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['application_slug'])

    def test_update_plugin_application_slug_rejects_wrong_service(
        self,
    ) -> None:
        plugin_raw = json.dumps(
            {
                'id': 'abc123',
                'plugin_slug': 'github-oauth2',
                'label': 'L',
                'options': '{}',
                'api_version': 1,
            }
        )
        svc_raw = json.dumps({'slug': 'github'})
        # dup-label, SET update, link delete, link create returns []
        self.mock_db.execute.side_effect = [
            [{'cnt': '0'}],
            [{'plugin': plugin_raw, 'svc': svc_raw}],
            [],
            [],
        ]
        with mock.patch(
            'imbi_api.endpoints.service_plugins.list_plugins',
            return_value=[],
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.put(
                    '/organizations/myorg/'
                    'third-party-services/github/plugins/abc123',
                    json={
                        'label': 'L',
                        'options': {},
                        'service_application_slug': 'foreign-app',
                    },
                )
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'not registered to service',
            response.json()['detail'],
        )


class ReplacePluginAssignmentsTestCase(support.SharedAppTestCase):
    """Tests for ``PUT /{plugin_id}/assignments`` (fused replace)."""

    BASE = (
        '/organizations/myorg/third-party-services/github/plugins/'
        'abc123/assignments'
    )

    def setUp(self) -> None:
        self.test_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,
            password_hash=password.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.test_user,
            session_id='test-session',
            auth_method='jwt',
            permissions={
                'third_party_service:read',
                'third_party_service:update',
            },
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

    @staticmethod
    def _entry() -> object:
        from imbi_common.plugins.base import (
            ConfigurationPlugin,
            PluginManifest,
        )
        from imbi_common.plugins.registry import RegistryEntry

        class _Fake(ConfigurationPlugin):
            manifest = PluginManifest(
                slug='ssm', name='SSM', plugin_type='configuration'
            )

            async def list_keys(self, ctx, credentials):  # type: ignore[override]
                return []

            async def get_values(self, ctx, credentials, keys=None):  # type: ignore[override]
                return []

            async def set_value(self, ctx, credentials, key, value):  # type: ignore[override]
                raise NotImplementedError

            async def delete_key(self, ctx, credentials, key):  # type: ignore[override]
                return None

        return RegistryEntry(
            handler_cls=_Fake,
            manifest=_Fake.manifest,
            package_name='imbi-plugin-ssm',
            package_version='1.0.0',
        )

    def _fused_call(self) -> tuple[str, dict[str, object]]:
        """Return (query, params) of the single columns=[] write call."""
        calls = [
            c
            for c in self.mock_db.execute.call_args_list
            if len(c.args) >= 3 and c.args[2] == []
        ]
        self.assertEqual(len(calls), 1)
        return calls[0].args[0], calls[0].args[1]

    def test_replace_emits_single_fused_write(self) -> None:
        # _ensure -> slug, validate pt -> found, fused write -> [], list -> []
        self.mock_db.execute.side_effect = [
            [{'slug': 'ssm'}],
            [{'found': 1}],
            [],
            [],
        ]
        with mock.patch(
            'imbi_api.endpoints.service_plugins.get_plugin',
            return_value=self._entry(),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.put(
                    self.BASE,
                    json=[
                        {
                            'project_type_slug': 'web',
                            'plugin_type': 'configuration',
                            'default': True,
                            'options': {'k': 'v'},
                        }
                    ],
                )
        self.assertEqual(response.status_code, 200)
        query, params = self._fused_call()
        self.assertIn('UNWIND', query)
        self.assertIn('DELETE old', query)
        # Collapsed before the UNWIND so K prior edges can't multiply.
        self.assertIn('count(old)', query)
        # Default-demotion runs after the CREATEs.
        self.assertIn('SET sibling.default = false', query)
        self.assertEqual(params['asgn_0_pt'], 'web')
        self.assertEqual(params['asgn_0_options'], json.dumps({'k': 'v'}))

    def test_replace_empty_body_is_delete_only(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'slug': 'ssm'}],
            [],
            [],
        ]
        with mock.patch(
            'imbi_api.endpoints.service_plugins.get_plugin',
            return_value=self._entry(),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.put(self.BASE, json=[])
        self.assertEqual(response.status_code, 200)
        query, _ = self._fused_call()
        self.assertIn('DELETE old', query)
        self.assertNotIn('UNWIND', query)

    def test_replace_rejects_plugin_type_mismatch(self) -> None:
        self.mock_db.execute.side_effect = [[{'slug': 'ssm'}]]
        with mock.patch(
            'imbi_api.endpoints.service_plugins.get_plugin',
            return_value=self._entry(),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.put(
                    self.BASE,
                    json=[
                        {
                            'project_type_slug': 'web',
                            'plugin_type': 'logs',
                            'default': True,
                            'options': {},
                        }
                    ],
                )
        self.assertEqual(response.status_code, 400)

    def test_replace_rejects_duplicate_pt_plugin_type(self) -> None:
        self.mock_db.execute.side_effect = [[{'slug': 'ssm'}]]
        row = {
            'project_type_slug': 'web',
            'plugin_type': 'configuration',
            'default': True,
            'options': {},
        }
        with mock.patch(
            'imbi_api.endpoints.service_plugins.get_plugin',
            return_value=self._entry(),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.put(self.BASE, json=[row, dict(row)])
        self.assertEqual(response.status_code, 400)
        self.assertIn('Duplicate', response.json()['detail'])

    def test_replace_rejects_invalid_project_type(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'slug': 'ssm'}],
            [{'found': 0}],
        ]
        with mock.patch(
            'imbi_api.endpoints.service_plugins.get_plugin',
            return_value=self._entry(),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.put(
                    self.BASE,
                    json=[
                        {
                            'project_type_slug': 'nope',
                            'plugin_type': 'configuration',
                            'default': True,
                            'options': {},
                        }
                    ],
                )
        self.assertEqual(response.status_code, 404)


class AssignmentRowsTemplateTestCase(unittest.TestCase):
    def test_template_serializes_and_collapses(self) -> None:
        from imbi_api.endpoints.service_plugins import (
            _assignment_rows_template,
            _AssignmentInput,
        )

        a = _AssignmentInput(
            project_type_slug='web',
            plugin_type='configuration',
            default=True,
            options={'k': 'v'},
            identity_plugin_id='',
        )
        tpl, params = _assignment_rows_template([a])
        self.assertIn('{asgn_0_pt}', tpl)
        self.assertEqual(params['asgn_0_pt'], 'web')
        self.assertEqual(params['asgn_0_ptype'], 'configuration')
        self.assertEqual(params['asgn_0_options'], json.dumps({'k': 'v'}))
        # Empty identity_plugin_id collapses to null.
        self.assertIsNone(params['asgn_0_idp'])

    def test_input_accepts_webhook_and_analysis_plugin_types(self) -> None:
        # Regression: the assignment body previously hard-coded a tab
        # Literal of {configuration, logs, deployment, lifecycle}, so a
        # webhook (or analysis) plugin assignment was rejected with 422
        # before ever reaching the manifest plugin_type check. The field
        # now uses imbi_common's PluginType, covering every plugin type.
        from imbi_api.endpoints.service_plugins import _AssignmentInput

        for plugin_type in ('webhook', 'analysis'):
            a = _AssignmentInput(
                project_type_slug='web',
                plugin_type=plugin_type,
                default=True,
                options={},
            )
            self.assertEqual(a.plugin_type, plugin_type)
