"""Tests for assistant auth module."""

import unittest
from unittest import mock

import fastapi

from imbi_assistant import auth


class UserModelTestCase(unittest.TestCase):
    """Test cases for User model."""

    def test_create_user(self) -> None:
        user = auth.User(
            email='test@example.com',
            display_name='Test User',
        )
        self.assertEqual(user.email, 'test@example.com')
        self.assertEqual(user.display_name, 'Test User')
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_admin)

    def test_create_admin_user(self) -> None:
        user = auth.User(
            email='admin@example.com',
            display_name='Admin',
            is_admin=True,
        )
        self.assertTrue(user.is_admin)


class AuthContextTestCase(unittest.TestCase):
    """Test cases for AuthContext."""

    def test_is_admin_with_admin_user(self) -> None:
        user = auth.User(
            email='admin@example.com',
            display_name='Admin',
            is_admin=True,
        )
        ctx = auth.AuthContext(user=user)
        self.assertTrue(ctx.is_admin)

    def test_is_admin_without_user(self) -> None:
        ctx = auth.AuthContext()
        self.assertFalse(ctx.is_admin)

    def test_require_user_returns_user(self) -> None:
        user = auth.User(
            email='test@example.com',
            display_name='Test',
        )
        ctx = auth.AuthContext(user=user)
        self.assertIs(ctx.require_user, user)

    def test_require_user_raises_without_user(self) -> None:
        ctx = auth.AuthContext()
        with self.assertRaises(fastapi.HTTPException) as exc:
            ctx.require_user
        self.assertEqual(exc.exception.status_code, 403)

    def test_permissions_default_empty(self) -> None:
        ctx = auth.AuthContext()
        self.assertEqual(ctx.permissions, set())


class LoadUserPermissionsTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for load_user_permissions."""

    async def test_load_permissions(self) -> None:
        ctx = mock.AsyncMock()
        ctx.__aenter__.return_value = ctx
        ctx.__aexit__.return_value = None
        ctx.data.return_value = [
            {
                'permissions': [
                    'project:read',
                    'team:read',
                ]
            }
        ]
        with mock.patch('imbi_common.age.run', return_value=ctx):
            perms = await auth.load_user_permissions('test@example.com')
        self.assertEqual(perms, {'project:read', 'team:read'})

    async def test_load_permissions_empty(self) -> None:
        ctx = mock.AsyncMock()
        ctx.__aenter__.return_value = ctx
        ctx.__aexit__.return_value = None
        ctx.data.return_value = []
        with mock.patch('imbi_common.age.run', return_value=ctx):
            perms = await auth.load_user_permissions('test@example.com')
        self.assertEqual(perms, set())


class GetCurrentUserTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for get_current_user."""

    async def test_missing_credentials(self) -> None:
        with self.assertRaises(fastapi.HTTPException) as ctx:
            await auth.get_current_user(None)
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_expired_token(self) -> None:
        import jwt

        creds = mock.MagicMock()
        creds.credentials = 'expired-token'
        with mock.patch(
            'imbi_common.auth.core.verify_token',
            side_effect=jwt.ExpiredSignatureError(),
        ):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                await auth.get_current_user(creds)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn('expired', str(ctx.exception.detail))

    async def test_invalid_token(self) -> None:
        import jwt

        creds = mock.MagicMock()
        creds.credentials = 'bad-token'
        with mock.patch(
            'imbi_common.auth.core.verify_token',
            side_effect=jwt.InvalidTokenError(),
        ):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                await auth.get_current_user(creds)
            self.assertEqual(ctx.exception.status_code, 401)

    async def test_invalid_token_type(self) -> None:
        creds = mock.MagicMock()
        creds.credentials = 'some-token'
        with mock.patch(
            'imbi_common.auth.core.verify_token',
            return_value={'type': 'refresh', 'sub': 'x'},
        ):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                await auth.get_current_user(creds)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn('token type', str(ctx.exception.detail))

    async def test_missing_subject(self) -> None:
        creds = mock.MagicMock()
        creds.credentials = 'some-token'
        with mock.patch(
            'imbi_common.auth.core.verify_token',
            return_value={'type': 'access'},
        ):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                await auth.get_current_user(creds)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn('subject', str(ctx.exception.detail))

    async def test_user_not_found(self) -> None:
        creds = mock.MagicMock()
        creds.credentials = 'some-token'
        age_ctx = mock.AsyncMock()
        age_ctx.__aenter__.return_value = age_ctx
        age_ctx.__aexit__.return_value = None
        age_ctx.data.return_value = []
        with (
            mock.patch(
                'imbi_common.auth.core.verify_token',
                return_value={
                    'type': 'access',
                    'sub': 'nobody@example.com',
                    'jti': 'j1',
                },
            ),
            mock.patch(
                'imbi_common.age.run',
                return_value=age_ctx,
            ),
        ):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                await auth.get_current_user(creds)
            self.assertEqual(ctx.exception.status_code, 401)

    async def test_inactive_user(self) -> None:
        creds = mock.MagicMock()
        creds.credentials = 'some-token'
        age_ctx = mock.AsyncMock()
        age_ctx.__aenter__.return_value = age_ctx
        age_ctx.__aexit__.return_value = None
        age_ctx.data.return_value = [
            {
                'u': {
                    'email': 'inactive@example.com',
                    'display_name': 'Inactive',
                    'is_active': False,
                    'is_admin': False,
                }
            }
        ]
        with (
            mock.patch(
                'imbi_common.auth.core.verify_token',
                return_value={
                    'type': 'access',
                    'sub': 'inactive@example.com',
                    'jti': 'j1',
                },
            ),
            mock.patch(
                'imbi_common.age.run',
                return_value=age_ctx,
            ),
            mock.patch(
                'imbi_common.age.convert_neo4j_types',
                side_effect=lambda x: x,
            ),
        ):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                await auth.get_current_user(creds)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn('inactive', str(ctx.exception.detail))

    async def test_successful_auth(self) -> None:
        creds = mock.MagicMock()
        creds.credentials = 'good-token'

        age_ctx = mock.AsyncMock()
        age_ctx.__aenter__.return_value = age_ctx
        age_ctx.__aexit__.return_value = None
        age_ctx.data.return_value = [
            {
                'u': {
                    'email': 'test@example.com',
                    'display_name': 'Test User',
                    'is_active': True,
                    'is_admin': False,
                }
            }
        ]

        perms_ctx = mock.AsyncMock()
        perms_ctx.__aenter__.return_value = perms_ctx
        perms_ctx.__aexit__.return_value = None
        perms_ctx.data.return_value = [{'permissions': ['project:read']}]

        with (
            mock.patch(
                'imbi_common.auth.core.verify_token',
                return_value={
                    'type': 'access',
                    'sub': 'test@example.com',
                    'jti': 'j1',
                },
            ),
            mock.patch(
                'imbi_common.age.run',
                side_effect=[age_ctx, perms_ctx],
            ),
            mock.patch(
                'imbi_common.age.convert_neo4j_types',
                side_effect=lambda x: x,
            ),
        ):
            result = await auth.get_current_user(creds)
        self.assertIsInstance(result, auth.AuthContext)
        self.assertEqual(result.require_user.email, 'test@example.com')
        self.assertEqual(result.permissions, {'project:read'})
        self.assertEqual(result.session_id, 'j1')
