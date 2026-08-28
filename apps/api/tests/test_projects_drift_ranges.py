"""Tests for environment-pair drift ranges on the projects list."""

from __future__ import annotations

import datetime
import typing
import unittest
from unittest import mock

from imbi.api.endpoints import projects
from imbi.common import clickhouse


def _at(day: int) -> datetime.datetime:
    return datetime.datetime(2026, 8, day, tzinfo=datetime.UTC)


def _env(
    slug: str, order: int, *, terminal: bool = False
) -> dict[str, typing.Any]:
    env: dict[str, typing.Any] = {
        'name': slug.title(),
        'slug': slug,
        'sort_order': order,
    }
    if terminal:
        env['terminal'] = True
    return env


def _release(sha: str) -> projects.ReleaseInfo:
    return projects.ReleaseInfo(deployed_at=_at(1), committish=sha)


#: testing sorts first and tracks HEAD; staging and production run tags.
PIPELINE = [_env('testing', 1), _env('staging', 2), _env('production', 3)]


class EnvironmentRangesTests(unittest.TestCase):
    def test_the_range_runs_from_the_later_environment_upward(self) -> None:
        # testing holds the newer code, so it is the *head* of the range
        # even though it sorts first.
        ranges = projects._environment_ranges(
            {
                'environments': PIPELINE,
                'current_releases': {
                    'testing': _release('ccc'),
                    'staging': _release('bbb'),
                    'production': _release('aaa'),
                },
            }
        )
        self.assertEqual([('bbb', 'ccc'), ('aaa', 'bbb')], ranges)

    def test_identical_committishes_have_no_range(self) -> None:
        ranges = projects._environment_ranges(
            {
                'environments': PIPELINE[:2],
                'current_releases': {
                    'testing': _release('same'),
                    'staging': _release('same'),
                },
            }
        )
        self.assertEqual([], ranges)

    def test_a_missing_side_has_no_range(self) -> None:
        ranges = projects._environment_ranges(
            {
                'environments': PIPELINE[:2],
                'current_releases': {'testing': _release('ccc')},
            }
        )
        self.assertEqual([], ranges)

    def test_environments_are_ordered_not_taken_as_given(self) -> None:
        ranges = projects._environment_ranges(
            {
                'environments': list(reversed(PIPELINE[:2])),
                'current_releases': {
                    'testing': _release('ccc'),
                    'staging': _release('bbb'),
                },
            }
        )
        self.assertEqual([('bbb', 'ccc')], ranges)

    def test_no_range_spans_a_terminal_boundary(self) -> None:
        # Two independent pipelines in one list (#285): the infra chain
        # ends at its terminal env, testing starts a new one.  All four
        # committishes differ, yet no infra->testing range is derived.
        ranges = projects._environment_ranges(
            {
                'environments': [
                    _env('infra-testing', 1),
                    _env('infra', 2, terminal=True),
                    _env('testing', 3),
                    _env('staging', 4),
                ],
                'current_releases': {
                    'infra-testing': _release('ddd'),
                    'infra': _release('ccc'),
                    'testing': _release('bbb'),
                    'staging': _release('aaa'),
                },
            }
        )
        self.assertEqual([('ccc', 'ddd'), ('aaa', 'bbb')], ranges)


