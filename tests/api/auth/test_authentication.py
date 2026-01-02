"""Tests for authentication functionality."""

import datetime
import unittest
from unittest import mock

import jwt
from fastapi import testclient

from imbi import app, models, settings
from imbi.auth import core
from imbi.middleware import rate_limit


class PasswordHashingTestCase(unittest.TestCase):
    """Test password hashing and verification."""

    def test_hash_password(self) -> None:
        """Test password hashing."""
        password = 'TestPassword123!'
        password_hash = core.hash_password(password)

        self.assertIsInstance(password_hash, str)
        self.assertNotEqual(password, password_hash)
        self.assertIn('$argon2', password_hash)

    def test_verify_password_success(self) -> None:
        """Test successful password verification."""
        password = 'TestPassword123!'
        password_hash = core.hash_password(password)

        self.assertTrue(core.verify_password(password, password_hash))

    def test_verify_password_failure(self) -> None:
        """Test failed password verification."""
        password = 'TestPassword123!'
        password_hash = core.hash_password(password)

        self.assertFalse(core.verify_password('WrongPassword', password_hash))


class JWTTokenTestCase(unittest.TestCase):
    """Test JWT token creation and validation."""

    def setUp(self) -> None:
        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-32-characters!',
            jwt_algorithm='HS256',
            access_token_expire_seconds=3600,
            refresh_token_expire_seconds=86400,
        )

    def test_create_access_token(self) -> None:
        """Test access token creation."""
        user_id = 'testuser'
        token, jti = core.create_access_token(user_id, self.auth_settings)

        self.assertIsInstance(token, str)
        self.assertIsInstance(jti, str)

        # Decode and verify token
        payload = core.decode_token(token, self.auth_settings)
        self.assertEqual(payload['sub'], user_id)
        self.assertEqual(payload['type'], 'access')
        self.assertEqual(payload['jti'], jti)
        self.assertIn('exp', payload)
        self.assertIn('iat', payload)

    def test_create_refresh_token(self) -> None:
        """Test refresh token creation."""
        user_id = 'testuser'
        token, jti = core.create_refresh_token(user_id, self.auth_settings)

        self.assertIsInstance(token, str)
        self.assertIsInstance(jti, str)

        # Decode and verify token
        payload = core.decode_token(token, self.auth_settings)
        self.assertEqual(payload['sub'], user_id)
        self.assertEqual(payload['type'], 'refresh')
        self.assertEqual(payload['jti'], jti)

    def test_decode_token_success(self) -> None:
        """Test successful token decoding."""
        user_id = 'testuser'
        token, _ = core.create_access_token(user_id, self.auth_settings)

        payload = core.decode_token(token, self.auth_settings)
        self.assertEqual(payload['sub'], user_id)

    def test_decode_token_expired(self) -> None:
        """Test decoding expired token."""
        # Create settings with expired token
        expired_settings = settings.Auth(
            jwt_secret='test-secret-key-32-characters!',
            access_token_expire_seconds=-1,  # Already expired
        )

        user_id = 'testuser'
        token, _ = core.create_access_token(user_id, expired_settings)

        with self.assertRaises(jwt.ExpiredSignatureError):
            core.decode_token(token, expired_settings)

    def test_decode_token_invalid(self) -> None:
        """Test decoding invalid token."""
        with self.assertRaises(jwt.InvalidTokenError):
            core.decode_token('invalid.token.here', self.auth_settings)


