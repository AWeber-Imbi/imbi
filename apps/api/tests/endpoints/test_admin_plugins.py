"""Tests for admin plugin management endpoints."""

import datetime
from unittest import mock

from fastapi import testclient

from apps.api.tests import support
from imbi.api import models
from imbi.api.auth import password, permissions
from imbi.api.endpoints import plugin_edges as _plugin_edges
from imbi.common import graph


class AdminPluginsEndpointTestCase(support.SharedAppTestCase):
    """Test cases for /admin/plugins admin endpoints."""

    def setUp(self) -> None:
        self.test_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,
            password_hash=password.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.admin_context = permissions.AuthContext(
            user=self.test_user,
            session_id='test-session',
            auth_method='jwt',
            permissions={'admin:plugins:read', 'admin:plugins:manage'},
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.admin_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.mock_db.execute.return_value = []
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

    def test_list_installed_plugins_empty(self) -> None:
        with (
            mock.patch(
                'imbi.api.endpoints.admin_plugins.list_plugins',
                return_value=[],
            ),
            mock.patch(
                'imbi.api.endpoints.admin_plugins.get_enabled_map',
                new_callable=mock.AsyncMock,
                return_value={},
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get('/admin/plugins')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_get_plugin_not_found(self) -> None:
        from imbi.common.plugins.errors import PluginNotFoundError

        with mock.patch(
            'imbi.api.endpoints.admin_plugins.get_plugin',
            side_effect=PluginNotFoundError('no-such-plugin'),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get('/admin/plugins/no-such-plugin')
        self.assertEqual(response.status_code, 404)

    def _make_entry(self) -> object:
        from imbi.common.plugins.base import (
            Capability,
            ConfigurationCapability,
            PluginEdgeLabel,
            PluginManifest,
        )

        class _FakeConfiguration(ConfigurationCapability):
            async def list_keys(self, ctx, credentials):  # type: ignore[override]
                return []

            async def get_values(self, ctx, credentials, keys=None):  # type: ignore[override]
                return []

            async def set_value(self, ctx, credentials, key, value):  # type: ignore[override]
                raise NotImplementedError

            async def delete_key(self, ctx, credentials, key):  # type: ignore[override]
                return None

        manifest = PluginManifest(
            slug='ssm',
            name='SSM',
            edge_labels=[
                PluginEdgeLabel(
                    name='MAPS_TO',
                    from_labels=['Environment'],
                    to_labels=['AwsAccount'],
                )
            ],
            capabilities=[
                Capability(
                    kind='configuration',
                    label='Configuration',
                    handler=_FakeConfiguration,
                )
            ],
        )

        return support.registry_entry(manifest)

    def test_get_plugin_found(self) -> None:
        entry = self._make_entry()
        with (
            mock.patch(
                'imbi.api.endpoints.admin_plugins.get_plugin',
                return_value=entry,
            ),
            mock.patch(
                'imbi.api.endpoints.admin_plugins.get_enabled_map',
                new_callable=mock.AsyncMock,
                return_value={'ssm': True},
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get('/admin/plugins/ssm')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'ssm')
        self.assertTrue(data['enabled'])

    def test_update_plugin_enable(self) -> None:
        entry = self._make_entry()
        with (
            mock.patch(
                'imbi.api.endpoints.admin_plugins.get_plugin',
                return_value=entry,
            ),
            mock.patch(
                'imbi.api.endpoints.admin_plugins.set_plugin_enabled',
                new_callable=mock.AsyncMock,
            ),
            mock.patch(
                'imbi.api.endpoints.admin_plugins.get_enabled_map',
                new_callable=mock.AsyncMock,
                return_value={'ssm': True},
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.put(
                    '/admin/plugins/ssm/registration', json={'enabled': True}
                )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['enabled'])

    def test_update_plugin_not_found(self) -> None:
        from imbi.common.plugins.errors import PluginNotFoundError

        with mock.patch(
            'imbi.api.endpoints.admin_plugins.get_plugin',
            side_effect=PluginNotFoundError('no-such-plugin'),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.put(
                    '/admin/plugins/no-such/registration',
                    json={'enabled': True},
                )
        self.assertEqual(response.status_code, 404)

    def test_list_plugin_edges_not_found(self) -> None:
        from imbi.common.plugins.errors import PluginNotFoundError

        with mock.patch(
            'imbi.api.endpoints.admin_plugins.get_plugin',
            side_effect=PluginNotFoundError('no-such-plugin'),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/admin/plugins/no-such/edges',
                    params={'rel_type': 'MAPS_TO', 'org_slug': 'acme'},
                )
        self.assertEqual(response.status_code, 404)

    def test_list_plugin_edges_returns_grouping(self) -> None:
        entry = self._make_entry()
        edges_by_anchor = {
            'prod': [
                _plugin_edges.EdgeResponse(
                    rel_type='MAPS_TO',
                    target_label='AwsAccount',
                    target={'id': 't-1', 'account_id': '111122223333'},
                    properties={},
                )
            ],
            'dev': [],
        }
        with (
            mock.patch(
                'imbi.api.endpoints.admin_plugins.get_plugin',
                return_value=entry,
            ),
            mock.patch(
                'imbi.api.endpoints.admin_plugins'
                '._plugin_edges.list_org_environment_edges',
                new_callable=mock.AsyncMock,
                return_value=edges_by_anchor,
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/admin/plugins/ssm/edges',
                    params={'rel_type': 'MAPS_TO', 'org_slug': 'acme'},
                )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data.keys()), {'prod', 'dev'})
        self.assertEqual(data['dev'], [])
        self.assertEqual(len(data['prod']), 1)
        self.assertEqual(
            data['prod'][0]['target']['account_id'], '111122223333'
        )

    def test_list_plugin_edges_rejects_foreign_rel_type(self) -> None:
        entry = self._make_entry()
        with mock.patch(
            'imbi.api.endpoints.admin_plugins.get_plugin',
            return_value=entry,
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/admin/plugins/ssm/edges',
                    params={'rel_type': 'OTHER', 'org_slug': 'acme'},
                )
        self.assertEqual(response.status_code, 404)
        self.assertIn('OTHER', response.json()['detail'])
