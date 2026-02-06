"""Tests for authentication system seeding."""

import unittest
from unittest import mock

from imbi_api.auth import seed


class SeedPermissionsTestCase(unittest.IsolatedAsyncioTestCase):
    """Test permission seeding functionality."""

    async def test_seed_permissions_creates_all(self) -> None:
        """Verify all 22 standard permissions are created."""
        mock_result = mock.AsyncMock()
        # Simulate all permissions being newly created
        mock_result.data.return_value = [{'is_new': True}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            count = await seed.seed_permissions()

        # Should create 22 permissions (6 resource types x 3-4 actions each)
        self.assertEqual(count, 22)

    async def test_seed_permissions_idempotent(self) -> None:
        """Second run creates no duplicates."""
        mock_result = mock.AsyncMock()
        # Simulate all permissions already existing
        mock_result.data.return_value = [{'is_new': False}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            count = await seed.seed_permissions()

        # Should create 0 new permissions
        self.assertEqual(count, 0)

    async def test_permission_format_validation(self) -> None:
        """Ensure all permission names match resource_type:action."""
        for (
            name,
            resource_type,
            action,
            _description,
        ) in seed.STANDARD_PERMISSIONS:
            expected_name = f'{resource_type}:{action}'
            self.assertEqual(
                name,
                expected_name,
                f'Permission {name!r} should be {expected_name!r}',
            )


class SeedDefaultRolesTestCase(unittest.IsolatedAsyncioTestCase):
    """Test default role seeding functionality."""

    async def test_seed_default_roles_creates_all(self) -> None:
        """Verify all 3 default roles are created."""
        # Mock for role creation
        mock_role_result = mock.AsyncMock()
        mock_role_result.data.return_value = [{'is_new': True}]
        mock_role_result.__aenter__.return_value = mock_role_result
        mock_role_result.__aexit__.return_value = None

        # Mock for permission grants (consume only, no data)
        mock_perm_result = mock.AsyncMock()
        mock_perm_result.consume.return_value = None
        mock_perm_result.__aenter__.return_value = mock_perm_result
        mock_perm_result.__aexit__.return_value = None

        def run_side_effect(query: str, **_kwargs: object) -> mock.AsyncMock:
            # Return role result for MERGE queries, perm result for GRANTS
            if 'GRANTS' in query:
                return mock_perm_result
            return mock_role_result

        with mock.patch('imbi_common.neo4j.run', side_effect=run_side_effect):
            count = await seed.seed_default_roles()

        # Should create 3 roles (admin, developer, readonly)
        self.assertEqual(count, 3)

    async def test_seed_default_roles_idempotent(self) -> None:
        """Second run creates no duplicate roles."""
        mock_role_result = mock.AsyncMock()
        mock_role_result.data.return_value = [{'is_new': False}]
        mock_role_result.__aenter__.return_value = mock_role_result
        mock_role_result.__aexit__.return_value = None

        mock_perm_result = mock.AsyncMock()
        mock_perm_result.consume.return_value = None
        mock_perm_result.__aenter__.return_value = mock_perm_result
        mock_perm_result.__aexit__.return_value = None

        def run_side_effect(query: str, **_kwargs: object) -> mock.AsyncMock:
            if 'GRANTS' in query:
                return mock_perm_result
            return mock_role_result

        with mock.patch('imbi_common.neo4j.run', side_effect=run_side_effect):
            count = await seed.seed_default_roles()

        # Should create 0 new roles
        self.assertEqual(count, 0)

    def test_default_roles_structure(self) -> None:
        """Verify default role definitions are well-formed."""
        role_slugs = {role[0] for role in seed.DEFAULT_ROLES}
        self.assertEqual(role_slugs, {'admin', 'developer', 'readonly'})

        # Verify admin has all permissions
        admin_role = next(r for r in seed.DEFAULT_ROLES if r[0] == 'admin')
        admin_permissions = admin_role[4]
        self.assertEqual(len(admin_permissions), 22)

        # Verify developer has subset of permissions
        dev_role = next(r for r in seed.DEFAULT_ROLES if r[0] == 'developer')
        dev_permissions = dev_role[4]
        self.assertGreater(len(dev_permissions), 0)
        self.assertLess(len(dev_permissions), 21)

        # Verify readonly has only read permissions
        readonly_role = next(
            r for r in seed.DEFAULT_ROLES if r[0] == 'readonly'
        )
        readonly_permissions = readonly_role[4]
        self.assertTrue(
            all(':read' in perm for perm in readonly_permissions),
            'Readonly role should only have read permissions',
        )


class SeedDefaultOrganizationTestCase(unittest.IsolatedAsyncioTestCase):
    """Test default organization seeding."""

    async def test_seed_default_organization_creates(self) -> None:
        """Verify default organization is created when new."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'is_new': True}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            created = await seed.seed_default_organization()

        self.assertTrue(created)

    async def test_seed_default_organization_idempotent(self) -> None:
        """Second run does not recreate the organization."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'is_new': False}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            created = await seed.seed_default_organization()

        self.assertFalse(created)


class SeedDefaultGroupTestCase(unittest.IsolatedAsyncioTestCase):
    """Test default users group seeding."""

    async def test_seed_default_group_creates(self) -> None:
        """Verify default users group is created when new."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'is_new': True}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            created = await seed.seed_default_group()

        self.assertTrue(created)

    async def test_seed_default_group_idempotent(self) -> None:
        """Second run does not recreate the group."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'is_new': False}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            created = await seed.seed_default_group()

        self.assertFalse(created)


class BootstrapAuthSystemTestCase(unittest.IsolatedAsyncioTestCase):
    """Test complete bootstrap orchestration."""

    async def test_bootstrap_auth_system_complete(self) -> None:
        """Complete bootstrap creates all seed entities."""
        with (
            mock.patch(
                'imbi_api.auth.seed.seed_permissions', return_value=21
            ) as mock_perms,
            mock.patch(
                'imbi_api.auth.seed.seed_default_roles', return_value=3
            ) as mock_roles,
            mock.patch(
                'imbi_api.auth.seed.seed_default_organization',
                return_value=True,
            ) as mock_org,
            mock.patch(
                'imbi_api.auth.seed.seed_default_group',
                return_value=True,
            ) as mock_group,
        ):
            result = await seed.bootstrap_auth_system()

        mock_perms.assert_called_once()
        mock_roles.assert_called_once()
        mock_org.assert_called_once()
        mock_group.assert_called_once()

        self.assertEqual(result['permissions'], 21)
        self.assertEqual(result['roles'], 3)
        self.assertTrue(result['organization'])
        self.assertTrue(result['group'])

    async def test_bootstrap_auth_system_idempotent(self) -> None:
        """Bootstrap can be safely run multiple times."""
        with (
            mock.patch('imbi_api.auth.seed.seed_permissions', return_value=0),
            mock.patch(
                'imbi_api.auth.seed.seed_default_roles', return_value=0
            ),
            mock.patch(
                'imbi_api.auth.seed.seed_default_organization',
                return_value=False,
            ),
            mock.patch(
                'imbi_api.auth.seed.seed_default_group',
                return_value=False,
            ),
        ):
            result = await seed.bootstrap_auth_system()

        self.assertEqual(result['permissions'], 0)
        self.assertEqual(result['roles'], 0)
        self.assertFalse(result['organization'])
        self.assertFalse(result['group'])


class CheckIfSeededTestCase(unittest.IsolatedAsyncioTestCase):
    """Test seeding status check."""

    async def test_check_if_seeded_true(self) -> None:
        """Returns True when permissions exist."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'count': 24}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            is_seeded = await seed.check_if_seeded()

        self.assertTrue(is_seeded)

    async def test_check_if_seeded_false_no_permissions(self) -> None:
        """Returns False when no permissions exist."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'count': 0}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            is_seeded = await seed.check_if_seeded()

        self.assertFalse(is_seeded)

    async def test_check_if_seeded_false_empty_result(self) -> None:
        """Returns False when query returns empty."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = []
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch('imbi_common.neo4j.run', return_value=mock_result):
            is_seeded = await seed.check_if_seeded()

        self.assertFalse(is_seeded)