class LoginEndpointTestCase(unittest.TestCase):
    """Test login endpoint."""

    def setUp(self) -> None:
        """
        Set up a TestClient and a default active test User instance
        used by tests.

        Initializes self.client as a TestClient for the application
        and self.test_user as an active, non-admin, non-service-account
        User whose password_hash is populated with a hashed password
        and whose created_at is the current time.
        """
        self.client = testclient.TestClient(app.create_app())
        # Reset rate limiter to avoid 429 errors across tests
        rate_limit.limiter.reset()

        self.test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            password_hash=core.hash_password('TestPassword123!'),
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

    def test_login_success(self) -> None:
        """Test successful login."""
        # Mock neo4j.run for MFA query (returns empty result = no MFA)
        mock_result = mock.AsyncMock()
        mock_result.data = mock.AsyncMock(return_value=[])
        mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
        mock_result.__aexit__ = mock.AsyncMock(return_value=None)

        with (
            mock.patch('imbi.neo4j.fetch_node') as mock_fetch,
            mock.patch('imbi.neo4j.create_node'),
            mock.patch('imbi.neo4j.upsert') as mock_upsert,
            mock.patch('imbi.neo4j.run', return_value=mock_result),
        ):
            mock_fetch.return_value = self.test_user

            response = self.client.post(
                '/auth/login',
                json={
                    'email': 'test@example.com',
                    'password': 'TestPassword123!',
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn('access_token', data)
            self.assertIn('refresh_token', data)
            self.assertEqual(data['token_type'], 'bearer')
            self.assertIn('expires_in', data)

            # Verify Neo4j calls
            mock_fetch.assert_called()
            mock_upsert.assert_called()  # Update last_login

    def test_login_invalid_email(self) -> None:
        """Test login with invalid email."""
        with mock.patch('imbi.neo4j.fetch_node') as mock_fetch:
            mock_fetch.return_value = None

            response = self.client.post(
                '/auth/login',
                json={'email': 'invalid@example.com', 'password': 'password'},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn('detail', response.json())

    def test_login_invalid_password(self) -> None:
        """Test login with invalid password."""
        with mock.patch('imbi.neo4j.fetch_node') as mock_fetch:
            mock_fetch.return_value = self.test_user

            response = self.client.post(
                '/auth/login',
                json={
                    'email': 'test@example.com',
                    'password': 'WrongPassword!',
                },
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn('detail', response.json())

    def test_login_inactive_user(self) -> None:
        """Test login with inactive user."""
        inactive_user = models.User(
            email='inactive@example.com',
            display_name='Inactive User',
            password_hash=core.hash_password('password'),
            is_active=False,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        with mock.patch('imbi.neo4j.fetch_node') as mock_fetch:
            mock_fetch.return_value = inactive_user

            response = self.client.post(
                '/auth/login',
                json={'email': 'inactive@example.com', 'password': 'password'},
            )

            self.assertEqual(response.status_code, 401)

    def test_login_no_password_hash(self) -> None:
        """Test login for user without password authentication."""
        oauth_user = models.User(
            email='oauth@example.com',
            display_name='OAuth User',
            password_hash=None,  # OAuth-only user
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        with mock.patch('imbi.neo4j.fetch_node') as mock_fetch:
            mock_fetch.return_value = oauth_user

            response = self.client.post(
                '/auth/login',
                json={'email': 'oauth@example.com', 'password': 'anypassword'},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn('not available', response.json()['detail'])


class TokenRefreshEndpointTestCase(unittest.TestCase):
    """Test token refresh endpoint."""

    def setUp(self) -> None:
        """
        Prepare test fixtures for authentication endpoint tests.

        Creates a FastAPI test client and default authentication
        settings, and constructs a default active, non-admin test user
        assigned to `self.test_user`. The test user has a username,
        email, display name, active status, service-account flag, admin
        flag, and creation timestamp.
        """
        self.client = testclient.TestClient(app.create_app())
        # Reset rate limiter to avoid 429 errors across tests
        rate_limit.limiter.reset()

        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-32-characters!'
        )
        self.test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

    def test_token_refresh_success(self) -> None:
        """Test successful token refresh."""
        # Create a valid refresh token
        refresh_token, refresh_jti = core.create_refresh_token(
            self.test_user.email, self.auth_settings
        )

        # Create non-revoked token metadata
        token_metadata = models.TokenMetadata(
            jti=refresh_jti,
            token_type='refresh',
            issued_at=datetime.datetime.now(datetime.UTC),
            expires_at=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(days=30),
            revoked=False,
            user=self.test_user,
        )

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch('imbi.neo4j.fetch_node') as mock_fetch,
            mock.patch('imbi.neo4j.create_node'),
            mock.patch('imbi.neo4j.upsert'),
        ):
            # Mock settings to use our test JWT secret
            mock_settings.return_value = self.auth_settings

            # First call returns token metadata (not revoked)
            # Second call returns user
            mock_fetch.side_effect = [token_metadata, self.test_user]

            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': refresh_token},
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn('access_token', data)
            self.assertIn('refresh_token', data)
            # Token rotation: new refresh token should be different
            self.assertNotEqual(data['refresh_token'], refresh_token)

    def test_token_refresh_expired(self) -> None:
        """Test refresh with expired token."""
        # Create expired refresh token
        expired_settings = settings.Auth(
            jwt_secret='test-secret-key-32-characters!',
            refresh_token_expire_seconds=-1,
        )
        refresh_token, _ = core.create_refresh_token(
            self.test_user.email, expired_settings
        )

        with mock.patch('imbi.settings.get_auth_settings') as mock_settings:
            # Mock settings to use our test JWT secret
            mock_settings.return_value = expired_settings

            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': refresh_token},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn('expired', response.json()['detail'].lower())

    def test_token_refresh_invalid(self) -> None:
        """Test refresh with invalid token."""
        response = self.client.post(
            '/auth/token/refresh',
            json={'refresh_token': 'invalid.token.here'},
        )

        self.assertEqual(response.status_code, 401)

    def test_token_refresh_wrong_type(self) -> None:
        """Test refresh with access token instead of refresh token."""
        # Use access token instead of refresh token
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        with mock.patch('imbi.settings.get_auth_settings') as mock_settings:
            # Mock settings to use our test JWT secret
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': access_token},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn('type', response.json()['detail'].lower())

    def test_token_refresh_revoked(self) -> None:
        """Test refresh with revoked token."""
        refresh_token, refresh_jti = core.create_refresh_token(
            self.test_user.email, self.auth_settings
        )

        # Create revoked token metadata
        revoked_token = models.TokenMetadata(
            jti=refresh_jti,
            token_type='refresh',
            issued_at=datetime.datetime.now(datetime.UTC),
            expires_at=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(days=30),
            revoked=True,
            user=self.test_user,
        )

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch('imbi.neo4j.fetch_node') as mock_fetch,
        ):
            # Mock settings to use our test JWT secret
            mock_settings.return_value = self.auth_settings
            mock_fetch.return_value = revoked_token

            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': refresh_token},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn('revoked', response.json()['detail'].lower())


class LogoutEndpointTestCase(unittest.TestCase):
    """Test logout endpoint."""

    def setUp(self) -> None:
        self.client = testclient.TestClient(app.create_app())
        # Reset rate limiter to avoid 429 errors across tests
        rate_limit.limiter.reset()

        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-32-characters!'
        )
        self.test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

    def test_logout(self) -> None:
        """Test logout endpoint revokes tokens."""
        # Create access token
        access_token, _ = core.create_access_token(
            self.test_user.email, self.auth_settings
        )

        # Mock Neo4j run calls - different results for different queries
        def mock_run_side_effect(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.consume = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            # Check if token is revoked (authenticate_jwt)
            if 'TokenMetadata' in query and 'revoked' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'revoked': False}]
                )
            # Load user (authenticate_jwt)
            elif 'User' in query and 'email' in query:
                user_dict = self.test_user.model_dump(mode='json')
                mock_result.data = mock.AsyncMock(
                    return_value=[{'u': user_dict}]
                )
            # Load permissions (load_user_permissions)
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': []}]
                )
            # Logout operations (revoke token, delete sessions)
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.settings.get_auth_settings') as mock_settings,
            mock.patch('imbi.neo4j.run', side_effect=mock_run_side_effect),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/auth/logout',
                headers={'Authorization': f'Bearer {access_token}'},
            )

            self.assertEqual(response.status_code, 204)
