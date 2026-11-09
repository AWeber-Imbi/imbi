"""Org-wide ClickHouse reads split project IDs into batches (#593).

ClickHouse rejects a form field over 131072 bytes, and one
``Array(String)`` of every project ID in a large organization is
longer than that.  Each test here gives enough IDs to need more than
one batch and checks that the rows of all batches merge correctly.
"""

import datetime
import typing
import unittest
from unittest import mock

from imbi.api import component_facts
from imbi.api.endpoints import dashboard, pull_requests, scoring
from imbi.common import clickhouse

#: 3000 IDs of 21 characters: 75000 bytes, more than one batch.
PIDS = [f'project-{n:013d}' for n in range(3000)]
T0 = datetime.datetime(2026, 1, 1)  # noqa: DTZ001 -- ClickHouse is naive

Rows = list[dict[str, typing.Any]]


def _index(pid: str) -> int:
    return int(pid[-4:])


def _db(*results: Rows) -> mock.MagicMock:
    db = mock.MagicMock()
    db.execute = mock.AsyncMock(side_effect=list(results))
    return db


class _BatchTestCase(unittest.IsolatedAsyncioTestCase):
    def _patch(
        self, rows: typing.Callable[[str, list[str]], Rows]
    ) -> mock.AsyncMock:
        def query(sql: str, parameters: dict[str, typing.Any]) -> Rows:
            return rows(sql, parameters.get('project_ids', []))

        mocked = mock.AsyncMock(side_effect=query)
        patcher = mock.patch.object(clickhouse, 'query', mocked)
        patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def assert_batched(self, mocked: mock.AsyncMock, queries: int = 1) -> None:
        batches = len(clickhouse.project_id_batches(PIDS))
        self.assertGreater(batches, 1)
        self.assertEqual(mocked.await_count, batches * queries)


class ScoringTestCase(_BatchTestCase):
    def _dims(self) -> mock.MagicMock:
        return _db([{'project_id': p, 'dim_key': 'team-a'} for p in PIDS])

    async def test_rollup(self) -> None:
        mocked = self._patch(
            lambda _sql, ids: [
                {
                    'project_id': p,
                    'latest_score': float(_index(p)),
                    'last_updated': None,
                }
                for p in ids
            ]
        )
        rows = await scoring.score_rollup(self._dims(), None, 'org')  # type: ignore[arg-type]
        self.assert_batched(mocked)
        self.assertEqual(rows[0].latest_score, 2999.0)
        self.assertEqual(rows[0].avg_score, 1499.5)

    async def test_monthly_improvement(self) -> None:
        mocked = self._patch(
            lambda _sql, ids: [{'project_id': p, 'score': 1.0} for p in ids]
        )
        rows = await scoring.score_monthly_improvement(
            self._dims(),
            None,  # type: ignore[arg-type]
            'org',
            year=2026,
            month=1,
        )
        self.assert_batched(mocked, queries=2)
        self.assertEqual(rows[0].project_count, len(PIDS))

    async def test_history_by_team(self) -> None:
        mocked = self._patch(
            lambda _sql, ids: [
                {'ts': T0, 'project_id': p, 'score': float(_index(p))}
                for p in ids
            ]
        )
        result = await scoring.score_history_by_team(
            self._dims(),
            None,  # type: ignore[arg-type]
            'org',
        )
        self.assert_batched(mocked)
        self.assertEqual(result.teams[0].points[0].score, 1499.5)

    async def test_history_feed_keeps_newest_overall(self) -> None:
        def rows(_sql: str, ids: list[str]) -> Rows:
            # Each batch returns its own newest three, as LIMIT would.
            newest = sorted(ids, key=_index, reverse=True)[:3]
            return [
                {
                    'timestamp': T0 + datetime.timedelta(seconds=_index(p)),
                    'project_id': p,
                    'score': 1.0,
                    'previous_score': None,
                    'change_reason': '',
                }
                for p in newest
            ]

        mocked = self._patch(rows)
        db = _db(
            [
                {'project_id': p, 'project_name': p, 'team_slug': 't'}
                for p in PIDS
            ]
        )
        events = await scoring.score_history_feed(
            db,
            None,  # type: ignore[arg-type]
            'org',
            limit=3,
        )
        self.assert_batched(mocked)
        self.assertEqual([e.project_id for e in events], PIDS[-1:-4:-1])


