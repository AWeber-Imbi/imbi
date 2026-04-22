"""Tests for session management."""

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

    async def test_update_session_activity(self) -> None:
        """Test update_session_activity updates timestamp."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []

        await sessions.update_session_activity(mock_db, 'session123')

        # Verify execute was called with correct session_id
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else {}
        self.assertEqual('session123', params.get('session_id'))


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
