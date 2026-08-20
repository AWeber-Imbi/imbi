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


def _synthetic_release_id(row: dict[str, typing.Any]) -> str:
    """The release a pointer row would really name.

    A release belongs to one project and pins one version of a given
    component, so two pointer rows agreeing on both are the same
    project running the same release in two environments -- one
    release id, two pointers. Keying on the row's position instead
    would give every pointer its own release, and the fan-out the
    handler performs when ClickHouse returns its ``DISTINCT`` row per
    release would never run under test.
    """
    return f'rel-{row["project_id"]}-{row["component_release_id"]}'


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
        # The usage facts live in ClickHouse now, so every read here is
        # a graph call for identity and governance plus a ClickHouse
        # call for "which ids". Both are mocked, and the tests assert
        # on the parameters each was given rather than on the SQL,
        # which no unit test can execute.
        # A bare probe answers "yes, in the org": most tests here are
        # about what the endpoint does once that check has passed, and
        # the ones that are about the check queue their own results.
        self.mock_ch = mock.AsyncMock(return_value=[{'hit': 1}])
        ch_patcher = mock.patch('imbi.common.clickhouse.query', self.mock_ch)
        ch_patcher.start()
        self.addCleanup(ch_patcher.stop)
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

    def _ch_results(self, *results: list[dict[str, typing.Any]]) -> None:
        """Queue one result set per ClickHouse call, in order."""
        self.mock_ch.side_effect = list(results)

    def _ch_params(self, index: int) -> dict[str, typing.Any]:
        """Return the params of the n-th ClickHouse call."""
        return typing.cast(
            'dict[str, typing.Any]',
            self.mock_ch.await_args_list[index].args[1],
        )

    def _projects(self, *ids: str) -> list[dict[str, typing.Any]]:
        """Rows shaped like the org project set query returns."""
        return [{'project_id': project_id} for project_id in ids]


