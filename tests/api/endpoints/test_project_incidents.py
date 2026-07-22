"""Tests for the project incidents plugin endpoint."""

import datetime
from unittest import mock

import fastapi
from fastapi import testclient

from imbi.api import models
from imbi.api.auth import password, permissions
from imbi.api.plugins.resolution import ResolvedCapability
from imbi.common import graph
from imbi.common.plugins.base import (
    Capability,
    IncidentResult,
    IncidentsCapability,
    IncidentView,
    Plugin,
    PluginManifest,
)
from imbi.common.plugins.errors import CursorExpiredError
from imbi.common.plugins.registry import RegistryEntry
from tests.api import support


class _FakeIncidentsHandler(IncidentsCapability):
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


class _FakePlugin(Plugin):
    pass


def _manifest(handler: type[IncidentsCapability]) -> PluginManifest:
    return PluginManifest(
        slug='pagerduty-incidents',
        name='PagerDuty Incidents',
        capabilities=[
            Capability(kind='incidents', label='Incidents', handler=handler)
        ],
    )


def _entry(
    handler: type[IncidentsCapability] = _FakeIncidentsHandler,
) -> RegistryEntry:
    return RegistryEntry(
        plugin_cls=_FakePlugin,
        manifest=_manifest(handler),
        package_name='imbi-plugin-pagerduty',
        package_version='1.0.0',
    )


def _resolved(
    handler: type[IncidentsCapability] = _FakeIncidentsHandler,
) -> ResolvedCapability:
    entry = _entry(handler)
    return ResolvedCapability(
        integration_id='i1',
        integration_slug='pagerduty-prod',
        plugin_slug='pagerduty-incidents',
        kind='incidents',
        entry=entry,
        capability_cls=entry.manifest.get_capability('incidents').handler,
        integration={
            'id': 'i1',
            'slug': 'pagerduty-prod',
            'plugin': 'pagerduty-incidents',
        },
        integration_options={},
        capability_options={},
        encrypted_credentials={},
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
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

    def _resolved(self) -> ResolvedCapability:
        return _resolved()

    def test_list_incidents_happy_path(self) -> None:
        with (
            mock.patch(
                'imbi.api.endpoints.project_incidents.resolve_capability',
                return_value=self._resolved(),
            ),
            mock.patch(
                'imbi.api.endpoints.project_incidents.lookup_project_slugs',
                return_value=('proj-slug', 'team-slug'),
            ),
            mock.patch(
                'imbi.api.endpoints.project_incidents'
                '.decrypt_integration_credentials',
                return_value={'token': 'x'},
            ),
            mock.patch(
                'imbi.api.endpoints.project_incidents.lookup_project_links',
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
            'imbi.api.endpoints.project_incidents.resolve_capability',
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
            'imbi.api.endpoints.project_incidents.resolve_capability',
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
            'imbi.api.endpoints.project_incidents.resolve_capability',
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
        with (
            mock.patch(
                'imbi.api.endpoints.project_incidents.resolve_capability',
                return_value=self._resolved(),
            ),
            mock.patch(
                'imbi.api.endpoints.project_incidents.lookup_project_slugs',
                return_value=('proj-slug', 'team-slug'),
            ),
            mock.patch(
                'imbi.api.endpoints.project_incidents'
                '.decrypt_integration_credentials',
                return_value={},
            ),
            mock.patch(
                'imbi.api.endpoints.project_incidents.lookup_project_links',
                return_value={},
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/incidents/'
                )
        self.assertEqual(response.status_code, 503)

    def test_list_incidents_cursor_expired_returns_409(self) -> None:
        class _Expiring(_FakeIncidentsHandler):
            async def list_incidents(  # type: ignore[override]
                self, ctx, credentials, **kwargs
            ):
                raise CursorExpiredError('expired')

        with (
            mock.patch(
                'imbi.api.endpoints.project_incidents.resolve_capability',
                return_value=_resolved(_Expiring),
            ),
            mock.patch(
                'imbi.api.endpoints.project_incidents.lookup_project_slugs',
                return_value=('proj-slug', 'team-slug'),
            ),
            mock.patch(
                'imbi.api.endpoints.project_incidents'
                '.decrypt_integration_credentials',
                return_value={'token': 'x'},
            ),
            mock.patch(
                'imbi.api.endpoints.project_incidents.lookup_project_links',
                return_value={},
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/incidents/'
                )
        self.assertEqual(response.status_code, 409)
