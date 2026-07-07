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
    AnalysisCapability,
    AnalysisResultItem,
    Capability,
    Plugin,
    PluginManifest,
    RemediationOffer,
    RemediationResult,
    ServiceWriteback,
)
from imbi_common.plugins.registry import RegistryEntry

from imbi_api import app, models
from imbi_api.auth import password, permissions
from imbi_api.plugins.resolution import ResolvedCapability

_MODULE = 'imbi_api.endpoints.project_analysis'


class _PassPlugin(AnalysisCapability):
    _SLUG = 'pass-plugin'
    _NAME = 'Pass'

    async def analyze(self, ctx, credentials) -> list[AnalysisResultItem]:  # type: ignore[override]
        return [
            AnalysisResultItem(
                slug='pass-plugin:ok',
                title='Looks good',
                description='no findings',
                status='pass',
            )
        ]


class _FailPlugin(AnalysisCapability):
    _SLUG = 'fail-plugin'
    _NAME = 'Fail'

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


class _BoomPlugin(AnalysisCapability):
    _SLUG = 'boom-plugin'
    _NAME = 'Boom'

    async def analyze(self, ctx, credentials) -> list[AnalysisResultItem]:  # type: ignore[override]
        raise RuntimeError('boom')


class _RemediablePlugin(AnalysisCapability):
    _SLUG = 'fix-plugin'
    _NAME = 'Fix'

    async def analyze(self, ctx, credentials) -> list[AnalysisResultItem]:  # type: ignore[override]
        return [
            AnalysisResultItem(
                slug='fix-plugin:drift',
                title='Edge drift',
                description='out of sync',
                status='fail',
                remediation=RemediationOffer(id='fix-it', label='Fix it'),
            )
        ]

    async def remediate(self, ctx, credentials, remediation_id):  # type: ignore[override]
        ctx.service_writeback = ServiceWriteback(
            identifier='42',
            canonical_url='https://api.github.com/repositories/42',
        )
        return RemediationResult(
            status='fixed', message=f'fixed {remediation_id}'
        )


class _FakePlugin(Plugin):
    pass


def _registry_entry(cls: type[AnalysisCapability]) -> RegistryEntry:
    return RegistryEntry(
        plugin_cls=_FakePlugin,
        manifest=PluginManifest(
            slug=cls._SLUG,
            name=cls._NAME,
            capabilities=[
                Capability(kind='analysis', label='Analysis', handler=cls)
            ],
        ),
        package_name='test-pkg',
        package_version='0',
    )


