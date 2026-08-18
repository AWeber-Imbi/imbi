"""Tests for component governance and the package reports."""

import datetime
import typing
from unittest import mock

import fastapi.testclient

from apps.api.tests import support
from imbi.api import models
from imbi.common import graph

ORG = 'engineering'
COMPONENT_ID = 'cmp123nanoid'
RELEASE_A = 'crel4x0nanoid'
RELEASE_B = 'crel5x0nanoid'


def _usage_row(**overrides: typing.Any) -> dict[str, typing.Any]:
    row: dict[str, typing.Any] = {
        'component_release_id': RELEASE_A,
        'version': '4.18.2',
        'version_status': None,
        'version_status_at': None,
        'version_status_by': None,
        'first_seen': '2026-05-01T00:00:00+00:00',
        'project_id': 'proj-1',
        'project_name': 'Billing API',
        'project_slug': 'billing-api',
        'team_name': 'Platform',
        'team_slug': 'platform',
        'environment_name': 'Production',
        'environment_slug': 'production',
        'environment_color': '#3B82F6',
        'project_types': ['HTTP API'],
    }
    row.update(overrides)
    return row


def _version_row(**overrides: typing.Any) -> dict[str, typing.Any]:
    row: dict[str, typing.Any] = {
        'component_release_id': RELEASE_A,
        'version': '4.18.2',
        'version_status': None,
        'version_status_at': None,
        'version_status_by': None,
        'first_seen': '2026-05-01T00:00:00+00:00',
    }
    row.update(overrides)
    return row


def _problem_row(**overrides: typing.Any) -> dict[str, typing.Any]:
    row: dict[str, typing.Any] = {
        'component_id': COMPONENT_ID,
        'purl_name': 'pkg:npm/express',
        'component_name': 'express',
        'ecosystem': 'npm',
        'component_status': None,
        'component_release_id': RELEASE_A,
        'version': '4.18.2',
        'version_status': 'forbidden',
        'project_id': 'proj-1',
        'project_name': 'Billing API',
        'project_slug': 'billing-api',
        'team_name': 'Platform',
        'team_slug': 'platform',
        'environment_name': 'Production',
        'environment_slug': 'production',
        'environment_color': '#3B82F6',
        'project_types': ['HTTP API'],
    }
    row.update(overrides)
    return row


class _ComponentsTestBase(support.SharedAppTestCase):
    """Shared setup: identity ``parse_agtype`` and a mocked graph."""

    permissions_granted: typing.ClassVar[set[str]] = {
        'component:read',
        'component:write',
    }
    is_admin: bool = False

    def setUp(self) -> None:
        from imbi.api.auth import permissions

        self.user = models.User(
            email='alice@example.com',
            display_name='Alice',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=self.is_admin,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.user,
            session_id='test-session',
            auth_method='jwt',
            permissions=self.permissions_granted,
        )

        async def _current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            _current_user
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )
        patcher = mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = fastapi.testclient.TestClient(self.test_app)
        self.addCleanup(self.client.close)

    def _components(self, tail: str = '') -> str:
        return f'/organizations/{ORG}/components{tail}'

    def _versions(self, tail: str = '') -> str:
        return f'/organizations/{ORG}/component-releases{tail}'

    def _query(self, index: int) -> str:
        """Return the Cypher template of the n-th ``execute`` call."""
        return str(self.mock_db.execute.await_args_list[index].args[0])

    def _params(self, index: int) -> dict[str, typing.Any]:
        """Return the params of the n-th ``execute`` call."""
        return typing.cast(
            'dict[str, typing.Any]',
            self.mock_db.execute.await_args_list[index].args[1],
        )


