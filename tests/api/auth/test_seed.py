"""Tests for authentication system seeding."""

import unittest
from unittest import mock

from imbi_api.auth import seed


class SeedPermissionsTestCase(unittest.IsolatedAsyncioTestCase):
    """Test permission seeding functionality."""

    async def test_seed_permissions_creates_all(self) -> None:
        """Verify all standard permissions are created."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {'created': len(seed.STANDARD_PERMISSIONS)}
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            count = await seed.seed_permissions(mock_db)

        self.assertEqual(count, len(seed.STANDARD_PERMISSIONS))
        mock_db.execute.assert_awaited_once()

    async def test_seed_permissions_idempotent(self) -> None:
        """Second run creates no duplicates."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'created': 0}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            count = await seed.seed_permissions(mock_db)

        self.assertEqual(count, 0)
        mock_db.execute.assert_awaited_once()

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
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'created': len(seed.DEFAULT_ROLES)}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            count = await seed.seed_default_roles(mock_db)

        self.assertEqual(count, len(seed.DEFAULT_ROLES))
        mock_db.execute.assert_awaited_once()

    async def test_seed_default_roles_idempotent(self) -> None:
        """Second run creates no duplicate roles."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'created': 0}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            count = await seed.seed_default_roles(mock_db)

        self.assertEqual(count, 0)
        mock_db.execute.assert_awaited_once()

    def test_default_roles_structure(self) -> None:
        """Verify default role definitions are well-formed."""
        role_slugs = {role[0] for role in seed.DEFAULT_ROLES}
        self.assertEqual(role_slugs, {'admin', 'developer', 'readonly'})

        # Verify admin has all permissions
        admin_role = next(r for r in seed.DEFAULT_ROLES if r[0] == 'admin')
        admin_permissions = admin_role[4]
        self.assertEqual(
            len(admin_permissions),
            len(seed.STANDARD_PERMISSIONS),
        )

        # Verify developer has subset of permissions
        dev_role = next(r for r in seed.DEFAULT_ROLES if r[0] == 'developer')
        dev_permissions = dev_role[4]
        self.assertGreater(len(dev_permissions), 0)
        self.assertLess(
            len(dev_permissions),
            len(seed.STANDARD_PERMISSIONS),
        )

        # Verify readonly has only read permissions
        readonly_role = next(
            r for r in seed.DEFAULT_ROLES if r[0] == 'readonly'
        )
        readonly_permissions = readonly_role[4]
        self.assertTrue(
            all(':read' in perm for perm in readonly_permissions),
            'Readonly role should only have read permissions',
        )

    def test_no_group_permissions(self) -> None:
        """Verify no group permissions exist."""
        perm_names = {p[0] for p in seed.STANDARD_PERMISSIONS}
        group_perms = {p for p in perm_names if p.startswith('group:')}
        self.assertEqual(
            group_perms, set(), 'No group permissions should exist'
        )


class SeedDefaultOrganizationTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test default organization seeding."""

    async def test_seed_default_organization_creates(self) -> None:
        """Verify default organization is created when new."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'is_new': True}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            created = await seed.seed_default_organization(mock_db)

        self.assertTrue(created)

    async def test_seed_default_organization_idempotent(
        self,
    ) -> None:
        """Second run does not recreate the organization."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'is_new': False}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            created = await seed.seed_default_organization(mock_db)

        self.assertFalse(created)