class SearchComponentsTestCase(_ComponentsTestBase):
    """GET /components

    Two graph reads -- the org project set, then the name match -- and
    then ClickHouse for membership and counts. The name match no longer
    carries the org traversal, so the graph half is bounded by the
    catalog's name index and the org half never leaves ClickHouse.
    """

    def _hits(self, *names: str) -> list[dict[str, typing.Any]]:
        return [
            {
                'id': f'cmp-{name}',
                'purl_name': f'pkg:npm/{name}',
                'name': name,
                'ecosystem': 'npm',
                'status': None,
            }
            for name in names
        ]

    def test_search_ranks_by_how_the_name_matched(self) -> None:
        """Exact, then prefix, then substring -- not by project count.

        The counts belong to the page the search picked, so they cannot
        also be what picks it.
        """
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
            [
                {
                    'id': 'cmp-a',
                    'purl_name': 'pkg:npm/requests-mock',
                    'name': 'requests-mock',
                    'ecosystem': 'npm',
                    'status': None,
                },
                {
                    'id': 'cmp-b',
                    'purl_name': 'pkg:pypi/requests',
                    'name': 'requests',
                    'ecosystem': 'pypi',
                    'status': 'deprecated',
                },
            ],
        ]
        self._ch_results(
            [{'component_id': 'cmp-a'}, {'component_id': 'cmp-b'}],
            [
                {
                    'component_id': 'cmp-a',
                    'version_count': 1,
                    'project_count': 9,
                },
                {
                    'component_id': 'cmp-b',
                    'version_count': 4,
                    'project_count': 2,
                },
            ],
        )
        response = self.client.get(
            self._components('/'), params={'q': 'REQUESTS'}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        # cmp-a has the higher project count and still sorts second:
        # 'requests' matches the query exactly.
        self.assertEqual(
            [row['purl_name'] for row in body['data']],
            ['pkg:pypi/requests', 'pkg:npm/requests-mock'],
        )
        self.assertEqual(body['data'][0]['status'], 'deprecated')
        self.assertEqual(body['data'][0]['version_count'], 4)
        self.assertEqual(body['data'][0]['project_count'], 2)
        self.assertEqual(body['total'], 2)

    def test_a_name_match_outside_the_org_is_not_returned(self) -> None:
        """Membership is the ClickHouse intersection, nothing else.

        The name clause matches the whole catalog now, so dropping the
        intersection would leak every organization's packages into
        every other organization's search.
        """
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
            self._hits('express', 'expressive'),
        ]
        self._ch_results([{'component_id': 'cmp-express'}], [])
        body = self.client.get(
            self._components('/'), params={'q': 'express'}
        ).json()
        self.assertEqual([row['name'] for row in body['data']], ['express'])
        # ``total`` counts what the reader may see, so the intersection
        # has to precede it rather than only trimming the page.
        self.assertEqual(body['total'], 1)

    def test_membership_is_narrowed_to_the_name_matches(self) -> None:
        """A keystroke intersects its own candidates, not the catalog.

        Asking ClickHouse for every component the org depends on and
        discarding all but a handful would make the aggregate grow with
        the org rather than with the query.
        """
        self.mock_db.execute.side_effect = [
            self._projects('proj-1', 'proj-2'),
            self._hits('express', 'expressive'),
        ]
        self._ch_results([], [])
        self.client.get(self._components('/'), params={'q': 'express'})
        self.assertEqual(
            self._ch_params(0)['component_ids'],
            ['cmp-express', 'cmp-expressive'],
        )
        self.assertEqual(
            self._ch_params(0)['project_ids'], ['proj-1', 'proj-2']
        )

    def test_counts_are_gathered_only_for_the_returned_page(self) -> None:
        """Phase two is bounded by the ids phase one settled on."""
        hits = self._hits(*[f'p{index}' for index in range(5)])
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
            hits,
        ]
        self._ch_results(
            [{'component_id': row['id']} for row in hits],
            [],
        )
        self.client.get(self._components('/'), params={'limit': 2, 'q': 'p'})
        self.assertEqual(
            self._ch_params(1)['component_ids'], ['cmp-p0', 'cmp-p1']
        )

    def test_a_hit_with_no_counted_rows_reports_zero(self) -> None:
        """A component phase two says nothing about is not a 500."""
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
            self._hits('express'),
        ]
        self._ch_results([{'component_id': 'cmp-express'}], [])
        body = self.client.get(
            self._components('/'), params={'q': 'express'}
        ).json()
        self.assertEqual(body['data'][0]['version_count'], 0)
        self.assertEqual(body['data'][0]['project_count'], 0)

    def test_catalog_totals_only_on_the_unfiltered_request(self) -> None:
        """An empty query costs one graph read, and it is the cheap one.

        The screen shows recently-viewed packages rather than a slice
        of the catalog when the box is empty, so walking the catalog to
        build that slice would be work whose result is discarded.
        """
        self.mock_db.execute.side_effect = [self._projects('proj-1')]
        self._ch_results(
            [
                {'ecosystem': 'npm', 'total': 120},
                {'ecosystem': 'pypi', 'total': 45},
            ],
        )
        body = self.client.get(self._components('/')).json()
        self.assertEqual(body['ecosystem_totals'], {'npm': 120, 'pypi': 45})
        self.assertEqual(body['data'], [])
        self.assertEqual(self.mock_db.execute.await_count, 1)

    def test_catalog_totals_are_scoped_to_the_organization(self) -> None:
        """The chips count what the org depends on, not the catalog.

        This scoping was traded away when the totals were a graph
        traversal, because traversing to the org cost 36.5s against
        1.07s. The ClickHouse aggregate is org-scoped and still cheap,
        so the chips describe the reader's organization again.
        """
        self.mock_db.execute.side_effect = [self._projects('proj-1', 'proj-2')]
        self._ch_results([])
        self.client.get(self._components('/'))
        self.assertEqual(
            self._ch_params(0)['project_ids'], ['proj-1', 'proj-2']
        )

    def test_ecosystem_filter_keeps_the_catalog_totals(self) -> None:
        """The totals are what the ecosystem chips count.

        Dropping them once a chip is selected would empty the control
        the reader just used.
        """
        self.mock_db.execute.side_effect = [self._projects('proj-1')]
        self._ch_results(
            [
                {'ecosystem': 'npm', 'total': 120},
                {'ecosystem': 'pypi', 'total': 45},
            ],
        )
        body = self.client.get(
            self._components('/'), params={'ecosystem': 'npm'}
        ).json()
        self.assertEqual(body['ecosystem_totals'], {'npm': 120, 'pypi': 45})
        self.assertEqual(body['data'], [])

    def test_filtered_search_skips_the_catalog_scan(self) -> None:
        """The totals restate a constant; a keystroke must not rescan."""
        self.mock_db.execute.side_effect = [self._projects('proj-1'), []]
        body = self.client.get(
            self._components('/'), params={'q': 'express'}
        ).json()
        self.assertEqual(body['ecosystem_totals'], {})
        self.assertEqual(self.mock_db.execute.await_count, 2)

    def test_an_org_with_no_projects_finds_nothing(self) -> None:
        """No project set means no membership, so no ClickHouse read.

        The catalog name match still runs -- the query is non-empty --
        and the intersection it feeds is what comes back empty.
        """
        self.mock_db.execute.side_effect = [[], self._hits('express')]
        body = self.client.get(
            self._components('/'), params={'q': 'express'}
        ).json()
        self.assertEqual(body['data'], [])
        self.assertEqual(body['total'], 0)
        self.mock_ch.assert_not_awaited()

    def test_query_is_lowercased_for_case_insensitive_match(self) -> None:
        self.mock_db.execute.side_effect = [self._projects('proj-1'), []]
        self.client.get(self._components('/'), params={'q': '  ExPrEsS '})
        self.assertEqual(self._params(1)['q'], 'express')

    def test_limit_is_capped(self) -> None:
        hits = self._hits(*[f'p{index}' for index in range(5)])
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
            hits,
        ]
        self._ch_results(
            [{'component_id': row['id']} for row in hits],
            [],
        )
        response = self.client.get(
            self._components('/'), params={'limit': 2, 'q': 'p'}
        )
        body = response.json()
        self.assertEqual(len(body['data']), 2)
        # ``total`` counts every match, not the page -- the dropdown
        # says "N more matches, keep typing to narrow".
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
        """Queue both stores for one usage request.

        *usage_rows* are deployment pointer rows now -- project, team,
        and environment, keyed by the release deployed there. Which of
        those releases carry a version of the package is the ClickHouse
        half, and the handler re-joins the two into the cross-product
        the traversal used to return, so the folding under test is
        unchanged.
        """
        pointers = usage_rows if usage_rows is not None else [_usage_row()]
        for row in pointers:
            row.setdefault('release_id', _synthetic_release_id(row))
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
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
            version_rows if version_rows is not None else [_version_row()],
            pointers,
            advisories or [],
            note_counts or [],
        ]
        # ``component_usage`` selects DISTINCT, so a release deployed
        # to two environments yields one row however many pointers
        # name it. Emitting one per pointer would hand the handler a
        # pre-expanded cross-product and hide the re-join.
        usage = {
            (row['release_id'], row['component_release_id']): {
                'release_id': row['release_id'],
                'component_release_id': row['component_release_id'],
                'version': row['version'],
            }
            for row in pointers
        }
        self._ch_results([{'hit': 1}], list(usage.values()))

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
        self.assertEqual(body['versions'][0]['version'], '5.0.0')
        self.assertEqual(body['deployed_version_count'], 0)
        self.assertIsNone(body['newest_deployed_version'])

    def _version_order(self, *versions: str) -> list[str]:
        self._respond(
            usage_rows=[],
            version_rows=[
                _version_row(
                    component_release_id=f'crel{index}nanoid',
                    version=version,
                )
                for index, version in enumerate(versions)
            ],
        )
        body = self.client.get(
            self._components(f'/{COMPONENT_ID}/usage')
        ).json()
        return [version['version'] for version in body['versions']]

    def test_versions_sort_numerically(self) -> None:
        # A string sort puts 4.23.0 below 4.9.0.
        self.assertEqual(
            self._version_order('4.9.0', '4.23.0'), ['4.23.0', '4.9.0']
        )

    def test_prerelease_sorts_below_its_release(self) -> None:
        self.assertEqual(
            self._version_order('1.0.0', '1.0.0-rc1'), ['1.0.0', '1.0.0-rc1']
        )

    def test_a_non_decimal_digit_does_not_raise(self) -> None:
        # ``isdigit`` accepts superscripts that ``int()`` rejects, so
        # the comparator tests ``isdecimal``. It must sort oddly rather
        # than 500.
        self.assertEqual(
            sorted(self._version_order('1.\u00b2.0', '1.0.0')),
            ['1.0.0', '1.\u00b2.0'],
        )

    def test_build_metadata_does_not_demote_a_release(self) -> None:
        # SemVer gives build metadata no bearing on precedence, so it
        # must not read as a pre-release suffix.
        self.assertEqual(
            self._version_order('1.0.0-rc1', '1.0.0+build.5'),
            ['1.0.0+build.5', '1.0.0-rc1'],
        )

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
        # The membership check runs alongside the three reads it
        # guards rather than ahead of them, so all four are mocked.
        self.mock_db.execute.side_effect = [[], [], [], []]
        response = self.client.get(self._components(f'/{COMPONENT_ID}/usage'))
        self.assertEqual(response.status_code, 404)


