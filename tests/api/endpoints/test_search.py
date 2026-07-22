"""Tests for the org-scoped vector similarity search endpoint."""

import datetime
import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from imbi.api import models
from imbi.api.auth import permissions
from imbi.api.endpoints import search as search_endpoint
from imbi.common import graph
from imbi.common.graph.client import SearchResult
from tests.api import support

_ORG_SLUG = 'test-org'
_BASE_URL = f'/organizations/{_ORG_SLUG}/search'


class SearchEndpointTestCase(support.SharedAppTestCase):
    def setUp(self) -> None:
        admin_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        auth_context = permissions.AuthContext(
            user=admin_user,
            session_id='test-session',
            auth_method='jwt',
            permissions={'search:read'},
        )

        async def mock_get_current_user():
            return auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

        # Enrichment issues its own db.execute calls after the scope/search
        # loop; stub it out so these tests can keep a fixed execute sequence
        # for just the org-enumeration queries. Enrichment has dedicated
        # coverage in EnrichResultsTestCase.
        enrich_patcher = mock.patch(
            'imbi.api.endpoints.search._enrich_results',
        )
        self.mock_enrich = enrich_patcher.start()
        self.addCleanup(enrich_patcher.stop)

        self.client = TestClient(self.test_app)

    def _make_result(
        self,
        node_label: str = 'Project',
        node_id: str = 'proj-1',
        attribute: str = 'description',
        chunk_text: str = 'a sample description',
        distance: float = 0.12,
    ) -> SearchResult:
        return SearchResult(
            node_label=node_label,
            node_id=node_id,
            attribute=attribute,
            chunk_text=chunk_text,
            distance=distance,
        )

    def _setup_org(self, node_ids: list[str] | None = None) -> None:
        """Configure mock_db.execute for the org-membership queries.

        The search handler calls db.execute in this order:
          1. org lookup -> [{org_id: ...}] or []
          2. direct BELONGS_TO children -> [{nid: ...}, ...]
          3. Project nodes -> [{nid: ...}, ...]
          4. Document nodes -> []
          5. Release nodes -> []
          6. Comment nodes -> []
          7. Component nodes -> []
        """
        if node_ids is None:
            node_ids = ['proj-1']
        self.mock_db.execute.side_effect = [
            [{'org_id': '"org-abc"'}],
            [],
            [{'nid': f'"{nid}"'} for nid in node_ids],
            [],
            [],
            [],
            [],
        ]

    def _setup_org_not_found(self) -> None:
        self.mock_db.execute.side_effect = [[]]

    def test_basic_search(self) -> None:
        self._setup_org()
        self.mock_db.search.return_value = [self._make_result()]
        response = self.client.get(f'{_BASE_URL}?q=api+gateway')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['node_label'], 'Project')
        self.assertEqual(data[0]['node_id'], 'proj-1')
        self.assertEqual(data[0]['attribute'], 'description')
        self.assertAlmostEqual(data[0]['distance'], 0.12)
        # The handler enriches results for UI routing before returning.
        self.mock_enrich.assert_awaited_once()

    def test_archived_projects_excluded_from_scope(self) -> None:
        """Each project-traversing scope query filters out archived projects.

        The org lookup and the direct BELONGS_TO query do not traverse a
        Project, so they must not carry the filter; the Project, Document,
        Release, Comment, and Component queries must.
        """
        self._setup_org()
        self.mock_db.search.return_value = []
        self.client.get(f'{_BASE_URL}?q=test')
        queries = [c.args[0] for c in self.mock_db.execute.call_args_list]
        archived_clause = 'coalesce(p.archived, false) = false'
        # The org lookup and the direct BELONGS_TO query do not traverse a
        # Project, so they must not carry the filter.
        self.assertNotIn(archived_clause, queries[0])
        self.assertNotIn(archived_clause, queries[1])
        # Every subsequent project-traversing query must carry the filter.
        for query in queries[2:]:
            self.assertIn(archived_clause, query)

    def test_org_not_found_returns_404(self) -> None:
        self._setup_org_not_found()
        response = self.client.get(f'{_BASE_URL}?q=foo')
        self.assertEqual(response.status_code, 404)

    def test_node_ids_pushed_to_db_search(self) -> None:
        """Org node ids are forwarded to ``db.search`` (SQL filter, C7).

        With C7 the org enumeration is pushed into the pgvector query via
        the ``node_ids`` kwarg, so the endpoint never post-filters by org
        in Python. The mock therefore mirrors what the real SQL would
        return: only in-org rows.
        """
        self._setup_org(node_ids=['proj-1'])
        self.mock_db.search.return_value = [
            self._make_result(node_id='proj-1', distance=0.10),
        ]
        response = self.client.get(f'{_BASE_URL}?q=test')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['node_id'], 'proj-1')
        # _get_org_node_ids enumerates the org node itself plus the Project.
        call_kwargs = self.mock_db.search.call_args.kwargs
        self.assertEqual(set(call_kwargs['node_ids']), {'org-abc', 'proj-1'})

    def test_passes_query_to_db_search(self) -> None:
        self._setup_org()
        self.mock_db.search.return_value = []
        self.client.get(f'{_BASE_URL}?q=hello+world')
        self.mock_db.search.assert_awaited_once()
        call_args = self.mock_db.search.call_args
        self.assertEqual(call_args.args[0], 'hello world')

    def test_node_label_filter(self) -> None:
        self._setup_org()
        self.mock_db.search.return_value = []
        self.client.get(f'{_BASE_URL}?q=foo&node_label=Team')
        call_kwargs = self.mock_db.search.call_args.kwargs
        self.assertEqual(call_kwargs['node_label'], 'Team')

    def test_attribute_filter_pushed_to_db_search(self) -> None:
        """attribute is pushed into db.search, not post-filtered."""
        self._setup_org(node_ids=['a'])
        # db.search does the attribute filtering server-side, so the mock
        # returns only the matching row.
        self.mock_db.search.return_value = [
            self._make_result(node_id='a', attribute='name'),
        ]
        response = self.client.get(f'{_BASE_URL}?q=foo&attribute=name')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['node_id'], 'a')
        self.assertEqual(
            self.mock_db.search.call_args.kwargs['attribute'], 'name'
        )

    def test_attribute_defaults_to_none(self) -> None:
        """No attribute query param passes attribute=None to db.search."""
        self._setup_org()
        self.mock_db.search.return_value = []
        self.client.get(f'{_BASE_URL}?q=foo')
        self.assertIsNone(self.mock_db.search.call_args.kwargs['attribute'])

    def test_initial_batch_at_least_limit(self) -> None:
        """First db.search call uses at least limit rows."""
        self._setup_org()
        self.mock_db.search.return_value = []
        self.client.get(f'{_BASE_URL}?q=foo&limit=10')
        call_kwargs = self.mock_db.search.call_args.kwargs
        self.assertGreaterEqual(call_kwargs['limit'], 10)

    def test_paged_loop_fetches_more_when_needed(self) -> None:
        """When the first batch dedups under limit, a second is fetched.

        With C7 the SQL filter eliminates out-of-org rows, so the only way the
        post-fetch loop can return fewer distinct results than the batch size
        is chunk-level duplicates: the same ``node_id`` appearing across
        multiple ``(node_id, attribute, chunk)`` rows.
        """
        self._setup_org(node_ids=['a', 'b'])
        # 50 rows that all collapse to a single distinct node id after dedup.
        first = [
            self._make_result(node_id='a', distance=float(i) / 100)
            for i in range(50)
        ]
        second = [self._make_result(node_id='b', distance=0.99)]
        self.mock_db.search.side_effect = [first, second]
        response = self.client.get(f'{_BASE_URL}?q=test&limit=2')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([r['node_id'] for r in data], ['a', 'b'])
        self.assertEqual(self.mock_db.search.await_count, 2)

    def test_stops_when_result_set_exhausted(self) -> None:
        """Loop stops when db.search returns fewer rows than requested."""
        self._setup_org(node_ids=['proj-1'])
        # Return a single in-org row (less than the batch size); ensures
        # we don't loop forever even when limit > available results.
        self.mock_db.search.return_value = [
            self._make_result(node_id='proj-1', distance=0.2),
        ]
        response = self.client.get(f'{_BASE_URL}?q=test&limit=5')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(self.mock_db.search.await_count, 1)

    def test_threshold_param(self) -> None:
        self._setup_org()
        self.mock_db.search.return_value = []
        self.client.get(f'{_BASE_URL}?q=foo&threshold=0.5')
        call_kwargs = self.mock_db.search.call_args.kwargs
        self.assertAlmostEqual(call_kwargs['distance_threshold'], 0.5)

    def test_model_param(self) -> None:
        self._setup_org()
        self.mock_db.search.return_value = []
        self.client.get(f'{_BASE_URL}?q=foo&model=code')
        call_kwargs = self.mock_db.search.call_args.kwargs
        self.assertEqual(call_kwargs['model_name'], 'code')

    def test_empty_query_rejected(self) -> None:
        response = self.client.get(f'{_BASE_URL}?q=')
        self.assertEqual(response.status_code, 422)

    def test_limit_too_large_rejected(self) -> None:
        response = self.client.get(f'{_BASE_URL}?q=foo&limit=101')
        self.assertEqual(response.status_code, 422)

    def test_limit_zero_rejected(self) -> None:
        response = self.client.get(f'{_BASE_URL}?q=foo&limit=0')
        self.assertEqual(response.status_code, 422)

    def test_missing_query_param_rejected(self) -> None:
        response = self.client.get(_BASE_URL)
        self.assertEqual(response.status_code, 422)

    def test_multiple_results_preserved_in_order(self) -> None:
        self._setup_org(node_ids=['a', 'b', 'c'])
        self.mock_db.search.return_value = [
            self._make_result(node_id='b', distance=0.15),
            self._make_result(node_id='a', distance=0.05),
            self._make_result(node_id='c', distance=0.30),
        ]
        response = self.client.get(f'{_BASE_URL}?q=test')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 3)
        self.assertEqual(data[0]['node_id'], 'b')
        self.assertEqual(data[1]['node_id'], 'a')
        self.assertEqual(data[2]['node_id'], 'c')

    def test_limit_truncates_after_org_filter(self) -> None:
        self._setup_org(node_ids=['a', 'b', 'c'])
        self.mock_db.search.return_value = [
            self._make_result(node_id='a', distance=0.05),
            self._make_result(node_id='b', distance=0.10),
            self._make_result(node_id='c', distance=0.20),
        ]
        response = self.client.get(f'{_BASE_URL}?q=test&limit=2')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['node_id'], 'a')
        self.assertEqual(data[1]['node_id'], 'b')

    def test_no_filter_defaults(self) -> None:
        self._setup_org()
        self.mock_db.search.return_value = []
        self.client.get(f'{_BASE_URL}?q=test')
        call_kwargs = self.mock_db.search.call_args.kwargs
        self.assertIsNone(call_kwargs['node_label'])
        self.assertIsNone(call_kwargs['distance_threshold'])
        self.assertEqual(call_kwargs['model_name'], 'text')

    def test_threshold_too_high_rejected(self) -> None:
        response = self.client.get(f'{_BASE_URL}?q=foo&threshold=2.1')
        self.assertEqual(response.status_code, 422)

    def test_threshold_negative_rejected(self) -> None:
        response = self.client.get(f'{_BASE_URL}?q=foo&threshold=-0.1')
        self.assertEqual(response.status_code, 422)

    def test_threshold_boundary_values_accepted(self) -> None:
        self._setup_org()
        self.mock_db.search.return_value = []
        response = self.client.get(f'{_BASE_URL}?q=foo&threshold=0.0')
        self.assertEqual(response.status_code, 200)
        self._setup_org()
        response = self.client.get(f'{_BASE_URL}?q=foo&threshold=2.0')
        self.assertEqual(response.status_code, 200)

    def test_falsy_org_id_and_nids_skipped(self) -> None:
        """parse_agtype returning falsy for org_id or any nid skips it."""
        # org_id is falsy ('') so org node is not added to the set,
        # but the org IS found (non-empty list returned).
        # BELONGS_TO and Document/Release return falsy nids; Projects is valid.
        self.mock_db.execute.side_effect = [
            [{'org_id': '""'}],  # org found but parse_agtype -> ''
            [{'nid': '""'}],  # BELONGS_TO: falsy nid skipped
            [{'nid': '"proj-1"'}],  # Project: valid nid included
            [{'nid': '""'}],  # Document: falsy nid skipped
            [{'nid': '""'}],  # Release: falsy nid skipped
            [{'nid': '""'}],  # Comment: falsy nid skipped
            [{'nid': '""'}],  # Component: falsy nid skipped
        ]
        self.mock_db.search.return_value = [
            self._make_result(node_id='proj-1'),
        ]
        response = self.client.get(f'{_BASE_URL}?q=test')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['node_id'], 'proj-1')

    def test_belongs_to_node_ids_included(self) -> None:
        """Nodes returned by the BELONGS_TO query are included in org scope."""
        self.mock_db.execute.side_effect = [
            [{'org_id': '"org-abc"'}],
            [{'nid': '"team-1"'}],  # BELONGS_TO child (e.g. Team)
            [],  # Projects
            [],  # Documents
            [],  # Releases
            [],  # Comments
            [],  # Components
        ]
        self.mock_db.search.return_value = [
            self._make_result(node_id='team-1', node_label='Team'),
        ]
        response = self.client.get(f'{_BASE_URL}?q=test')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['node_id'], 'team-1')

    def test_document_node_ids_included(self) -> None:
        """Document ATTACHED_TO query nodes are included in org scope."""
        self.mock_db.execute.side_effect = [
            [{'org_id': '"org-abc"'}],
            [],  # BELONGS_TO
            [],  # Projects
            [{'nid': '"doc-1"'}],  # Documents
            [],  # Releases
            [],  # Comments
            [],  # Components
        ]
        self.mock_db.search.return_value = [
            self._make_result(node_id='doc-1', node_label='Document'),
        ]
        response = self.client.get(f'{_BASE_URL}?q=test')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['node_id'], 'doc-1')

    def test_release_node_ids_included(self) -> None:
        """Nodes returned by the Release HAS_RELEASE query are in org scope."""
        self.mock_db.execute.side_effect = [
            [{'org_id': '"org-abc"'}],
            [],  # BELONGS_TO
            [],  # Projects
            [],  # Documents
            [{'nid': '"rel-1"'}],  # Releases
            [],  # Comments
            [],  # Components
        ]
        self.mock_db.search.return_value = [
            self._make_result(node_id='rel-1', node_label='Release'),
        ]
        response = self.client.get(f'{_BASE_URL}?q=test')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['node_id'], 'rel-1')

    def test_comment_node_ids_included(self) -> None:
        """Comment IN_THREAD query nodes are included in org scope."""
        self.mock_db.execute.side_effect = [
            [{'org_id': '"org-abc"'}],
            [],  # BELONGS_TO
            [],  # Projects
            [],  # Documents
            [],  # Releases
            [{'nid': '"comment-1"'}],  # Comments
            [],  # Components
        ]
        self.mock_db.search.return_value = [
            self._make_result(
                node_id='comment-1',
                node_label='Comment',
                attribute='body',
            ),
        ]
        response = self.client.get(f'{_BASE_URL}?q=test')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['node_id'], 'comment-1')

    def test_component_node_ids_included(self) -> None:
        """Component dependency-graph query nodes are in org scope."""
        self.mock_db.execute.side_effect = [
            [{'org_id': '"org-abc"'}],
            [],  # BELONGS_TO
            [],  # Projects
            [],  # Documents
            [],  # Releases
            [],  # Comments
            [{'nid': '"comp-1"'}],  # Components
        ]
        self.mock_db.search.return_value = [
            self._make_result(node_id='comp-1', node_label='Component'),
        ]
        response = self.client.get(f'{_BASE_URL}?q=test')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['node_id'], 'comp-1')

    def test_limit_reached_mid_batch_stops_inner_loop(self) -> None:
        """Inner loop breaks early when limit is reached mid-batch."""
        self._setup_org(node_ids=['a', 'b', 'c'])
        # Three in-org results in one batch; limit=2 should stop after 'b'.
        self.mock_db.search.return_value = [
            self._make_result(node_id='a', distance=0.1),
            self._make_result(node_id='b', distance=0.2),
            self._make_result(node_id='c', distance=0.3),
        ]
        response = self.client.get(f'{_BASE_URL}?q=test&limit=2')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['node_id'], 'a')
        self.assertEqual(data[1]['node_id'], 'b')
        # Only one search call needed because the limit was met in the batch.
        self.assertEqual(self.mock_db.search.await_count, 1)

    def test_duplicate_node_id_across_batches_deduped(self) -> None:
        """A node seen in an earlier batch is skipped if it recurs.

        The handler tracks emitted ``node_id``s in ``seen`` so the same
        node returned across two growth batches is counted once. Batch 1
        emits ``a`` then fills the rest with duplicate chunk rows for the
        same node id (so the batch is full and a second fetch is triggered);
        batch 2 returns ``a`` again (deduped) plus ``b`` to reach the limit.
        """
        from imbi.api.endpoints.search import _INITIAL_BATCH

        self._setup_org(node_ids=['a', 'b'])
        batch_one = [
            self._make_result(node_id='a', distance=float(i + 1) / 100)
            for i in range(_INITIAL_BATCH)
        ]
        batch_two = [
            self._make_result(node_id='a', distance=0.01),
            self._make_result(node_id='b', distance=0.02),
        ]
        self.mock_db.search.side_effect = [batch_one, batch_two]
        response = self.client.get(f'{_BASE_URL}?q=test&limit=2')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([r['node_id'] for r in data], ['a', 'b'])
        self.assertEqual(self.mock_db.search.await_count, 2)

    def test_project_falsy_nid_skipped(self) -> None:
        """A falsy nid from the Project query is skipped."""
        self.mock_db.execute.side_effect = [
            [{'org_id': '"org-abc"'}],
            [],  # BELONGS_TO
            [{'nid': '""'}],  # Project: falsy nid skipped
            [],  # Documents
            [],  # Releases
            [],  # Comments
            [],  # Components
        ]
        self.mock_db.search.return_value = []
        response = self.client.get(f'{_BASE_URL}?q=test')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_while_exits_at_condition_after_full_batch(self) -> None:
        """While loop exits at condition when limit is met and batch was full.

        When limit results are found mid-batch (inner break fires) but the
        batch was not exhausted (len(raw) >= batch_size), the code re-enters
        the while condition check, which is now false, and exits cleanly.
        """
        from imbi.api.endpoints.search import _INITIAL_BATCH

        self._setup_org(node_ids=['target'])
        # Return exactly _INITIAL_BATCH (50) rows; the first emits ``target``
        # and the rest are duplicate-chunk rows for the same node. After dedup
        # we have one distinct node, the inner ``break`` fires once limit=1
        # is met, and the while condition then exits without a second fetch.
        batch = [
            self._make_result(node_id='target', distance=float(i + 1) / 100)
            for i in range(_INITIAL_BATCH)
        ]
        self.mock_db.search.return_value = batch
        response = self.client.get(f'{_BASE_URL}?q=test&limit=1')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['node_id'], 'target')
        # Only one db.search call (limit met mid-batch, no second call needed).
        self.assertEqual(self.mock_db.search.await_count, 1)


