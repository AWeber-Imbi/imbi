"""Tests for authorization and permission checking."""

import datetime
import unittest
from unittest import mock

import fastapi
from imbi_common import graph
from imbi_common.auth import core

from imbi_api import app, models, settings
from imbi_api.auth import password, permissions


class PermissionLoadingTestCase(unittest.IsolatedAsyncioTestCase):
    """Test permission loading from org membership roles."""

    async def test_load_user_permissions_direct_role(self) -> None:
        """Test loading permissions from direct role assignment."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {'permissions': ['blueprint:read', 'blueprint:write']}
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            perms = await permissions.load_user_permissions(
                mock_db, 'testuser'
            )

        self.assertEqual(perms, {'blueprint:read', 'blueprint:write'})

    async def test_load_user_permissions_empty(self) -> None:
        """Test loading permissions for user with no roles."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []

        perms = await permissions.load_user_permissions(mock_db, 'testuser')

        self.assertEqual(perms, set())


class AuthenticateJWTTestCase(unittest.IsolatedAsyncioTestCase):
    """Test JWT authentication."""

    async def asyncSetUp(self) -> None:
        """Set up test authentication settings and a sample user."""
        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-32-characters!',
            jwt_algorithm='HS256',
            access_token_expire_seconds=3600,
        )
        self.test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            password_hash=password.hash_password('TestPassword123!'),
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

    async def test_authenticate_jwt_success(self) -> None:
        """Test successful JWT authentication."""
        token = core.create_access_token(
            'testuser', auth_settings=self.auth_settings
        )
        import jwt as pyjwt

        payload = pyjwt.decode(
            token,
            self.auth_settings.jwt_secret,
            algorithms=[self.auth_settings.jwt_algorithm],
        )
        jti = payload['jti']

        mock_db = mock.AsyncMock()

        def execute_side_effect(query, params=None, columns=None):
            if 'TokenMetadata' in query:
                return [{'revoked': False}]
            elif 'MEMBER_OF' in query or 'GRANTS' in query:
                return [{'permissions': ['blueprint:read']}]
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)
        # authenticate_jwt uses db.match() for user lookup
        mock_db.match.return_value = [self.test_user]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            auth_context = await permissions.authenticate_jwt(
                mock_db, token, self.auth_settings
            )

        self.assertEqual(auth_context.user.email, 'test@example.com')
        self.assertEqual(auth_context.auth_method, 'jwt')
        self.assertEqual(auth_context.session_id, jti)
        self.assertIn('blueprint:read', auth_context.permissions)

    async def test_authenticate_jwt_expired(self) -> None:
        """Test authentication with expired token."""
        expired_settings = settings.Auth(
            jwt_secret='test-secret-key-32-characters!',
            access_token_expire_seconds=-1,  # Already expired
        )
        token = core.create_access_token(
            'testuser', auth_settings=expired_settings
        )

        mock_db = mock.AsyncMock()

        with self.assertRaises(fastapi.HTTPException) as ctx:
            await permissions.authenticate_jwt(
                mock_db, token, expired_settings
            )

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn('expired', str(ctx.exception.detail).lower())

    async def test_authenticate_jwt_invalid_token(self) -> None:
        """Test authentication with invalid token."""
        mock_db = mock.AsyncMock()

        with self.assertRaises(fastapi.HTTPException) as ctx:
            await permissions.authenticate_jwt(
                mock_db, 'invalid.token.here', self.auth_settings
            )

        self.assertEqual(ctx.exception.status_code, 401)

    async def test_authenticate_jwt_revoked_token(self) -> None:
        """Test authentication with revoked token."""
        token = core.create_access_token(
            'testuser', auth_settings=self.auth_settings
        )

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'revoked': True}]

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            self.assertRaises(fastapi.HTTPException) as ctx,
        ):
            await permissions.authenticate_jwt(
                mock_db, token, self.auth_settings
            )

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn('revoked', str(ctx.exception.detail).lower())

    async def test_authenticate_jwt_inactive_user(self) -> None:
        """Test authentication with inactive user."""
        token = core.create_access_token(
            'testuser', auth_settings=self.auth_settings
        )

        inactive_user = models.User(
            email='test@example.com',
            display_name='Test User',
            password_hash=self.test_user.password_hash,
            is_active=False,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        mock_db = mock.AsyncMock()

        def execute_side_effect(query, params=None, columns=None):
            if 'TokenMetadata' in query:
                return [{'revoked': False}]
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)
        # authenticate_jwt uses db.match() for user lookup
        mock_db.match.return_value = [inactive_user]

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            self.assertRaises(fastapi.HTTPException) as ctx,
        ):
            await permissions.authenticate_jwt(
                mock_db, token, self.auth_settings
            )

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn('inactive', str(ctx.exception.detail).lower())

    async def test_authenticate_jwt_invalid_token_type(self) -> None:
        """Verifies that a refresh token is rejected."""
        token_settings = settings.Auth(
            jwt_secret='test-secret-key-32-characters!',
            jwt_algorithm='HS256',
            access_token_expire_seconds=3600,
        )
        refresh_token = core.create_refresh_token(
            'testuser', auth_settings=token_settings
        )

        mock_db = mock.AsyncMock()

        with self.assertRaises(fastapi.HTTPException) as ctx:
            await permissions.authenticate_jwt(
                mock_db, refresh_token, token_settings
            )

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn('token type', str(ctx.exception.detail).lower())

    async def test_authenticate_jwt_missing_subject(self) -> None:
        """Test authentication with token missing subject."""
        import jwt as pyjwt

        # Create a token without 'sub' claim
        claims_without_sub = {
            'type': 'access',
            'jti': 'test-jti',
            'exp': datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(hours=1),
        }
        token_no_sub = pyjwt.encode(
            claims_without_sub,
            self.auth_settings.jwt_secret,
            algorithm=self.auth_settings.jwt_algorithm,
        )

        mock_db = mock.AsyncMock()

        # verify_token requires 'sub' claim, so PyJWT raises
        # MissingRequiredClaimError (subclass of InvalidTokenError)
        with self.assertRaises(fastapi.HTTPException) as ctx:
            await permissions.authenticate_jwt(
                mock_db, token_no_sub, self.auth_settings
            )

        self.assertEqual(ctx.exception.status_code, 401)

    async def test_authenticate_jwt_user_not_found(self) -> None:
        """Test authentication when user doesn't exist."""
        token = core.create_access_token(
            'testuser', auth_settings=self.auth_settings
        )

        mock_db = mock.AsyncMock()

        def execute_side_effect(query, params=None, columns=None):
            if 'TokenMetadata' in query:
                return [{'revoked': False}]
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)
        # authenticate_jwt uses db.match() for user lookup
        mock_db.match.return_value = []

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            self.assertRaises(fastapi.HTTPException) as ctx,
        ):
            await permissions.authenticate_jwt(
                mock_db, token, self.auth_settings
            )

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn('not found', str(ctx.exception.detail).lower())


