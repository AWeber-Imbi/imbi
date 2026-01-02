"""Tests for API key authentication in permissions module."""

import datetime
import unittest
from unittest import mock

import fastapi
from fastapi import security

from imbi import models, settings
from imbi.auth import core, permissions


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
            'key_hash': core.hash_password(self.key_secret),
            'scopes': [],
            'revoked': False,
            'expires_at': None,
        }

    async def test_authenticate_api_key_success(self) -> None:
        """Test successful API key authentication."""

        def mock_run(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()

            # API key fetch query
            if 'APIKey' in query and 'OWNED_BY' in query:
                user_dict = self.test_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'k': self.api_key_data, 'u': user_dict}]
                )
            # Update last_used query
            elif 'last_used' in query:
                mock_result.data = mock.AsyncMock(return_value=[])
            # Load permissions query
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[
                        {'permissions': ['read:projects', 'write:projects']}
                    ]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with mock.patch('imbi.neo4j.run', side_effect=mock_run):
            auth_context = await permissions.authenticate_api_key(
                self.full_key, self.auth_settings
            )

            self.assertEqual(auth_context.user.email, 'test@example.com')
            self.assertEqual(auth_context.session_id, self.key_id)
            self.assertEqual(auth_context.auth_method, 'api_key')
            self.assertIn('read:projects', auth_context.permissions)
            self.assertIn('write:projects', auth_context.permissions)

    async def test_authenticate_api_key_invalid_format(self) -> None:
        """Test authentication with invalid key format."""
        with self.assertRaises(fastapi.HTTPException) as cm:
            await permissions.authenticate_api_key(
                'invalid-key-format', self.auth_settings
            )

        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.detail, 'Invalid API key format')

    async def test_authenticate_api_key_not_found(self) -> None:
        """Test authentication with non-existent API key."""

        def mock_run(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.data = mock.AsyncMock(return_value=[])
            return mock_result

        with (
            mock.patch('imbi.neo4j.run', side_effect=mock_run),
            self.assertRaises(fastapi.HTTPException) as cm,
        ):
            await permissions.authenticate_api_key(
                self.full_key, self.auth_settings
            )

        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.detail, 'Invalid or revoked API key')

    async def test_authenticate_api_key_user_not_found(self) -> None:
        """Test authentication when API key user is missing."""

        def mock_run(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            if 'APIKey' in query and 'OWNED_BY' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'k': self.api_key_data, 'u': None}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.neo4j.run', side_effect=mock_run),
            self.assertRaises(fastapi.HTTPException) as cm,
        ):
            await permissions.authenticate_api_key(
                self.full_key, self.auth_settings
            )

        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.detail, 'API key user not found')

    async def test_authenticate_api_key_revoked(self) -> None:
        """Test authentication with revoked API key."""
        revoked_key_data = self.api_key_data.copy()
        revoked_key_data['revoked'] = True

        def mock_run(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            if 'APIKey' in query and 'OWNED_BY' in query:
                user_dict = self.test_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'k': revoked_key_data, 'u': user_dict}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.neo4j.run', side_effect=mock_run),
            self.assertRaises(fastapi.HTTPException) as cm,
        ):
            await permissions.authenticate_api_key(
                self.full_key, self.auth_settings
            )

        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.detail, 'Invalid or revoked API key')

    async def test_authenticate_api_key_expired(self) -> None:
        """Test authentication with expired API key."""
        expired_key_data = self.api_key_data.copy()
        expired_key_data['expires_at'] = datetime.datetime.now(
            datetime.UTC
        ) - datetime.timedelta(days=1)

        def mock_run(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            if 'APIKey' in query and 'OWNED_BY' in query:
                user_dict = self.test_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'k': expired_key_data, 'u': user_dict}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.neo4j.run', side_effect=mock_run),
            self.assertRaises(fastapi.HTTPException) as cm,
        ):
            await permissions.authenticate_api_key(
                self.full_key, self.auth_settings
            )

        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.detail, 'API key expired')

    async def test_authenticate_api_key_invalid_secret(self) -> None:
        """Test authentication with wrong API key secret."""
        wrong_key = f'{self.key_id}_wrongsecret'

        def mock_run(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            if 'APIKey' in query and 'OWNED_BY' in query:
                user_dict = self.test_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'k': self.api_key_data, 'u': user_dict}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.neo4j.run', side_effect=mock_run),
            self.assertRaises(fastapi.HTTPException) as cm,
        ):
            await permissions.authenticate_api_key(
                wrong_key, self.auth_settings
            )

        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.detail, 'Invalid or revoked API key')

    async def test_authenticate_api_key_user_inactive(self) -> None:
        """Test authentication with inactive user."""
        inactive_user = models.User(
            email='inactive@example.com',
            display_name='Inactive User',
            is_active=False,  # Inactive user
            created_at=datetime.datetime.now(datetime.UTC),
        )

        def mock_run(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            if 'APIKey' in query and 'OWNED_BY' in query:
                user_dict = inactive_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'k': self.api_key_data, 'u': user_dict}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.neo4j.run', side_effect=mock_run),
            self.assertRaises(fastapi.HTTPException) as cm,
        ):
            await permissions.authenticate_api_key(
                self.full_key, self.auth_settings
            )

        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.detail, 'User account is inactive')

    async def test_authenticate_api_key_with_scopes(self) -> None:
        """Test API key authentication with scoped permissions."""
        scoped_key_data = self.api_key_data.copy()
        scoped_key_data['scopes'] = ['read:projects']  # Limit to read only

        def mock_run(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()

            if 'APIKey' in query and 'OWNED_BY' in query:
                user_dict = self.test_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'k': scoped_key_data, 'u': user_dict}]
                )
            elif 'last_used' in query:
                mock_result.data = mock.AsyncMock(return_value=[])
            elif 'Permission' in query or 'GRANTS' in query:
                # User has both read and write permissions
                mock_result.data = mock.AsyncMock(
                    return_value=[
                        {'permissions': ['read:projects', 'write:projects']}
                    ]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with mock.patch('imbi.neo4j.run', side_effect=mock_run):
            auth_context = await permissions.authenticate_api_key(
                self.full_key, self.auth_settings
            )

            # Should only have read permission (filtered by scope)
            self.assertIn('read:projects', auth_context.permissions)
            self.assertNotIn('write:projects', auth_context.permissions)

    async def test_authenticate_api_key_neo4j_datetime_expiration(
        self,
    ) -> None:
        """Test API key expiration with Neo4j DateTime object."""

        # Create Neo4j DateTime-like object with to_native() method
        class MockNeo4jDateTime:
            def to_native(self):
                return datetime.datetime.now(
                    datetime.UTC
                ) - datetime.timedelta(days=1)

        expired_key_data = self.api_key_data.copy()
        expired_key_data['expires_at'] = MockNeo4jDateTime()

        def mock_run(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            if 'APIKey' in query and 'OWNED_BY' in query:
                user_dict = self.test_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'k': expired_key_data, 'u': user_dict}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.neo4j.run', side_effect=mock_run),
            self.assertRaises(fastapi.HTTPException) as cm,
        ):
            await permissions.authenticate_api_key(
                self.full_key, self.auth_settings
            )

        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.detail, 'API key expired')

    async def test_authenticate_api_key_neo4j_datetime_not_expired(
        self,
    ) -> None:
        """Test API key with Neo4j DateTime that is NOT expired."""

        # Create Neo4j DateTime-like object with future expiration
        class MockNeo4jDateTime:
            def to_native(self):
                return datetime.datetime.now(
                    datetime.UTC
                ) + datetime.timedelta(days=30)

        valid_key_data = self.api_key_data.copy()
        valid_key_data['expires_at'] = MockNeo4jDateTime()

        def mock_run(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()

            if 'APIKey' in query and 'OWNED_BY' in query:
                user_dict = self.test_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'k': valid_key_data, 'u': user_dict}]
                )
            elif 'last_used' in query:
                mock_result.data = mock.AsyncMock(return_value=[])
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': ['read:projects']}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with mock.patch('imbi.neo4j.run', side_effect=mock_run):
            auth_context = await permissions.authenticate_api_key(
                self.full_key, self.auth_settings
            )

            # Should succeed - key not expired
            self.assertEqual(auth_context.user.email, 'test@example.com')
            self.assertEqual(auth_context.session_id, self.key_id)


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

        def mock_run(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()

            if 'APIKey' in query and 'OWNED_BY' in query:
                api_key_data = {
                    'key_id': self.key_id,
                    'key_hash': core.hash_password(self.key_secret),
                    'scopes': [],
                    'revoked': False,
                    'expires_at': None,
                }
                user_dict = self.test_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'k': api_key_data, 'u': user_dict}]
                )
            elif 'last_used' in query:
                mock_result.data = mock.AsyncMock(return_value=[])
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': ['read:projects']}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch('imbi.neo4j.run', side_effect=mock_run),
        ):
            mock_settings.return_value = self.auth_settings

            # Create credentials with API key format
            credentials = security.HTTPAuthorizationCredentials(
                scheme='Bearer', credentials=self.full_key
            )

            auth_context = await permissions.get_current_user(credentials)

            self.assertEqual(auth_context.user.email, 'test@example.com')
            self.assertEqual(auth_context.session_id, self.key_id)
            self.assertEqual(auth_context.auth_method, 'api_key')
