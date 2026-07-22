"""Tests for session management."""

import unittest
from unittest import mock

from imbi.api.auth import sessions


class DeleteExpiredSessionsTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test delete_expired_sessions function."""

    async def test_delete_expired_sessions_none_expired(self) -> None:
        """Test delete_expired_sessions when no sessions expired."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'deleted_count': 0}]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
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
            'imbi.common.graph.parse_agtype',
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
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            count = await sessions.delete_expired_sessions(mock_db)
            self.assertEqual(0, count)
