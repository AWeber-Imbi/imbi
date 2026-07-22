"""Tests for the Integration management endpoints."""

import datetime
import typing
from unittest import mock

import psycopg
from fastapi import testclient

from imbi.api import models
from imbi.api.auth import password, permissions
from imbi.common import graph
from imbi.common.plugins.base import (
    Capability,
    ConfigurationCapability,
    IdentityCapability,
    LogsCapability,
    Plugin,
    PluginManifest,
)
from imbi.common.plugins.errors import PluginNotFoundError
from imbi.common.plugins.registry import RegistryEntry
from tests.api import support


class _FakeLogs(LogsCapability):
    pass


class _FakeConfig(ConfigurationCapability):
    pass


class _FakeIdentity(IdentityCapability):
    pass


class _FakePlugin(Plugin):
    pass


def _create_manifest() -> PluginManifest:
    """Manifest with a default-on logs cap and a default-off config cap."""
    return PluginManifest(
        slug='logzio',
        name='Logz.io',
        capabilities=[
            Capability(
                kind='logs',
                label='Logs',
                handler=_FakeLogs,
                default_enabled=True,
            ),
            Capability(
                kind='configuration',
                label='Config',
                handler=_FakeConfig,
                default_enabled=False,
            ),
        ],
    )


def _identity_manifest(login_capable: bool = True) -> PluginManifest:
    return PluginManifest(
        slug='ghlogin',
        name='GitHub Login',
        capabilities=[
            Capability(
                kind='identity',
                label='Identity',
                handler=_FakeIdentity,
                hints={'login_capable': login_capable},
            )
        ],
    )


def _entry(manifest: PluginManifest) -> RegistryEntry:
    return support.registry_entry(manifest, plugin_cls=_FakePlugin)


def _node(slug: str = 'logzio-prod', **over: typing.Any) -> dict[str, object]:
    """A hydrated Integration node as returned by an agtype column."""
    node: dict[str, typing.Any] = {
        'plugin': 'logzio',
        'name': 'Logz.io Prod',
        'slug': slug,
        'status': 'active',
        'options': {},
        'capabilities': {},
        'links': {},
        'identifiers': {},
        'encrypted_credentials': {},
        'organization': {'slug': 'myorg'},
        'team': None,
    }
    node.update(over)
    return node