class EvaluateEnvironmentDriftTests(unittest.IsolatedAsyncioTestCase):
    PROJECT: typing.ClassVar[dict[str, typing.Any]] = {
        'id': 'p1',
        'environments': PIPELINE[:2],
        'current_releases': {
            'testing': _release('head'),
            'staging': _release('base'),
        },
    }

    def _patch(
        self,
        times: dict[tuple[str, str], datetime.datetime],
        actionable: dict[str, list[tuple[str, datetime.datetime]]] | None,
    ) -> typing.Any:
        return (
            mock.patch.object(
                projects,
                '_fetch_commit_times',
                mock.AsyncMock(return_value=times),
            ),
            mock.patch.object(
                projects,
                '_fetch_actionable_commit_times',
                mock.AsyncMock(return_value=actionable),
            ),
        )

    async def _run(
        self,
        actionable: list[tuple[str, datetime.datetime]] | None,
        times: dict[tuple[str, str], datetime.datetime] | None = None,
    ) -> dict[str, dict[str, bool]]:
        resolved = (
            {('p1', 'base'): _at(10), ('p1', 'head'): _at(20)}
            if times is None
            else times
        )
        a, b = self._patch(
            resolved, {'p1': actionable} if actionable is not None else None
        )
        with a, b:
            return await projects._evaluate_environment_drift([self.PROJECT])

    async def test_a_drifting_commit_inside_the_range_needs_action(
        self,
    ) -> None:
        self.assertEqual(
            {'p1': {'base..head': True}}, await self._run([('mid', _at(15))])
        )

    async def test_all_quiet_in_range_is_nothing_to_do(self) -> None:
        self.assertEqual({'p1': {'base..head': False}}, await self._run([]))

    async def test_a_drifting_commit_before_the_range_is_ignored(
        self,
    ) -> None:
        # Already promoted; it is behind the base endpoint.
        self.assertEqual(
            {'p1': {'base..head': False}}, await self._run([('old', _at(5))])
        )

    async def test_a_drifting_commit_after_the_range_is_ignored(
        self,
    ) -> None:
        # Not yet in the lower environment either.
        self.assertEqual(
            {'p1': {'base..head': False}}, await self._run([('new', _at(25))])
        )

    async def test_the_base_endpoint_itself_is_excluded(self) -> None:
        # The base commit is what the higher environment already runs.
        self.assertEqual(
            {'p1': {'base..head': False}}, await self._run([('base', _at(10))])
        )

    async def test_a_commit_tied_with_the_base_is_actionable(self) -> None:
        # Git timestamps have one-second precision, so a distinct commit
        # can share the base commit's time. Only the base commit itself
        # is excluded from the range, by sha.
        self.assertEqual(
            {'p1': {'base..head': True}},
            await self._run([('base', _at(10)), ('twin', _at(10))]),
        )

    async def test_the_head_endpoint_itself_is_included(self) -> None:
        self.assertEqual(
            {'p1': {'base..head': True}}, await self._run([('head', _at(20))])
        )

    async def test_an_undatable_endpoint_yields_no_key(self) -> None:
        # Absent, not False: nothing was evaluated, and the client
        # fails closed on an absent key.
        self.assertEqual(
            {},
            await self._run(
                [('mid', _at(15))], times={('p1', 'base'): _at(10)}
            ),
        )

    async def test_tied_endpoint_times_are_actionable(self) -> None:
        # Different shas whose commits share a one-second timestamp:
        # order cannot be established, so the range must not read clean.
        self.assertEqual(
            {'p1': {'base..head': True}},
            await self._run(
                [], times={('p1', 'base'): _at(10), ('p1', 'head'): _at(10)}
            ),
        )

    async def test_reversed_endpoint_times_are_actionable(self) -> None:
        self.assertEqual(
            {'p1': {'base..head': True}},
            await self._run(
                [], times={('p1', 'base'): _at(20), ('p1', 'head'): _at(10)}
            ),
        )

    async def test_a_failed_verdict_fetch_fails_closed(self) -> None:
        # None means the verdict store could not answer; an unavailable
        # store must not read as proof of cleanliness.
        self.assertEqual({'p1': {'base..head': True}}, await self._run(None))

    async def test_the_window_spans_every_orderable_range(self) -> None:
        project = {
            'id': 'p1',
            'environments': PIPELINE,
            'current_releases': {
                'testing': _release('head'),
                'staging': _release('mid'),
                'production': _release('base'),
            },
        }
        times = {
            ('p1', 'base'): _at(5),
            ('p1', 'mid'): _at(10),
            ('p1', 'head'): _at(20),
        }
        a, b = self._patch(times, {'p1': []})
        with a, b as actionable:
            await projects._evaluate_environment_drift([project])
        actionable.assert_awaited_once_with({'p1': (_at(5), _at(20))})

    async def test_no_ranges_skips_both_queries(self) -> None:
        a, b = self._patch({}, {})
        with a as times, b as actionable:
            result = await projects._evaluate_environment_drift(
                [{'id': 'p1', 'environments': [], 'current_releases': {}}]
            )
        self.assertEqual({}, result)
        times.assert_not_awaited()
        actionable.assert_not_awaited()


class FetchActionableCommitTimesTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_lower_bound_is_inclusive_and_carries_the_sha(
        self,
    ) -> None:
        # The tied-with-base regression test above patches this function
        # away, so it alone cannot catch the SQL quietly reverting from
        # ``>=`` to ``>`` -- the tied commit would be dropped before the
        # caller's predicate could see it. Pin the operator and the sha
        # column in the rendered query, and the window parameters.
        query = mock.AsyncMock(return_value=[])
        with mock.patch.object(clickhouse, 'query', query):
            await projects._fetch_actionable_commit_times(
                {'p1': (_at(10), _at(20))}
            )
        sql, params = query.await_args.args
        self.assertIn('COALESCE(c.committed_at, c.authored_at) >=', sql)
        self.assertIn('c.short_sha AS short_sha', sql)
        self.assertEqual(
            {'project_ids': ['p1'], 'los': [_at(10)], 'his': [_at(20)]},
            params,
        )

    async def test_rows_come_back_as_sha_time_pairs(self) -> None:
        query = mock.AsyncMock(
            return_value=[
                {'project_id': 'p1', 'short_sha': 'twin', 'at': _at(10)}
            ]
        )
        with mock.patch.object(clickhouse, 'query', query):
            result = await projects._fetch_actionable_commit_times(
                {'p1': (_at(10), _at(20))}
            )
        self.assertEqual({'p1': [('twin', _at(10))]}, result)
