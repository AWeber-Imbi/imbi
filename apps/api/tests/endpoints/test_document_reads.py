"""Tests for read-tracking policy: clamping, classification, ingest."""

import datetime
import unittest
from unittest import mock

import fastapi.testclient

from apps.api.tests import support
from imbi.api import models
from imbi.api.endpoints import _document_reads


class ClampEngagedTimeTestCase(unittest.TestCase):
    """A heartbeat may not claim more time than it could have accrued."""

    def test_normal_delta_passes_through(self) -> None:
        value, clamped = _document_reads.clamp_engaged_ms(12_000)
        self.assertEqual(value, 12_000)
        self.assertFalse(clamped)

    def test_delta_above_ceiling_is_clamped_and_flagged(self) -> None:
        value, clamped = _document_reads.clamp_engaged_ms(8 * 60 * 60 * 1000)
        self.assertEqual(value, _document_reads.MAX_ENGAGED_DELTA_MS)
        self.assertTrue(clamped)

    def test_ceiling_allows_a_late_beat(self) -> None:
        """One interval plus the 1.5x cushion is legitimate, not clamped."""
        value, clamped = _document_reads.clamp_engaged_ms(
            _document_reads.HEARTBEAT_INTERVAL_SECONDS * 1000
        )
        self.assertEqual(
            value, _document_reads.HEARTBEAT_INTERVAL_SECONDS * 1000
        )
        self.assertFalse(clamped)

    def test_negative_delta_clamps_to_zero(self) -> None:
        """A backwards clock cannot subtract engagement."""
        value, clamped = _document_reads.clamp_engaged_ms(-5_000)
        self.assertEqual(value, 0)
        self.assertTrue(clamped)


class ClassifySessionTestCase(unittest.TestCase):
    """View/read classification from a finalized session's totals."""

    def test_below_view_floor_is_neither(self) -> None:
        is_view, is_read = _document_reads.classify(
            surface='web', engaged_ms=2_000, max_scroll_pct=100, read_ms=60_000
        )
        self.assertFalse(is_view)
        self.assertFalse(is_read)

    def test_scroll_depth_makes_a_long_document_read(self) -> None:
        is_view, is_read = _document_reads.classify(
            surface='web',
            engaged_ms=30_000,
            max_scroll_pct=85,
            read_ms=600_000,
        )
        self.assertTrue(is_view)
        self.assertTrue(is_read)

    def test_dwell_makes_a_short_document_read(self) -> None:
        is_view, is_read = _document_reads.classify(
            surface='web', engaged_ms=45_000, max_scroll_pct=10, read_ms=30_000
        )
        self.assertTrue(is_view)
        self.assertTrue(is_read)

    def test_skim_is_a_view_but_not_a_read(self) -> None:
        is_view, is_read = _document_reads.classify(
            surface='web',
            engaged_ms=8_000,
            max_scroll_pct=20,
            read_ms=600_000,
        )
        self.assertTrue(is_view)
        self.assertFalse(is_read)

    def test_agent_fetch_is_a_view_never_a_read(self) -> None:
        """Agents have no attention to measure, so they never 'read'."""
        for surface in ('mcp', 'assistant', 'slackbot', 'api'):
            with self.subTest(surface=surface):
                is_view, is_read = _document_reads.classify(
                    surface=surface,
                    engaged_ms=0,
                    max_scroll_pct=0,
                    read_ms=60_000,
                )
                self.assertTrue(is_view)
                self.assertFalse(is_read)


class EstimatedReadTimeTestCase(unittest.TestCase):
    def test_empty_content_has_no_estimate(self) -> None:
        self.assertEqual(_document_reads.estimated_read_ms(''), 0)

    def test_estimate_tracks_word_count(self) -> None:
        content = ' '.join(['word'] * _document_reads.WORDS_PER_MINUTE)
        self.assertEqual(_document_reads.estimated_read_ms(content), 60_000)


