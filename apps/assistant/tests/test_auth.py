"""Tests for assistant auth module."""

import unittest
from unittest import mock

import fastapi

from imbi.assistant import auth


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

    def test_require_user_raises_without_user(
        self,
    ) -> None:
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
        db = mock.AsyncMock()
        db.execute.return_value = [
            {
                'permissions': [
                    'project:read',
                    'team:read',
                ]
            }
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            return_value=[
                'project:read',
                'team:read',
            ],
        ):
            perms = await auth.load_user_permissions(db, 'test@example.com')
        self.assertEqual(perms, {'project:read', 'team:read'})

    async def test_load_permissions_empty(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        perms = await auth.load_user_permissions(db, 'test@example.com')
        self.assertEqual(perms, set())


class GetCurrentUserTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for get_current_user."""

    async def test_missing_credentials(self) -> None:
        db = mock.AsyncMock()
        with self.assertRaises(
            fastapi.HTTPException,
        ) as ctx:
            await auth.get_current_user(db, None)
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_expired_token(self) -> None:
        import jwt

        db = mock.AsyncMock()
        creds = mock.MagicMock()
        creds.credentials = 'expired-token'
        with mock.patch(
            'imbi.common.auth.core.verify_token',
            side_effect=jwt.ExpiredSignatureError(),
        ):
            with self.assertRaises(
                fastapi.HTTPException,
            ) as ctx:
                await auth.get_current_user(db, creds)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn('expired', str(ctx.exception.detail))

    async def test_invalid_token(self) -> None:
        import jwt

        db = mock.AsyncMock()
        creds = mock.MagicMock()
        creds.credentials = 'bad-token'
        with mock.patch(
            'imbi.common.auth.core.verify_token',
            side_effect=jwt.InvalidTokenError(),
        ):
            with self.assertRaises(
                fastapi.HTTPException,
            ) as ctx:
                await auth.get_current_user(db, creds)
            self.assertEqual(ctx.exception.status_code, 401)

    async def test_invalid_token_type(self) -> None:
        db = mock.AsyncMock()
        creds = mock.MagicMock()
        creds.credentials = 'some-token'
        with mock.patch(
            'imbi.common.auth.core.verify_token',
            return_value={
                'type': 'refresh',
                'sub': 'x',
            },
        ):
            with self.assertRaises(
                fastapi.HTTPException,
            ) as ctx:
                await auth.get_current_user(db, creds)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn('token type', str(ctx.exception.detail))

    async def test_missing_subject(self) -> None:
        db = mock.AsyncMock()
        creds = mock.MagicMock()
        creds.credentials = 'some-token'
        with mock.patch(
            'imbi.common.auth.core.verify_token',
            return_value={'type': 'access'},
        ):
            with self.assertRaises(
                fastapi.HTTPException,
            ) as ctx:
                await auth.get_current_user(db, creds)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn('subject', str(ctx.exception.detail))

    async def test_user_not_found(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        creds = mock.MagicMock()
        creds.credentials = 'some-token'
        with mock.patch(
            'imbi.common.auth.core.verify_token',
            return_value={
                'type': 'access',
                'sub': 'nobody@example.com',
                'jti': 'j1',
            },
        ):
            with self.assertRaises(
                fastapi.HTTPException,
            ) as ctx:
                await auth.get_current_user(db, creds)
            self.assertEqual(ctx.exception.status_code, 401)

    async def test_inactive_user(self) -> None:
        db = mock.AsyncMock()
        creds = mock.MagicMock()
        creds.credentials = 'some-token'
        user_data = {
            'email': 'inactive@example.com',
            'display_name': 'Inactive',
            'is_active': False,
            'is_admin': False,
        }
        db.execute.return_value = [{'u': user_data}]
        with (
            mock.patch(
                'imbi.common.auth.core.verify_token',
                return_value={
                    'type': 'access',
                    'sub': 'inactive@example.com',
                    'jti': 'j1',
                },
            ),
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            with self.assertRaises(
                fastapi.HTTPException,
            ) as ctx:
                await auth.get_current_user(db, creds)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn('inactive', str(ctx.exception.detail))

    async def test_successful_auth(self) -> None:
        db = mock.AsyncMock()
        creds = mock.MagicMock()
        creds.credentials = 'good-token'

        user_data = {
            'email': 'test@example.com',
            'display_name': 'Test User',
            'is_active': True,
            'is_admin': False,
        }

        # First call: user lookup; second: permissions
        db.execute.side_effect = [
            [{'u': user_data}],
            [{'permissions': ['project:read']}],
        ]

        with (
            mock.patch(
                'imbi.common.auth.core.verify_token',
                return_value={
                    'type': 'access',
                    'sub': 'test@example.com',
                    'jti': 'j1',
                },
            ),
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=[
                    user_data,
                    ['project:read'],
                ],
            ),
        ):
            result = await auth.get_current_user(db, creds)
        self.assertIsInstance(result, auth.AuthContext)
        self.assertEqual(
            result.require_user.email,
            'test@example.com',
        )
        self.assertEqual(result.permissions, {'project:read'})
        self.assertEqual(result.session_id, 'j1')