class SearchComponentsTestCase(_ComponentsTestBase):
    """GET /components"""

    def test_search_sorts_by_project_count(self) -> None:
        self.mock_db.execute.side_effect = [
            [
                {
                    'id': 'cmp-a',
                    'purl_name': 'pkg:npm/left-pad',
                    'name': 'left-pad',
                    'ecosystem': 'npm',
                    'status': None,
                    'version_count': 1,
                    'project_count': 2,
                },
                {
                    'id': 'cmp-b',
                    'purl_name': 'pkg:pypi/requests',
                    'name': 'requests',
                    'ecosystem': 'pypi',
                    'status': 'deprecated',
                    'version_count': 4,
                    'project_count': 9,
                },
            ],
        ]
        response = self.client.get(self._components('/'), params={'q': 'RE'})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            [row['purl_name'] for row in body['data']],
            ['pkg:pypi/requests', 'pkg:npm/left-pad'],
        )
        self.assertEqual(body['data'][0]['status'], 'deprecated')
        self.assertEqual(body['total'], 2)

    def test_catalog_totals_only_on_the_unfiltered_request(self) -> None:
        self.mock_db.execute.side_effect = [
            [],
            [
                {'ecosystem': 'npm', 'total': 120},
                {'ecosystem': 'pypi', 'total': 45},
            ],
        ]
        body = self.client.get(self._components('/')).json()
        self.assertEqual(body['ecosystem_totals'], {'npm': 120, 'pypi': 45})
        self.assertEqual(self.mock_db.execute.await_count, 2)

    def test_filtered_search_skips_the_catalog_scan(self) -> None:
        """The totals restate a constant; a keystroke must not rescan."""
        self.mock_db.execute.side_effect = [[]]
        body = self.client.get(
            self._components('/'), params={'q': 'express'}
        ).json()
        self.assertEqual(body['ecosystem_totals'], {})
        self.assertEqual(self.mock_db.execute.await_count, 1)

    def test_query_is_lowercased_for_case_insensitive_match(self) -> None:
        self.mock_db.execute.side_effect = [[], []]
        self.client.get(self._components('/'), params={'q': '  ExPrEsS '})
        self.assertEqual(self._params(0)['q'], 'express')

    def test_limit_is_capped(self) -> None:
        self.mock_db.execute.side_effect = [
            [
                {
                    'id': f'cmp-{index}',
                    'purl_name': f'pkg:npm/p{index}',
                    'name': f'p{index}',
                    'ecosystem': 'npm',
                    'status': None,
                    'version_count': 1,
                    'project_count': 1,
                }
                for index in range(5)
            ],
            [],
        ]
        response = self.client.get(self._components('/'), params={'limit': 2})
        body = response.json()
        self.assertEqual(len(body['data']), 2)
        self.assertEqual(body['total'], 5)


