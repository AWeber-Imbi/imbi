"""Tests for the merged-but-not-deployed pull request view."""

from __future__ import annotations

import datetime
import typing
import unittest
from unittest import mock

from imbi.api.endpoints import pull_requests


def _env(
    slug: str, order: int, *, terminal: bool = False
) -> dict[str, typing.Any]:
    return {
        'name': slug.title(),
        'slug': slug,
        'sort_order': order,
        'terminal': terminal,
    }


class TerminalEnvironmentSlugsTests(unittest.TestCase):
    def test_the_last_environment_of_the_pipeline_is_terminal(self) -> None:
        envs = [_env('testing', 1), _env('staging', 2), _env('production', 3)]
        self.assertEqual(
            ['production'], pull_requests.terminal_environment_slugs(envs)
        )

    def test_ordering_follows_sort_order_not_input_order(self) -> None:
        envs = [_env('production', 3), _env('testing', 1)]
        self.assertEqual(
            ['production'], pull_requests.terminal_environment_slugs(envs)
        )

    def test_every_pipeline_contributes_its_terminal(self) -> None:
        # Two pipelines in one list (#285): infrastructure ends the first.
        envs = [
            _env('infrastructure-testing', 1),
            _env('infrastructure', 2, terminal=True),
            _env('testing', 3),
            _env('staging', 4),
            _env('production', 5, terminal=True),
        ]
        self.assertEqual(
            ['infrastructure', 'production'],
            pull_requests.terminal_environment_slugs(envs),
        )

    def test_no_environments_yields_no_slugs(self) -> None:
        self.assertEqual([], pull_requests.terminal_environment_slugs([]))


_DEPLOYED = [('p1', '2026-06-01 00:00:00.000', 'production')]


class ListPendingDeployTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.since = datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC)
        self.query = mock.AsyncMock(return_value=[])
        patcher = mock.patch('imbi.common.clickhouse.query', self.query)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_no_deployed_projects_skips_clickhouse(self) -> None:
        rows, total = await pull_requests._list_pending_deploy(
            deployed=[], author='gmr', since=self.since
        )
        self.assertEqual(([], 0), (rows, total))
        self.query.assert_not_awaited()

    async def test_query_scopes_projects_environments_and_author(
        self,
    ) -> None:
        deployed = [
            ('p1', '2026-06-01 00:00:00.000', 'production'),
            ('p2', '2026-06-02 00:00:00.000', 'infrastructure'),
        ]
        await pull_requests._list_pending_deploy(
            deployed=deployed,
            author='gmr',
            since=self.since,
        )
        sql, params = self.query.await_args.args
        self.assertIn('INNER JOIN project_ids AS d', sql)
        self.assertIn('d.last_deployed_at <= pr.merged_at', sql)
        self.assertIn('pr.merged_at >= {since:DateTime64(3)}', sql)
        self.assertIn('pr.author = {author:String}', sql)
        self.assertIn('NOT pr.draft', sql)
        self.assertIn(
            'project_id IN (SELECT project_id FROM project_ids)', sql
        )
        kwargs = self.query.await_args.kwargs
        self.assertEqual(deployed, kwargs['project_ids'])
        self.assertEqual(pull_requests._DEPLOYED_COLUMNS, kwargs['columns'])
        self.assertEqual('gmr', params['author'])
        self.assertEqual(self.since, params['since'])

    async def test_author_is_optional(self) -> None:
        await pull_requests._list_pending_deploy(
            deployed=_DEPLOYED,
            author=None,
            since=self.since,
        )
        sql, params = self.query.await_args.args
        self.assertNotIn('pr.author = {author:String}', sql)
        self.assertNotIn('author', params)

    async def test_bots_filter_matches_the_github_bot_suffix(self) -> None:
        await pull_requests._list_pending_deploy(
            deployed=_DEPLOYED,
            author=None,
            since=self.since,
            bots=True,
        )
        sql, params = self.query.await_args.args
        self.assertIn("pr.author LIKE '%[bot]'", sql)
        self.assertNotIn("LIKE '%[bot]%'", sql)
        self.assertNotIn('author', params)

    async def test_bots_filter_is_off_by_default(self) -> None:
        await pull_requests._list_pending_deploy(
            deployed=_DEPLOYED,
            author='gmr',
            since=self.since,
        )
        sql, _params = self.query.await_args.args
        self.assertNotIn('[bot]', sql)

    async def test_rows_become_utc_models(self) -> None:
        # ClickHouse hands back naive datetimes; the endpoint stamps UTC.
        merged = datetime.datetime(2026, 8, 2, 12, 0)  # noqa: DTZ001
        deployed = datetime.datetime(2026, 8, 1, 9, 30)  # noqa: DTZ001
        self.query.side_effect = [
            [{'total': 1}],
            [
                {
                    'project_id': 'p1',
                    'pr_id': 'PR_1',
                    'pr_number': 7,
                    'title': 'Ship it',
                    'url': 'https://example.test/pr/7',
                    'author': 'gmr',
                    'merged_at': merged,
                    'additions': 3,
                    'deletions': 1,
                    'last_deployed_at': deployed,
                    'last_deployed_environment': 'production',
                }
            ],
        ]
        rows, total = await pull_requests._list_pending_deploy(
            deployed=_DEPLOYED,
            author='gmr',
            since=self.since,
        )
        self.assertEqual(1, len(rows))
        self.assertEqual(1, total)
        self.assertEqual(datetime.UTC, rows[0].merged_at.tzinfo)
        self.assertEqual(datetime.UTC, rows[0].last_deployed_at.tzinfo)
        self.assertEqual(7, rows[0].pr_number)
        self.assertEqual('production', rows[0].last_deployed_environment)
        self.assertIsNone(rows[0].last_deployed_environment_name)

    async def test_count_and_page_share_the_filters(self) -> None:
        self.query.side_effect = [[{'total': 7}], []]
        rows, total = await pull_requests._list_pending_deploy(
            deployed=_DEPLOYED,
            author='gmr',
            since=self.since,
            limit=5,
            offset=5,
        )
        self.assertEqual(([], 7), (rows, total))
        (count_sql, count_params), (data_sql, data_params) = (
            c.args for c in self.query.await_args_list
        )
        self.assertIn('SELECT count() AS total', count_sql)
        self.assertNotIn('LIMIT', count_sql)
        for sql in (count_sql, data_sql):
            self.assertIn('pr.author = {author:String}', sql)
            self.assertIn('d.last_deployed_at <= pr.merged_at', sql)
        self.assertIn('LIMIT {limit:UInt32} OFFSET {offset:UInt32}', data_sql)
        self.assertEqual(5, data_params['limit'])
        self.assertEqual(5, data_params['offset'])
        self.assertIs(count_params, data_params)