class ProtectedEndpointTestCase(unittest.TestCase):
    """Test protected endpoints require authentication."""

    def setUp(self) -> None:
        """Prepare TestClient and auth settings."""
        self.app = app.create_app()
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
            elif 'MEMBER_OF' in query or 'GRANTS' in query:
                return [{'permissions': ['blueprint:read']}]
            return []

        self.mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)
        # match() is called for user lookup then blueprint listing
        self.mock_db.match.side_effect = [
            [test_user],  # authenticate_jwt user lookup
            [],  # blueprint listing
        ]

        with (
            mock.patch('imbi_api.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
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
            elif 'MEMBER_OF' in query or 'GRANTS' in query:
                # No permissions
                return [{'permissions': []}]
            return []

        self.mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)
        # authenticate_jwt uses db.match() for user lookup
        self.mock_db.match.return_value = [test_user]

        with (
            mock.patch('imbi_api.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
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
        mock_db.execute.return_value = [{'actions': ['read', 'write']}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
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
        mock_db.execute.return_value = [{'actions': ['read']}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
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
        mock_db.execute.return_value = [{'actions': ['read', 'write']}]

        check_fn = permissions.require_resource_access('blueprint', 'read')

        with mock.patch(
            'imbi_common.graph.parse_agtype',
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
