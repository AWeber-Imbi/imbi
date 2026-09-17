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


class ListPendingDeployTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.since = datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC)
        self.query = mock.AsyncMock(return_value=[])
        patcher = mock.patch('imbi.common.clickhouse.query', self.query)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_no_projects_skips_clickhouse(self) -> None:
        rows = await pull_requests._list_pending_deploy(
            project_ids=[],
            environment_slugs=['production'],
            author='gmr',
            since=self.since,
        )
        self.assertEqual([], rows)
        self.query.assert_not_awaited()

    async def test_no_terminal_environment_skips_clickhouse(self) -> None:
        rows = await pull_requests._list_pending_deploy(
            project_ids=['p1'],
            environment_slugs=[],
            author='gmr',
            since=self.since,
        )
        self.assertEqual([], rows)
        self.query.assert_not_awaited()

    async def test_query_scopes_projects_environments_and_author(
        self,
    ) -> None:
        await pull_requests._list_pending_deploy(
            project_ids=['p1', 'p2'],
            environment_slugs=['production'],
            author='gmr',
            since=self.since,
        )
        sql, params = self.query.await_args.args
        self.assertIn("entry_type = 'Deployed'", sql)
        self.assertIn('environment_slug IN {environments:Array(String)}', sql)
        self.assertIn('d.last_deployed_at <= pr.merged_at', sql)
        self.assertIn('pr.merged_at >= {since:DateTime64(3)}', sql)
        self.assertIn('pr.author = {author:String}', sql)
        self.assertIn('NOT pr.draft', sql)
        self.assertEqual(['p1', 'p2'], params['project_ids'])
        self.assertEqual(['production'], params['environments'])
        self.assertEqual('gmr', params['author'])
        self.assertEqual(self.since, params['since'])

    async def test_author_is_optional(self) -> None:
        await pull_requests._list_pending_deploy(
            project_ids=['p1'],
            environment_slugs=['production'],
            author=None,
            since=self.since,
        )
        sql, params = self.query.await_args.args
        self.assertNotIn('pr.author = {author:String}', sql)
        self.assertNotIn('author', params)

    async def test_bots_filter_matches_the_github_bot_suffix(self) -> None:
        await pull_requests._list_pending_deploy(
            project_ids=['p1'],
            environment_slugs=['production'],
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
            project_ids=['p1'],
            environment_slugs=['production'],
            author='gmr',
            since=self.since,
        )
        sql, _params = self.query.await_args.args
        self.assertNotIn('[bot]', sql)

    async def test_rows_become_utc_models(self) -> None:
        # ClickHouse hands back naive datetimes; the endpoint stamps UTC.
        merged = datetime.datetime(2026, 8, 2, 12, 0)  # noqa: DTZ001
        deployed = datetime.datetime(2026, 8, 1, 9, 30)  # noqa: DTZ001
        self.query.return_value = [
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
            }
        ]
        rows = await pull_requests._list_pending_deploy(
            project_ids=['p1'],
            environment_slugs=['production'],
            author='gmr',
            since=self.since,
        )
        self.assertEqual(1, len(rows))
        self.assertEqual(datetime.UTC, rows[0].merged_at.tzinfo)
        self.assertEqual(datetime.UTC, rows[0].last_deployed_at.tzinfo)
        self.assertEqual(7, rows[0].pr_number)
