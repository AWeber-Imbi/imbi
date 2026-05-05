"""Tests for admin plugin management endpoints."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common import graph

from imbi_api import app, models
from imbi_api.auth import password, permissions


class AdminPluginsEndpointTestCase(unittest.TestCase):
    """Test cases for /admin/plugins admin endpoints."""

    def setUp(self) -> None:
        self.test_app = app.create_app()
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
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

    def test_list_installed_plugins_empty(self) -> None:
        with (
            mock.patch(
                'imbi_api.endpoints.admin_plugins.list_plugins',
                return_value=[],
            ),
            mock.patch(
                'imbi_api.endpoints.admin_plugins.importlib.metadata.distributions',
                return_value=[],
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get('/admin/plugins')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('installed', data)
        self.assertNotIn('unavailable', data)
        self.assertEqual(data['installed'], [])

    def test_get_plugin_not_found(self) -> None:
        from imbi_common.plugins.errors import PluginNotFoundError

        with mock.patch(
            'imbi_api.endpoints.admin_plugins.get_plugin',
            side_effect=PluginNotFoundError('no-such-plugin'),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get('/admin/plugins/no-such-plugin')
        self.assertEqual(response.status_code, 404)

    def _make_entry(self) -> object:
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

    def test_get_plugin_found(self) -> None:
        entry = self._make_entry()
        with (
            mock.patch(
                'imbi_api.endpoints.admin_plugins.get_plugin',
                return_value=entry,
            ),
            mock.patch(
                'imbi_api.endpoints.admin_plugins.get_enabled_map',
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
                'imbi_api.endpoints.admin_plugins.get_plugin',
                return_value=entry,
            ),
            mock.patch(
                'imbi_api.endpoints.admin_plugins.set_plugin_enabled',
                new_callable=mock.AsyncMock,
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.patch(
                    '/admin/plugins/ssm', json={'enabled': True}
                )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['enabled'])

    def test_update_plugin_not_found(self) -> None:
        from imbi_common.plugins.errors import PluginNotFoundError

        with mock.patch(
            'imbi_api.endpoints.admin_plugins.get_plugin',
            side_effect=PluginNotFoundError('no-such-plugin'),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.patch(
                    '/admin/plugins/no-such', json={'enabled': True}
                )
        self.assertEqual(response.status_code, 404)
