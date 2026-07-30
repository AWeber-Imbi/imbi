"""Tests for imbi-api's resource-level permission helper.

The shared permission-resolution cases moved to
``libraries/common/tests/auth/test_permissions.py`` alongside the code
they cover.
"""

import unittest
from unittest import mock

from imbi.api.auth import permissions


class ResourceLevelPermissionTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test resource-level CAN_ACCESS permissions (user direct only)."""

    async def test_check_resource_permission_user_access(self) -> None:
        """Test checking permission with direct user CAN_ACCESS."""
        mock_db = mock.AsyncMock()
        mock_db.execute.side_effect = [
            [{'allowed': True}],
            [{'allowed': True}],
            [{'allowed': False}],
        ]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            has_read = await permissions.check_resource_permission(
                mock_db, 'testuser', 'Blueprint', 'test-blueprint', 'read'
            )
            has_write = await permissions.check_resource_permission(
                mock_db,
                'testuser',
                'Blueprint',
                'test-blueprint',
                'write',
            )
            has_delete = await permissions.check_resource_permission(
                mock_db,
                'testuser',
                'Blueprint',
                'test-blueprint',
                'delete',
            )

        self.assertTrue(has_read)
        self.assertTrue(has_write)
        self.assertFalse(has_delete)

    async def test_check_resource_permission_no_access(self) -> None:
        """Test no access when no CAN_ACCESS relationship exists."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []

        has_access = await permissions.check_resource_permission(
            mock_db, 'testuser', 'Project', 'test-project', 'read'
        )

        self.assertFalse(has_access)
