"""Tests for JWT authentication and permission loading.

These cover :mod:`imbi.common.auth.permissions`, shared by imbi-api,
imbi-assistant, and imbi-scheduler. The resource-level (``CAN_ACCESS``)
cases that only apply to imbi-api's domain entities stay in
``apps/api/tests/auth/test_authorization.py``.
"""

import datetime
import unittest
from unittest import mock

import fastapi

from imbi.common import models, settings
from imbi.common.auth import core, password, permissions


class PermissionLoadingTestCase(unittest.IsolatedAsyncioTestCase):
    """Test permission loading from org membership roles."""

    async def test_load_user_permissions_direct_role(self) -> None:
        """Test loading permissions from direct role assignment."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {'permissions': ['blueprint:read', 'blueprint:write']}
        ]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            perms = await permissions.load_principal_permissions(
                mock_db, 'User', 'email', 'testuser'
            )

        self.assertEqual(perms, {'blueprint:read', 'blueprint:write'})

    async def test_load_user_permissions_empty(self) -> None:
        """Test loading permissions for user with no roles."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []

        perms = await permissions.load_principal_permissions(
            mock_db, 'User', 'email', 'testuser'
        )

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
            if 'MEMBER_OF' in query or 'GRANTS' in query:
                return [{'permissions': ['blueprint:read']}]
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)
        # authenticate_jwt uses db.match() for user lookup
        mock_db.match.return_value = [self.test_user]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
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
                'imbi.common.graph.parse_agtype',
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
                'imbi.common.graph.parse_agtype',
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
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            self.assertRaises(fastapi.HTTPException) as ctx,
        ):
            await permissions.authenticate_jwt(
                mock_db, token, self.auth_settings
            )

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn('not found', str(ctx.exception.detail).lower())
