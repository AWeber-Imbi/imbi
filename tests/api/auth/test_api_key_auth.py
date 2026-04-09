"""Tests for API key authentication in permissions module."""

import datetime
import typing
import unittest
from unittest import mock

import fastapi
from fastapi import security

from imbi_api import models, settings
from imbi_api.auth import password, permissions


class AuthenticateAPIKeyTestCase(unittest.IsolatedAsyncioTestCase):
    """Test authenticate_api_key function."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        # Create test user
        self.test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        # Create test API key
        self.key_id = 'ik_test123'
        self.key_secret = 'secret456'
        self.full_key = f'{self.key_id}_{self.key_secret}'

        self.api_key_data = {
            'key_id': self.key_id,
            'key_hash': password.hash_password(self.key_secret),
            'scopes': [],
            'revoked': False,
            'expires_at': None,
        }

    async def test_authenticate_api_key_success(self) -> None:
        """Test successful API key authentication."""
        mock_db = mock.AsyncMock()
        user_dict = self.test_user.model_dump(mode='json')

        def execute_side_effect(query, params=None, columns=None):
            if 'APIKey' in query and 'OWNED_BY' in query:
                return [
                    {
                        'k': self.api_key_data,
                        'u': user_dict,
                        's': None,
                    }
                ]
            elif 'last_used' in query:
                return []
            elif (
                'Permission' in query
                or 'GRANTS' in query
                or 'MEMBER_OF' in query
            ):
                return [
                    {
                        'permissions': [
                            'read:projects',
                            'write:projects',
                        ]
                    }
                ]
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            auth_context = await permissions.authenticate_api_key(
                mock_db, self.full_key, self.auth_settings
            )

        self.assertEqual(auth_context.user.email, 'test@example.com')
        self.assertEqual(auth_context.session_id, self.key_id)
        self.assertEqual(auth_context.auth_method, 'api_key')
        self.assertIn('read:projects', auth_context.permissions)
        self.assertIn('write:projects', auth_context.permissions)

    async def test_authenticate_api_key_invalid_format(
        self,
    ) -> None:
        """Test authentication with invalid key format."""
        mock_db = mock.AsyncMock()

        with self.assertRaises(fastapi.HTTPException) as cm:
            await permissions.authenticate_api_key(
                mock_db, 'invalid-key-format', self.auth_settings
            )

        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.detail, 'Invalid API key format')

    async def test_authenticate_api_key_not_found(self) -> None:
        """Test authentication with non-existent API key."""
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []

        with self.assertRaises(fastapi.HTTPException) as cm:
            await permissions.authenticate_api_key(
                mock_db, self.full_key, self.auth_settings
            )

        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.detail, 'Invalid or revoked API key')

    async def test_authenticate_api_key_user_not_found(
        self,
    ) -> None:
        """Test authentication when API key user is missing."""
        mock_db = mock.AsyncMock()

        def execute_side_effect(query, params=None, columns=None):
            if 'APIKey' in query and 'OWNED_BY' in query:
                return [
                    {
                        'k': self.api_key_data,
                        'u': None,
                        's': None,
                    }
                ]
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            self.assertRaises(fastapi.HTTPException) as cm,
        ):
            await permissions.authenticate_api_key(
                mock_db, self.full_key, self.auth_settings
            )

        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.detail, 'API key owner not found')

    async def test_authenticate_api_key_revoked(self) -> None:
        """Test authentication with revoked API key."""
        revoked_key_data = self.api_key_data.copy()
        revoked_key_data['revoked'] = True

        mock_db = mock.AsyncMock()
        user_dict = self.test_user.model_dump(mode='json')

        def execute_side_effect(query, params=None, columns=None):
            if 'APIKey' in query and 'OWNED_BY' in query:
                return [
                    {
                        'k': revoked_key_data,
                        'u': user_dict,
                        's': None,
                    }
                ]
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            self.assertRaises(fastapi.HTTPException) as cm,
        ):
            await permissions.authenticate_api_key(
                mock_db, self.full_key, self.auth_settings
            )

        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.detail, 'Invalid or revoked API key')

    async def test_authenticate_api_key_expired(self) -> None:
        """Test authentication with expired API key."""
        expired_key_data: dict[str, typing.Any] = self.api_key_data.copy()
        expired_key_data['expires_at'] = datetime.datetime.now(
            datetime.UTC
        ) - datetime.timedelta(days=1)

        mock_db = mock.AsyncMock()
        user_dict = self.test_user.model_dump(mode='json')

        def execute_side_effect(query, params=None, columns=None):
            if 'APIKey' in query and 'OWNED_BY' in query:
                return [
                    {
                        'k': expired_key_data,
                        'u': user_dict,
                        's': None,
                    }
                ]
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            self.assertRaises(fastapi.HTTPException) as cm,
        ):
            await permissions.authenticate_api_key(
                mock_db, self.full_key, self.auth_settings
            )

        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.detail, 'API key expired')

    async def test_authenticate_api_key_invalid_secret(
        self,
    ) -> None:
        """Test authentication with wrong API key secret."""
        wrong_key = f'{self.key_id}_wrongsecret'

        mock_db = mock.AsyncMock()
        user_dict = self.test_user.model_dump(mode='json')

        def execute_side_effect(query, params=None, columns=None):
            if 'APIKey' in query and 'OWNED_BY' in query:
                return [
                    {
                        'k': self.api_key_data,
                        'u': user_dict,
                        's': None,
                    }
                ]
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            self.assertRaises(fastapi.HTTPException) as cm,
        ):
            await permissions.authenticate_api_key(
                mock_db, wrong_key, self.auth_settings
            )

        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.detail, 'Invalid or revoked API key')

    async def test_authenticate_api_key_user_inactive(
        self,
    ) -> None:
        """Test authentication with inactive user."""
        inactive_user = models.User(
            email='inactive@example.com',
            display_name='Inactive User',
            is_active=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        mock_db = mock.AsyncMock()
        user_dict = inactive_user.model_dump(mode='json')

        def execute_side_effect(query, params=None, columns=None):
            if 'APIKey' in query and 'OWNED_BY' in query:
                return [
                    {
                        'k': self.api_key_data,
                        'u': user_dict,
                        's': None,
                    }
                ]
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            self.assertRaises(fastapi.HTTPException) as cm,
        ):
            await permissions.authenticate_api_key(
                mock_db, self.full_key, self.auth_settings
            )

        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.detail, 'User account is inactive')

    async def test_authenticate_api_key_with_scopes(self) -> None:
        """Test API key authentication with scoped permissions."""
        scoped_key_data = self.api_key_data.copy()
        scoped_key_data['scopes'] = ['read:projects']

        mock_db = mock.AsyncMock()
        user_dict = self.test_user.model_dump(mode='json')

        def execute_side_effect(query, params=None, columns=None):
            if 'APIKey' in query and 'OWNED_BY' in query:
                return [
                    {
                        'k': scoped_key_data,
                        'u': user_dict,
                        's': None,
                    }
                ]
            elif 'last_used' in query:
                return []
            elif (
                'Permission' in query
                or 'GRANTS' in query
                or 'MEMBER_OF' in query
            ):
                return [
                    {
                        'permissions': [
                            'read:projects',
                            'write:projects',
                        ]
                    }
                ]
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            auth_context = await permissions.authenticate_api_key(
                mock_db, self.full_key, self.auth_settings
            )

        # Should only have read permission (filtered by scope)
        self.assertIn('read:projects', auth_context.permissions)
        self.assertNotIn('write:projects', auth_context.permissions)


class GetCurrentUserTestCase(unittest.IsolatedAsyncioTestCase):
    """Test get_current_user function with API key."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        self.test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.key_id = 'ik_test123'
        self.key_secret = 'secret456'
        self.full_key = f'{self.key_id}_{self.key_secret}'

    async def test_get_current_user_with_api_key(self) -> None:
        """Test get_current_user detects and authenticates API key."""
        mock_db = mock.AsyncMock()
        user_dict = self.test_user.model_dump(mode='json')

        def execute_side_effect(query, params=None, columns=None):
            if 'APIKey' in query and 'OWNED_BY' in query:
                api_key_data = {
                    'key_id': self.key_id,
                    'key_hash': password.hash_password(self.key_secret),
                    'scopes': [],
                    'revoked': False,
                    'expires_at': None,
                }
                return [
                    {
                        'k': api_key_data,
                        'u': user_dict,
                        's': None,
                    }
                ]
            elif 'last_used' in query:
                return []
            elif (
                'Permission' in query
                or 'GRANTS' in query
                or 'MEMBER_OF' in query
            ):
                return [{'permissions': ['read:projects']}]
            return []

        mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)

        with (
            mock.patch('imbi_api.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            credentials = security.HTTPAuthorizationCredentials(
                scheme='Bearer', credentials=self.full_key
            )

            auth_context = await permissions.get_current_user(
                mock_db, credentials
            )

        self.assertEqual(auth_context.user.email, 'test@example.com')
        self.assertEqual(auth_context.session_id, self.key_id)
        self.assertEqual(auth_context.auth_method, 'api_key')