def _pr(pid: str, **extra: typing.Any) -> dict[str, typing.Any]:
    return {
        'project_id': pid,
        'pr_id': f'pr-{pid}',
        'pr_number': 1,
        'title': 't',
        'url': 'u',
        'state': 'open',
        'author': 'alice',
        'draft': False,
        'merged': False,
        'created_at': T0 + datetime.timedelta(seconds=_index(pid)),
        'updated_at': T0,
        'additions': 0,
        'deletions': 0,
        'changed_files': 0,
        **extra,
    }


class PullRequestsTestCase(_BatchTestCase):
    async def test_list_pages_across_batches(self) -> None:
        def rows(sql: str, ids: list[str]) -> Rows:
            if 'count()' in sql:
                return [{'total': len(ids), 'project_count': len(ids)}]
            return [_pr(p) for p in ids]

        mocked = self._patch(rows)
        result = await pull_requests._list_prs(
            project_ids=PIDS, limit=2, offset=1
        )
        self.assert_batched(mocked, queries=2)
        self.assertEqual(result.total, len(PIDS))
        self.assertEqual(result.project_count, len(PIDS))
        self.assertEqual(
            [pr.project_id for pr in result.data], [PIDS[-2], PIDS[-3]]
        )

    async def test_pending_deploy_keeps_oldest_overall(self) -> None:
        mocked = self._patch(
            lambda _sql, ids: [
                _pr(
                    p,
                    merged_at=T0 - datetime.timedelta(seconds=_index(p)),
                    last_deployed_at=T0 - datetime.timedelta(days=1),
                )
                for p in ids
            ]
        )
        rows = await pull_requests._list_pending_deploy(
            project_ids=PIDS,
            environment_slugs=['production'],
            author=None,
            since=T0,
        )
        self.assert_batched(mocked)
        self.assertEqual(len(rows), pull_requests.PENDING_DEPLOY_LIMIT)
        self.assertEqual(rows[0].project_id, PIDS[-1])

    async def test_activity_adds_counts_per_author(self) -> None:
        mocked = self._patch(
            lambda _sql, ids: [
                {
                    'author': 'alice',
                    'created_count': len(ids),
                    'open_count': len(ids),
                    'closed_count': 0,
                    'merged_count': 0,
                }
            ]
        )
        rows = await pull_requests._fetch_pr_activity(PIDS, T0)
        self.assert_batched(mocked)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['created_count'], len(PIDS))


class DashboardTestCase(_BatchTestCase):
    async def test_pull_request_series_adds_batches(self) -> None:
        today = datetime.datetime.now(datetime.UTC).date()
        mocked = self._patch(
            lambda sql, ids: [{'day': today, 'c': len(ids)}]
            if 'pull_requests' in sql
            else []
        )
        metrics = await dashboard.get_dashboard_metrics(
            _db([{'id': p} for p in PIDS]),
            None,  # type: ignore[arg-type]
        )
        batches = len(clickhouse.project_id_batches(PIDS))
        self.assertGreater(batches, 1)
        self.assertEqual(mocked.await_count, batches + 3)
        self.assertEqual(metrics.pull_requests.total, len(PIDS))


class ComponentFactsTestCase(_BatchTestCase):
    async def test_ids_in_org_union(self) -> None:
        mocked = self._patch(
            lambda _sql, ids: [{'component_id': ids[0]}, {'component_id': 'x'}]
        )
        found = await component_facts.component_ids_in_org(PIDS)
        self.assert_batched(mocked)
        self.assertEqual(len(found), len(mocked.await_args_list) + 1)

    async def test_in_org_hit_in_a_later_batch(self) -> None:
        mocked = self._patch(
            lambda _sql, ids: [{'hit': 1}] if PIDS[-1] in ids else []
        )
        self.assertTrue(await component_facts.component_in_org(PIDS, 'c'))
        self.assertTrue(
            await component_facts.component_release_in_org(PIDS, 'c', 'r')
        )
        self.assert_batched(mocked, queries=2)

    async def test_search_counts_merge(self) -> None:
        mocked = self._patch(
            lambda _sql, ids: [
                {
                    'component_id': 'c',
                    'versions': ['1.0', ids[0]],
                    'project_count': len(ids),
                }
            ]
        )
        counts = await component_facts.search_counts(PIDS, ['c'])
        self.assert_batched(mocked)
        batches = mocked.await_count
        self.assertEqual(counts, {'c': (batches + 1, len(PIDS))})

    async def test_ecosystem_totals_merge(self) -> None:
        mocked = self._patch(
            lambda _sql, ids: [
                {'ecosystem': 'npm', 'components': ['shared', ids[0]]}
            ]
        )
        totals = await component_facts.ecosystem_totals(PIDS)
        self.assert_batched(mocked)
        self.assertEqual(totals, {'npm': mocked.await_count + 1})