class ComponentUsageTestCase(_ComponentsTestBase):
    """GET /components/{id}/usage"""

    def _respond(
        self,
        *,
        component_status: str | None = None,
        usage_rows: list[dict[str, typing.Any]] | None = None,
        version_rows: list[dict[str, typing.Any]] | None = None,
        advisories: list[dict[str, typing.Any]] | None = None,
        note_counts: list[dict[str, typing.Any]] | None = None,
    ) -> None:
        self.mock_db.execute.side_effect = [
            [{'cid': COMPONENT_ID}],
            [
                {
                    'id': COMPONENT_ID,
                    'purl_name': 'pkg:npm/express',
                    'name': 'express',
                    'ecosystem': 'npm',
                    'description': 'Fast web framework',
                    'status': component_status,
                    'status_at': '2026-06-01T00:00:00+00:00'
                    if component_status
                    else None,
                    'status_by': 'bob@example.com'
                    if component_status
                    else None,
                    'version_count': 2,
                }
            ],
            usage_rows if usage_rows is not None else [_usage_row()],
            version_rows if version_rows is not None else [_version_row()],
            advisories or [],
            note_counts or [],
        ]

    def test_groups_projects_and_environments_by_version(self) -> None:
        self._respond(
            usage_rows=[
                _usage_row(),
                _usage_row(
                    environment_name='Staging',
                    environment_slug='staging',
                ),
                _usage_row(
                    project_id='proj-2',
                    project_name='Auth API',
                    project_slug='auth-api',
                ),
            ]
        )
        response = self.client.get(self._components(f'/{COMPONENT_ID}/usage'))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['project_count'], 2)
        self.assertEqual(body['version_count'], 2)
        self.assertEqual(body['deployed_version_count'], 1)
        self.assertEqual(body['newest_deployed_version'], '4.18.2')
        version = body['versions'][0]
        self.assertEqual(version['project_count'], 2)
        self.assertEqual(
            [chip['name'] for chip in version['environments']],
            ['Production', 'Staging'],
        )
        self.assertEqual(
            [chip['count'] for chip in version['environments']], [2, 1]
        )
        self.assertEqual(
            sorted(p['name'] for p in version['projects']),
            ['Auth API', 'Billing API'],
        )
        self.assertEqual(
            version['projects'][1]['environments'],
            ['Production', 'Staging'],
        )

    def test_component_mark_is_inherited_by_versions(self) -> None:
        self._respond(component_status='forbidden')
        body = self.client.get(
            self._components(f'/{COMPONENT_ID}/usage')
        ).json()
        version = body['versions'][0]
        self.assertIsNone(version['status'])
        self.assertEqual(version['effective_status'], 'forbidden')
        self.assertTrue(version['status_inherited'])
        self.assertEqual(body['vulnerable_project_count'], 1)

    def test_version_mark_is_not_inherited(self) -> None:
        self._respond(
            version_rows=[
                _version_row(
                    version_status='deprecated',
                    version_status_at='2026-06-02T00:00:00+00:00',
                    version_status_by='bob@example.com',
                )
            ]
        )
        version = self.client.get(
            self._components(f'/{COMPONENT_ID}/usage')
        ).json()['versions'][0]
        self.assertEqual(version['status'], 'deprecated')
        self.assertEqual(version['effective_status'], 'deprecated')
        self.assertFalse(version['status_inherited'])

    def test_undeployed_version_still_listed(self) -> None:
        self._respond(
            usage_rows=[],
            version_rows=[
                _version_row(),
                _version_row(
                    component_release_id=RELEASE_B,
                    version='5.0.0',
                    first_seen='2026-07-01T00:00:00+00:00',
                ),
            ],
        )
        body = self.client.get(
            self._components(f'/{COMPONENT_ID}/usage')
        ).json()
        self.assertEqual(len(body['versions']), 2)
        # Newest-first by first-seen, not by version string.
        self.assertEqual(body['versions'][0]['version'], '5.0.0')
        self.assertEqual(body['deployed_version_count'], 0)
        self.assertIsNone(body['newest_deployed_version'])

    def test_advisories_and_note_counts_are_attached(self) -> None:
        self._respond(
            advisories=[
                {
                    'component_release_id': RELEASE_A,
                    'cve_id': 'CVE-2025-0002',
                    'url': 'https://example.com/2',
                    'title': None,
                    'created_by': 'bob@example.com',
                    'created_at': '2026-06-01T00:00:00+00:00',
                },
                {
                    'component_release_id': RELEASE_A,
                    'cve_id': 'CVE-2025-0001',
                    'url': 'https://example.com/1',
                    'title': 'Prototype pollution',
                    'created_by': 'bob@example.com',
                    'created_at': '2026-06-01T00:00:00+00:00',
                },
            ],
            note_counts=[{'component_release_id': RELEASE_A, 'note_count': 3}],
        )
        body = self.client.get(
            self._components(f'/{COMPONENT_ID}/usage')
        ).json()
        version = body['versions'][0]
        self.assertEqual(
            [a['cve_id'] for a in version['advisories']],
            ['CVE-2025-0001', 'CVE-2025-0002'],
        )
        self.assertEqual(version['note_count'], 3)
        # A current version carrying a CVE still counts as vulnerable.
        self.assertIsNone(version['effective_status'])
        self.assertEqual(body['vulnerable_project_count'], 1)

    def test_component_outside_org_is_404(self) -> None:
        self.mock_db.execute.side_effect = [[]]
        response = self.client.get(self._components(f'/{COMPONENT_ID}/usage'))
        self.assertEqual(response.status_code, 404)


