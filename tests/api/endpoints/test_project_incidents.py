"""Tests for the project incidents plugin endpoint."""

import datetime
from unittest import mock

import fastapi
from fastapi import testclient
from imbi_common import graph
from imbi_common.plugins.base import (
    IncidentResult,
    IncidentsPlugin,
    IncidentView,
    PluginManifest,
)
from imbi_common.plugins.errors import CursorExpiredError
from imbi_common.plugins.registry import RegistryEntry

from imbi_api import models
from imbi_api.auth import password, permissions
from imbi_api.plugins.resolution import ResolvedPlugin
from tests import support


class _FakeIncidentsPlugin(IncidentsPlugin):
    manifest = PluginManifest(
        slug='pagerduty-incidents',
        name='PagerDuty Incidents',
        plugin_type='incidents',
    )

    async def list_incidents(  # type: ignore[override]
        self,
        ctx,
        credentials,
        *,
        start_time,
        end_time,
        statuses=None,
        cursor=None,
        limit=100,
    ):
        return IncidentResult(
            incidents=[
                IncidentView(
                    id='PINC1',
                    title='High CPU',
                    status='triggered',
                    urgency='high',
                    created_at=datetime.datetime(
                        2026, 6, 1, tzinfo=datetime.UTC
                    ),
                    url='https://example.pagerduty.com/incidents/PINC1',
                    service='Production Web App',
                )
            ],
            next_cursor=None,
            total=1,
        )


def _entry() -> RegistryEntry:
    return RegistryEntry(
        handler_cls=_FakeIncidentsPlugin,
        manifest=_FakeIncidentsPlugin.manifest,
        package_name='imbi-plugin-pagerduty',
        package_version='1.0.0',
    )


class ProjectIncidentsEndpointTestCase(support.SharedAppTestCase):
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
            permissions={'project:read'},
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

    def _resolved(self) -> ResolvedPlugin:
        return ResolvedPlugin(
            plugin_id='p1',
            plugin_slug='pagerduty-incidents',
            entry=_entry(),
            options={},
        )

    def test_list_incidents_happy_path(self) -> None:
        with (
            mock.patch(
                'imbi_api.endpoints.project_incidents.resolve_plugin',
                return_value=self._resolved(),
            ),
            mock.patch(
                'imbi_api.endpoints.project_incidents.lookup_project_slugs',
                return_value=('proj-slug', 'team-slug'),
            ),
            mock.patch(
                'imbi_api.endpoints.project_incidents.get_plugin_credentials',
                return_value={},
            ),
            mock.patch(
                'imbi_api.endpoints.project_incidents.lookup_project_links',
                return_value={'pagerduty-service': 'https://api/services/X'},
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/incidents/'
                )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['incidents']), 1)
        self.assertEqual(data['incidents'][0]['id'], 'PINC1')
        self.assertEqual(data['total'], 1)

    def test_list_incidents_no_plugin_returns_404(self) -> None:
        with mock.patch(
            'imbi_api.endpoints.project_incidents.resolve_plugin',
            side_effect=fastapi.HTTPException(
                status_code=404, detail='No incidents plugin'
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/incidents/'
                )
        self.assertEqual(response.status_code, 404)

    def test_list_incidents_invalid_datetime_returns_400(self) -> None:
        with mock.patch(
            'imbi_api.endpoints.project_incidents.resolve_plugin',
            return_value=self._resolved(),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/incidents/'
                    '?start_time=not-a-date'
                )
        self.assertEqual(response.status_code, 400)

    def test_list_incidents_inverted_window_returns_400(self) -> None:
        with mock.patch(
            'imbi_api.endpoints.project_incidents.resolve_plugin',
            return_value=self._resolved(),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/incidents/'
                    '?start_time=2026-06-08T00:00:00Z'
                    '&end_time=2026-06-01T00:00:00Z'
                )
        self.assertEqual(response.status_code, 400)

    def test_list_incidents_credentials_missing_returns_503(self) -> None:
        from imbi_common.plugins.errors import PluginCredentialsMissing

        with (
            mock.patch(
                'imbi_api.endpoints.project_incidents.resolve_plugin',
                return_value=self._resolved(),
            ),
            mock.patch(
                'imbi_api.endpoints.project_incidents.lookup_project_slugs',
                return_value=('proj-slug', 'team-slug'),
            ),
            mock.patch(
                'imbi_api.endpoints.project_incidents.get_plugin_credentials',
                side_effect=PluginCredentialsMissing('no creds'),
            ),
            mock.patch(
                'imbi_api.endpoints.project_incidents.lookup_project_links',
                return_value={},
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/incidents/'
                )
        self.assertEqual(response.status_code, 503)

    def test_list_incidents_cursor_expired_returns_409(self) -> None:
        class _Expiring(_FakeIncidentsPlugin):
            async def list_incidents(  # type: ignore[override]
                self, ctx, credentials, **kwargs
            ):
                raise CursorExpiredError('expired')

        entry = RegistryEntry(
            handler_cls=_Expiring,
            manifest=_FakeIncidentsPlugin.manifest,
            package_name='imbi-plugin-pagerduty',
            package_version='1.0.0',
        )
        resolved = ResolvedPlugin(
            plugin_id='p1',
            plugin_slug='pagerduty-incidents',
            entry=entry,
            options={},
        )
        with (
            mock.patch(
                'imbi_api.endpoints.project_incidents.resolve_plugin',
                return_value=resolved,
            ),
            mock.patch(
                'imbi_api.endpoints.project_incidents.lookup_project_slugs',
                return_value=('proj-slug', 'team-slug'),
            ),
            mock.patch(
                'imbi_api.endpoints.project_incidents.get_plugin_credentials',
                return_value={},
            ),
            mock.patch(
                'imbi_api.endpoints.project_incidents.lookup_project_links',
                return_value={},
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/incidents/'
                )
        self.assertEqual(response.status_code, 409)
