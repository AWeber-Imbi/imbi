"""Tests for permission system with org-scoped role assignments."""

import datetime
import unittest
from unittest import mock

from imbi_api import models
from imbi_api.auth import permissions


class OrgMembershipPermissionTestCase(unittest.IsolatedAsyncioTestCase):
    """Test permission loading via org membership model."""

    async def test_load_permissions_from_org_membership(self) -> None:
        """Test loading permissions from org membership role."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'permissions': [
                    'blueprint:read',
                    'blueprint:write',
                    'project:read',
                ]
            }
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            perms = await permissions.load_user_permissions(
                mock_db, 'testuser@example.com'
            )

        self.assertEqual(
            perms,
            {'blueprint:read', 'blueprint:write', 'project:read'},
        )

    async def test_load_permissions_with_role_inheritance(self) -> None:
        """Test loading permissions with role inheritance."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'permissions': [
                    'blueprint:read',
                    'blueprint:write',
                    'project:read',  # From parent role
                ]
            }
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            perms = await permissions.load_user_permissions(
                mock_db, 'testuser@example.com'
            )

        self.assertEqual(
            perms,
            {'blueprint:read', 'blueprint:write', 'project:read'},
        )

    async def test_load_permissions_multiple_org_memberships(
        self,
    ) -> None:
        """Test permissions from multiple org memberships are merged."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'permissions': [
                    'blueprint:read',
                    'blueprint:write',
                    'role:read',
                    'user:read',
                ]
            }
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            perms = await permissions.load_user_permissions(
                mock_db, 'testuser@example.com'
            )

        self.assertIn('blueprint:read', perms)
        self.assertIn('role:read', perms)
        self.assertIn('user:read', perms)

    async def test_load_permissions_no_memberships(self) -> None:
        """Test empty permissions for user with no org memberships."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []

        perms = await permissions.load_user_permissions(
            mock_db, 'nobody@example.com'
        )

        self.assertEqual(perms, set())


class ResourceLevelPermissionTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test resource-level CAN_ACCESS permissions (user direct only)."""

    async def test_check_resource_permission_user_access(self) -> None:
        """Test checking permission with direct user CAN_ACCESS."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'actions': ['read', 'write']}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
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


class PermissionDeduplicationTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test duplicate permissions from multiple sources are deduped."""

    async def test_deduplicate_permissions(self) -> None:
        """Test that duplicate permissions are deduplicated."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
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

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            perms = await permissions.load_user_permissions(
                mock_db, 'testuser@example.com'
            )

        # Should be deduplicated to a set
        self.assertEqual(
            perms,
            {'blueprint:read', 'blueprint:write', 'project:read'},
        )
        self.assertEqual(len(perms), 3)  # No duplicates


class AuthContextTestCase(unittest.TestCase):
    """Test AuthContext properties for users and service accounts."""

    def test_auth_context_principal_name_user(self) -> None:
        """User principal returns email."""
        user = models.User(
            email='user@example.com',
            display_name='Test User',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        ctx = permissions.AuthContext(
            user=user,
            session_id='sess-1',
            auth_method='jwt',
            permissions={'project:read'},
        )
        self.assertEqual(ctx.principal_name, 'user@example.com')

    def test_auth_context_principal_name_service_account(
        self,
    ) -> None:
        """Service account principal returns slug."""
        sa = models.ServiceAccount(
            slug='deploy-bot',
            display_name='Deploy Bot',
            is_active=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        ctx = permissions.AuthContext(
            service_account=sa,
            session_id='sess-2',
            auth_method='client_credentials',
            permissions={'project:read'},
        )
        self.assertEqual(ctx.principal_name, 'deploy-bot')

    def test_auth_context_is_admin_user(self) -> None:
        """Admin user returns True for is_admin."""
        user = models.User(
            email='admin@example.com',
            display_name='Admin',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        ctx = permissions.AuthContext(
            user=user,
            session_id='sess-3',
            auth_method='jwt',
        )
        self.assertTrue(ctx.is_admin)

    def test_auth_context_is_admin_service_account(self) -> None:
        """Service account always returns False for is_admin."""
        sa = models.ServiceAccount(
            slug='deploy-bot',
            display_name='Deploy Bot',
            is_active=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        ctx = permissions.AuthContext(
            service_account=sa,
            session_id='sess-4',
            auth_method='client_credentials',
        )
        self.assertFalse(ctx.is_admin)


class ServiceAccountPermissionTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test service account permission loading."""

    async def test_load_service_account_permissions(self) -> None:
        """Test loading permissions for a SA via graph."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'permissions': [
                    'project:read',
                    'project:write',
                    'blueprint:read',
                ]
            }
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            perms = await permissions.load_service_account_permissions(
                mock_db, 'deploy-bot'
            )

        self.assertEqual(
            perms,
            {'project:read', 'project:write', 'blueprint:read'},
        )

    async def test_authenticate_jwt_client_credentials(
        self,
    ) -> None:
        """JWT with auth_method=client_credentials loads SA."""
        from imbi_common.auth import core

        from imbi_api import settings

        auth_settings = settings.get_auth_settings()

        # Create a token with client_credentials auth_method
        token = core.create_access_token(
            'deploy-bot',
            extra_claims={'auth_method': 'client_credentials'},
            auth_settings=auth_settings,
        )

        test_sa = models.ServiceAccount(
            slug='deploy-bot',
            display_name='Deploy Bot',
            is_active=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        mock_db = mock.AsyncMock()

        def execute_side_effect(query, params=None, columns=None):
            if 'TokenMetadata' in query:
                return [{'revoked': False}]
            elif 'MEMBER_OF' in query:
                # Permissions query (contains both ServiceAccount
                # and MEMBER_OF)
                return [{'permissions': ['project:read']}]
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)
        # authenticate_jwt uses db.match() for SA lookup
        mock_db.match.return_value = [test_sa]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            ctx = await permissions.authenticate_jwt(
                mock_db, token, auth_settings
            )

        self.assertIsNotNone(ctx.service_account)
        self.assertIsNone(ctx.user)
        self.assertEqual(ctx.service_account.slug, 'deploy-bot')
        self.assertEqual(ctx.auth_method, 'client_credentials')
        self.assertIn('project:read', ctx.permissions)
