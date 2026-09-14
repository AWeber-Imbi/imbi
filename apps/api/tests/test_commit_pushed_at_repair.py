"""Tests for the re-stamped ``pushed_at`` repair."""

from __future__ import annotations

import datetime
import typing
import unittest
from unittest import mock

from imbi.api import commit_pushed_at_repair
from imbi.common.models import CommitRecord

_QUERY = 'imbi.api.commit_pushed_at_repair.clickhouse.query'
_INSERT = 'imbi.api.commit_pushed_at_repair.clickhouse.insert'

UTC = datetime.UTC
_ZERO = '0' * 40


def _at(day: int, hour: int, minute: int = 0) -> datetime.datetime:
    return datetime.datetime(2026, 9, day, hour, minute, tzinfo=UTC)


def _delivery(
    recorded_at: datetime.datetime,
    *commit_ids: str,
    ref: str = 'refs/heads/main',
    after: str | None = None,
) -> dict[str, typing.Any]:
    """A ``push`` delivery row as ``_DELIVERIES_SQL`` returns it."""
    return {
        # The driver hands DateTime64 back naive; the repair re-attaches
        # UTC, so feed it the naive shape.
        'recorded_at': recorded_at.replace(tzinfo=None),
        'ref': ref,
        'after': after
        if after is not None
        else (commit_ids[-1] if commit_ids else _ZERO),
        'commit_ids': list(commit_ids),
    }


def _commit(
    sha: str,
    pushed_at: datetime.datetime,
    *,
    ref: str = 'main',
    authored_at: datetime.datetime | None = None,
) -> dict[str, typing.Any]:
    """A ``commits`` row as ``_COMMITS_SQL`` returns it."""
    authored = (authored_at or pushed_at).replace(tzinfo=None)
    return {
        'project_id': 'p1',
        'sha': sha,
        'short_sha': sha[:7],
        'ref': ref,
        'message': f'commit {sha[:7]}',
        'author_name': 'Alice',
        'author_email': 'alice@example.com',
        'author_login': 'alice',
        'author_user': 'alice@example.com',
        'committer_name': 'GitHub',
        'ci_status': 'pass',
        'authored_at': authored,
        'committed_at': authored,
        'url': f'https://github.example/commit/{sha}',
        'pushed_at': pushed_at.replace(tzinfo=None),
    }


def _router(
    deliveries: list[dict[str, typing.Any]],
    commits: list[dict[str, typing.Any]],
) -> mock.AsyncMock:
    """A ``clickhouse.query`` that answers each statement by table."""

    async def _answer(
        sql: str, params: dict[str, typing.Any]
    ) -> list[dict[str, typing.Any]]:
        if 'FROM events' in sql:
            return deliveries
        wanted = set(params['shas'])
        return [row for row in commits if row['sha'] in wanted]

    return mock.AsyncMock(side_effect=_answer)


def _inserted(insert: mock.AsyncMock) -> dict[str, CommitRecord]:
    if not insert.await_args_list:
        return {}
    table, records = insert.await_args_list[0].args
    assert table == 'commits'
    return {r.sha: r for r in records}


