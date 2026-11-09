"""Tests for project endpoint helper functions.

Covers the private helpers added in the release-committish work:
``_fetch_pr_counts``, ``_resolve_display_names``,
``_fetch_current_releases`` and ``lookup_ops_log_performed_by``.
"""

import datetime
import json
import typing
import unittest
from unittest import mock

from imbi.api.endpoints import projects


class FetchPrCountsTestCase(unittest.IsolatedAsyncioTestCase):
    """Coverage for ``_fetch_pr_counts``."""

    async def test_empty_project_ids_short_circuits(self) -> None:
        self.assertEqual(await projects._fetch_pr_counts([]), {})

    async def test_returns_counts_without_viewer(self) -> None:
        rows = [
            {
                'project_id': 'p1',
                'open_count': 3,
                'closed_count': 1,
                'viewer_open_count': 0,
                'viewer_closed_count': 0,
            }
        ]
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(return_value=rows)
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=ch,
        ):
            result = await projects._fetch_pr_counts(['p1'])
        self.assertEqual(result, {'p1': (3, 1, 0, 0)})
        # No viewer param when viewer is None
        called_sql = ch.query.call_args.args[0]
        called_params = ch.query.call_args.kwargs['parameters']
        self.assertNotIn('viewer', called_params)
        self.assertIn('0 AS viewer_open_count', called_sql)
        self.assertIn('AND NOT draft', called_sql)

    async def test_returns_counts_with_viewer(self) -> None:
        rows = [
            {
                'project_id': 'p1',
                'open_count': 5,
                'closed_count': 4,
                'viewer_open_count': 2,
                'viewer_closed_count': 1,
            }
        ]
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(return_value=rows)
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=ch,
        ):
            result = await projects._fetch_pr_counts(
                ['p1'], viewer='alice@example.com'
            )
        self.assertEqual(result, {'p1': (5, 4, 2, 1)})
        called_sql = ch.query.call_args.args[0]
        called_params = ch.query.call_args.kwargs['parameters']
        self.assertEqual(called_params['viewer'], 'alice@example.com')
        self.assertIn('viewer_open_count', called_sql)
        self.assertIn('AND NOT draft', called_sql)

    async def test_swallows_clickhouse_errors(self) -> None:
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(side_effect=RuntimeError('boom'))
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=ch,
        ):
            result = await projects._fetch_pr_counts(['p1'])
        self.assertEqual(result, {})