class ComponentStatusTestCase(_ComponentsTestBase):
    """PUT/DELETE /components/{id}/status"""

    def test_set_writes_the_triple(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'cid': COMPONENT_ID}],
            [{'id': COMPONENT_ID}],
        ]
        response = self.client.put(
            self._components(f'/{COMPONENT_ID}/status'),
            json={'status': 'forbidden'},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['status'], 'forbidden')
        self.assertEqual(body['status_by'], 'alice@example.com')
        self.assertIsNotNone(body['status_at'])
        params = self._params(1)
        self.assertEqual(params['status'], 'forbidden')
        self.assertEqual(params['status_by'], 'alice@example.com')

    def test_clear_nulls_the_triple(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'cid': COMPONENT_ID}],
            [{'id': COMPONENT_ID}],
        ]
        response = self.client.delete(
            self._components(f'/{COMPONENT_ID}/status')
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNone(body['status'])
        self.assertIsNone(body['status_at'])
        self.assertIsNone(body['status_by'])
        params = self._params(1)
        self.assertIsNone(params['status'])
        self.assertIsNone(params['status_at'])
        self.assertIsNone(params['status_by'])

    def test_rejects_unknown_status(self) -> None:
        response = self.client.put(
            self._components(f'/{COMPONENT_ID}/status'),
            json={'status': 'blocked'},
        )
        self.assertEqual(response.status_code, 422)

    def test_missing_component_is_404(self) -> None:
        self.mock_db.execute.side_effect = [[{'cid': COMPONENT_ID}], []]
        response = self.client.put(
            self._components(f'/{COMPONENT_ID}/status'),
            json={'status': 'deprecated'},
        )
        self.assertEqual(response.status_code, 404)


class ComponentReleaseStatusTestCase(_ComponentsTestBase):
    """PUT/DELETE /component-releases/{id}/status"""

    def test_set_writes_the_triple(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'cid': RELEASE_A}],
            [{'id': RELEASE_A}],
        ]
        response = self.client.put(
            self._versions(f'/{RELEASE_A}/status'),
            json={'status': 'deprecated'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'deprecated')
        self.assertEqual(self._params(1)['status'], 'deprecated')

    def test_clear_nulls_the_triple(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'cid': RELEASE_A}],
            [{'id': RELEASE_A}],
        ]
        response = self.client.delete(self._versions(f'/{RELEASE_A}/status'))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['status'])

    def test_version_outside_org_is_404(self) -> None:
        self.mock_db.execute.side_effect = [[]]
        response = self.client.put(
            self._versions(f'/{RELEASE_A}/status'),
            json={'status': 'deprecated'},
        )
        self.assertEqual(response.status_code, 404)


class ComponentNotesTestCase(_ComponentsTestBase):
    """GET/POST /component-releases/{id}/notes"""

    def test_list_is_oldest_first(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'cid': RELEASE_A}],
            [
                {
                    'id': 'note-2',
                    'author': 'bob@example.com',
                    'body': 'Second',
                    'created_at': '2026-06-02T00:00:00+00:00',
                },
                {
                    'id': 'note-1',
                    'author': 'alice@example.com',
                    'body': 'First',
                    'created_at': '2026-06-01T00:00:00+00:00',
                },
            ],
        ]
        body = self.client.get(self._versions(f'/{RELEASE_A}/notes')).json()
        self.assertEqual([note['body'] for note in body], ['First', 'Second'])

    def test_create_uses_the_principal_as_author(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'cid': RELEASE_A}],
            [{'id': 'note-3'}],
        ]
        response = self.client.post(
            self._versions(f'/{RELEASE_A}/notes'),
            json={'body': 'Migrate to 5.x'},
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['author'], 'alice@example.com')
        self.assertEqual(body['body'], 'Migrate to 5.x')
        self.assertEqual(self._params(1)['author'], 'alice@example.com')

    def test_empty_body_is_rejected(self) -> None:
        response = self.client.post(
            self._versions(f'/{RELEASE_A}/notes'), json={'body': ''}
        )
        self.assertEqual(response.status_code, 422)