def _state(
    project_id: str, slug: str, started: datetime.datetime
) -> mock.Mock:
    env = {'slug': slug}
    return mock.Mock(
        project_id=project_id,
        environment=env,
        latest=mock.Mock(environment=env, started_at=started),
    )


class LastTerminalDeploysTests(unittest.IsolatedAsyncioTestCase):
    async def test_newest_terminal_attempt_per_project(self) -> None:
        early = datetime.datetime(2026, 11, 1, 9, 0, tzinfo=datetime.UTC)
        late = datetime.datetime(2026, 11, 2, 10, 30, 1, 5000, datetime.UTC)
        states = [
            _state('p1', 'infrastructure', late),
            _state('p1', 'production', early),
            # A newer deploy to a non-terminal environment is ignored.
            _state('p2', 'staging', late),
            _state('p2', 'production', early),
            _state('p3', 'testing', late),
        ]
        with mock.patch.object(
            pull_requests.deployment_nodes,
            'current_and_latest_from_state',
            mock.AsyncMock(return_value=states),
        ):
            rows = await pull_requests._last_terminal_deploys(
                mock.Mock(),
                ['p1', 'p2', 'p3'],
                ['production', 'infrastructure'],
            )
        self.assertEqual(
            sorted(
                [
                    ('p1', '2026-11-02 10:30:01.005', 'infrastructure'),
                    ('p2', '2026-11-01 09:00:00.000', 'production'),
                ]
            ),
            sorted(rows),
        )

    async def test_active_since_drops_projects_that_stopped_deploying(
        self,
    ) -> None:
        old = datetime.datetime(2023, 3, 7, tzinfo=datetime.UTC)
        new = datetime.datetime(2026, 11, 2, tzinfo=datetime.UTC)
        states = [
            _state('p1', 'production', old),
            _state('p2', 'production', new),
        ]
        with mock.patch.object(
            pull_requests.deployment_nodes,
            'current_and_latest_from_state',
            mock.AsyncMock(return_value=states),
        ):
            rows = await pull_requests._last_terminal_deploys(
                mock.Mock(),
                ['p1', 'p2'],
                ['production'],
                datetime.datetime(2026, 8, 29, tzinfo=datetime.UTC),
            )
        self.assertEqual(
            [('p2', '2026-11-02 00:00:00.000', 'production')], rows
        )