class ComponentStatusTestCase(_ComponentsTestBase):
    """PUT/DELETE /components/{id}/status"""

    def test_set_writes_the_triple(self) -> None:
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
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
            self._projects('proj-1'),
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
        self.mock_db.execute.side_effect = [self._projects('proj-1'), []]
        response = self.client.put(
            self._components(f'/{COMPONENT_ID}/status'),
            json={'status': 'deprecated'},
        )
        self.assertEqual(response.status_code, 404)


class ComponentReleaseStatusTestCase(_ComponentsTestBase):
    """PUT/DELETE /component-releases/{id}/status"""

    def test_set_writes_the_triple(self) -> None:
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
            [{'component_id': COMPONENT_ID}],
            [{'id': RELEASE_A}],
        ]
        response = self.client.put(
            self._versions(f'/{RELEASE_A}/status'),
            json={'status': 'deprecated'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'deprecated')
        self.assertEqual(self._params(2)['status'], 'deprecated')

    def test_clear_nulls_the_triple(self) -> None:
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
            [{'component_id': COMPONENT_ID}],
            [{'id': RELEASE_A}],
        ]
        response = self.client.delete(self._versions(f'/{RELEASE_A}/status'))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['status'])

    def test_version_outside_org_is_404(self) -> None:
        """The version exists; nothing the org deploys uses it."""
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
            [{'component_id': COMPONENT_ID}],
        ]
        self._ch_results([])
        response = self.client.put(
            self._versions(f'/{RELEASE_A}/status'),
            json={'status': 'deprecated'},
        )
        self.assertEqual(response.status_code, 404)

    def test_unknown_version_is_404_without_probing(self) -> None:
        """No owning component means no sort-key prefix to seek on.

        "No such version" and "version you cannot see" stay the same
        404 they have always been, and the probe is skipped rather than
        run against an id ClickHouse could only answer no to.
        """
        self.mock_db.execute.side_effect = [self._projects('proj-1'), []]
        response = self.client.put(
            self._versions(f'/{RELEASE_A}/status'),
            json={'status': 'deprecated'},
        )
        self.assertEqual(response.status_code, 404)
        self.mock_ch.assert_not_awaited()