class ProjectIdBatchingTestCase(unittest.IsolatedAsyncioTestCase):
    """Large orgs split project IDs across queries (#529)."""

    #: 25 bytes per 21-character nanoid, so 4000 IDs is ~100 KB, over
    #: the 64 KB budget.
    PIDS: typing.ClassVar[list[str]] = [f'{n:021d}' for n in range(4000)]

    @staticmethod
    def _echo(
        sql: str, parameters: dict[str, typing.Any]
    ) -> list[dict[str, typing.Any]]:
        if 'pull_requests' in sql:
            return [
                {
                    'project_id': pid,
                    'open_count': 1,
                    'closed_count': 0,
                    'viewer_open_count': 0,
                    'viewer_closed_count': 0,
                }
                for pid in parameters['project_ids']
            ]
        if 'FROM commits FINAL' in sql and 'LIMIT 1 BY' in sql:
            return [
                {'project_id': pid, 'sha': 'a' * 40}
                for pid in parameters['project_ids']
            ]
        return []

    async def test_pr_counts_batch_and_merge(self) -> None:
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(side_effect=self._echo)
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=ch,
        ):
            result = await projects._fetch_pr_counts(self.PIDS)
        self.assertGreater(ch.query.await_count, 1)
        self.assertEqual(set(result), set(self.PIDS))

    async def test_pr_counts_failed_batch_degrades_only_itself(self) -> None:
        calls = {'n': 0}

        def query(
            sql: str, parameters: dict[str, typing.Any]
        ) -> list[dict[str, typing.Any]]:
            calls['n'] += 1
            if calls['n'] == 1:
                raise RuntimeError('Field value too long')
            return self._echo(sql, parameters)

        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(side_effect=query)
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=ch,
        ):
            result = await projects._fetch_pr_counts(self.PIDS)
        self.assertTrue(result)
        self.assertLess(len(result), len(self.PIDS))

    async def test_small_org_makes_one_pr_count_query(self) -> None:
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(side_effect=self._echo)
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=ch,
        ):
            await projects._fetch_pr_counts(self.PIDS[:10])
        self.assertEqual(ch.query.await_count, 1)

    async def test_release_summaries_batch_and_merge(self) -> None:
        query = mock.AsyncMock(side_effect=self._echo)
        with mock.patch('imbi.api.endpoints.projects.clickhouse.query', query):
            result = await projects._fetch_release_summaries(self.PIDS)
        head_calls = [
            c for c in query.await_args_list if 'LIMIT 1 BY' in c.args[0]
        ]
        self.assertGreater(len(head_calls), 1)
        self.assertEqual(set(result), set(self.PIDS))

    async def test_commits_since_tag_batch_and_merge(self) -> None:
        tagged = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

        def query(
            sql: str, parameters: dict[str, typing.Any]
        ) -> list[dict[str, typing.Any]]:
            if 'FROM tags FINAL' in sql:
                return [
                    {
                        'project_id': pid,
                        'name': '1.0.0',
                        'sha': 'b' * 40,
                        'tagged_at': tagged,
                        'recorded_at': None,
                        'tagger_name': None,
                    }
                    for pid in parameters['project_ids']
                ]
            if 'count() AS c' in sql:
                self.assertEqual(
                    len(parameters['cuts']), len(parameters['pids'])
                )
                return [
                    {
                        'project_id': pid,
                        'c': 2,
                        'drifted': 0,
                        'answered': 2,
                        'actionable': 0,
                        'oldest_actionable_at': None,
                    }
                    for pid in parameters['pids']
                ]
            return self._echo(sql, parameters)

        mock_query = mock.AsyncMock(side_effect=query)
        with mock.patch(
            'imbi.api.endpoints.projects.clickhouse.query', mock_query
        ):
            result = await projects._fetch_release_summaries(self.PIDS)
        count_calls = [
            c
            for c in mock_query.await_args_list
            if 'count() AS c' in c.args[0]
        ]
        self.assertGreater(len(count_calls), 1)
        self.assertEqual(
            {pid for pid, s in result.items() if s.commits_since_tag == 2},
            set(self.PIDS),
        )

    async def test_small_org_makes_one_query_per_release_kind(self) -> None:
        query = mock.AsyncMock(side_effect=self._echo)
        with mock.patch('imbi.api.endpoints.projects.clickhouse.query', query):
            await projects._fetch_release_summaries(self.PIDS[:10])
        sqls = [c.args[0] for c in query.await_args_list]
        self.assertEqual(sum('FROM tags FINAL' in s for s in sqls), 1)
        self.assertEqual(sum('LIMIT 1 BY' in s for s in sqls), 1)


class ResolveDisplayNamesTestCase(unittest.IsolatedAsyncioTestCase):
    """Coverage for ``_resolve_display_names``."""

    async def test_empty_emails_short_circuits(self) -> None:
        db = mock.AsyncMock()
        self.assertEqual(await projects._resolve_display_names(db, []), {})
        db.execute.assert_not_called()

    async def test_returns_mapping(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {'email': 'a@example.com', 'display_name': 'Alice'},
            {'email': 'b@example.com', 'display_name': 'Bob'},
        ]
        with mock.patch(
            'imbi.api.endpoints.projects.graph.parse_agtype',
            side_effect=lambda v: v,
        ):
            result = await projects._resolve_display_names(
                db, ['a@example.com', 'b@example.com']
            )
        self.assertEqual(
            result,
            {'a@example.com': 'Alice', 'b@example.com': 'Bob'},
        )

    async def test_skips_rows_missing_fields(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {'email': 'a@example.com', 'display_name': None},
            {'email': None, 'display_name': 'NoEmail'},
            {'email': 'c@example.com', 'display_name': 'Carol'},
        ]
        with mock.patch(
            'imbi.api.endpoints.projects.graph.parse_agtype',
            side_effect=lambda v: v,
        ):
            result = await projects._resolve_display_names(
                db, ['a@example.com', 'c@example.com']
            )
        self.assertEqual(result, {'c@example.com': 'Carol'})

    async def test_swallows_db_errors(self) -> None:
        db = mock.AsyncMock()
        db.execute.side_effect = RuntimeError('graph down')
        result = await projects._resolve_display_names(db, ['a@example.com'])
        self.assertEqual(result, {})


