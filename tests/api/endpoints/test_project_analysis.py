"""Endpoint tests for the Project Doctor analysis routes."""

from __future__ import annotations

import datetime
import json
import typing
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common import graph
from imbi_common.plugins.base import (
    AnalysisPlugin,
    AnalysisResultItem,
    PluginManifest,
)
from imbi_common.plugins.registry import RegistryEntry

from imbi_api import app, models
from imbi_api.auth import password, permissions
from imbi_api.plugins.resolution import ResolvedPlugin

_MODULE = 'imbi_api.endpoints.project_analysis'


class _PassPlugin(AnalysisPlugin):
    manifest = PluginManifest(
        slug='pass-plugin', name='Pass', plugin_type='analysis'
    )

    async def analyze(self, ctx, credentials) -> list[AnalysisResultItem]:  # type: ignore[override]
        return [
            AnalysisResultItem(
                slug='pass-plugin:ok',
                title='Looks good',
                description='no findings',
                status='pass',
            )
        ]


class _FailPlugin(AnalysisPlugin):
    manifest = PluginManifest(
        slug='fail-plugin', name='Fail', plugin_type='analysis'
    )

    async def analyze(self, ctx, credentials) -> list[AnalysisResultItem]:  # type: ignore[override]
        return [
            AnalysisResultItem(
                slug='fail-plugin:bad',
                title='High severity finding',
                description='something bad',
                status='fail',
            ),
            AnalysisResultItem(
                slug='fail-plugin:meh',
                title='Mediocre',
                description='kinda bad',
                status='warn',
            ),
        ]


class _BoomPlugin(AnalysisPlugin):
    manifest = PluginManifest(
        slug='boom-plugin', name='Boom', plugin_type='analysis'
    )

    async def analyze(self, ctx, credentials) -> list[AnalysisResultItem]:  # type: ignore[override]
        raise RuntimeError('boom')


def _registry_entry(cls: type[AnalysisPlugin]) -> RegistryEntry:
    return RegistryEntry(
        handler_cls=cls,
        manifest=cls.manifest,
        package_name='test-pkg',
        package_version='0',
    )


def _resolved(plugin_id: str, cls: type[AnalysisPlugin]) -> ResolvedPlugin:
    return ResolvedPlugin(
        plugin_id=plugin_id,
        plugin_slug=cls.manifest.slug,
        entry=_registry_entry(cls),
        options={},
    )


class ProjectAnalysisTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.test_app = app.create_app()
        self.test_user = models.User(
            id='user-1',
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
            permissions={'project:read', 'project:write'},
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

        self.mocks: dict[str, mock.MagicMock] = {}
        self.mocks['lookup_project_slugs'] = self._start(
            mock.patch(
                f'{_MODULE}.lookup_project_slugs',
                return_value=('proj-slug', 'team'),
            )
        )
        self.mocks['lookup_project_links'] = self._start(
            mock.patch(
                f'{_MODULE}.lookup_project_links',
                return_value={},
            )
        )
        self.mocks['lookup_project_type_slugs'] = self._start(
            mock.patch(
                f'{_MODULE}.lookup_project_type_slugs',
                return_value=['service'],
            )
        )
        self.mocks['get_plugin_credentials'] = self._start(
            mock.patch(
                f'{_MODULE}.get_plugin_credentials',
                return_value={},
            )
        )

    def _start(self, patcher: typing.Any) -> mock.MagicMock:
        m = patcher.start()
        self.addCleanup(patcher.stop)
        return m

    def test_run_with_no_plugins_persists_empty_pass_report(self) -> None:
        with mock.patch(
            f'{_MODULE}.resolve_analysis_plugins',
            return_value=[],
        ):
            with testclient.TestClient(self.test_app) as client:
                resp = client.post(
                    '/organizations/acme/projects/proj-1/analysis/run'
                )
        self.assertEqual(200, resp.status_code, resp.text)
        body = resp.json()
        self.assertEqual('pass', body['overall_status'])
        self.assertEqual([], body['results'])

    def test_run_returns_worst_status_and_sorted_results(self) -> None:
        with mock.patch(
            f'{_MODULE}.resolve_analysis_plugins',
            return_value=[
                _resolved('p1', _PassPlugin),
                _resolved('p2', _FailPlugin),
            ],
        ):
            with testclient.TestClient(self.test_app) as client:
                resp = client.post(
                    '/organizations/acme/projects/proj-1/analysis/run'
                )
        self.assertEqual(200, resp.status_code, resp.text)
        body = resp.json()
        self.assertEqual('fail', body['overall_status'])
        statuses = [r['status'] for r in body['results']]
        # Sort puts fail first, then warn, then pass.
        self.assertEqual(['fail', 'warn', 'pass'], statuses)

    def test_run_captures_plugin_exception_as_fail_result(self) -> None:
        with mock.patch(
            f'{_MODULE}.resolve_analysis_plugins',
            return_value=[_resolved('p3', _BoomPlugin)],
        ):
            with testclient.TestClient(self.test_app) as client:
                resp = client.post(
                    '/organizations/acme/projects/proj-1/analysis/run'
                )
        self.assertEqual(200, resp.status_code, resp.text)
        body = resp.json()
        self.assertEqual('fail', body['overall_status'])
        self.assertEqual(1, len(body['results']))
        self.assertEqual(
            'boom-plugin:plugin-error', body['results'][0]['slug']
        )
        # The plugin's exception text (``'boom'``) must NOT leak into
        # the user-facing description -- only into the server log.
        self.assertNotIn('boom', body['results'][0]['description'])
        self.assertNotIn('RuntimeError', body['results'][0]['description'])

    def test_get_returns_404_when_no_report(self) -> None:
        self.mock_db.execute.return_value = []
        with testclient.TestClient(self.test_app) as client:
            resp = client.get('/organizations/acme/projects/proj-1/analysis/')
        self.assertEqual(404, resp.status_code, resp.text)

    def test_get_returns_persisted_report(self) -> None:
        created_at = datetime.datetime.now(datetime.UTC).isoformat()
        self.mock_db.execute.return_value = [
            {
                'r': json.dumps(
                    {
                        'id': 'report-1',
                        'project_id': 'proj-1',
                        'created_at': created_at,
                        'overall_status': 'warn',
                        'triggered_by_user_id': 'user-1',
                    }
                ),
                'results': json.dumps(
                    [
                        {
                            'slug': 'a',
                            'title': 'A finding',
                            'description': 'd',
                            'status': 'warn',
                            'plugin_slug': 'p',
                            'plugin_id': 'p1',
                        }
                    ]
                ),
            }
        ]
        with testclient.TestClient(self.test_app) as client:
            resp = client.get('/organizations/acme/projects/proj-1/analysis/')
        self.assertEqual(200, resp.status_code, resp.text)
        body = resp.json()
        self.assertEqual('report-1', body['id'])
        self.assertEqual('warn', body['overall_status'])
        self.assertEqual(1, len(body['results']))
        self.assertEqual('A finding', body['results'][0]['title'])

    def test_run_requires_project_write_permission(self) -> None:
        self.auth_context = permissions.AuthContext(
            user=self.test_user,
            session_id='test-session',
            auth_method='jwt',
            permissions={'project:read'},
        )
        # Force is_admin path off so permission check actually fires.
        self.auth_context.user = self.test_user.model_copy(
            update={'is_admin': False}
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        with mock.patch(
            f'{_MODULE}.resolve_analysis_plugins',
            return_value=[],
        ):
            with testclient.TestClient(self.test_app) as client:
                resp = client.post(
                    '/organizations/acme/projects/proj-1/analysis/run'
                )
        self.assertEqual(403, resp.status_code, resp.text)