class RepairTestCase(unittest.IsolatedAsyncioTestCase):
    async def _repair(
        self,
        deliveries: list[dict[str, typing.Any]],
        commits: list[dict[str, typing.Any]],
        *,
        dry_run: bool = False,
    ) -> tuple[commit_pushed_at_repair.RepairSummary, mock.AsyncMock]:
        query = _router(deliveries, commits)
        with (
            mock.patch(_QUERY, new=query),
            mock.patch(_INSERT, new=mock.AsyncMock()) as insert,
        ):
            summary = await commit_pushed_at_repair.repair_project(
                'p1', dry_run=dry_run
            )
        return summary, insert

    async def test_restores_the_delivery_time_of_a_restamped_commit(
        self,
    ) -> None:
        """The #308 shape: a release workflow completing re-stamped the
        commit the release was cut from, a day after its push."""
        head = 'a' * 40
        summary, insert = await self._repair(
            [_delivery(_at(9, 15, 8), head)],
            [_commit(head, _at(10, 16, 11), authored_at=_at(9, 15, 8))],
        )
        self.assertEqual(1, summary.deliveries)
        self.assertEqual(1, summary.examined)
        self.assertEqual(1, summary.repaired)
        self.assertEqual(
            int(
                datetime.timedelta(days=1, hours=1, minutes=3).total_seconds()
            ),
            summary.largest_shift_seconds,
        )
        record = _inserted(insert)[head]
        self.assertEqual(_at(9, 15, 8), record.pushed_at)
        # Every other column rides along unchanged; only the version
        # (recorded_at) is new so the re-insert wins the merge.
        self.assertEqual('main', record.ref)
        self.assertEqual('Alice', record.author_name)
        self.assertEqual('pass', record.ci_status)
        self.assertEqual(_at(9, 15, 8), record.authored_at)
        self.assertIsNotNone(record.committed_at)
        self.assertGreater(record.recorded_at, _at(10, 16, 11))

    async def test_uncollapses_a_backfilled_history(self) -> None:
        """The backfill stamped every commit with one instant; each goes
        back to its own delivery."""
        one, two, three = 'a' * 40, 'b' * 40, 'c' * 40
        backfilled = _at(25, 22)
        summary, insert = await self._repair(
            [
                _delivery(_at(1, 9), one),
                _delivery(_at(2, 9), two),
                _delivery(_at(3, 9), three),
            ],
            [
                _commit(one, backfilled),
                _commit(two, backfilled),
                _commit(three, backfilled),
            ],
        )
        self.assertEqual(3, summary.repaired)
        restored = {sha: r.pushed_at for sha, r in _inserted(insert).items()}
        self.assertEqual(
            {one: _at(1, 9), two: _at(2, 9), three: _at(3, 9)}, restored
        )

    async def test_a_commit_still_carrying_its_push_time_is_untouched(
        self,
    ) -> None:
        head = 'a' * 40
        summary, insert = await self._repair(
            [_delivery(_at(9, 15, 8), head)],
            # The sync stamps now() a moment after the delivery lands.
            [_commit(head, _at(9, 15, 8) + datetime.timedelta(seconds=2))],
        )
        self.assertEqual(1, summary.examined)
        self.assertEqual(0, summary.repaired)
        insert.assert_not_awaited()

    async def test_a_value_earlier_than_the_delivery_is_kept(self) -> None:
        """Earlier means an earlier sync recorded it -- closer to the
        truth than the delivery, never a re-stamp."""
        head = 'a' * 40
        summary, insert = await self._repair(
            [_delivery(_at(9, 15, 8), head)],
            [_commit(head, _at(9, 12))],
        )
        self.assertEqual(0, summary.repaired)
        insert.assert_not_awaited()

    async def test_only_pushes_to_the_stored_branch_count(self) -> None:
        """A PR's commits reach their feature branch first; the sync's
        branch-gated rule never recorded that push, and matching it
        would order them by branch push rather than by merge."""
        pr_commit, merge = 'a' * 40, 'b' * 40
        summary, insert = await self._repair(
            [
                _delivery(_at(10, 17, 25), pr_commit, ref='refs/heads/feat'),
                _delivery(_at(10, 19, 19), pr_commit, merge),
            ],
            [
                _commit(pr_commit, _at(11, 13, 1)),
                _commit(merge, _at(11, 13, 0)),
            ],
        )
        self.assertEqual(2, summary.repaired)
        restored = {sha: r.pushed_at for sha, r in _inserted(insert).items()}
        self.assertEqual(_at(10, 19, 19), restored[pr_commit])
        self.assertEqual(_at(10, 19, 19), restored[merge])

    async def test_a_commit_pushed_only_to_another_branch_is_skipped(
        self,
    ) -> None:
        sha = 'a' * 40
        summary, insert = await self._repair(
            [_delivery(_at(10, 17, 25), sha, ref='refs/heads/feat')],
            [_commit(sha, _at(11, 13, 1))],
        )
        self.assertEqual(1, summary.deliveries)
        self.assertEqual(0, summary.examined)
        self.assertEqual(0, summary.repaired)
        insert.assert_not_awaited()

    async def test_the_head_counts_when_the_commit_list_omits_it(
        self,
    ) -> None:
        """GitHub caps ``commits[]`` at twenty; ``after`` is always the
        head the delivery attests to."""
        head = 'a' * 40
        summary, insert = await self._repair(
            [_delivery(_at(9, 15, 8), after=head)],
            [_commit(head, _at(10, 16, 11))],
        )
        self.assertEqual(1, summary.repaired)
        self.assertEqual(_at(9, 15, 8), _inserted(insert)[head].pushed_at)

    async def test_a_branch_delete_names_no_head(self) -> None:
        summary, insert = await self._repair(
            [_delivery(_at(9, 15, 8), after=_ZERO)],
            [_commit(_ZERO, _at(10, 16, 11))],
        )
        self.assertEqual(0, summary.examined)
        insert.assert_not_awaited()

    async def test_the_earliest_delivery_wins(self) -> None:
        """A force-push or a re-delivery can list a commit again later;
        the first time it reached the branch is its push time."""
        head = 'a' * 40
        summary, insert = await self._repair(
            [
                _delivery(_at(9, 18), head),
                _delivery(_at(9, 15, 8), head),
            ],
            [_commit(head, _at(10, 16, 11))],
        )
        self.assertEqual(1, summary.repaired)
        self.assertEqual(_at(9, 15, 8), _inserted(insert)[head].pushed_at)

    async def test_dry_run_counts_but_writes_nothing(self) -> None:
        head = 'a' * 40
        summary, insert = await self._repair(
            [_delivery(_at(9, 15, 8), head)],
            [_commit(head, _at(10, 16, 11))],
            dry_run=True,
        )
        self.assertEqual(1, summary.repaired)
        insert.assert_not_awaited()

    async def test_no_deliveries_reads_no_commits(self) -> None:
        query = _router([], [_commit('a' * 40, _at(10, 16, 11))])
        with (
            mock.patch(_QUERY, new=query),
            mock.patch(_INSERT, new=mock.AsyncMock()) as insert,
        ):
            summary = await commit_pushed_at_repair.repair_project('p1')
        self.assertEqual(commit_pushed_at_repair.RepairSummary(), summary)
        query.assert_awaited_once()
        insert.assert_not_awaited()

    async def test_only_the_delivered_shas_are_read_back(self) -> None:
        """The commits read is bounded by what the deliveries name, not
        the project's whole history."""
        head = 'a' * 40
        query = _router([_delivery(_at(9, 15, 8), head)], [])
        with (
            mock.patch(_QUERY, new=query),
            mock.patch(_INSERT, new=mock.AsyncMock()),
        ):
            await commit_pushed_at_repair.repair_project('p1')
        commits_call = query.await_args_list[1]
        self.assertIn('FROM commits FINAL', commits_call.args[0])
        self.assertEqual([head], commits_call.args[1]['shas'])