class ComponentAdvisoriesTestCase(_ComponentsTestBase):
    """GET/PUT/DELETE /component-releases/{id}/advisories"""

    def test_upsert_normalizes_the_identifier(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'cid': RELEASE_A}],
            [{'cve_id': 'CVE-2025-1234'}],
        ]
        response = self.client.put(
            self._versions(f'/{RELEASE_A}/advisories/cve-2025-1234'),
            json={'url': 'https://example.com/x', 'title': 'RCE'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['cve_id'], 'CVE-2025-1234')
        self.assertEqual(self._params(1)['cve_id'], 'CVE-2025-1234')

    def test_upsert_merges_one_node_per_cve(self) -> None:
        """Two versions of the same CVE MERGE onto one Advisory node."""
        self.mock_db.execute.side_effect = [
            [{'cid': RELEASE_A}],
            [{'cve_id': 'CVE-2025-1234'}],
            [{'cid': RELEASE_B}],
            [{'cve_id': 'CVE-2025-1234'}],
        ]
        for release_id in (RELEASE_A, RELEASE_B):
            self.client.put(
                self._versions(f'/{release_id}/advisories/CVE-2025-1234'),
                json={'url': 'https://example.com/x'},
            )
        for index in (1, 3):
            self.assertIn('MERGE (a:Advisory', self._query(index))
            self.assertIn(
                'a.created_by = COALESCE(a.created_by', self._query(index)
            )
            self.assertEqual(self._params(index)['cve_id'], 'CVE-2025-1234')

    def test_delete_detaches_then_collects_orphan(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'cid': RELEASE_A}],
            [{'deleted': 1}],
            [],
        ]
        response = self.client.delete(
            self._versions(f'/{RELEASE_A}/advisories/CVE-2025-1234')
        )
        self.assertEqual(response.status_code, 204)
        self.assertIn('DELETE e', self._query(1))
        self.assertIn('NOT EXISTS', self._query(2))

    def test_list_sorts_by_identifier(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'cid': RELEASE_A}],
            [
                {
                    'cve_id': 'CVE-2025-0002',
                    'url': 'https://example.com/2',
                    'title': None,
                    'created_by': 'bob@example.com',
                    'created_at': '2026-06-01T00:00:00+00:00',
                },
                {
                    'cve_id': 'CVE-2025-0001',
                    'url': 'https://example.com/1',
                    'title': None,
                    'created_by': 'bob@example.com',
                    'created_at': '2026-06-01T00:00:00+00:00',
                },
            ],
        ]
        body = self.client.get(
            self._versions(f'/{RELEASE_A}/advisories')
        ).json()
        self.assertEqual(
            [advisory['cve_id'] for advisory in body],
            ['CVE-2025-0001', 'CVE-2025-0002'],
        )


