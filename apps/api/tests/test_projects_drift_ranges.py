"""Tests for environment-pair drift ranges on the projects list."""

from __future__ import annotations

import datetime
import typing
import unittest
from unittest import mock

from imbi.api.endpoints import projects


def _at(day: int) -> datetime.datetime:
    return datetime.datetime(2026, 8, day, tzinfo=datetime.UTC)


def _env(slug: str, order: int) -> dict[str, typing.Any]:
    return {'name': slug.title(), 'slug': slug, 'sort_order': order}


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
        actionable: dict[str, list[datetime.datetime]] | None,
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
        actionable: list[datetime.datetime] | None,
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
            {'p1': {'base..head': True}}, await self._run([_at(15)])
        )

    async def test_all_quiet_in_range_is_nothing_to_do(self) -> None:
        self.assertEqual({'p1': {'base..head': False}}, await self._run([]))

    async def test_a_drifting_commit_before_the_range_is_ignored(
        self,
    ) -> None:
        # Already promoted; it is behind the base endpoint.
        self.assertEqual(
            {'p1': {'base..head': False}}, await self._run([_at(5)])
        )

    async def test_a_drifting_commit_after_the_range_is_ignored(
        self,
    ) -> None:
        # Not yet in the lower environment either.
        self.assertEqual(
            {'p1': {'base..head': False}}, await self._run([_at(25)])
        )

    async def test_the_base_endpoint_itself_is_excluded(self) -> None:
        # The base commit is what the higher environment already runs.
        self.assertEqual(
            {'p1': {'base..head': False}}, await self._run([_at(10)])
        )

    async def test_the_head_endpoint_itself_is_included(self) -> None:
        self.assertEqual(
            {'p1': {'base..head': True}}, await self._run([_at(20)])
        )

    async def test_an_undatable_endpoint_yields_no_key(self) -> None:
        # Absent, not False: nothing was evaluated, and the client
        # fails closed on an absent key.
        self.assertEqual(
            {}, await self._run([_at(15)], times={('p1', 'base'): _at(10)})
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