class ReadEventIngestTestCase(support.SharedAppTestCase):
    """The heartbeat sink."""

    def setUp(self) -> None:
        from imbi.api.auth import permissions
        from imbi.common import graph, valkey

        self.user = models.User(
            email='reader@example.com',
            display_name='Reader',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.user,
            session_id='test-session',
            auth_method='jwt',
            permissions={'document:read'},
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.mock_db = mock.AsyncMock()
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )
        self.mock_valkey = mock.AsyncMock()
        self.mock_valkey.get.return_value = None
        self.test_app.dependency_overrides[valkey._inject_client] = (
            lambda: self.mock_valkey
        )

        # The document resolves in the org, with 220 words of content.
        self.mock_db.execute.return_value = [
            {
                'project_id': 'proj-1',
                'version': 3,
                'content': ' '.join(['word'] * 220),
                'created_by': 'author@example.com',
            }
        ]

        # Background tasks run inline under TestClient; stub the writes so
        # nothing reaches ClickHouse.
        self.record = mock.AsyncMock()
        self.finalize = mock.AsyncMock(return_value=1)
        for target, replacement in (
            ('_document_reads.record_events', self.record),
            ('_document_reads.finalize_sessions', self.finalize),
        ):
            patcher = mock.patch(
                f'imbi.api.endpoints.document_analytics.{target}', replacement
            )
            patcher.start()
            self.addCleanup(patcher.stop)

        self.client = fastapi.testclient.TestClient(self.test_app)

    def _event(self, **overrides: object) -> dict[str, object]:
        event: dict[str, object] = {
            'session_id': 'session-1',
            'seq': 0,
            'session_started_at': '2026-07-30T12:00:00+00:00',
            'engaged_ms': 12_000,
            'max_scroll_pct': 40,
            'is_final': False,
        }
        event.update(overrides)
        return event

    def _post(self, *events: dict[str, object]):
        return self.client.post(
            '/organizations/engineering/documents/document-1/read-events',
            json={'events': list(events)},
        )

    def test_accepts_a_heartbeat(self) -> None:
        response = self._post(self._event())
        self.assertEqual(response.status_code, 202)
        rows = self.record.await_args.args[0]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].engaged_ms, 12_000)
        self.assertEqual(rows[0].principal, 'reader@example.com')
        self.assertEqual(rows[0].project_id, 'proj-1')
        self.assertEqual(rows[0].document_version, 3)
        self.assertEqual(rows[0].estimated_read_ms, 60_000)
        self.assertEqual(rows[0].clamped, 0)

    def test_clamps_an_inflated_delta(self) -> None:
        self._post(self._event(engaged_ms=8 * 60 * 60 * 1000))
        rows = self.record.await_args.args[0]
        self.assertEqual(
            rows[0].engaged_ms, _document_reads.MAX_ENGAGED_DELTA_MS
        )
        self.assertEqual(rows[0].clamped, 1)

    def test_final_heartbeat_finalizes_the_session(self) -> None:
        self._post(self._event(is_final=True))
        self.finalize.assert_awaited_once_with(['session-1'])

    def test_unknown_document_is_404(self) -> None:
        self.mock_db.execute.return_value = []
        self.assertEqual(self._post(self._event()).status_code, 404)
        self.record.assert_not_awaited()

    def test_rejects_an_oversized_batch(self) -> None:
        events = [self._event(seq=i) for i in range(25)]
        self.assertEqual(self._post(*events).status_code, 400)

    def test_rejects_an_empty_batch(self) -> None:
        response = self.client.post(
            '/organizations/engineering/documents/document-1/read-events',
            json={'events': []},
        )
        self.assertEqual(response.status_code, 422)

    def test_rejects_an_out_of_range_scroll_depth(self) -> None:
        self.assertEqual(
            self._post(self._event(max_scroll_pct=140)).status_code, 422
        )