class ComponentNotesTestCase(_ComponentsTestBase):
    """GET/POST /component-releases/{id}/notes"""

    def test_list_is_oldest_first(self) -> None:
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
            [{'component_id': COMPONENT_ID}],
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
            self._projects('proj-1'),
            [{'component_id': COMPONENT_ID}],
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
        self.assertEqual(self._params(2)['author'], 'alice@example.com')

    def test_create_strips_the_body(self) -> None:
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
            [{'component_id': COMPONENT_ID}],
            [{'id': 'note-4'}],
        ]
        response = self.client.post(
            self._versions(f'/{RELEASE_A}/notes'),
            json={'body': '  Migrate to 5.x  '},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['body'], 'Migrate to 5.x')

    def test_empty_body_is_rejected(self) -> None:
        response = self.client.post(
            self._versions(f'/{RELEASE_A}/notes'), json={'body': ''}
        )
        self.assertEqual(response.status_code, 422)

    def test_whitespace_only_body_is_rejected(self) -> None:
        response = self.client.post(
            self._versions(f'/{RELEASE_A}/notes'), json={'body': '   '}
        )
        self.assertEqual(response.status_code, 422)

    def test_oversized_body_is_rejected(self) -> None:
        response = self.client.post(
            self._versions(f'/{RELEASE_A}/notes'), json={'body': 'x' * 2001}
        )
        self.assertEqual(response.status_code, 422)