def _resolved(
    plugin_id: str, cls: type[AnalysisCapability]
) -> ResolvedCapability:
    entry = _registry_entry(cls)
    return ResolvedCapability(
        integration_id=plugin_id,
        integration_slug=f'{cls._SLUG}-prod',
        plugin_slug=cls._SLUG,
        kind='analysis',
        entry=entry,
        capability_cls=entry.manifest.get_capability('analysis').handler,
        integration={
            'id': plugin_id,
            'slug': f'{cls._SLUG}-prod',
            'plugin': cls._SLUG,
        },
        integration_options={},
        capability_options={},
        encrypted_credentials={},
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
        self.mocks['check_blueprint_compliance'] = self._start(
            mock.patch(
                f'{_MODULE}.check_blueprint_compliance',
                return_value=[],
            )
        )
        self.mocks['lookup_project_exists_in'] = self._start(
            mock.patch(
                f'{_MODULE}.lookup_project_exists_in',
                return_value=[],
            )
        )
        # Remediation write-back persistence hits the graph; stub it so
        # the endpoint tests stay DB-free.
        self.mocks['persist_service_writeback'] = self._start(
            mock.patch(f'{_MODULE}.persist_service_writeback')
        )
        self.mocks['persist_link_writeback'] = self._start(
            mock.patch(f'{_MODULE}.persist_link_writeback')
        )

    def _start(self, patcher: typing.Any) -> mock.MagicMock:
        m = patcher.start()
        self.addCleanup(patcher.stop)
        return m

    def test_run_with_no_plugins_persists_empty_pass_report(self) -> None:
        with mock.patch(
            f'{_MODULE}.resolve_all_capabilities',
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
            f'{_MODULE}.resolve_all_capabilities',
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
            f'{_MODULE}.resolve_all_capabilities',
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
            f'{_MODULE}.resolve_all_capabilities',
            return_value=[],
        ):
            with testclient.TestClient(self.test_app) as client:
                resp = client.post(
                    '/organizations/acme/projects/proj-1/analysis/run'
                )
        self.assertEqual(403, resp.status_code, resp.text)

    def test_remediate_calls_plugin_and_persists_writeback(self) -> None:
        with mock.patch(
            f'{_MODULE}.resolve_all_capabilities',
            return_value=[_resolved('p1', _RemediablePlugin)],
        ):
            with testclient.TestClient(self.test_app) as client:
                resp = client.post(
                    '/organizations/acme/projects/proj-1/analysis/remediate',
                    json={
                        'plugin_id': 'p1',
                        'finding_slug': 'fix-plugin:drift',
                        'remediation_id': 'fix-it',
                    },
                )
        self.assertEqual(200, resp.status_code, resp.text)
        body = resp.json()
        self.assertEqual('fixed', body['result']['status'])
        self.assertEqual('fixed fix-it', body['result']['message'])
        self.assertIn('report', body)
        self.mocks['persist_service_writeback'].assert_awaited()

    def test_remediate_unknown_plugin_returns_404(self) -> None:
        with mock.patch(
            f'{_MODULE}.resolve_all_capabilities',
            return_value=[],
        ):
            with testclient.TestClient(self.test_app) as client:
                resp = client.post(
                    '/organizations/acme/projects/proj-1/analysis/remediate',
                    json={
                        'plugin_id': 'nope',
                        'finding_slug': 'x',
                        'remediation_id': 'fix-it',
                    },
                )
        self.assertEqual(404, resp.status_code, resp.text)

    def test_remediate_builtin_routes_to_blueprint(self) -> None:
        with (
            mock.patch(
                f'{_MODULE}.remediate_blueprint',
                return_value=RemediationResult(
                    status='fixed', message='set default'
                ),
            ) as rb,
            mock.patch(f'{_MODULE}.resolve_all_capabilities', return_value=[]),
        ):
            with testclient.TestClient(self.test_app) as client:
                resp = client.post(
                    '/organizations/acme/projects/proj-1/analysis/remediate',
                    json={
                        'plugin_id': 'built-in',
                        'finding_slug': 'blueprint-compliance:x:y:use-default',
                        'remediation_id': 'set-default:foo',
                    },
                )
        self.assertEqual(200, resp.status_code, resp.text)
        self.assertEqual('fixed', resp.json()['result']['status'])
        rb.assert_awaited_once()

    def test_remediate_requires_project_write_permission(self) -> None:
        self.auth_context.user = self.test_user.model_copy(
            update={'is_admin': False}
        )
        self.auth_context = permissions.AuthContext(
            user=self.auth_context.user,
            session_id='test-session',
            auth_method='jwt',
            permissions={'project:read'},
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        with testclient.TestClient(self.test_app) as client:
            resp = client.post(
                '/organizations/acme/projects/proj-1/analysis/remediate',
                json={
                    'plugin_id': 'p1',
                    'finding_slug': 'x',
                    'remediation_id': 'fix-it',
                },
            )
        self.assertEqual(403, resp.status_code, resp.text)

    def test_remediate_all_best_effort(self) -> None:
        from imbi_api.endpoints.project_analysis import (
            AnalysisReport,
            AnalysisResult,
        )

        report = AnalysisReport(
            id='r1',
            project_id='proj-1',
            created_at=datetime.datetime.now(datetime.UTC),
            overall_status='warn',
            results=[
                AnalysisResult(
                    slug='blueprint-compliance:s:p:use-default',
                    title='t',
                    description='d',
                    status='warn',
                    plugin_slug='blueprint-compliance',
                    plugin_id='built-in',
                    remediation=RemediationOffer(
                        id='set-default:foo', label='Fix'
                    ),
                ),
                AnalysisResult(
                    slug='no-fix',
                    title='t2',
                    description='d2',
                    status='pass',
                    plugin_slug='p',
                    plugin_id='p9',
                ),
            ],
        )
        with (
            mock.patch(f'{_MODULE}._fetch_report', return_value=report),
            mock.patch(
                f'{_MODULE}.remediate_blueprint',
                return_value=RemediationResult(status='fixed', message='ok'),
            ),
            mock.patch(f'{_MODULE}.resolve_all_capabilities', return_value=[]),
        ):
            with testclient.TestClient(self.test_app) as client:
                resp = client.post(
                    '/organizations/acme/projects/proj-1/analysis'
                    '/remediate-all'
                )
        self.assertEqual(200, resp.status_code, resp.text)
        body = resp.json()
        # Only the fixable finding produces an outcome.
        self.assertEqual(1, len(body['outcomes']))
        self.assertEqual('fixed', body['outcomes'][0]['result']['status'])

    def test_remediate_all_captures_non_http_error(self) -> None:
        # A non-HTTPException from one finding must be captured as a failed
        # outcome, not abort the whole request (best-effort contract).
        from imbi_api.endpoints.project_analysis import (
            AnalysisReport,
            AnalysisResult,
        )

        report = AnalysisReport(
            id='r1',
            project_id='proj-1',
            created_at=datetime.datetime.now(datetime.UTC),
            overall_status='warn',
            results=[
                AnalysisResult(
                    slug='blueprint-compliance:s:p:use-default',
                    title='t',
                    description='d',
                    status='warn',
                    plugin_slug='blueprint-compliance',
                    plugin_id='built-in',
                    remediation=RemediationOffer(
                        id='set-default:foo', label='Fix'
                    ),
                ),
            ],
        )
        with (
            mock.patch(f'{_MODULE}._fetch_report', return_value=report),
            mock.patch(
                f'{_MODULE}.remediate_blueprint',
                side_effect=RuntimeError('boom'),
            ),
            mock.patch(f'{_MODULE}.resolve_all_capabilities', return_value=[]),
        ):
            with testclient.TestClient(self.test_app) as client:
                resp = client.post(
                    '/organizations/acme/projects/proj-1/analysis'
                    '/remediate-all'
                )
        self.assertEqual(200, resp.status_code, resp.text)
        body = resp.json()
        self.assertEqual(1, len(body['outcomes']))
        self.assertEqual('failed', body['outcomes'][0]['result']['status'])


class FetchReportParsingTestCase(unittest.IsolatedAsyncioTestCase):
    """Regression: ``_fetch_report`` must decode collected result rows.

    ``collect(res)`` serialised each finding as a ``::vertex`` agtype that
    ``parse_agtype`` could not turn into a list, so persisted reports read
    back empty and "Fix all" became a no-op even with fixable findings.
    The query returns ``collect(properties(res))`` — plain property maps —
    which parse into findings with their remediation offers intact.
    """

    _REPORT_VERTEX = (
        '{"id": 1, "label": "AnalysisReport", "properties": '
        '{"id": "rep1", "created_at": "2026-07-02T21:05:25.264906+00:00", '
        '"project_id": "proj1", "overall_status": "warn", '
        '"triggered_by_user_id": "user1"}}::vertex'
    )
    # Shape of ``collect(properties(res))``: a JSON array of plain property
    # maps, with ``remediation`` stored as a JSON string ('' when none).
    _RESULTS = (
        '[{"slug": "dashboard-url-match", "title": "Dashboard URL match", '
        '"status": "warn", "plugin_id": "pid1", "report_id": "rep1", '
        '"description": "mismatch", "plugin_slug": "github-doctor", '
        '"remediation": "{\\"id\\": \\"repair-edge\\", \\"label\\": '
        '\\"Repair\\", \\"confirm\\": null, \\"destructive\\": false}"}, '
        '{"slug": "canonical-url-shape", "title": "Canonical URL shape", '
        '"status": "warn", "plugin_id": "pid1", "report_id": "rep1", '
        '"description": "no url", "plugin_slug": "github-doctor", '
        '"remediation": ""}]'
    )

    async def test_parses_findings_and_decodes_remediation(self) -> None:
        from imbi_api.endpoints import project_analysis as pa

        db = mock.AsyncMock(spec=graph.Graph)
        db.execute.return_value = [
            {'r': self._REPORT_VERTEX, 'results': self._RESULTS}
        ]
        report = await pa._fetch_report(db, 'proj1')
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual('warn', report.overall_status)
        self.assertEqual(2, len(report.results))
        by_slug = {r.slug: r for r in report.results}
        # Fixable finding keeps its decoded remediation offer.
        offer = by_slug['dashboard-url-match'].remediation
        self.assertIsNotNone(offer)
        assert offer is not None
        self.assertEqual('repair-edge', offer.id)
        # Non-fixable finding ('' remediation) decodes to None.
        self.assertIsNone(by_slug['canonical-url-shape'].remediation)

    def test_query_returns_property_maps_not_raw_vertices(self) -> None:
        from imbi_api.endpoints import project_analysis as pa

        # A bare ``collect(res)`` serialises ::vertex agtype that
        # parse_agtype cannot decode into a list; property maps are
        # required for the persisted report to round-trip on read.
        self.assertIn('collect(properties(res))', pa._FETCH_REPORT_QUERY)