class ProblemPackagesTestCase(_ComponentsTestBase):
    """GET /reports/problem-packages"""

    def _url(self) -> str:
        return f'/organizations/{ORG}/reports/problem-packages'

    def test_environments_collapse_into_one_row(self) -> None:
        self.mock_db.execute.side_effect = [
            [
                _problem_row(),
                _problem_row(
                    environment_name='Staging',
                    environment_slug='staging',
                ),
            ],
            [],
            [],
        ]
        body = self.client.get(self._url()).json()
        self.assertEqual(len(body['rows']), 1)
        row = body['rows'][0]
        self.assertEqual(
            [chip['name'] for chip in row['environments']],
            ['Production', 'Staging'],
        )
        self.assertEqual(row['status'], 'forbidden')
        self.assertFalse(row['status_inherited'])
        self.assertFalse(body['truncated'])

    def test_same_version_in_two_projects_is_two_rows(self) -> None:
        self.mock_db.execute.side_effect = [
            [
                _problem_row(),
                _problem_row(
                    project_id='proj-2',
                    project_name='Auth API',
                    project_slug='auth-api',
                ),
            ],
            [],
            [],
        ]
        body = self.client.get(self._url()).json()
        self.assertEqual(
            [row['project_name'] for row in body['rows']],
            ['Auth API', 'Billing API'],
        )

    def test_component_mark_marks_the_row_inherited(self) -> None:
        self.mock_db.execute.side_effect = [
            [_problem_row(component_status='deprecated', version_status=None)],
            [],
            [],
        ]
        row = self.client.get(self._url()).json()['rows'][0]
        self.assertEqual(row['status'], 'deprecated')
        self.assertTrue(row['status_inherited'])

    def test_current_version_with_advisory_is_a_finding(self) -> None:
        self.mock_db.execute.side_effect = [
            [_problem_row(version_status=None)],
            [
                {
                    'component_release_id': RELEASE_A,
                    'cve_id': 'CVE-2025-1234',
                    'url': 'https://example.com/x',
                    'title': None,
                    'created_by': 'bob@example.com',
                    'created_at': '2026-06-01T00:00:00+00:00',
                }
            ],
            [{'component_release_id': RELEASE_A, 'note_count': 2}],
        ]
        rows = self.client.get(self._url()).json()['rows']
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['status'])
        self.assertEqual(rows[0]['advisories'][0]['cve_id'], 'CVE-2025-1234')
        self.assertEqual(rows[0]['note_count'], 2)

    def test_current_version_without_advisory_is_dropped(self) -> None:
        """A stale advisory edge can leave a row with nothing to report."""
        self.mock_db.execute.side_effect = [
            [_problem_row(version_status=None)],
            [],
            [],
        ]
        self.assertEqual(self.client.get(self._url()).json()['rows'], [])


class ComponentPermissionsTestCase(_ComponentsTestBase):
    """Permission gating on the component endpoints."""

    permissions_granted: typing.ClassVar[set[str]] = {'component:read'}

    def test_read_only_may_read_the_report(self) -> None:
        self.mock_db.execute.side_effect = [[], [], []]
        response = self.client.get(
            f'/organizations/{ORG}/reports/problem-packages'
        )
        self.assertEqual(response.status_code, 200)

    def test_read_only_may_not_mark_a_component(self) -> None:
        response = self.client.put(
            self._components(f'/{COMPONENT_ID}/status'),
            json={'status': 'forbidden'},
        )
        self.assertEqual(response.status_code, 403)

    def test_read_only_may_not_mark_a_version(self) -> None:
        response = self.client.put(
            self._versions(f'/{RELEASE_A}/status'),
            json={'status': 'forbidden'},
        )
        self.assertEqual(response.status_code, 403)

    def test_read_only_may_not_add_a_note(self) -> None:
        response = self.client.post(
            self._versions(f'/{RELEASE_A}/notes'), json={'body': 'nope'}
        )
        self.assertEqual(response.status_code, 403)

    def test_read_only_may_not_record_an_advisory(self) -> None:
        response = self.client.put(
            self._versions(f'/{RELEASE_A}/advisories/CVE-2025-1234'),
            json={'url': 'https://example.com/x'},
        )
        self.assertEqual(response.status_code, 403)


class ComponentReadDeniedTestCase(_ComponentsTestBase):
    """A principal with neither permission gets nothing."""

    permissions_granted: typing.ClassVar[set[str]] = set()

    def test_search_is_denied(self) -> None:
        response = self.client.get(self._components('/'))
        self.assertEqual(response.status_code, 403)

    def test_usage_is_denied(self) -> None:
        response = self.client.get(self._components(f'/{COMPONENT_ID}/usage'))
        self.assertEqual(response.status_code, 403)
