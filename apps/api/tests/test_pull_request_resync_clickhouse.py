"""Pull request history resync against a live ClickHouse.

``sync_all_history`` used to only upsert the PRs GitHub listed, so a row
filed under the project for a PR GitHub no longer lists (one from another
repository, say) stayed ``open`` forever. These seed such rows, run the
sync with GitHub mocked, and read ``pull_requests`` back with ``FINAL``.
"""

import datetime
import typing
import unittest
import uuid

import httpx
import respx

from apps.api.tests import support
from imbi.common import clickhouse, iggy
from imbi.common.clickhouse import client
from imbi.common.models import PullRequestRecord
from imbi.common.plugins.base import PluginContext
from imbi.plugins.github import pull_requests

_REPO = 'https://api.github.com/repos/octo/demo'


def _ctx(project_id: str) -> PluginContext:
    return PluginContext(
        project_id=project_id,
        project_slug='demo',
        org_slug='octo',
        integration_options={'flavor': 'github'},
        project_links={'github-repository': 'https://github.com/octo/demo'},
    )


def _github_pr(**overrides: typing.Any) -> dict[str, typing.Any]:
    pr: dict[str, typing.Any] = {
        'id': 1001,
        'number': 1,
        'title': 'Listed PR',
        'html_url': 'https://github.com/octo/demo/pull/1',
        'state': 'open',
        'user': {'login': 'octocat'},
        'draft': False,
        'created_at': '2026-01-01T00:00:00Z',
        'updated_at': '2026-01-02T00:00:00Z',
        'merged_at': None,
    }
    pr.update(overrides)
    return pr


def _seed_record(
    project_id: str, pr_id: str, pr_number: int, url: str
) -> PullRequestRecord:
    now = datetime.datetime.now(datetime.UTC)
    return PullRequestRecord(
        project_id=project_id,
        pr_id=pr_id,
        pr_number=pr_number,
        title='Seeded PR',
        url=url,
        state='open',
        author='octocat',
        draft=False,
        merged=False,
        created_at=now - datetime.timedelta(days=30),
        updated_at=now - datetime.timedelta(days=30),
        recorded_at=now - datetime.timedelta(hours=1),
    )


class PullRequestResyncClickhouseTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # ``Clickhouse`` is a process-wide singleton bound to the loop that
        # opened it, and each test method gets its own loop, so take a
        # private instance and hand the previous one back afterwards.
        self._previous = client.Clickhouse._instance
        client.Clickhouse._instance = None
        self.addAsyncCleanup(self._restore_singleton)
        await clickhouse.initialize()
        await clickhouse.setup_schema()
        self.project_id = f'pr-resync-{uuid.uuid4()}'

    async def _restore_singleton(self) -> None:
        await clickhouse.aclose()
        client.Clickhouse._instance = self._previous

    async def _seed(self, record: PullRequestRecord) -> None:
        with support.sink_to_clickhouse():
            await iggy.publish('pull_requests', 'github', [record])

    async def _sync(self, prs: list[dict[str, typing.Any]]) -> int:
        respx.get(f'{_REPO}/pulls').mock(
            return_value=httpx.Response(200, json=prs)
        )
        handler = pull_requests.GitHubPullRequestSync()
        with support.sink_to_clickhouse():
            return await handler.sync_all_history(
                ctx=_ctx(self.project_id),
                credentials={'access_token': 'gho_test'},
            )

    async def _rows(self) -> dict[str, dict[str, typing.Any]]:
        rows = await clickhouse.query(
            'SELECT pr_id, state, merged FROM pull_requests FINAL'
            ' WHERE project_id = {project_id:String}',
            {'project_id': self.project_id},
        )
        return {str(row['pr_id']): row for row in rows}

    @respx.mock
    async def test_a_misfiled_row_is_removed(self) -> None:
        await self._seed(
            _seed_record(
                self.project_id,
                '9009',
                9,
                'https://github.com/octo/other/pull/9',
            )
        )
        self.assertIn('9009', await self._rows())

        count = await self._sync([_github_pr(id=1001, number=1)])

        self.assertEqual(1, count)
        open_rows = await clickhouse.query(
            'SELECT pr_id FROM pull_requests FINAL'
            ' WHERE project_id = {project_id:String}'
            " AND state = 'open'",
            {'project_id': self.project_id},
        )
        open_ids = {str(row['pr_id']) for row in open_rows}
        self.assertNotIn('9009', open_ids)
        self.assertIn('1001', open_ids)

    @respx.mock
    async def test_a_closed_pr_replaces_the_older_open_row(self) -> None:
        await self._seed(
            _seed_record(
                self.project_id,
                '1001',
                1,
                'https://github.com/octo/demo/pull/1',
            )
        )

        await self._sync(
            [
                _github_pr(
                    id=1001,
                    number=1,
                    state='closed',
                    merged_at='2026-01-03T00:00:00Z',
                )
            ]
        )

        rows = await self._rows()
        self.assertEqual(['1001'], list(rows))
        self.assertEqual('closed', rows['1001']['state'])
        self.assertTrue(rows['1001']['merged'])
