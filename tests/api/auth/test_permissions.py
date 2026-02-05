"""Tests for permission system including roles, groups, and inheritance."""

import unittest
from unittest import mock

from imbi_api.auth import permissions


class RoleHierarchyTestCase(unittest.IsolatedAsyncioTestCase):
    """Test role hierarchy and permission inheritance."""

    async def test_load_permissions_with_role_inheritance(self) -> None:
        """Test loading permissions with role inheritance."""
        # Mock user with role that inherits from parent role
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

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            perms = await permissions.load_user_permissions('testuser')

        self.assertEqual(
            perms, {'blueprint:read', 'blueprint:write', 'project:read'}
        )

    async def test_load_permissions_multiple_roles(self) -> None:
        """Test loading permissions from multiple roles."""
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

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            perms = await permissions.load_user_permissions('testuser')

        self.assertIn('blueprint:read', perms)
        self.assertIn('role:read', perms)
        self.assertIn('user:read', perms)


class GroupMembershipTestCase(unittest.IsolatedAsyncioTestCase):
    """Test permission loading from group membership."""

    async def test_load_permissions_from_group(self) -> None:
        """Test loading permissions from group role assignment."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                'permissions': [
                    'blueprint:read',
                    'project:read',  # From group role
                ]
            }
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            perms = await permissions.load_user_permissions('testuser')

        self.assertIn('blueprint:read', perms)
        self.assertIn('project:read', perms)

    async def test_load_permissions_nested_groups(self) -> None:
        """Test loading permissions from nested group hierarchy."""
        # User is in child group, which is in parent group
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                'permissions': [
                    'blueprint:read',  # From child group
                    'project:read',  # From parent group
                ]
            }
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            perms = await permissions.load_user_permissions('testuser')

        self.assertIn('blueprint:read', perms)
        self.assertIn('project:read', perms)


class ResourceLevelPermissionTestCase(unittest.IsolatedAsyncioTestCase):
    """Test resource-level CAN_ACCESS permissions."""

    async def test_check_resource_permission_user_access(self) -> None:
        """Test checking permission with direct user CAN_ACCESS."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'actions': ['read', 'write']}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
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

    async def test_check_resource_permission_group_access(self) -> None:
        """Test checking permission with group CAN_ACCESS."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'actions': ['read']}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            has_access = await permissions.check_resource_permission(
                'testuser', 'Project', 'test-project', 'read'
            )

        self.assertTrue(has_access)

    async def test_check_resource_permission_combined_access(self) -> None:
        """Test checking permission with both user and group CAN_ACCESS."""
        # User has 'read', group has 'write' - should have both
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'actions': ['read', 'write']}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            has_read = await permissions.check_resource_permission(
                'testuser', 'Blueprint', 'test-blueprint', 'read'
            )
            has_write = await permissions.check_resource_permission(
                'testuser', 'Blueprint', 'test-blueprint', 'write'
            )

        self.assertTrue(has_read)
        self.assertTrue(has_write)


class PermissionDeduplicationTestCase(unittest.IsolatedAsyncioTestCase):
    """Test duplicate permissions from multiple sources are deduped."""

    async def test_deduplicate_permissions_from_multiple_roles(self) -> None:
        """Test that duplicate permissions are deduplicated."""
        # User has multiple roles with overlapping permissions
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

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            perms = await permissions.load_user_permissions('testuser')

        # Should be deduplicated to a set
        self.assertEqual(
            perms, {'blueprint:read', 'blueprint:write', 'project:read'}
        )
        self.assertEqual(len(perms), 3)  # No duplicates
