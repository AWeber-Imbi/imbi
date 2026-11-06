"""Pull request reviewers against a live ClickHouse.

Seeds a PR with pending review requests plus a set of reviews, then
reads the PR back through the list endpoint's query path, so the
schema ALTER, the reviews table, and the reviewer reduction all run
for real.
"""

import datetime
import unittest
import uuid

from apps.api.tests import support
from imbi.api.endpoints import pull_requests
from imbi.common import clickhouse, iggy
from imbi.common.clickhouse import client
from imbi.common.models import (
    PullRequestRecord,
    PullRequestReviewRecord,
    PullRequestReviewRequestsRecord,
)

_START = datetime.datetime(2026, 4, 1, 12, tzinfo=datetime.UTC)


class PullRequestReviewsClickhouseTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # See test_pull_request_resync_clickhouse for why the singleton
        # is swapped out per test.
        self._previous = client.Clickhouse._instance
        client.Clickhouse._instance = None
        self.addAsyncCleanup(self._restore_singleton)
        await clickhouse.initialize()
        await clickhouse.setup_schema()
        self.project_id = f'pr-reviews-{uuid.uuid4()}'

    async def _restore_singleton(self) -> None:
        await clickhouse.aclose()
        client.Clickhouse._instance = self._previous

    def _review(
        self, review_id: str, reviewer: str, state: str, hours: int
    ) -> PullRequestReviewRecord:
        return PullRequestReviewRecord(
            project_id=self.project_id,
            pr_id='pr-1',
            review_id=review_id,
            reviewer=reviewer,
            state=state,
            submitted_at=_START + datetime.timedelta(hours=hours),
        )

    async def test_reviewers_reduce_to_latest_verdict(self) -> None:
        pr = PullRequestRecord(
            project_id=self.project_id,
            pr_id='pr-1',
            pr_number=1,
            title='Add reviewers',
            url='https://github.com/octo/demo/pull/1',
            state='open',
            author='octocat',
            draft=False,
            merged=False,
            created_at=_START,
            updated_at=_START,
        )
        requests = PullRequestReviewRequestsRecord(
            project_id=self.project_id,
            pr_id='pr-1',
            requested_reviewers=['carol'],
            requested_teams=['platform'],
        )
        reviews = [
            # A comment after an approval keeps the approval.
            self._review('1', 'bob', 'approved', 1),
            self._review('2', 'bob', 'commented', 2),
            self._review('3', 'dave', 'commented', 3),
            self._review('4', 'erin', 'approved', 4),
            self._review('5', 'octocat', 'commented', 5),
        ]
        with support.sink_to_clickhouse():
            await iggy.publish('pull_requests', 'github', [pr])
            await iggy.publish(
                'pull_request_review_requests', 'github', [requests]
            )
            await iggy.publish('pull_request_reviews', 'github', reviews)
            # Dismissing erin's approval replaces that review's row.
            await iggy.publish(
                'pull_request_reviews',
                'github',
                [self._review('4', 'erin', 'dismissed', 4)],
            )

        result = await pull_requests._list_prs(
            project_ids=[self.project_id], state='open'
        )

        self.assertEqual(result.total, 1)
        self.assertEqual(
            [(r.login, r.state, r.team) for r in result.data[0].reviewers],
            [
                ('bob', 'approved', False),
                ('dave', 'commented', False),
                ('erin', 'dismissed', False),
                ('carol', 'requested', False),
                ('platform', 'requested', True),
            ],
        )
