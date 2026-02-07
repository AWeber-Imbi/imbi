"""Tests for permission system with org-scoped role assignments."""

import unittest
from unittest import mock

from imbi_api.auth import permissions


class OrgMembershipPermissionTestCase(unittest.IsolatedAsyncioTestCase):
    """Test permission loading via org membership model."""

    async def test_load_permissions_from_org_membership(self) -> None:
        """Test loading permissions from org membership role."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                'permissions': [
                    'blueprint:read',
                    'blueprint:write',
                    'project:read',
                ]
            }
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            perms = await permissions.load_user_permissions(
                'testuser@example.com'
            )

        self.assertEqual(
            perms,
            {'blueprint:read', 'blueprint:write', 'project:read'},
        )

    async def test_load_permissions_with_role_inheritance(self) -> None:
        """Test loading permissions with role inheritance."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                'permissions': [
                    'blueprint:read',
                    'blueprint:write',
                    'project:read',  # From parent role
                ]
            }
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            perms = await permissions.load_user_permissions(
                'testuser@example.com'
            )

        self.assertEqual(
            perms,
            {'blueprint:read', 'blueprint:write', 'project:read'},
        )

    async def test_load_permissions_multiple_org_memberships(self) -> None:
        """Test permissions from multiple org memberships are merged."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                'permissions': [
                    'blueprint:read',
                    'blueprint:write',
                    'role:read',
                    'user:read',
                ]
            }
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            perms = await permissions.load_user_permissions(
                'testuser@example.com'
            )

        self.assertIn('blueprint:read', perms)
        self.assertIn('role:read', perms)
        self.assertIn('user:read', perms)

    async def test_load_permissions_no_memberships(self) -> None:
        """Test empty permissions for user with no org memberships."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = []
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            perms = await permissions.load_user_permissions(
                'nobody@example.com'
            )

        self.assertEqual(perms, set())


class ResourceLevelPermissionTestCase(unittest.IsolatedAsyncioTestCase):
    """Test resource-level CAN_ACCESS permissions (user direct only)."""

    async def test_check_resource_permission_user_access(self) -> None:
        """Test checking permission with direct user CAN_ACCESS."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'actions': ['read', 'write']}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            has_read = await permissions.check_resource_permission(
                'testuser', 'Blueprint', 'test-blueprint', 'read'
            )
            has_write = await permissions.check_resource_permission(
                'testuser', 'Blueprint', 'test-blueprint', 'write'
            )
            has_delete = await permissions.check_resource_permission(
                'testuser', 'Blueprint', 'test-blueprint', 'delete'
            )

        self.assertTrue(has_read)
        self.assertTrue(has_write)
        self.assertFalse(has_delete)

    async def test_check_resource_permission_no_access(self) -> None:
        """Test no access when no CAN_ACCESS relationship exists."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = []
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            has_access = await permissions.check_resource_permission(
                'testuser', 'Project', 'test-project', 'read'
            )

        self.assertFalse(has_access)


class PermissionDeduplicationTestCase(unittest.IsolatedAsyncioTestCase):
    """Test duplicate permissions from multiple sources are deduped."""

    async def test_deduplicate_permissions(self) -> None:
        """Test that duplicate permissions are deduplicated."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                'permissions': [
                    'blueprint:read',
                    'blueprint:read',  # Duplicate
                    'blueprint:write',
                    'project:read',
                    'project:read',  # Duplicate
                ]
            }
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            perms = await permissions.load_user_permissions(
                'testuser@example.com'
            )

        # Should be deduplicated to a set
        self.assertEqual(
            perms,
            {'blueprint:read', 'blueprint:write', 'project:read'},
        )
        self.assertEqual(len(perms), 3)  # No duplicates