def _ag(value: object) -> str:
    """Encode a Python value the way db.execute returns an agtype scalar."""
    return 'null' if value is None else json.dumps(value)


class EnrichResultsTestCase(unittest.IsolatedAsyncioTestCase):
    """Direct coverage for _enrich_results (name/slug/project_id)."""

    def setUp(self) -> None:
        # node_id -> base properties (name/slug/title) by graph label.
        self.base = {
            'proj-1': {'name': 'Kafka', 'slug': 'kafka', 'title': None},
            'team-1': {'name': 'Platform', 'slug': 'platform', 'title': None},
            'doc-1': {'name': None, 'slug': None, 'title': 'SSL Runbook'},
            'rel-1': {'name': None, 'slug': None, 'title': 'v2.1.0'},
        }
        # child node_id -> parent project id.
        self.parents = {'doc-1': 'proj-1', 'rel-1': 'proj-1'}

        def fake_execute(query, params=None, columns=None, raw=False):
            ids = (params or {}).get('ids', [])
            if 'project_id' in query:
                return [
                    {'id': _ag(i), 'project_id': _ag(self.parents[i])}
                    for i in ids
                    if i in self.parents
                ]
            return [
                {
                    'id': _ag(i),
                    'name': _ag(self.base[i]['name']),
                    'slug': _ag(self.base[i]['slug']),
                    'title': _ag(self.base[i]['title']),
                }
                for i in ids
                if i in self.base
            ]

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.mock_db.execute.side_effect = fake_execute

    @staticmethod
    def _result(node_label: str, node_id: str) -> search_endpoint.SearchResult:
        return search_endpoint.SearchResult(
            node_label=node_label,
            node_id=node_id,
            attribute='description',
            chunk_text='…',
            distance=0.1,
        )

    async def test_empty_results_short_circuits(self) -> None:
        await search_endpoint._enrich_results(self.mock_db, [])
        self.mock_db.execute.assert_not_awaited()

    async def test_node_name_and_slug(self) -> None:
        results = [self._result('Project', 'proj-1')]
        await search_endpoint._enrich_results(self.mock_db, results)
        self.assertEqual(results[0].name, 'Kafka')
        self.assertEqual(results[0].slug, 'kafka')
        self.assertIsNone(results[0].project_id)

    async def test_document_uses_title_and_parent_project(self) -> None:
        results = [self._result('Document', 'doc-1')]
        await search_endpoint._enrich_results(self.mock_db, results)
        self.assertEqual(results[0].name, 'SSL Runbook')
        self.assertIsNone(results[0].slug)
        self.assertEqual(results[0].project_id, 'proj-1')

    async def test_release_uses_title_and_parent_project(self) -> None:
        results = [self._result('Release', 'rel-1')]
        await search_endpoint._enrich_results(self.mock_db, results)
        self.assertEqual(results[0].name, 'v2.1.0')
        self.assertEqual(results[0].project_id, 'proj-1')

    async def test_mixed_labels_enriched_together(self) -> None:
        results = [
            self._result('Project', 'proj-1'),
            self._result('Team', 'team-1'),
            self._result('Document', 'doc-1'),
        ]
        await search_endpoint._enrich_results(self.mock_db, results)
        by_id = {r.node_id: r for r in results}
        self.assertEqual(by_id['team-1'].slug, 'platform')
        self.assertEqual(by_id['doc-1'].project_id, 'proj-1')
        self.assertIsNone(by_id['proj-1'].project_id)

    async def test_unresolved_node_leaves_fields_none(self) -> None:
        results = [self._result('Tag', 'tag-missing')]
        await search_endpoint._enrich_results(self.mock_db, results)
        self.assertIsNone(results[0].name)
        self.assertIsNone(results[0].slug)
        self.assertIsNone(results[0].project_id)


if __name__ == '__main__':
    unittest.main()
