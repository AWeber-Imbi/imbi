"""Tests for git-notes drift ingestion."""

from __future__ import annotations

import datetime
import typing
import unittest
from unittest import mock

import fastapi

from imbi.api import drift
from imbi.common import graph
from imbi.common.plugins import errors as plugin_errors

FULL_SHA = 'abc1234' + 'f' * 33


class ParseNoteTests(unittest.TestCase):
    def test_true_and_false_verdicts(self) -> None:
        self.assertIs(True, drift.parse_note('{"drift_detected": true}'))
        self.assertIs(False, drift.parse_note('{"drift_detected": false}'))

    def test_unknown_keys_are_ignored(self) -> None:
        self.assertIs(
            True,
            drift.parse_note('{"drift_detected": true, "run": 42}'),
        )

    def test_invalid_json_is_none(self) -> None:
        with self.assertLogs(drift.LOGGER, level='WARNING'):
            self.assertIsNone(drift.parse_note('not json {'))

    def test_non_object_is_none(self) -> None:
        with self.assertLogs(drift.LOGGER, level='WARNING'):
            self.assertIsNone(drift.parse_note('[true]'))

    def test_non_boolean_verdict_is_none(self) -> None:
        with self.assertLogs(drift.LOGGER, level='WARNING'):
            self.assertIsNone(drift.parse_note('{"drift_detected": "yes"}'))

    def test_missing_key_is_none(self) -> None:
        self.assertIsNone(drift.parse_note('{"something_else": true}'))

    def test_no_note_is_none(self) -> None:
        self.assertIsNone(drift.parse_note(None))


class ApplyNoteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = mock.AsyncMock(spec=graph.Graph)
        patcher = mock.patch(
            'imbi.api.endpoints.project_deployments.sync_drift_blocker',
            new_callable=mock.AsyncMock,
        )
        self.sync_blocker = patcher.start()
        self.addCleanup(patcher.stop)

    async def test_stamps_every_matching_release(self) -> None:
        self.db.execute.side_effect = [
            [
                {'id': '"rel-1"', 'tag': '"v1.0.0"'},
                {'id': '"rel-2"', 'tag': None},
            ],
            [{'id': '"rel-1"'}],
            [{'id': '"rel-2"'}],
        ]
        updated = await drift.apply_note(
            self.db,
            org_slug='org',
            project_id='p1',
            full_sha=FULL_SHA,
            body='{"drift_detected": true}',
        )
        self.assertEqual(2, updated)
        lookup = self.db.execute.await_args_list[0]
        self.assertEqual('abc1234', lookup.args[1]['committish'])
        set_calls = self.db.execute.await_args_list[1:]
        self.assertEqual(
            ['rel-1', 'rel-2'],
            [call.args[1]['release_id'] for call in set_calls],
        )
        for call in set_calls:
            self.assertIs(True, call.args[1]['value'])
            self.assertIn('drift_checked_at', call.args[0])
        # Only the tagged release gets the blocker tie-in.
        self.sync_blocker.assert_awaited_once()
        kwargs = self.sync_blocker.await_args.kwargs
        self.assertEqual('v1.0.0', kwargs['tag'])
        self.assertIs(True, kwargs['drift_detected'])

    async def test_invalid_note_stamps_null_without_failing(self) -> None:
        self.db.execute.side_effect = [
            [{'id': '"rel-1"', 'tag': '"v1.0.0"'}],
            [{'id': '"rel-1"'}],
        ]
        with self.assertLogs(drift.LOGGER, level='WARNING'):
            updated = await drift.apply_note(
                self.db,
                org_slug='org',
                project_id='p1',
                full_sha=FULL_SHA,
                body='definitely not json',
            )
        self.assertEqual(1, updated)
        set_call = self.db.execute.await_args_list[1]
        self.assertIsNone(set_call.args[1]['value'])
        # A null verdict still reaches the blocker sync so a stale
        # drift blocker is resolved when its note goes away.
        self.assertIsNone(
            self.sync_blocker.await_args.kwargs['drift_detected']
        )

    async def test_no_matching_release_is_zero(self) -> None:
        self.db.execute.return_value = []
        self.db.execute.side_effect = None
        updated = await drift.apply_note(
            self.db,
            org_slug='org',
            project_id='p1',
            full_sha=FULL_SHA,
            body='{"drift_detected": false}',
        )
        self.assertEqual(0, updated)
        self.sync_blocker.assert_not_awaited()


class ApplyNotesDiffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = mock.AsyncMock(spec=graph.Graph)
        self.handler = mock.AsyncMock()
        patcher = mock.patch(
            'imbi.api.endpoints.project_deployments'
            '.resolve_deployment_capability',
            new_callable=mock.AsyncMock,
            return_value=(self.handler, mock.Mock(), {'access_token': 't'}),
        )
        self.resolve = patcher.start()
        self.addCleanup(patcher.stop)

    async def test_applies_each_changed_note(self) -> None:
        self.handler.diff_commit_notes.return_value = {
            FULL_SHA: '{"drift_detected": true}',
            'e' * 40: None,
        }
        with mock.patch.object(
            drift, 'apply_note', new_callable=mock.AsyncMock, return_value=1
        ) as apply_note:
            updated = await drift.apply_notes_diff(
                self.db,
                org_slug='org',
                project_id='p1',
                before='a' * 40,
                after='b' * 40,
            )
        self.assertEqual(2, updated)
        self.assertEqual(2, apply_note.await_count)
        diff_kwargs = self.handler.diff_commit_notes.await_args.kwargs
        self.assertEqual('imbi-drift', diff_kwargs['namespace'])
        self.assertEqual('a' * 40, diff_kwargs['before'])
        self.assertEqual('b' * 40, diff_kwargs['after'])

    async def test_unsupported_plugin_propagates(self) -> None:
        self.handler.diff_commit_notes.side_effect = NotImplementedError
        with self.assertRaises(NotImplementedError):
            await drift.apply_notes_diff(
                self.db,
                org_slug='org',
                project_id='p1',
                before='a' * 40,
                after='b' * 40,
            )


class SweepProjectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = mock.AsyncMock(spec=graph.Graph)
        self.handler = mock.AsyncMock()
        self.resolve = mock.AsyncMock(
            return_value=(self.handler, mock.Mock(), {'access_token': 't'})
        )
        for target, replacement in (
            (
                'imbi.api.endpoints.project_deployments'
                '.resolve_deployment_capability',
                self.resolve,
            ),
            (
                'imbi.api.endpoints.project_deployments.sync_drift_blocker',
                mock.AsyncMock(),
            ),
        ):
            patcher = mock.patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _rows(self) -> list[dict[str, typing.Any]]:
        return [
            {'id': '"rel-1"', 'tag': '"v1.0.0"', 'committish': '"abc1234"'},
            {'id': '"rel-2"', 'tag': None, 'committish': '"def5678"'},
        ]

    async def test_stamps_unanswered_releases(self) -> None:
        self.db.execute.side_effect = [
            self._rows(),
            [{'id': '"rel-1"'}],
            [{'id': '"rel-2"'}],
        ]
        self.handler.get_commit_note.side_effect = [
            '{"drift_detected": true}',
            None,
        ]
        stamped = await drift.sweep_project(
            self.db, org_slug='org', project_id='p1'
        )
        self.assertEqual(2, stamped)
        # "Looked, no note" still stamps drift_checked_at with a null
        # verdict -- distinguishable from "never looked".
        second_set = self.db.execute.await_args_list[2]
        self.assertIsNone(second_set.args[1]['value'])

    async def test_nothing_unanswered_short_circuits(self) -> None:
        self.db.execute.return_value = []
        stamped = await drift.sweep_project(
            self.db, org_slug='org', project_id='p1'
        )
        self.assertEqual(0, stamped)
        self.resolve.assert_not_awaited()

    async def test_no_capability_is_none(self) -> None:
        self.db.execute.return_value = self._rows()
        for status_code in (400, 404):
            self.resolve.side_effect = fastapi.HTTPException(
                status_code=status_code, detail='nope'
            )
            self.assertIsNone(
                await drift.sweep_project(
                    self.db, org_slug='org', project_id='p1'
                )
            )

    async def test_notes_unsupported_is_none(self) -> None:
        self.db.execute.return_value = self._rows()
        self.handler.get_commit_note.side_effect = NotImplementedError
        self.assertIsNone(
            await drift.sweep_project(self.db, org_slug='org', project_id='p1')
        )

    async def test_recheck_backoff_governs_the_lookup(self) -> None:
        # The filtering itself happens in Cypher; the contract this
        # guards is that the query excludes recently-checked releases
        # and asks about never-checked ones first, with the cutoff
        # derived from RECHECK_AFTER.
        self.db.execute.return_value = []
        now = datetime.datetime(2026, 8, 18, 12, tzinfo=datetime.UTC)
        await drift.sweep_project(
            self.db, org_slug='org', project_id='p1', now=now
        )
        query, params = self.db.execute.await_args.args[:2]
        self.assertIn('r.drift_checked_at IS NULL', query)
        self.assertIn('r.drift_checked_at < {cutoff}', query)
        self.assertIn("COALESCE(r.drift_checked_at, '') ASC", query)
        self.assertEqual(
            (now - drift.RECHECK_AFTER).isoformat(), params['cutoff']
        )

    async def test_rate_limit_propagates_and_stops_the_sweep(self) -> None:
        # PluginRateLimited must reach the maintenance worker so the
        # project is requeued -- swallowing it would hammer the
        # remaining releases against a throttled remote.
        self.db.execute.return_value = self._rows()
        self.handler.get_commit_note.side_effect = (
            plugin_errors.PluginRateLimited(retry_at=1234.0)
        )
        with self.assertRaises(plugin_errors.PluginRateLimited):
            await drift.sweep_project(self.db, org_slug='org', project_id='p1')
        # Only the release lookup ran; nothing was stamped.
        self.assertEqual(1, self.db.execute.await_count)

    async def test_remote_error_skips_the_release(self) -> None:
        self.db.execute.side_effect = [
            self._rows(),
            [{'id': '"rel-2"'}],
        ]
        self.handler.get_commit_note.side_effect = [
            RuntimeError('remote unhappy'),
            '{"drift_detected": false}',
        ]
        with self.assertLogs(drift.LOGGER, level='ERROR'):
            stamped = await drift.sweep_project(
                self.db, org_slug='org', project_id='p1'
            )
        self.assertEqual(1, stamped)
