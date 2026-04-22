"""Tests for authentication functionality."""

import datetime
import unittest
from unittest import mock

import fastapi.testclient
import jwt
from imbi_common import graph
from imbi_common.auth import core

from imbi_api import app, models, settings
from imbi_api.auth import password
from imbi_api.middleware import rate_limit


class PasswordHashingTestCase(unittest.TestCase):
    """Test password hashing and verification."""

    def test_hash_password(self) -> None:
        """Test password hashing."""
        plaintext = 'TestPassword123!'
        password_hash = password.hash_password(plaintext)

        self.assertIsInstance(password_hash, str)
        self.assertNotEqual(plaintext, password_hash)
        self.assertIn('$argon2', password_hash)

    def test_verify_password_success(self) -> None:
        """Test successful password verification."""
        plaintext = 'TestPassword123!'
        password_hash = password.hash_password(plaintext)

        self.assertTrue(
            password.verify_password(plaintext, password_hash),
        )

    def test_verify_password_failure(self) -> None:
        """Test failed password verification."""
        plaintext = 'TestPassword123!'
        password_hash = password.hash_password(plaintext)

        self.assertFalse(
            password.verify_password('WrongPassword', password_hash),
        )


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
        token = core.create_access_token(
            user_id, auth_settings=self.auth_settings
        )

        self.assertIsInstance(token, str)

        # Decode and verify token
        payload = jwt.decode(
            token,
            self.auth_settings.jwt_secret,
            algorithms=[self.auth_settings.jwt_algorithm],
        )
        self.assertEqual(payload['sub'], user_id)
        self.assertEqual(payload['type'], 'access')
        self.assertIn('jti', payload)
        self.assertIn('exp', payload)
        self.assertIn('iat', payload)

    def test_create_refresh_token(self) -> None:
        """Test refresh token creation."""
        user_id = 'testuser'
        token = core.create_refresh_token(
            user_id, auth_settings=self.auth_settings
        )

        self.assertIsInstance(token, str)

        # Decode and verify token
        payload = jwt.decode(
            token,
            self.auth_settings.jwt_secret,
            algorithms=[self.auth_settings.jwt_algorithm],
        )
        self.assertEqual(payload['sub'], user_id)
        self.assertEqual(payload['type'], 'refresh')
        self.assertIn('jti', payload)

    def test_decode_token_success(self) -> None:
        """Test successful token decoding."""
        user_id = 'testuser'
        token = core.create_access_token(
            user_id, auth_settings=self.auth_settings
        )

        payload = jwt.decode(
            token,
            self.auth_settings.jwt_secret,
            algorithms=[self.auth_settings.jwt_algorithm],
        )
        self.assertEqual(payload['sub'], user_id)

    def test_decode_token_expired(self) -> None:
        """Test decoding expired token."""
        # Create settings with expired token
        expired_settings = settings.Auth(
            jwt_secret='test-secret-key-32-characters!',
            access_token_expire_seconds=-1,  # Already expired
        )

        user_id = 'testuser'
        token = core.create_access_token(
            user_id, auth_settings=expired_settings
        )

        with self.assertRaises(jwt.ExpiredSignatureError):
            jwt.decode(
                token,
                expired_settings.jwt_secret,
                algorithms=[expired_settings.jwt_algorithm],
            )

    def test_decode_token_invalid(self) -> None:
        """Test decoding invalid token."""
        with self.assertRaises(jwt.InvalidTokenError):
            jwt.decode(
                'invalid.token.here',
                self.auth_settings.jwt_secret,
                algorithms=[self.auth_settings.jwt_algorithm],
            )


