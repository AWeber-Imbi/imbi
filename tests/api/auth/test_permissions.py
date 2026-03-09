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


class AuthContextTestCase(unittest.TestCase):
    """Test AuthContext properties for users and service accounts."""

    def test_auth_context_principal_name_user(self) -> None:
        """User principal returns email."""
        import datetime

        from imbi_api import models

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
        import datetime

        from imbi_api import models

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
        import datetime

        from imbi_api import models

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
        import datetime

        from imbi_api import models

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
        """Test loading permissions from Neo4j for a SA."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                'permissions': [
                    'project:read',
                    'project:write',
                    'blueprint:read',
                ]
            }
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            perms = await permissions.load_service_account_permissions(
                'deploy-bot'
            )

        self.assertEqual(
            perms,
            {'project:read', 'project:write', 'blueprint:read'},
        )

    async def test_authenticate_jwt_client_credentials(
        self,
    ) -> None:
        """JWT with auth_method=client_credentials loads SA."""
        import datetime

        from imbi_common.auth import core

        from imbi_api import settings

        auth_settings = settings.get_auth_settings()

        # Create a token with client_credentials auth_method
        token = core.create_access_token(
            'deploy-bot',
            extra_claims={'auth_method': 'client_credentials'},
            auth_settings=auth_settings,
        )

        sa_data = {
            'slug': 'deploy-bot',
            'display_name': 'Deploy Bot',
            'is_active': True,
            'created_at': datetime.datetime.now(datetime.UTC).isoformat(),
        }

        call_count = 0

        def mock_run_side_effect(query, **params):
            nonlocal call_count
            call_count += 1
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            if 'TokenMetadata' in query:
                # Token not revoked
                mock_result.data = mock.AsyncMock(return_value=[])
            elif 'MEMBER_OF' in query:
                # SA permissions (check before ServiceAccount)
                mock_result.data = mock.AsyncMock(
                    return_value=[
                        {
                            'permissions': [
                                'project:read',
                            ]
                        }
                    ]
                )
            elif 'ServiceAccount' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'s': sa_data}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=mock_run_side_effect,
            ),
            mock.patch(
                'imbi_common.neo4j.convert_neo4j_types',
                side_effect=lambda x: x,
            ),
        ):
            ctx = await permissions.authenticate_jwt(token, auth_settings)

        self.assertIsNotNone(ctx.service_account)
        self.assertIsNone(ctx.user)
        self.assertEqual(ctx.service_account.slug, 'deploy-bot')
        self.assertEqual(ctx.auth_method, 'client_credentials')
        self.assertIn('project:read', ctx.permissions)
