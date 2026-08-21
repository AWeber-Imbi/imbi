"""Tests for the mislabelled-``rolled_back`` repair."""

from __future__ import annotations

import datetime
import typing
import unittest

from imbi.api import deployment_status_repair

NOW = datetime.datetime(2026, 8, 21, 12, tzinfo=datetime.UTC)


def _entry(status: str, source: str = 'api') -> dict[str, typing.Any]:
    return {
        'status': status,
        'source': source,
        'timestamp': '2026-08-18T18:40:08+00:00',
    }


class _GraphStub:
    """Answers the candidate read, records each repair write.

    ``repair_rows`` is what the ``SET`` returns per call -- an empty
    list models the node having moved out of ``rolled_back`` between the
    read and the write.
    """

    def __init__(
        self,
        candidates: list[dict[str, typing.Any]],
        repair_rows: list[list[dict[str, typing.Any]]] | None = None,
    ) -> None:
        self.candidates = candidates
        self.repair_rows = repair_rows
        self.writes: list[dict[str, typing.Any]] = []

    async def execute(
        self,
        query: str,
        params: dict[str, typing.Any],
        _columns: list[str],
    ) -> list[dict[str, typing.Any]]:
        if 'SET d.status' in query:
            self.writes.append(params)
            if self.repair_rows is not None:
                return self.repair_rows[len(self.writes) - 1]
            return [{'id': params['deployment_id']}]
        return self.candidates


def _graph(stub: _GraphStub) -> typing.Any:
    return stub


class RepairTestCase(unittest.IsolatedAsyncioTestCase):
    async def _repair(
        self, stub: _GraphStub
    ) -> deployment_status_repair.RepairSummary:
        return await deployment_status_repair.repair_project(
            _graph(stub), 'p1', now=NOW
        )

    async def test_restores_a_success_the_resync_overwrote(self) -> None:
        """The production shape: success, then resync's rolled_back."""
        stub = _GraphStub(
            [
                {
                    'id': 'dep-1',
                    'history': [
                        _entry('success', 'migration'),
                        _entry('rolled_back'),
                    ],
                    'note': 'resync via github',
                }
            ]
        )
        summary = await self._repair(stub)
        self.assertEqual(1, summary.examined)
        self.assertEqual(1, summary.repaired)
        self.assertEqual(0, summary.unrepairable)
        self.assertTrue(summary.wrote_anything)
        self.assertEqual(1, len(stub.writes))
        self.assertEqual('success', stub.writes[0]['restored'])
        self.assertEqual(
            deployment_status_repair.REPAIR_SOURCE, stub.writes[0]['source']
        )

    async def test_leaves_a_rollback_with_no_recorded_success(self) -> None:
        """No evidence, no repair.

        The migration wrote some nodes ``rolled_back`` outright. There
        is nothing to restore, and guessing would be worse than the
        mislabel.
        """
        stub = _GraphStub(
            [
                {
                    'id': 'dep-2',
                    'history': [_entry('rolled_back', 'migration')],
                    'note': 'resync via github',
                }
            ]
        )
        summary = await self._repair(stub)
        self.assertEqual(1, summary.examined)
        self.assertEqual(0, summary.repaired)
        self.assertEqual(1, summary.unrepairable)
        self.assertFalse(summary.wrote_anything)
        self.assertEqual([], stub.writes)

    async def test_success_anywhere_in_the_trail_counts(self) -> None:
        # A rollout reported by both a watcher and a webhook passes
        # through in_progress more than once; the entries between the
        # success and the mislabel do not change what the success said.
        stub = _GraphStub(
            [
                {
                    'id': 'dep-3',
                    'history': [
                        _entry('in_progress'),
                        _entry('success'),
                        _entry('in_progress'),
                        _entry('rolled_back'),
                    ],
                    'note': 'resync via github',
                }
            ]
        )
        summary = await self._repair(stub)
        self.assertEqual(1, summary.repaired)

    async def test_never_writes_a_timestamp_field(self) -> None:
        """``updated_at`` is the ordering key; the repair must not move it.

        Bumping it would make every repaired node its environment's
        newest and hand the environment to whatever the repair touched
        last -- the same class of bug this whole change is undoing.
        """
        stub = _GraphStub(
            [
                {
                    'id': 'dep-4',
                    'history': [_entry('success'), _entry('rolled_back')],
                    'note': 'resync via github',
                }
            ]
        )
        await self._repair(stub)
        self.assertNotIn('updated_at', stub.writes[0])

    async def test_a_node_that_moved_is_not_counted_as_repaired(
        self,
    ) -> None:
        # The guarded SET matched nothing: another writer answered for
        # the node between the read and the write.
        stub = _GraphStub(
            [
                {
                    'id': 'dep-5',
                    'history': [_entry('success'), _entry('rolled_back')],
                    'note': 'resync via github',
                }
            ],
            repair_rows=[[]],
        )
        summary = await self._repair(stub)
        self.assertEqual(1, summary.examined)
        self.assertEqual(0, summary.repaired)

    async def test_malformed_history_is_not_restorable(self) -> None:
        stub = _GraphStub(
            [
                {'id': 'dep-6', 'history': 'not-a-list', 'note': None},
                {'id': 'dep-7', 'history': None, 'note': None},
                {'id': 'dep-8', 'history': ['bare-string'], 'note': None},
            ]
        )
        summary = await self._repair(stub)
        self.assertEqual(3, summary.examined)
        self.assertEqual(0, summary.repaired)
        self.assertEqual(3, summary.unrepairable)

    async def test_nothing_mislabelled_is_an_empty_summary(self) -> None:
        summary = await self._repair(_GraphStub([]))
        self.assertEqual(deployment_status_repair.RepairSummary(), summary)
