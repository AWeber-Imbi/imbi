"""Tests for session management."""

import datetime
import unittest
from unittest import mock

from imbi_api import settings
from imbi_api.auth import sessions


class EnforceSessionLimitTestCase(unittest.IsolatedAsyncioTestCase):
    """Test enforce_session_limit function."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.auth_settings = settings.Auth(max_concurrent_sessions=3)

    async def test_enforce_limit_no_sessions(self) -> None:
        """Test enforce_session_limit with no sessions."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []

        # Should not raise, just return
        await sessions.enforce_session_limit(
            mock_db, 'testuser', self.auth_settings
        )
        mock_db.execute.assert_awaited_once()

    async def test_enforce_limit_within_limit(self) -> None:
        """Test enforce_session_limit with sessions within limit."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'removed': 0}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            # Should issue a single query and not log any removal
            await sessions.enforce_session_limit(
                mock_db, 'testuser', self.auth_settings
            )
        mock_db.execute.assert_awaited_once()
        call_args = mock_db.execute.await_args
        params = call_args[0][1] if len(call_args[0]) > 1 else {}
        self.assertEqual('testuser', params.get('email'))
        self.assertEqual(3, params.get('limit'))

    async def test_enforce_limit_exceeds_limit(self) -> None:
        """Test enforce_session_limit removes oldest sessions."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'removed': 2}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            await sessions.enforce_session_limit(
                mock_db, 'testuser', self.auth_settings
            )

        # Single query with email and limit params
        mock_db.execute.assert_awaited_once()
        call_args = mock_db.execute.await_args
        params = call_args[0][1] if len(call_args[0]) > 1 else {}
        self.assertEqual('testuser', params.get('email'))
        self.assertEqual(3, params.get('limit'))


class UpdateSessionActivityTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test update_session_activity function."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.auth_settings = settings.Auth(last_used_throttle_seconds=60)

    async def test_update_session_activity(self) -> None:
        """Test update_session_activity issues a throttled SET query."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []

        await sessions.update_session_activity(
            mock_db, 'session123', self.auth_settings
        )

        # Verify execute was called with the expected params and the
        # query carries the throttling guard.
        mock_db.execute.assert_awaited_once()
        call_args = mock_db.execute.await_args
        assert call_args is not None
        query = call_args[0][0]
        params = call_args[0][1] if len(call_args[0]) > 1 else {}
        self.assertEqual('session123', params.get('session_id'))
        self.assertIn('threshold', params)
        self.assertIn('s.last_activity IS NULL', query)
        self.assertIn('s.last_activity < {threshold}', query)
        # ``now`` and ``threshold`` should be 60 seconds apart.
        now_dt = datetime.datetime.fromisoformat(params['now'])
        threshold_dt = datetime.datetime.fromisoformat(params['threshold'])
        self.assertEqual(60.0, (now_dt - threshold_dt).total_seconds())

    async def test_zero_throttle_uses_now_as_threshold(self) -> None:
        """With throttle=0 the WHERE filter never blocks the write."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []
        zero_settings = settings.Auth(last_used_throttle_seconds=0)

        await sessions.update_session_activity(
            mock_db, 'session123', zero_settings
        )

        call_args = mock_db.execute.await_args
        assert call_args is not None
        params = call_args[0][1] if len(call_args[0]) > 1 else {}
        self.assertEqual(params['now'], params['threshold'])


class DeleteExpiredSessionsTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test delete_expired_sessions function."""

    async def test_delete_expired_sessions_none_expired(self) -> None:
        """Test delete_expired_sessions when no sessions expired."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'deleted_count': 0}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            count = await sessions.delete_expired_sessions(mock_db)
            self.assertEqual(0, count)

    async def test_delete_expired_sessions_some_expired(
        self,
    ) -> None:
        """Test delete_expired_sessions removes expired sessions."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'deleted_count': 5}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            count = await sessions.delete_expired_sessions(mock_db)
            self.assertEqual(5, count)

    async def test_delete_expired_sessions_empty_result(
        self,
    ) -> None:
        """Test delete_expired_sessions with empty result."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            count = await sessions.delete_expired_sessions(mock_db)
            self.assertEqual(0, count)