class IntegrationsEndpointTestCase(support.SharedAppTestCase):
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
                'integration:create',
                'integration:read',
                'integration:update',
                'integration:delete',
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
        self.client = testclient.TestClient(self.test_app)

    # -- list / get ------------------------------------------------------

    def test_list_integrations(self) -> None:
        self.mock_db.execute.return_value = [{'integration': _node()}]
        response = self.client.get('/organizations/myorg/integrations/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['slug'], 'logzio-prod')

    def test_get_integration(self) -> None:
        self.mock_db.execute.return_value = [{'integration': _node()}]
        response = self.client.get(
            '/organizations/myorg/integrations/logzio-prod'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['slug'], 'logzio-prod')

    def test_get_integration_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.get('/organizations/myorg/integrations/missing')
        self.assertEqual(response.status_code, 404)

    def test_icon_falls_back_to_plugin_manifest(self) -> None:
        """With no icon of its own, an Integration inherits its plugin's."""
        manifest = _create_manifest()
        manifest.icon = 'si-logzio'
        self.mock_db.execute.return_value = [{'integration': _node()}]
        with mock.patch(
            'imbi.api.endpoints.integrations.get_plugin',
            return_value=_entry(manifest),
        ):
            response = self.client.get(
                '/organizations/myorg/integrations/logzio-prod'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['icon'], 'si-logzio')

    def test_icon_prefers_integration_over_plugin(self) -> None:
        """An Integration's own icon overrides the plugin manifest icon."""
        manifest = _create_manifest()
        manifest.icon = 'si-logzio'
        self.mock_db.execute.return_value = [
            {'integration': _node(icon='si-custom')}
        ]
        with mock.patch(
            'imbi.api.endpoints.integrations.get_plugin',
            return_value=_entry(manifest),
        ):
            response = self.client.get(
                '/organizations/myorg/integrations/logzio-prod'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['icon'], 'si-custom')

    def test_icon_none_when_plugin_missing(self) -> None:
        """No plugin registered and no own icon → icon stays null."""
        self.mock_db.execute.return_value = [{'integration': _node()}]
        with mock.patch(
            'imbi.api.endpoints.integrations.get_plugin',
            side_effect=PluginNotFoundError('logzio'),
        ):
            response = self.client.get(
                '/organizations/myorg/integrations/logzio-prod'
            )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['icon'])

    # -- create ----------------------------------------------------------

    def _patch_encryptor(self) -> typing.Any:
        encryptor = mock.Mock()
        encryptor.encrypt.side_effect = lambda v: f'enc:{v}'
        token = mock.Mock()
        token.get_instance.return_value = encryptor
        return mock.patch(
            'imbi.api.endpoints.integrations.TokenEncryption', token
        )

    def test_create_integration_defaults_capabilities_from_manifest(
        self,
    ) -> None:
        self.mock_db.execute.return_value = [{'integration': _node()}]
        with (
            mock.patch(
                'imbi.api.endpoints.integrations.get_plugin',
                return_value=_entry(_create_manifest()),
            ),
            self._patch_encryptor(),
        ):
            response = self.client.post(
                '/organizations/myorg/integrations/',
                json={
                    'plugin': 'logzio',
                    'name': 'Logz.io Prod',
                    'slug': 'logzio-prod',
                },
            )
        self.assertEqual(response.status_code, 201)
        params = self.mock_db.execute.call_args.args[1]
        self.assertEqual(
            params['capabilities'],
            {
                'logs': {'enabled': True, 'options': {}},
                'configuration': {'enabled': False, 'options': {}},
            },
        )
        # No team_slug -> team-less CREATE query.
        self.assertNotIn('team_slug', params)

    def test_create_integration_capability_override(self) -> None:
        self.mock_db.execute.return_value = [{'integration': _node()}]
        with (
            mock.patch(
                'imbi.api.endpoints.integrations.get_plugin',
                return_value=_entry(_create_manifest()),
            ),
            self._patch_encryptor(),
        ):
            response = self.client.post(
                '/organizations/myorg/integrations/',
                json={
                    'plugin': 'logzio',
                    'name': 'Logz.io Prod',
                    'slug': 'logzio-prod',
                    'capabilities': {
                        'logs': {'enabled': False, 'options': {'k': 'v'}}
                    },
                },
            )
        self.assertEqual(response.status_code, 201)
        params = self.mock_db.execute.call_args.args[1]
        self.assertEqual(
            params['capabilities']['logs'],
            {'enabled': False, 'options': {'k': 'v'}},
        )

    def test_create_integration_with_team(self) -> None:
        node = _node(team={'slug': 'team-a'})
        self.mock_db.execute.return_value = [{'integration': node}]
        with (
            mock.patch(
                'imbi.api.endpoints.integrations.get_plugin',
                return_value=_entry(_create_manifest()),
            ),
            self._patch_encryptor(),
        ):
            response = self.client.post(
                '/organizations/myorg/integrations/',
                json={
                    'plugin': 'logzio',
                    'name': 'Logz.io Prod',
                    'slug': 'logzio-prod',
                    'team_slug': 'team-a',
                },
            )
        self.assertEqual(response.status_code, 201)
        params = self.mock_db.execute.call_args.args[1]
        self.assertEqual(params['team_slug'], 'team-a')
        self.assertEqual(response.json()['team'], {'slug': 'team-a'})

    def test_create_integration_encrypts_credentials(self) -> None:
        self.mock_db.execute.return_value = [{'integration': _node()}]
        with (
            mock.patch(
                'imbi.api.endpoints.integrations.get_plugin',
                return_value=_entry(_create_manifest()),
            ),
            self._patch_encryptor(),
        ):
            response = self.client.post(
                '/organizations/myorg/integrations/',
                json={
                    'plugin': 'logzio',
                    'name': 'Logz.io Prod',
                    'slug': 'logzio-prod',
                    'credentials': {'token': 'secret'},
                },
            )
        self.assertEqual(response.status_code, 201)
        params = self.mock_db.execute.call_args.args[1]
        self.assertEqual(
            params['encrypted_credentials'], {'token': 'enc:secret'}
        )

    def test_create_integration_strips_credential_whitespace(self) -> None:
        self.mock_db.execute.return_value = [{'integration': _node()}]
        with (
            mock.patch(
                'imbi.api.endpoints.integrations.get_plugin',
                return_value=_entry(_create_manifest()),
            ),
            self._patch_encryptor(),
        ):
            response = self.client.post(
                '/organizations/myorg/integrations/',
                json={
                    'plugin': 'logzio',
                    'name': 'Logz.io Prod',
                    'slug': 'logzio-prod',
                    'credentials': {'token': '  secret\n', 'blank': '   '},
                },
            )
        self.assertEqual(response.status_code, 201)
        params = self.mock_db.execute.call_args.args[1]
        # Surrounding whitespace stripped; whitespace-only field dropped.
        self.assertEqual(
            params['encrypted_credentials'], {'token': 'enc:secret'}
        )

    def test_create_integration_plugin_not_installed(self) -> None:
        with mock.patch(
            'imbi.api.endpoints.integrations.get_plugin',
            side_effect=PluginNotFoundError('nope'),
        ):
            response = self.client.post(
                '/organizations/myorg/integrations/',
                json={
                    'plugin': 'nope',
                    'name': 'Nope',
                    'slug': 'nope-prod',
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('not installed', response.json()['detail'])

    def test_create_integration_slug_conflict(self) -> None:
        self.mock_db.execute.side_effect = psycopg.errors.UniqueViolation(
            'dup'
        )
        with (
            mock.patch(
                'imbi.api.endpoints.integrations.get_plugin',
                return_value=_entry(_create_manifest()),
            ),
            self._patch_encryptor(),
        ):
            response = self.client.post(
                '/organizations/myorg/integrations/',
                json={
                    'plugin': 'logzio',
                    'name': 'Logz.io Prod',
                    'slug': 'logzio-prod',
                },
            )
        self.assertEqual(response.status_code, 409)

    def test_create_integration_org_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with (
            mock.patch(
                'imbi.api.endpoints.integrations.get_plugin',
                return_value=_entry(_create_manifest()),
            ),
            self._patch_encryptor(),
        ):
            response = self.client.post(
                '/organizations/myorg/integrations/',
                json={
                    'plugin': 'logzio',
                    'name': 'Logz.io Prod',
                    'slug': 'logzio-prod',
                },
            )
        self.assertEqual(response.status_code, 404)
        self.assertIn('Organization', response.json()['detail'])

    def test_create_integration_org_or_team_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with (
            mock.patch(
                'imbi.api.endpoints.integrations.get_plugin',
                return_value=_entry(_create_manifest()),
            ),
            self._patch_encryptor(),
        ):
            response = self.client.post(
                '/organizations/myorg/integrations/',
                json={
                    'plugin': 'logzio',
                    'name': 'Logz.io Prod',
                    'slug': 'logzio-prod',
                    'team_slug': 'team-a',
                },
            )
        self.assertEqual(response.status_code, 404)
        self.assertIn('team', response.json()['detail'])

    # -- update ----------------------------------------------------------

    def test_update_integration_merges_options_and_capabilities(self) -> None:
        existing = _node(
            options={'a': 0, 'b': 2},
            capabilities={'logs': {'enabled': True, 'options': {'x': 1}}},
        )
        updated = _node(
            options={'a': 1, 'b': 2},
            capabilities={'logs': {'enabled': False, 'options': {'x': 1}}},
        )
        self.mock_db.execute.side_effect = [
            [{'integration': existing}],
            [{'integration': updated}],
        ]
        response = self.client.patch(
            '/organizations/myorg/integrations/logzio-prod',
            json={
                'options': {'a': 1},
                'capabilities': {
                    'logs': {'enabled': False, 'options': {'y': 2}}
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        params = self.mock_db.execute.call_args.args[1]
        self.assertEqual(params['options'], {'a': 1, 'b': 2})
        self.assertEqual(
            params['capabilities']['logs'],
            {'enabled': False, 'options': {'x': 1, 'y': 2}},
        )

    def test_update_integration_team_reassignment(self) -> None:
        existing = _node()
        updated = _node(team={'slug': 'team-b'})
        self.mock_db.execute.side_effect = [
            [{'integration': existing}],
            [{'integration': updated}],
        ]
        response = self.client.patch(
            '/organizations/myorg/integrations/logzio-prod',
            json={'team_slug': 'team-b'},
        )
        self.assertEqual(response.status_code, 200)
        params = self.mock_db.execute.call_args.args[1]
        self.assertEqual(params['team_slug'], 'team-b')

    def test_update_integration_team_removal(self) -> None:
        existing = _node(team={'slug': 'team-b'})
        updated = _node(name='Renamed', team=None)
        self.mock_db.execute.side_effect = [
            [{'integration': existing}],
            [{'integration': updated}],
        ]
        response = self.client.patch(
            '/organizations/myorg/integrations/logzio-prod',
            json={'team_slug': None, 'name': 'Renamed'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['team'])

    def test_update_integration_no_op(self) -> None:
        existing = _node()
        self.mock_db.execute.return_value = [{'integration': existing}]
        response = self.client.patch(
            '/organizations/myorg/integrations/logzio-prod',
            json={},
        )
        self.assertEqual(response.status_code, 200)
        # Only the GET query ran; no write query.
        self.assertEqual(self.mock_db.execute.call_count, 1)

    def test_update_integration_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.patch(
            '/organizations/myorg/integrations/missing',
            json={'name': 'x'},
        )
        self.assertEqual(response.status_code, 404)

    def test_update_integration_write_returns_no_rows(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'integration': _node()}],
            [],
        ]
        response = self.client.patch(
            '/organizations/myorg/integrations/logzio-prod',
            json={'name': 'x'},
        )
        self.assertEqual(response.status_code, 404)

    # -- delete ----------------------------------------------------------

    def test_delete_integration(self) -> None:
        self.mock_db.execute.return_value = [{'deleted': 1}]
        response = self.client.delete(
            '/organizations/myorg/integrations/logzio-prod'
        )
        self.assertEqual(response.status_code, 204)

    def test_delete_integration_not_found(self) -> None:
        self.mock_db.execute.return_value = [{'deleted': 0}]
        response = self.client.delete(
            '/organizations/myorg/integrations/missing'
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_integration_no_records(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.delete(
            '/organizations/myorg/integrations/missing'
        )
        self.assertEqual(response.status_code, 404)

    # -- credentials -----------------------------------------------------

    def test_update_credentials(self) -> None:
        with mock.patch(
            'imbi.api.endpoints.integrations.patch_integration_credentials',
            new=mock.AsyncMock(return_value=['token']),
        ) as patched:
            response = self.client.put(
                '/organizations/myorg/integrations/logzio-prod/credentials',
                json={'credentials': {'token': 'new'}},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'credential_fields': ['token']})
        patched.assert_awaited_once()

    # -- login provider --------------------------------------------------

    def test_set_login_provider_promotes(self) -> None:
        node = _node(slug='ghlogin-prod', plugin='ghlogin')
        self.mock_db.execute.side_effect = [
            [{'integration': node}],
            [],
            [{'integration': {**node, 'used_as_login': True}}],
        ]
        with (
            mock.patch(
                'imbi.api.endpoints.integrations.get_plugin',
                return_value=_entry(_identity_manifest(login_capable=True)),
            ),
            mock.patch(
                'imbi.api.endpoints.integrations.login_providers'
                '.invalidate_cache'
            ) as invalidate,
        ):
            response = self.client.put(
                '/organizations/myorg/integrations/ghlogin-prod'
                '/login-provider',
                json={'used_as_login': True},
            )
        self.assertEqual(response.status_code, 200)
        invalidate.assert_called_once()

    def test_set_login_provider_demotes(self) -> None:
        node = _node(slug='ghlogin-prod', plugin='ghlogin')
        self.mock_db.execute.side_effect = [
            [{'integration': node}],
            [{'integration': {**node, 'used_as_login': False}}],
        ]
        with (
            mock.patch(
                'imbi.api.endpoints.integrations.get_plugin',
            ) as get_plugin,
            mock.patch(
                'imbi.api.endpoints.integrations.login_providers'
                '.invalidate_cache'
            ) as invalidate,
        ):
            # build_response consults the plugin only for the display icon.
            get_plugin.return_value.manifest.icon = None
            response = self.client.put(
                '/organizations/myorg/integrations/ghlogin-prod'
                '/login-provider',
                json={'used_as_login': False},
            )
        self.assertEqual(response.status_code, 200)
        # Demotion never checks login capability.
        get_plugin.return_value.manifest.get_capability.assert_not_called()
        invalidate.assert_called_once()

    def test_set_login_provider_not_login_capable(self) -> None:
        node = _node(slug='ghlogin-prod', plugin='ghlogin')
        self.mock_db.execute.return_value = [{'integration': node}]
        with mock.patch(
            'imbi.api.endpoints.integrations.get_plugin',
            return_value=_entry(_identity_manifest(login_capable=False)),
        ):
            response = self.client.put(
                '/organizations/myorg/integrations/ghlogin-prod'
                '/login-provider',
                json={'used_as_login': True},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('login-capable', response.json()['detail'])

    def test_set_login_provider_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.put(
            '/organizations/myorg/integrations/missing/login-provider',
            json={'used_as_login': True},
        )
        self.assertEqual(response.status_code, 404)

    # -- capability assignments ------------------------------------------

    def test_list_capability_assignments(self) -> None:
        record = {
            'project_type_slug': 'api',
            'edge': {'default': True, 'options': {'o': 1}, 'env_payloads': {}},
        }
        self.mock_db.execute.return_value = [record]
        response = self.client.get(
            '/organizations/myorg/integrations/logzio-prod'
            '/capabilities/logs/assignments'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['project_type_slug'], 'api')
        self.assertTrue(data[0]['default'])
        self.assertIsNone(data[0]['identity_integration_slug'])

    def test_list_capability_assignments_with_identity(self) -> None:
        record = {
            'project_type_slug': 'api',
            'edge': {
                'default': False,
                'options': {},
                'env_payloads': {},
                'identity_integration_id': 'id-2',
            },
        }
        self.mock_db.execute.side_effect = [
            [record],
            [{'slug': 'ident-int'}],
        ]
        response = self.client.get(
            '/organizations/myorg/integrations/logzio-prod'
            '/capabilities/logs/assignments'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()[0]['identity_integration_slug'], 'ident-int'
        )

    def test_replace_capability_assignments(self) -> None:
        listed = {
            'project_type_slug': 'api',
            'edge': {'default': True, 'options': {}, 'env_payloads': {}},
        }
        self.mock_db.execute.side_effect = [
            [{'integration': _node()}],  # GET integration
            [{'found': 1}],  # project-type existence check
            [],  # replace write
            [listed],  # re-list
        ]
        response = self.client.put(
            '/organizations/myorg/integrations/logzio-prod'
            '/capabilities/logs/assignments',
            json={
                'assignments': [{'project_type_slug': 'api', 'default': True}]
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['project_type_slug'], 'api')

    def test_replace_capability_assignments_integration_not_found(
        self,
    ) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.put(
            '/organizations/myorg/integrations/missing'
            '/capabilities/logs/assignments',
            json={
                'assignments': [{'project_type_slug': 'api', 'default': True}]
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_replace_capability_assignments_unknown_project_type(
        self,
    ) -> None:
        self.mock_db.execute.side_effect = [
            [{'integration': _node()}],
            [{'found': 0}],
        ]
        response = self.client.put(
            '/organizations/myorg/integrations/logzio-prod'
            '/capabilities/logs/assignments',
            json={
                'assignments': [{'project_type_slug': 'nope', 'default': True}]
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn('project type', response.json()['detail'])

    def test_replace_capability_assignments_unknown_identity(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'integration': _node()}],
            [{'found': 1}],
            [],  # identity slug does not resolve
        ]
        response = self.client.put(
            '/organizations/myorg/integrations/logzio-prod'
            '/capabilities/logs/assignments',
            json={
                'assignments': [
                    {
                        'project_type_slug': 'api',
                        'identity_integration_slug': 'ghlogin-prod',
                    }
                ]
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn('Identity integration', response.json()['detail'])

    def test_replace_capability_assignments_empty(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'integration': _node()}],  # GET integration
            [],  # replace write (delete-only)
            [],  # re-list
        ]
        response = self.client.put(
            '/organizations/myorg/integrations/logzio-prod'
            '/capabilities/logs/assignments',
            json={'assignments': []},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
