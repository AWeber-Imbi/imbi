"""Tests for non-admin plugin manifest endpoint."""

import datetime
from unittest import mock

from fastapi import testclient
from imbi_common import graph

from imbi_api import models
from imbi_api.auth import password, permissions
from tests import support


class PluginManifestEndpointTestCase(support.SharedAppTestCase):
    """Test cases for ``GET /plugins/{slug}/manifest``."""

    def setUp(self) -> None:
        self.test_user = models.User(
            email='editor@example.com',
            display_name='Project Editor',
            is_active=True,
            is_admin=False,
            password_hash=password.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        # Note: deliberately no ``admin:plugins:read`` -- this endpoint
        # must work for any authenticated user.
        self.auth_context = permissions.AuthContext(
            user=self.test_user,
            session_id='test-session',
            auth_method='jwt',
            permissions={'project:read', 'project:write'},
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.mock_db.execute.return_value = []
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

    def _entry(self) -> object:
        from imbi_common.plugins.base import (
            Capability,
            CredentialField,
            LogsCapability,
            PluginManifest,
            PluginOption,
        )

        class _FakeLogs(LogsCapability):
            async def search(self, ctx, credentials, query):  # type: ignore[override]
                raise NotImplementedError

            async def schema(self, ctx, credentials):  # type: ignore[override]
                return []

        manifest = PluginManifest(
            slug='logzio',
            name='Logz.io',
            description='Logz.io log search',
            options=[
                PluginOption(
                    name='base_query',
                    label='Base Query Template',
                    type='string',
                    description='Elasticsearch query_string clause.',
                ),
                PluginOption(
                    name='region',
                    label='Region',
                    type='string',
                    choices=['us', 'eu'],
                    default='us',
                ),
            ],
            credentials=[
                CredentialField(
                    name='api_token',
                    label='API Token',
                ),
            ],
            capabilities=[
                Capability(kind='logs', label='Logs', handler=_FakeLogs)
            ],
        )

        return support.registry_entry(manifest, package_version='0.1.0')

    def test_returns_manifest(self) -> None:
        with (
            mock.patch(
                'imbi_api.endpoints.plugins.get_plugin',
                return_value=self._entry(),
            ),
            testclient.TestClient(self.test_app) as client,
        ):
            response = client.get('/plugins/logzio/manifest')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'logzio')
        self.assertEqual(data['name'], 'Logz.io')
        self.assertEqual([c['kind'] for c in data['capabilities']], ['logs'])
        self.assertEqual(len(data['options']), 2)
        self.assertEqual(data['options'][0]['name'], 'base_query')
        self.assertEqual(data['options'][0]['label'], 'Base Query Template')
        self.assertEqual(data['options'][1]['choices'], ['us', 'eu'])
        self.assertEqual(len(data['credentials']), 1)
        self.assertEqual(data['credentials'][0]['name'], 'api_token')

    def test_returns_404_for_unknown_slug(self) -> None:
        from imbi_common.plugins.errors import PluginNotFoundError

        with (
            mock.patch(
                'imbi_api.endpoints.plugins.get_plugin',
                side_effect=PluginNotFoundError('no-such-plugin'),
            ),
            testclient.TestClient(self.test_app) as client,
        ):
            response = client.get('/plugins/no-such-plugin/manifest')

        self.assertEqual(response.status_code, 404)

    def test_requires_authentication(self) -> None:
        # Without the override, get_current_user runs its real flow and
        # rejects the unauthenticated request.
        self.test_app.dependency_overrides.pop(
            permissions.get_current_user, None
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.get('/plugins/logzio/manifest')
        self.assertIn(response.status_code, {401, 403})
