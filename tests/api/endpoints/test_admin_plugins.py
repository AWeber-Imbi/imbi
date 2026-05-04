"""Tests for admin plugin management endpoints."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient

from imbi_api import app, models
from imbi_api.auth import password, permissions


class AdminPluginsEndpointTestCase(unittest.TestCase):
    """Test cases for /plugins admin endpoints."""

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

    def test_list_installed_plugins_empty(self) -> None:
        with (
            mock.patch(
                'imbi_api.endpoints.admin_plugins.list_plugins',
                return_value=[],
            ),
            mock.patch(
                'imbi_api.endpoints.admin_plugins.get_unavailable_slugs',
                return_value=[],
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get('/plugins')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('installed', data)
        self.assertIn('unavailable', data)
        self.assertEqual(data['installed'], [])
        self.assertEqual(data['unavailable'], [])

    def test_get_plugin_not_found(self) -> None:
        from imbi_common.plugins.errors import PluginNotFoundError

        with mock.patch(
            'imbi_api.endpoints.admin_plugins.get_plugin',
            side_effect=PluginNotFoundError('no-such-plugin'),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get('/plugins/no-such-plugin')
        self.assertEqual(response.status_code, 404)

    def test_list_catalog(self) -> None:
        from imbi_api.plugins.catalog import CatalogEntry

        entries: list[CatalogEntry] = [
            CatalogEntry(
                package='imbi-plugin-ssm',
                version='>=1.0,<2',
                slugs=['ssm'],
                author='AWeber / Imbi',
                description='AWS SSM Parameter Store.',
                docs_url='https://docs.imbi.app/plugins/ssm',
                status='not_installed',
            )
        ]
        with mock.patch(
            'imbi_api.endpoints.admin_plugins.catalog.list_catalog_entries',
            return_value=entries,
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get('/plugins/catalog')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]['package'], 'imbi-plugin-ssm')

    def test_install_plugin_missing_package(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.post('/plugins/install', json={})
        self.assertEqual(response.status_code, 400)

    def test_install_plugin_not_in_catalog(self) -> None:
        from imbi_api.plugins.installer import InstallError

        with mock.patch(
            'imbi_api.endpoints.admin_plugins.installer.install_package',
            side_effect=InstallError('not in catalog'),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.post(
                    '/plugins/install',
                    json={'package': 'unknown-pkg'},
                )
        self.assertEqual(response.status_code, 400)