class LoginEndpointTestCase(unittest.TestCase):
    """Test login endpoint."""

    def setUp(self) -> None:
        """Set up TestClient and test User."""
        self.application = app.create_app()
        self.client = fastapi.testclient.TestClient(self.application)
        self.mock_db = mock.AsyncMock()
        # Override graph dependency
        self.application.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )
        # Reset rate limiter to avoid 429 errors across tests
        rate_limit.limiter.reset()

        self.test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            password_hash=password.hash_password('TestPassword123!'),
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

    def tearDown(self) -> None:
        """Remove dependency overrides."""
        self.application.dependency_overrides.clear()

    def test_login_success(self) -> None:
        """Test successful login."""
        # match() returns the user
        self.mock_db.match.return_value = [self.test_user]
        # merge() for token metadata and last_login update
        self.mock_db.merge.return_value = None
        # execute() is called twice during login: MFA check (no MFA ->
        # []) and the atomic MATCH/CREATE inside issue_token_pair that
        # both persists token metadata and returns principal_count.
        self.mock_db.execute.side_effect = [
            [],
            [{'principal_count': 1}],
        ]

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

        # Verify graph calls
        self.mock_db.match.assert_called()
        self.mock_db.merge.assert_called()

    def test_login_invalid_email(self) -> None:
        """Test login with invalid email."""
        self.mock_db.match.return_value = []

        response = self.client.post(
            '/auth/login',
            json={
                'email': 'invalid@example.com',
                'password': 'password',
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn('detail', response.json())

    def test_login_invalid_password(self) -> None:
        """Test login with invalid password."""
        self.mock_db.match.return_value = [self.test_user]

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
            password_hash=password.hash_password('password'),
            is_active=False,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.mock_db.match.return_value = [inactive_user]

        response = self.client.post(
            '/auth/login',
            json={
                'email': 'inactive@example.com',
                'password': 'password',
            },
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

        self.mock_db.match.return_value = [oauth_user]

        response = self.client.post(
            '/auth/login',
            json={
                'email': 'oauth@example.com',
                'password': 'anypassword',
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn('not available', response.json()['detail'])


class TokenRefreshEndpointTestCase(unittest.TestCase):
    """Test token refresh endpoint."""

    def setUp(self) -> None:
        """Prepare test fixtures."""
        self.application = app.create_app()
        self.client = fastapi.testclient.TestClient(self.application)
        self.mock_db = mock.AsyncMock()
        self.application.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )
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

    def tearDown(self) -> None:
        """Remove dependency overrides."""
        self.application.dependency_overrides.clear()

    def test_token_refresh_success(self) -> None:
        """Test successful token refresh."""
        # Create a valid refresh token
        refresh_token = core.create_refresh_token(
            self.test_user.email, auth_settings=self.auth_settings
        )
        payload = jwt.decode(
            refresh_token,
            self.auth_settings.jwt_secret,
            algorithms=[self.auth_settings.jwt_algorithm],
        )
        refresh_jti = payload['jti']

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

        # match() returns token metadata first, then user
        self.mock_db.match.side_effect = [
            [token_metadata],
            [self.test_user],
        ]
        # merge() for revoking old token
        self.mock_db.merge.return_value = None
        # execute() runs the atomic MATCH/CREATE inside
        # issue_token_pair that persists token metadata and returns
        # principal_count.
        self.mock_db.execute.return_value = [
            {'principal_count': 1},
        ]

        with mock.patch(
            'imbi_api.settings.get_auth_settings'
        ) as mock_settings:
            mock_settings.return_value = self.auth_settings

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
        refresh_token = core.create_refresh_token(
            self.test_user.email, auth_settings=expired_settings
        )

        with mock.patch(
            'imbi_api.settings.get_auth_settings'
        ) as mock_settings:
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
        """Test refresh with access token instead of refresh."""
        # Use access token instead of refresh token
        access_token = core.create_access_token(
            self.test_user.email, auth_settings=self.auth_settings
        )

        with mock.patch(
            'imbi_api.settings.get_auth_settings'
        ) as mock_settings:
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': access_token},
            )

        self.assertEqual(response.status_code, 401)
        self.assertIn('type', response.json()['detail'].lower())

    def test_token_refresh_revoked(self) -> None:
        """Test refresh with revoked token."""
        refresh_token = core.create_refresh_token(
            self.test_user.email, auth_settings=self.auth_settings
        )
        payload = jwt.decode(
            refresh_token,
            self.auth_settings.jwt_secret,
            algorithms=[self.auth_settings.jwt_algorithm],
        )
        refresh_jti = payload['jti']

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

        self.mock_db.match.return_value = [revoked_token]

        with mock.patch(
            'imbi_api.settings.get_auth_settings'
        ) as mock_settings:
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': refresh_token},
            )

        self.assertEqual(response.status_code, 401)
        self.assertIn('revoked', response.json()['detail'].lower())


class LogoutEndpointTestCase(unittest.TestCase):
    """Test logout endpoint."""

    def setUp(self) -> None:
        self.application = app.create_app()
        self.client = fastapi.testclient.TestClient(self.application)
        self.mock_db = mock.AsyncMock()
        self.application.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )
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

    def tearDown(self) -> None:
        """Remove dependency overrides."""
        self.application.dependency_overrides.clear()

    def test_logout(self) -> None:
        """Test logout endpoint revokes tokens."""
        # Create access token
        access_token = core.create_access_token(
            self.test_user.email,
            auth_settings=self.auth_settings,
        )

        def execute_side_effect(query, params=None, columns=None):
            # Check if token is revoked (authenticate_jwt)
            if 'TokenMetadata' in query and 'revoked' in query:
                return [{'revoked': False}]
            # Load permissions (must check before User since
            # the permissions query also contains 'User')
            elif 'MEMBER_OF' in query:
                return [{'permissions': []}]
            # Logout operations (revoke token, delete sessions)
            return []

        self.mock_db.execute = mock.AsyncMock(side_effect=execute_side_effect)
        # authenticate_jwt uses db.match() for user lookup
        self.mock_db.match.return_value = [self.test_user]

        with (
            mock.patch('imbi_api.settings.get_auth_settings') as mock_settings,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_settings.return_value = self.auth_settings

            response = self.client.post(
                '/auth/logout',
                headers={'Authorization': f'Bearer {access_token}'},
            )

        self.assertEqual(response.status_code, 204)