def _event(
    timestamp: datetime.datetime,
    *,
    status: str = 'success',
    performed_by: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        'timestamp': timestamp.isoformat(),
        'status': status,
    }
    if performed_by is not None:
        payload['performed_by'] = performed_by
    return payload


def _row(
    *,
    project_id: str,
    env_slug: str,
    tag: str | None,
    committish: str | None,
    events: list[dict[str, object]],
) -> dict[str, object]:
    return {
        'project_id': project_id,
        'env_slug': env_slug,
        'tag': tag,
        'committish': committish,
        'deployments': json.dumps(events),
    }


class FetchCurrentReleasesTestCase(unittest.IsolatedAsyncioTestCase):
    """Coverage for ``_fetch_current_releases`` reading from AGE."""

    async def test_empty_project_ids_short_circuits(self) -> None:
        db = mock.AsyncMock()
        result = await projects._fetch_current_releases(db, [])
        self.assertEqual(result, ({}, {}))
        db.execute.assert_not_called()

    async def test_returns_release_info_per_env(self) -> None:
        older = datetime.datetime(2026, 4, 1, 12, 0, 0, tzinfo=datetime.UTC)
        newer = datetime.datetime(2026, 4, 2, 12, 0, 0, tzinfo=datetime.UTC)
        db = mock.AsyncMock()
        db.execute.return_value = [
            # An older release also deployed to prod — must not win.
            _row(
                project_id='p1',
                env_slug='prod',
                tag='0.9.0',
                committish='abc1234',
                events=[_event(older, performed_by='legacy@example.com')],
            ),
            # The current prod release: latest event wins.
            _row(
                project_id='p1',
                env_slug='prod',
                tag='1.0.0',
                committish='abcdef0',
                events=[_event(newer, performed_by='alice@example.com')],
            ),
            # Stage release with a null performer (in-product deploy).
            _row(
                project_id='p1',
                env_slug='stage',
                tag=None,
                committish='7654321',
                events=[_event(newer)],
            ),
        ]

        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(return_value=[])

        with (
            mock.patch(
                'imbi.api.endpoints.projects.ch_client.Clickhouse.'
                'get_instance',
                return_value=ch,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.graph.parse_agtype',
                side_effect=lambda v: v,
            ),
        ):
            result = await projects._fetch_current_releases(db, ['p1'])

        prod = result.current['p1']['prod']
        stage = result.current['p1']['stage']
        self.assertEqual(prod.tag, '1.0.0')
        self.assertEqual(prod.committish, 'abcdef0')
        self.assertEqual(prod.performed_by, 'alice@example.com')
        self.assertEqual(prod.deployed_at, newer)
        self.assertIsNone(stage.tag)
        self.assertEqual(stage.committish, '7654321')
        self.assertIsNone(stage.performed_by)

    async def test_enriches_performed_by_from_ops_log(self) -> None:
        deployed = datetime.datetime(2026, 4, 1, 12, 0, 0, tzinfo=datetime.UTC)
        db = mock.AsyncMock()
        db.execute.return_value = [
            _row(
                project_id='p1',
                env_slug='prod',
                tag='1.0.0',
                committish='abcdef0',
                events=[_event(deployed)],
            ),
        ]
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(
            return_value=[
                {
                    'project_id': 'p1',
                    'environment_slug': 'prod',
                    'version': '1.0.0',
                    'performed_by': 'bob@example.com',
                },
            ]
        )

        with (
            mock.patch(
                'imbi.api.endpoints.projects.ch_client.Clickhouse.'
                'get_instance',
                return_value=ch,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.graph.parse_agtype',
                side_effect=lambda v: v,
            ),
        ):
            result = await projects._fetch_current_releases(db, ['p1'])

        self.assertEqual(
            result.current['p1']['prod'].performed_by, 'bob@example.com'
        )

    async def test_enriches_performed_by_from_committish_when_tag_set(
        self,
    ) -> None:
        # A branch/SHA deploy records version = committish in the ops log
        # even though the release carries a tag; the backfill must probe
        # the committish key too, not just the tag.
        deployed = datetime.datetime(2026, 4, 1, 12, 0, 0, tzinfo=datetime.UTC)
        db = mock.AsyncMock()
        db.execute.return_value = [
            _row(
                project_id='p1',
                env_slug='prod',
                tag='1.0.0',
                committish='abcdef0',
                events=[_event(deployed)],
            ),
        ]
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(
            return_value=[
                {
                    'project_id': 'p1',
                    'environment_slug': 'prod',
                    'version': 'abcdef0',
                    'performed_by': 'carol@example.com',
                },
            ]
        )

        with (
            mock.patch(
                'imbi.api.endpoints.projects.ch_client.Clickhouse.'
                'get_instance',
                return_value=ch,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.graph.parse_agtype',
                side_effect=lambda v: v,
            ),
        ):
            result = await projects._fetch_current_releases(db, ['p1'])

        self.assertEqual(
            result.current['p1']['prod'].performed_by, 'carol@example.com'
        )

    async def test_skips_environments_with_no_events(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            _row(
                project_id='p1',
                env_slug='prod',
                tag='1.0.0',
                committish='abcdef0',
                events=[],
            ),
        ]
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(return_value=[])
        with (
            mock.patch(
                'imbi.api.endpoints.projects.ch_client.Clickhouse.'
                'get_instance',
                return_value=ch,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.graph.parse_agtype',
                side_effect=lambda v: v,
            ),
        ):
            result = await projects._fetch_current_releases(db, ['p1'])
        self.assertEqual(result, ({}, {}))

    async def test_swallows_graph_errors(self) -> None:
        db = mock.AsyncMock()
        db.execute.side_effect = RuntimeError('graph down')
        result = await projects._fetch_current_releases(db, ['p1'])
        self.assertEqual(result, ({}, {}))


