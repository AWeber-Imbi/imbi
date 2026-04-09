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

    async def test_enforce_limit_within_limit(self) -> None:
        """Test enforce_session_limit with sessions within limit."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'session_id': 'sess1',
                'last_activity': datetime.datetime.now(
                    datetime.UTC
                ).isoformat(),
            },
            {
                'session_id': 'sess2',
                'last_activity': datetime.datetime.now(
                    datetime.UTC
                ).isoformat(),
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            # Should not delete any sessions
            await sessions.enforce_session_limit(
                mock_db, 'testuser', self.auth_settings
            )

    async def test_enforce_limit_exceeds_limit(self) -> None:
        """Test enforce_session_limit removes oldest sessions."""
        now = datetime.datetime.now(datetime.UTC)

        # Create 5 sessions (limit is 3), returned sorted by
        # last_activity DESC
        session_data = [
            {
                'session_id': 'sess1',
                'last_activity': (
                    now - datetime.timedelta(minutes=1)
                ).isoformat(),
            },
            {
                'session_id': 'sess2',
                'last_activity': (
                    now - datetime.timedelta(minutes=2)
                ).isoformat(),
            },
            {
                'session_id': 'sess3',
                'last_activity': (
                    now - datetime.timedelta(minutes=3)
                ).isoformat(),
            },
            {
                'session_id': 'sess4',
                'last_activity': (
                    now - datetime.timedelta(minutes=4)
                ).isoformat(),
            },
            {
                'session_id': 'sess5',
                'last_activity': (
                    now - datetime.timedelta(minutes=5)
                ).isoformat(),
            },
        ]

        mock_db = mock.AsyncMock()
        deleted_session_ids: list[str] = []

        def execute_side_effect(query, params=None, columns=None):
            if 'RETURN s.session_id' in query:
                return session_data
            elif 'DETACH DELETE' in query:
                if params and 'session_id' in params:
                    deleted_session_ids.append(params['session_id'])
                return []
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            await sessions.enforce_session_limit(
                mock_db, 'testuser', self.auth_settings
            )

        # Sessions 4 and 5 (oldest) should be deleted
        self.assertIn('sess4', deleted_session_ids)
        self.assertIn('sess5', deleted_session_ids)
        self.assertEqual(len(deleted_session_ids), 2)


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