class BootstrapAuthSystemTestCase(unittest.IsolatedAsyncioTestCase):
    """Test complete bootstrap orchestration."""

    async def test_bootstrap_auth_system_complete(self) -> None:
        """Complete bootstrap creates all seed entities."""
        mock_db = mock.AsyncMock()

        with (
            mock.patch(
                'imbi_api.auth.seed.seed_default_organization',
                return_value=True,
            ) as mock_org,
            mock.patch(
                'imbi_api.auth.seed.seed_permissions',
                return_value=len(seed.STANDARD_PERMISSIONS),
            ) as mock_perms,
            mock.patch(
                'imbi_api.auth.seed.seed_default_roles',
                return_value=3,
            ) as mock_roles,
        ):
            result = await seed.bootstrap_auth_system(mock_db)

        mock_org.assert_called_once_with(mock_db, 'default', 'Default')
        mock_perms.assert_called_once_with(mock_db)
        mock_roles.assert_called_once_with(mock_db)

        self.assertTrue(result['organization'])
        self.assertEqual(
            result['permissions'],
            len(seed.STANDARD_PERMISSIONS),
        )
        self.assertEqual(result['roles'], 3)

    async def test_bootstrap_auth_system_idempotent(self) -> None:
        """Bootstrap can be safely run multiple times."""
        mock_db = mock.AsyncMock()

        with (
            mock.patch(
                'imbi_api.auth.seed.seed_default_organization',
                return_value=False,
            ),
            mock.patch(
                'imbi_api.auth.seed.seed_permissions',
                return_value=0,
            ),
            mock.patch(
                'imbi_api.auth.seed.seed_default_roles',
                return_value=0,
            ),
        ):
            result = await seed.bootstrap_auth_system(mock_db)

        self.assertFalse(result['organization'])
        self.assertEqual(result['permissions'], 0)
        self.assertEqual(result['roles'], 0)

    async def test_bootstrap_result_has_no_group_key(self) -> None:
        """Verify bootstrap result does not contain group key."""
        mock_db = mock.AsyncMock()

        with (
            mock.patch(
                'imbi_api.auth.seed.seed_default_organization',
                return_value=True,
            ),
            mock.patch(
                'imbi_api.auth.seed.seed_permissions',
                return_value=0,
            ),
            mock.patch(
                'imbi_api.auth.seed.seed_default_roles',
                return_value=0,
            ),
        ):
            result = await seed.bootstrap_auth_system(mock_db)

        self.assertNotIn('group', result)


class CheckIfSeededTestCase(unittest.IsolatedAsyncioTestCase):
    """Test seeding status check."""

    async def test_check_if_seeded_true(self) -> None:
        """Returns True when all seed components exist."""
        expected_perms = len(seed.STANDARD_PERMISSIONS)
        expected_roles = len(seed.DEFAULT_ROLES)
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'perm_count': expected_perms,
                'role_count': expected_roles,
                'org_count': 1,
            }
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            is_seeded = await seed.check_if_seeded(mock_db)

        self.assertTrue(is_seeded)

    async def test_check_if_seeded_false_no_permissions(
        self,
    ) -> None:
        """Returns False when no permissions exist."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'perm_count': 0,
                'role_count': 0,
                'org_count': 0,
            }
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            is_seeded = await seed.check_if_seeded(mock_db)

        self.assertFalse(is_seeded)

    async def test_check_if_seeded_false_partial_seed(
        self,
    ) -> None:
        """Returns False when only permissions seeded."""
        expected_perms = len(seed.STANDARD_PERMISSIONS)
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'perm_count': expected_perms,
                'role_count': 0,
                'org_count': 0,
            }
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            is_seeded = await seed.check_if_seeded(mock_db)

        self.assertFalse(is_seeded)

    async def test_check_if_seeded_false_empty_result(
        self,
    ) -> None:
        """Returns False when query returns empty."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []

        is_seeded = await seed.check_if_seeded(mock_db)

        self.assertFalse(is_seeded)


class StandardPermissionsTests(unittest.TestCase):
    """Tests for the STANDARD_PERMISSIONS catalogue."""

    def test_operations_log_permissions_present(self) -> None:
        slugs = {perm[0] for perm in seed.STANDARD_PERMISSIONS}
        for action in ('create', 'read', 'update', 'delete'):
            with self.subTest(action=action):
                self.assertIn(f'operations_log:{action}', slugs)
