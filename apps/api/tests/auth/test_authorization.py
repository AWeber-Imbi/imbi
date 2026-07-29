"""Tests for imbi-api's resource-level authorization.

Token verification and global permission checks moved to
:mod:`imbi.common.auth.permissions`; their tests live in
``libraries/common/tests/auth/test_authorization.py``. What remains here
exercises the ``CAN_ACCESS`` edges and the protected-endpoint wiring,
both specific to this service.
"""

import datetime
import unittest
from unittest import mock

import fastapi

from apps.api.tests import support
from imbi.api import models, settings
from imbi.api.auth import password, permissions
from imbi.common import graph
from imbi.common.auth import core


class ProtectedEndpointTestCase(support.SharedAppTestCase):
    """Test protected endpoints require authentication."""

    def setUp(self) -> None:
        """Prepare TestClient and auth settings."""
        self.app = self.test_app
        self.client = fastapi.testclient.TestClient(self.app)
        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-32-characters!',
            jwt_algorithm='HS256',
            access_token_expire_seconds=3600,
        )
        self.mock_db = mock.AsyncMock()

    def _override_graph_dependency(self) -> None:
        """Override the graph dependency to return mock_db."""
        self.app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

    def tearDown(self) -> None:
        """Remove dependency overrides."""
        self.app.dependency_overrides.clear()

    def test_blueprint_list_without_auth(self) -> None:
        """Test accessing blueprint list without authentication."""
        self._override_graph_dependency()
        response = self.client.get('/blueprints')
        self.assertEqual(response.status_code, 401)

    def test_blueprint_list_with_valid_token(self) -> None:
        """Test accessing blueprint list with valid token."""
        self._override_graph_dependency()

        token = core.create_access_token(
            'testuser', auth_settings=self.auth_settings
        )

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            password_hash=password.hash_password('TestPassword123!'),
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        def execute_side_effect(query, params=None, columns=None):
            if 'TokenMetadata' in query:
                return [{'revoked': False}]
            if 'MEMBER_OF' in query or 'GRANTS' in query:
                return [{'permissions': ['blueprint:read']}]
            return []

        self.mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)
        # match() is called for user lookup then blueprint listing
        self.mock_db.match.side_effect = [
            [test_user],  # authenticate_jwt user lookup
            [],  # blueprint listing
        ]

        with (
            mock.patch('imbi.api.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get(
                '/blueprints',
                headers={'Authorization': f'Bearer {token}'},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)

    def test_blueprint_list_without_permission(self) -> None:
        """Test accessing blueprint list without permission."""
        self._override_graph_dependency()

        token = core.create_access_token(
            'testuser', auth_settings=self.auth_settings
        )

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            password_hash=password.hash_password('TestPassword123!'),
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        def execute_side_effect(query, params=None, columns=None):
            if 'TokenMetadata' in query:
                return [{'revoked': False}]
            if 'MEMBER_OF' in query or 'GRANTS' in query:
                # No permissions
                return [{'permissions': []}]
            return []

        self.mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)
        # authenticate_jwt uses db.match() for user lookup
        self.mock_db.match.return_value = [test_user]

        with (
            mock.patch('imbi.api.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.get(
                '/blueprints',
                headers={'Authorization': f'Bearer {token}'},
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn('Permission denied', response.json()['detail'])


class ResourcePermissionTestCase(unittest.IsolatedAsyncioTestCase):
    """Test resource-level permission checking."""

    async def test_check_resource_permission_granted(self) -> None:
        """Test checking resource permission when granted."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'allowed': True}]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            has_access = await permissions.check_resource_permission(
                mock_db,
                'testuser',
                'Blueprint',
                'test-blueprint',
                'read',
            )

        self.assertTrue(has_access)

    async def test_check_resource_permission_denied(self) -> None:
        """Test checking resource permission when denied."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'allowed': False}]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            has_access = await permissions.check_resource_permission(
                mock_db,
                'testuser',
                'Blueprint',
                'test-blueprint',
                'delete',
            )

        self.assertFalse(has_access)

    async def test_check_resource_permission_no_access(self) -> None:
        """Test checking resource permission with no CAN_ACCESS."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []

        has_access = await permissions.check_resource_permission(
            mock_db,
            'testuser',
            'Blueprint',
            'test-blueprint',
            'read',
        )

        self.assertFalse(has_access)


class ResourceAccessDependencyTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test require_resource_access dependency function."""

    async def asyncSetUp(self) -> None:
        """Create test user fixtures."""
        self.admin_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            password_hash='hash',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.regular_user = models.User(
            email='regular@example.com',
            display_name='Regular User',
            password_hash='hash',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

    async def test_require_resource_access_admin_bypass(
        self,
    ) -> None:
        """Test admin users bypass resource access checks."""
        admin_context = permissions.AuthContext(
            user=self.admin_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        check_fn = permissions.require_resource_access('blueprint', 'read')
        mock_db = mock.AsyncMock()
        result = await check_fn('test-slug', admin_context, mock_db)

        self.assertEqual(result, admin_context)

    async def test_require_resource_access_global_permission(
        self,
    ) -> None:
        """Test user with global permission gets access."""
        user_context = permissions.AuthContext(
            user=self.regular_user,
            session_id='test-session',
            auth_method='jwt',
            permissions={'blueprint:read'},
        )

        check_fn = permissions.require_resource_access('blueprint', 'read')
        mock_db = mock.AsyncMock()
        result = await check_fn('test-slug', user_context, mock_db)

        self.assertEqual(result, user_context)

    async def test_require_resource_access_resource_permission(
        self,
    ) -> None:
        """Test user with resource-level permission gets access."""
        user_context = permissions.AuthContext(
            user=self.regular_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),  # No global permission
        )

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'allowed': True}]

        check_fn = permissions.require_resource_access('blueprint', 'read')

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            result = await check_fn('test-slug', user_context, mock_db)

        self.assertEqual(result, user_context)

    async def test_require_resource_access_denied(self) -> None:
        """Test access denied when user has no permission."""
        user_context = permissions.AuthContext(
            user=self.regular_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []

        check_fn = permissions.require_resource_access('blueprint', 'write')

        with self.assertRaises(fastapi.HTTPException) as ctx:
            await check_fn('test-slug', user_context, mock_db)

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn('Access denied', str(ctx.exception.detail))

    async def test_require_resource_access_unknown_resource_type(
        self,
    ) -> None:
        """M36: unmapped resource_type surfaces as a hard KeyError."""
        user_context = permissions.AuthContext(
            user=self.regular_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )
        mock_db = mock.AsyncMock()

        check_fn = permissions.require_resource_access('bogus_type', 'read')

        with self.assertRaises(KeyError) as ctx:
            await check_fn('test-slug', user_context, mock_db)

        self.assertIn('bogus_type', str(ctx.exception))
        self.assertIn('_RESOURCE_LABEL_MAP', str(ctx.exception))