class ComponentAdvisoriesTestCase(_ComponentsTestBase):
    """GET/PUT/DELETE /component-releases/{id}/advisories"""

    def test_upsert_normalizes_the_identifier(self) -> None:
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
            [{'component_id': COMPONENT_ID}],
            [{'cve_id': 'CVE-2025-1234'}],
        ]
        response = self.client.put(
            self._versions(f'/{RELEASE_A}/advisories/cve-2025-1234'),
            json={'url': 'https://example.com/x', 'title': 'RCE'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['cve_id'], 'CVE-2025-1234')
        self.assertEqual(self._params(2)['cve_id'], 'CVE-2025-1234')

    def test_upsert_merges_one_node_per_cve(self) -> None:
        """Two versions of the same CVE MERGE onto one Advisory node."""
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
            [{'component_id': COMPONENT_ID}],
            [{'cve_id': 'CVE-2025-1234'}],
            self._projects('proj-1'),
            [{'component_id': COMPONENT_ID}],
            [{'cve_id': 'CVE-2025-1234'}],
        ]
        for release_id in (RELEASE_A, RELEASE_B):
            self.client.put(
                self._versions(f'/{release_id}/advisories/CVE-2025-1234'),
                json={'url': 'https://example.com/x'},
            )
        for index in (2, 5):
            self.assertIn('MERGE (a:Advisory', self._query(index))
            self.assertIn(
                'a.created_by = COALESCE(a.created_by', self._query(index)
            )
            self.assertEqual(self._params(index)['cve_id'], 'CVE-2025-1234')

    def test_upsert_rejects_a_non_http_url(self) -> None:
        response = self.client.put(
            self._versions(f'/{RELEASE_A}/advisories/CVE-2025-1234'),
            json={'url': 'javascript:alert(1)'},
        )
        self.assertEqual(response.status_code, 422)

    def test_delete_detaches_then_collects_orphan(self) -> None:
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
            [{'component_id': COMPONENT_ID}],
            [{'deleted': 1}],
            [],
        ]
        response = self.client.delete(
            self._versions(f'/{RELEASE_A}/advisories/CVE-2025-1234')
        )
        self.assertEqual(response.status_code, 204)
        self.assertIn('DELETE e', self._query(2))
        self.assertIn('NOT EXISTS', self._query(3))
        self.assertIn('DETACH DELETE a', self._query(3))

    def test_delete_skips_the_gc_when_no_edge_matched(self) -> None:
        """An unattached advisory must not trigger an orphan sweep."""
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
            [{'component_id': COMPONENT_ID}],
            [],
        ]
        response = self.client.delete(
            self._versions(f'/{RELEASE_A}/advisories/CVE-2025-1234')
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.mock_db.execute.call_count, 3)

    def test_list_sorts_by_identifier(self) -> None:
        self.mock_db.execute.side_effect = [
            self._projects('proj-1'),
            [{'component_id': COMPONENT_ID}],
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


#: Which columns of a report row the graph supplies. The rest are the
#: deployment pointer's -- project, team, environment -- and the two
#: halves meet on a release id that only ClickHouse can match up.
_GOVERNED_KEYS = frozenset(
    {
        'component_id',
        'purl_name',
        'component_name',
        'ecosystem',
        'component_status',
        'component_release_id',
        'version',
        'version_status',
    }
)


class ProblemPackagesTestCase(_ComponentsTestBase):
    """GET /reports/problem-packages"""

    def _url(self) -> str:
        return f'/organizations/{ORG}/reports/problem-packages'

    def _queue(
        self,
        *rows: dict[str, typing.Any],
        advisories: list[dict[str, typing.Any]] | None = None,
        note_counts: list[dict[str, typing.Any]] | None = None,
    ) -> None:
        """Split report rows back into the two stores they come from.

        Each row here is one (version, project, environment) finding,
        which is what the traversal used to return whole. The governed
        half goes to the graph, the deployment half to the pointer
        read, and ClickHouse says which release joins them -- so the
        folding under test still sees the same cross-product.
        """
        governed: dict[str, dict[str, typing.Any]] = {}
        pointers: list[dict[str, typing.Any]] = []
        usages: dict[tuple[str, str], dict[str, typing.Any]] = {}
        for row in rows:
            release_id = _synthetic_release_id(row)
            governed[row['component_release_id']] = {
                key: value
                for key, value in row.items()
                if key in _GOVERNED_KEYS
            }
            pointers.append(
                {
                    key: value
                    for key, value in row.items()
                    if key not in _GOVERNED_KEYS
                }
                | {'release_id': release_id}
            )
            # ``governed_usage`` selects DISTINCT, so the two findings
            # a release deployed to two environments produces collapse
            # to one ClickHouse row and the handler fans them back out.
            usages[release_id, row['component_release_id']] = {
                'release_id': release_id,
                'component_id': row['component_id'],
                'component_release_id': row['component_release_id'],
                'version': row['version'],
            }
        self.mock_db.execute.side_effect = [
            list(governed.values()),
            pointers,
            advisories or [],
            note_counts or [],
        ]
        self._ch_results(list(usages.values()))

    def test_environments_collapse_into_one_row(self) -> None:
        self._queue(
            _problem_row(),
            _problem_row(
                environment_name='Staging',
                environment_slug='staging',
            ),
        )
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
        self._queue(
            _problem_row(),
            _problem_row(
                project_id='proj-2',
                project_name='Auth API',
                project_slug='auth-api',
            ),
        )
        body = self.client.get(self._url()).json()
        self.assertEqual(
            [row['project_name'] for row in body['rows']],
            ['Auth API', 'Billing API'],
        )

    def test_rows_sort_on_a_version_key_not_lexically(self) -> None:
        """``4.9.0`` is below ``4.23.0``, which a string sort inverts.

        The report's whole job is telling an operator which version
        they are running, so ordering two versions of one package
        backwards is the one thing it must not do.
        """
        self._queue(
            _problem_row(component_release_id='cr-9', version='4.9.0'),
            _problem_row(component_release_id='cr-23', version='4.23.0'),
        )
        body = self.client.get(self._url()).json()
        self.assertEqual(
            [row['version'] for row in body['rows']], ['4.9.0', '4.23.0']
        )

    def test_a_governed_version_nothing_deploys_is_not_a_row(self) -> None:
        """The report describes what is running, not what is marked."""
        self.mock_db.execute.side_effect = [
            [_problem_row()],
            [],
            [],
            [],
        ]
        self._ch_results([])
        self.assertEqual(self.client.get(self._url()).json()['rows'], [])

    def test_component_mark_marks_the_row_inherited(self) -> None:
        self._queue(
            _problem_row(component_status='deprecated', version_status=None)
        )
        row = self.client.get(self._url()).json()['rows'][0]
        self.assertEqual(row['status'], 'deprecated')
        self.assertTrue(row['status_inherited'])

    def test_current_version_with_advisory_is_a_finding(self) -> None:
        self._queue(
            _problem_row(version_status=None),
            advisories=[
                {
                    'component_release_id': RELEASE_A,
                    'cve_id': 'CVE-2025-1234',
                    'url': 'https://example.com/x',
                    'title': None,
                    'created_by': 'bob@example.com',
                    'created_at': '2026-06-01T00:00:00+00:00',
                }
            ],
            note_counts=[{'component_release_id': RELEASE_A, 'note_count': 2}],
        )
        rows = self.client.get(self._url()).json()['rows']
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['status'])
        self.assertEqual(rows[0]['advisories'][0]['cve_id'], 'CVE-2025-1234')
        self.assertEqual(rows[0]['note_count'], 2)

    def test_current_version_without_advisory_is_dropped(self) -> None:
        """A stale advisory edge can leave a row with nothing to report."""
        self._queue(_problem_row(version_status=None))
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
