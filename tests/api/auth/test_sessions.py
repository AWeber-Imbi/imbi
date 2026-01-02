"""Tests for session management."""

import datetime
import unittest
from unittest import mock

from imbi import settings
from imbi.auth import sessions


class EnforceSessionLimitTestCase(unittest.IsolatedAsyncioTestCase):
    """Test enforce_session_limit function."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.auth_settings = settings.Auth(max_concurrent_sessions=3)

    async def test_enforce_limit_no_sessions(self) -> None:
        """Test enforce_session_limit with no sessions."""
        mock_result = mock.AsyncMock()
        mock_result.data = mock.AsyncMock(return_value=[])
        mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
        mock_result.__aexit__ = mock.AsyncMock(return_value=None)

        with mock.patch('imbi.neo4j.run', return_value=mock_result):
            # Should not raise, just return
            await sessions.enforce_session_limit(
                'testuser', self.auth_settings
            )

    async def test_enforce_limit_within_limit(self) -> None:
        """Test enforce_session_limit with sessions within limit."""
        mock_result = mock.AsyncMock()
        mock_result.data = mock.AsyncMock(
            return_value=[
                {
                    'session_id': 'sess1',
                    'last_activity': datetime.datetime.now(datetime.UTC),
                },
                {
                    'session_id': 'sess2',
                    'last_activity': datetime.datetime.now(datetime.UTC),
                },
            ]
        )
        mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
        mock_result.__aexit__ = mock.AsyncMock(return_value=None)

        with mock.patch('imbi.neo4j.run', return_value=mock_result):
            # Should not delete any sessions
            await sessions.enforce_session_limit(
                'testuser', self.auth_settings
            )

    async def test_enforce_limit_exceeds_limit(self) -> None:
        """Test enforce_session_limit removes oldest sessions."""
        now = datetime.datetime.now(datetime.UTC)

        # Create 5 sessions (limit is 3)
        session_data = [
            {
                'session_id': 'sess1',
                'last_activity': now - datetime.timedelta(minutes=1),
            },  # Newest
            {
                'session_id': 'sess2',
                'last_activity': now - datetime.timedelta(minutes=2),
            },
            {
                'session_id': 'sess3',
                'last_activity': now - datetime.timedelta(minutes=3),
            },
            {
                'session_id': 'sess4',
                'last_activity': now - datetime.timedelta(minutes=4),
            },  # Should be removed
            {
                'session_id': 'sess5',
                'last_activity': now - datetime.timedelta(minutes=5),
            },  # Should be removed
        ]

        def mock_run_side_effect(query: str, **kwargs):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            if 'RETURN s.session_id' in query:
                # First query - return all sessions
                mock_result.data = mock.AsyncMock(return_value=session_data)
            else:
                # Second query - delete sessions
                mock_result.consume = mock.AsyncMock()
                # Verify correct sessions are being deleted
                self.assertIn('sess4', kwargs.get('session_ids', []))
                self.assertIn('sess5', kwargs.get('session_ids', []))
                self.assertEqual(2, len(kwargs.get('session_ids', [])))

            return mock_result

        with mock.patch('imbi.neo4j.run', side_effect=mock_run_side_effect):
            await sessions.enforce_session_limit(
                'testuser', self.auth_settings
            )


class UpdateSessionActivityTestCase(unittest.IsolatedAsyncioTestCase):
    """Test update_session_activity function."""

    async def test_update_session_activity(self) -> None:
        """Test update_session_activity updates timestamp."""
        mock_result = mock.AsyncMock()
        mock_result.consume = mock.AsyncMock()
        mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
        mock_result.__aexit__ = mock.AsyncMock(return_value=None)

        with mock.patch(
            'imbi.neo4j.run', return_value=mock_result
        ) as mock_run:
            await sessions.update_session_activity('session123')

            # Verify query was called with correct session_id
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            self.assertIn('session_id', call_args.kwargs)
            self.assertEqual('session123', call_args.kwargs['session_id'])


class DeleteExpiredSessionsTestCase(unittest.IsolatedAsyncioTestCase):
    """Test delete_expired_sessions function."""

    async def test_delete_expired_sessions_none_expired(self) -> None:
        """Test delete_expired_sessions when no sessions expired."""
        mock_result = mock.AsyncMock()
        mock_result.data = mock.AsyncMock(return_value=[{'deleted_count': 0}])
        mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
        mock_result.__aexit__ = mock.AsyncMock(return_value=None)

        with mock.patch('imbi.neo4j.run', return_value=mock_result):
            count = await sessions.delete_expired_sessions()
            self.assertEqual(0, count)

    async def test_delete_expired_sessions_some_expired(self) -> None:
        """Test delete_expired_sessions removes expired sessions."""
        mock_result = mock.AsyncMock()
        mock_result.data = mock.AsyncMock(return_value=[{'deleted_count': 5}])
        mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
        mock_result.__aexit__ = mock.AsyncMock(return_value=None)

        with mock.patch('imbi.neo4j.run', return_value=mock_result):
            count = await sessions.delete_expired_sessions()
            self.assertEqual(5, count)

    async def test_delete_expired_sessions_empty_result(self) -> None:
        """Test delete_expired_sessions with empty result."""
        mock_result = mock.AsyncMock()
        mock_result.data = mock.AsyncMock(return_value=[])
        mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
        mock_result.__aexit__ = mock.AsyncMock(return_value=None)

        with mock.patch('imbi.neo4j.run', return_value=mock_result):
            count = await sessions.delete_expired_sessions()
            self.assertEqual(0, count)