class LookupOpsLogPerformedByTestCase(unittest.IsolatedAsyncioTestCase):
    """Coverage for ``lookup_ops_log_performed_by``."""

    async def test_empty_targets_short_circuits(self) -> None:
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance'
        ) as gi:
            result = await projects.lookup_ops_log_performed_by([])
        self.assertEqual(result, {})
        gi.assert_not_called()

    async def test_filters_to_requested_keys(self) -> None:
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(
            return_value=[
                {
                    'project_id': 'p1',
                    'environment_slug': 'prod',
                    'version': '1.0.0',
                    'performed_by': 'alice@example.com',
                },
                # Stale row for a version we no longer need — must be dropped.
                {
                    'project_id': 'p1',
                    'environment_slug': 'prod',
                    'version': '0.9.0',
                    'performed_by': 'legacy@example.com',
                },
            ]
        )
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=ch,
        ):
            result = await projects.lookup_ops_log_performed_by(
                [('p1', 'prod', '1.0.0', None)]
            )
        self.assertEqual(result, {('p1', 'prod'): 'alice@example.com'})

    async def test_swallows_clickhouse_errors(self) -> None:
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(side_effect=RuntimeError('boom'))
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=ch,
        ):
            result = await projects.lookup_ops_log_performed_by(
                [('p1', 'prod', '1.0.0', None)]
            )
        self.assertEqual(result, {})
