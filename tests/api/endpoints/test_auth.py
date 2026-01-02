import unittest
from unittest import mock

from fastapi import testclient

from imbi import app, settings
from imbi.auth import models as auth_models
from imbi.middleware import rate_limit


class AuthProvidersEndpointTestCase(unittest.TestCase):
    """Test cases for GET /auth/providers endpoint."""

    def setUp(self) -> None:
        """Set up test client and mock settings."""
        # Reset settings singleton
        settings._auth_settings = None
        self.client = testclient.TestClient(app.create_app())

    def tearDown(self) -> None:
        """Reset settings singleton after tests."""
        settings._auth_settings = None

    def test_get_providers_default_config(self) -> None:
        """Test /auth/providers with default config (local auth only)."""
        response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Validate response structure
        self.assertIn('providers', data)
        self.assertIn('default_redirect', data)
        self.assertEqual(data['default_redirect'], '/dashboard')

        # Only local auth should be enabled by default
        self.assertEqual(len(data['providers']), 1)
        local_provider = data['providers'][0]
        self.assertEqual(local_provider['id'], 'local')
        self.assertEqual(local_provider['type'], 'password')
        self.assertEqual(local_provider['name'], 'Email/Password')
        self.assertTrue(local_provider['enabled'])
        self.assertEqual(local_provider['icon'], 'lock')

    @mock.patch.dict('os.environ', {'IMBI_AUTH_OAUTH_GOOGLE_ENABLED': 'true'})
    def test_get_providers_google_enabled(self) -> None:
        """Test /auth/providers with Google OAuth enabled."""
        # Reset settings to pick up env vars
        settings._auth_settings = None

        response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Should have local and Google
        self.assertEqual(len(data['providers']), 2)

        # Find Google provider
        google_provider = next(
            (p for p in data['providers'] if p['id'] == 'google'), None
        )
        self.assertIsNotNone(google_provider)
        self.assertEqual(google_provider['type'], 'oauth')
        self.assertEqual(google_provider['name'], 'Google')
        self.assertTrue(google_provider['enabled'])
        self.assertEqual(google_provider['auth_url'], '/auth/oauth/google')
        self.assertEqual(google_provider['icon'], 'google')

    @mock.patch.dict('os.environ', {'IMBI_AUTH_OAUTH_GITHUB_ENABLED': 'true'})
    def test_get_providers_github_enabled(self) -> None:
        """Test /auth/providers with GitHub OAuth enabled."""
        # Reset settings to pick up env vars
        settings._auth_settings = None

        response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Should have local and GitHub
        self.assertEqual(len(data['providers']), 2)

        # Find GitHub provider
        github_provider = next(
            (p for p in data['providers'] if p['id'] == 'github'), None
        )
        self.assertIsNotNone(github_provider)
        self.assertEqual(github_provider['type'], 'oauth')
        self.assertEqual(github_provider['name'], 'GitHub')
        self.assertTrue(github_provider['enabled'])
        self.assertEqual(github_provider['auth_url'], '/auth/oauth/github')
        self.assertEqual(github_provider['icon'], 'github')

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_OAUTH_OIDC_ENABLED': 'true',
            'IMBI_AUTH_OAUTH_OIDC_NAME': 'Custom OIDC',
        },
    )
    def test_get_providers_oidc_enabled(self) -> None:
        """Test /auth/providers with OIDC enabled and custom name."""
        # Reset settings to pick up env vars
        settings._auth_settings = None

        response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Should have local and OIDC
        self.assertEqual(len(data['providers']), 2)

        # Find OIDC provider
        oidc_provider = next(
            (p for p in data['providers'] if p['id'] == 'oidc'), None
        )
        self.assertIsNotNone(oidc_provider)
        self.assertEqual(oidc_provider['type'], 'oauth')
        self.assertEqual(oidc_provider['name'], 'Custom OIDC')
        self.assertTrue(oidc_provider['enabled'])
        self.assertEqual(oidc_provider['auth_url'], '/auth/oauth/oidc')
        self.assertEqual(oidc_provider['icon'], 'key')

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_OAUTH_GOOGLE_ENABLED': 'true',
            'IMBI_AUTH_OAUTH_GITHUB_ENABLED': 'true',
            'IMBI_AUTH_OAUTH_OIDC_ENABLED': 'true',
        },
    )
    def test_get_providers_all_enabled(self) -> None:
        """Test /auth/providers with all OAuth providers enabled."""
        # Reset settings to pick up env vars
        settings._auth_settings = None

        response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Should have all 4 providers (local, Google, GitHub, OIDC)
        self.assertEqual(len(data['providers']), 4)

        provider_ids = {p['id'] for p in data['providers']}
        self.assertEqual(provider_ids, {'local', 'google', 'github', 'oidc'})

    @mock.patch.dict('os.environ', {'IMBI_AUTH_LOCAL_AUTH_ENABLED': 'false'})
    def test_get_providers_local_auth_disabled(self) -> None:
        """Test /auth/providers with local auth disabled."""
        # Reset settings to pick up env vars
        settings._auth_settings = None

        response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Should have no providers
        self.assertEqual(len(data['providers']), 0)

    def test_get_providers_response_model(self) -> None:
        """Test /auth/providers returns valid AuthProvidersResponse model."""
        response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)

        # Validate the response against the model
        providers_response = auth_models.AuthProvidersResponse(
            **response.json()
        )
        self.assertIsInstance(
            providers_response, auth_models.AuthProvidersResponse
        )
        self.assertIsInstance(providers_response.providers, list)
        for provider in providers_response.providers:
            self.assertIsInstance(provider, auth_models.AuthProvider)


class OAuthFlowTestCase(unittest.TestCase):
    """Test cases for OAuth login flow endpoints."""

    def setUp(self) -> None:
        """Set up test client."""
        settings._auth_settings = None
        self.client = testclient.TestClient(app.create_app())

    def tearDown(self) -> None:
        """Reset settings singleton after tests."""
        settings._auth_settings = None

    def test_oauth_login_invalid_provider(self) -> None:
        """Test OAuth login with invalid provider."""
        response = self.client.get('/auth/oauth/invalid')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Invalid provider', response.json()['detail'])

    def test_oauth_login_disabled_provider(self) -> None:
        """Test OAuth login with disabled provider."""
        response = self.client.get('/auth/oauth/google')
        self.assertEqual(response.status_code, 400)
        self.assertIn('not enabled', response.json()['detail'])

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_OAUTH_GOOGLE_ENABLED': 'true',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_ID': 'test-id',
        },
    )
    def test_oauth_login_google_redirect(self) -> None:
        """Test OAuth login redirects to Google."""
        settings._auth_settings = None
        response = self.client.get(
            '/auth/oauth/google', follow_redirects=False
        )
        self.assertEqual(response.status_code, 307)

        # Verify redirect URL contains Google OAuth endpoint
        location = response.headers['location']
        self.assertIn('accounts.google.com/o/oauth2/v2/auth', location)
        self.assertIn('client_id=test-id', location)
        self.assertIn('response_type=code', location)
        self.assertIn('state=', location)

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_OAUTH_GITHUB_ENABLED': 'true',
            'IMBI_AUTH_OAUTH_GITHUB_CLIENT_ID': 'github-id',
        },
    )
    def test_oauth_login_github_redirect(self) -> None:
        """Test OAuth login redirects to GitHub."""
        settings._auth_settings = None
        response = self.client.get(
            '/auth/oauth/github', follow_redirects=False
        )
        self.assertEqual(response.status_code, 307)

        # Verify redirect URL contains GitHub OAuth endpoint
        location = response.headers['location']
        self.assertIn('github.com/login/oauth/authorize', location)
        self.assertIn('client_id=github-id', location)

    def test_oauth_callback_error_handling(self) -> None:
        """Test OAuth callback handles provider errors."""
        url = (
            '/auth/oauth/google/callback'
            '?error=access_denied&error_description=User denied'
        )
        response = self.client.get(url, follow_redirects=False)
        self.assertEqual(response.status_code, 307)

        # Should redirect to error page
        location = response.headers['location']
        self.assertIn('error=access_denied', location)

    def test_oauth_callback_missing_code(self) -> None:
        """Test OAuth callback with missing code parameter."""
        url = '/auth/oauth/google/callback?state=test-state'
        response = self.client.get(url, follow_redirects=False)
        # Should redirect to error page
        self.assertEqual(response.status_code, 307)
        location = response.headers['location']
        self.assertIn('error=authentication_failed', location)

    def test_oauth_callback_missing_state(self) -> None:
        """Test OAuth callback with missing state parameter."""
        url = '/auth/oauth/google/callback?code=test-code'
        response = self.client.get(url, follow_redirects=False)
        # Should redirect to error page
        self.assertEqual(response.status_code, 307)
        location = response.headers['location']
        self.assertIn('error=authentication_failed', location)

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_OAUTH_OIDC_ENABLED': 'true',
            'IMBI_AUTH_OAUTH_OIDC_CLIENT_ID': 'oidc-id',
            'IMBI_AUTH_OAUTH_OIDC_ISSUER_URL': 'https://auth.example.com',
        },
    )
    def test_oauth_login_oidc_redirect(self) -> None:
        """Test OAuth login redirects to OIDC with proper URL."""
        settings._auth_settings = None
        response = self.client.get('/auth/oauth/oidc', follow_redirects=False)
        self.assertEqual(response.status_code, 307)

        # Verify redirect URL contains OIDC endpoint
        location = response.headers['location']
        self.assertIn(
            'auth.example.com/protocol/openid-connect/auth', location
        )
        self.assertIn('client_id=oidc-id', location)


class LoginPasswordRehashTestCase(unittest.TestCase):
    """Test password rehashing during login."""

    def setUp(self) -> None:
        """Set up test client."""
        settings._auth_settings = None
        self.client = testclient.TestClient(app.create_app())
        # Reset rate limiter to avoid 429 errors across tests
        rate_limit.limiter.reset()

    def tearDown(self) -> None:
        """Reset settings singleton after tests."""
        settings._auth_settings = None

    def test_login_with_password_rehash(self) -> None:
        """Test login rehashes password if needed."""
        import datetime

        from imbi import models

        # Create user with old password hash format (needs rehashing)
        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash='old-hash-format',  # Mock old hash
            created_at=datetime.datetime.now(datetime.UTC),
        )

        def mock_run_side_effect(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()

            # Check TOTPSecret FIRST (before User)
            if 'TOTPSecret' in query:
                mock_result.data = mock.AsyncMock(return_value=[])
            elif 'TokenMetadata' in query and 'jti' in query:
                mock_result.data = mock.AsyncMock(return_value=[])
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': []}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.neo4j.run', side_effect=mock_run_side_effect),
            mock.patch('imbi.neo4j.fetch_node', return_value=test_user),
            mock.patch('imbi.neo4j.create_node'),
            mock.patch('imbi.neo4j.upsert') as mock_upsert,
            mock.patch('imbi.auth.core.verify_password', return_value=True),
            mock.patch(
                'imbi.auth.core.password_needs_rehash', return_value=True
            ) as mock_needs_rehash,
            mock.patch(
                'imbi.auth.core.hash_password',
                return_value='new-hashed-password',
            ) as mock_hash,
        ):
            response = self.client.post(
                '/auth/login',
                json={'email': 'test@example.com', 'password': 'password123'},
            )

            self.assertEqual(response.status_code, 200)
            # Verify password was checked for rehash
            mock_needs_rehash.assert_called_once()
            # Verify new hash was created
            mock_hash.assert_called_once_with('password123')
            # Verify user was updated with new hash (called at least once)
            mock_upsert.assert_called()
            # Verify user object has new hash
            call_args = mock_upsert.call_args_list[0]
            updated_user = call_args[0][0]
            self.assertEqual(updated_user.password_hash, 'new-hashed-password')


class LoginMFATestCase(unittest.TestCase):
    """Test MFA integration in login endpoint."""

    def setUp(self) -> None:
        """Set up test client."""
        settings._auth_settings = None
        self.client = testclient.TestClient(app.create_app())
        # Reset rate limiter to avoid 429 errors across tests
        rate_limit.limiter.reset()

        # Mock encryption for MFA tests (plaintext secrets in tests)
        from imbi.auth.encryption import TokenEncryption

        mock_encryptor = mock.Mock()
        # decrypt() returns the input as-is (plaintext)
        mock_encryptor.decrypt = mock.Mock(side_effect=lambda x: x)
        # encrypt() returns the input as-is (plaintext)
        mock_encryptor.encrypt = mock.Mock(side_effect=lambda x: x)

        self.encryption_patcher = mock.patch.object(
            TokenEncryption, 'get_instance', return_value=mock_encryptor
        )
        self.encryption_patcher.start()

    def tearDown(self) -> None:
        """Reset settings singleton after tests."""
        self.encryption_patcher.stop()
        settings._auth_settings = None

    def test_login_mfa_required_no_code(self) -> None:
        """Test login with MFA enabled but no code provided."""
        import datetime

        from imbi import models
        from imbi.auth import core

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=core.hash_password('password123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        def mock_run_side_effect(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            # Check TOTPSecret FIRST (before User)
            if 'TOTPSecret' in query:
                # MFA is enabled
                totp_data = {
                    'secret': 'JBSWY3DPEHPK3PXP',
                    'enabled': True,
                    'backup_codes': [],
                }
                mock_result.data = mock.AsyncMock(
                    return_value=[{'t': totp_data}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.neo4j.run', side_effect=mock_run_side_effect),
            mock.patch('imbi.neo4j.fetch_node', return_value=test_user),
        ):
            response = self.client.post(
                '/auth/login',
                json={'email': 'test@example.com', 'password': 'password123'},
            )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()['detail'], 'MFA code required')
            self.assertEqual(response.headers.get('X-MFA-Required'), 'true')

    def test_login_mfa_valid_totp(self) -> None:
        """Test login with valid TOTP code."""
        import datetime

        import pyotp

        from imbi import models
        from imbi.auth import core

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=core.hash_password('password123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        # Generate valid TOTP code
        secret = 'JBSWY3DPEHPK3PXP'
        totp = pyotp.TOTP(secret)
        valid_code = totp.now()

        def mock_run_side_effect(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()

            # Check TOTPSecret FIRST (before User)
            if 'TOTPSecret' in query and 'RETURN t' in query:
                totp_data = {
                    'secret': secret,
                    'enabled': True,
                    'backup_codes': [],
                }
                mock_result.data = mock.AsyncMock(
                    return_value=[{'t': totp_data}]
                )
            elif 't.last_used' in query:
                # Update last used
                mock_result.data = mock.AsyncMock(return_value=[])
            elif 'TokenMetadata' in query and 'jti' in query:
                mock_result.data = mock.AsyncMock(return_value=[])
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': []}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.neo4j.run', side_effect=mock_run_side_effect),
            mock.patch('imbi.neo4j.fetch_node', return_value=test_user),
            mock.patch('imbi.neo4j.create_node'),
        ):
            response = self.client.post(
                '/auth/login',
                json={
                    'email': 'test@example.com',
                    'password': 'password123',
                    'mfa_code': valid_code,
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn('access_token', data)
            self.assertIn('refresh_token', data)

    def test_login_mfa_valid_backup_code(self) -> None:
        """Test login with valid backup code."""
        import datetime

        from imbi import models
        from imbi.auth import core

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=core.hash_password('password123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        backup_code = 'backup123'
        hashed_backup = core.hash_password(backup_code)

        def mock_run_side_effect(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()

            # Check TOTPSecret FIRST (before User)
            if 'TOTPSecret' in query and 'RETURN t' in query:
                totp_data = {
                    'secret': 'JBSWY3DPEHPK3PXP',
                    'enabled': True,
                    'backup_codes': [hashed_backup, 'other-code-hash'],
                }
                mock_result.data = mock.AsyncMock(
                    return_value=[{'t': totp_data}]
                )
            elif 't.backup_codes' in query:
                # Update backup codes (remove used one)
                mock_result.data = mock.AsyncMock(return_value=[])
            elif 'TokenMetadata' in query and 'jti' in query:
                mock_result.data = mock.AsyncMock(return_value=[])
            elif 'Permission' in query or 'GRANTS' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[{'permissions': []}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.neo4j.run', side_effect=mock_run_side_effect),
            mock.patch('imbi.neo4j.fetch_node', return_value=test_user),
            mock.patch('imbi.neo4j.create_node'),
        ):
            response = self.client.post(
                '/auth/login',
                json={
                    'email': 'test@example.com',
                    'password': 'password123',
                    'mfa_code': backup_code,
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn('access_token', data)
            self.assertIn('refresh_token', data)

    def test_login_mfa_invalid_code(self) -> None:
        """Test login with invalid MFA code."""
        import datetime

        from imbi import models
        from imbi.auth import core

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=core.hash_password('password123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        def mock_run_side_effect(query: str, **params):
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)

            # Check TOTPSecret FIRST (before User)
            if 'TOTPSecret' in query:
                totp_data = {
                    'secret': 'JBSWY3DPEHPK3PXP',
                    'enabled': True,
                    'backup_codes': [],
                }
                mock_result.data = mock.AsyncMock(
                    return_value=[{'t': totp_data}]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        with (
            mock.patch('imbi.neo4j.run', side_effect=mock_run_side_effect),
            mock.patch('imbi.neo4j.fetch_node', return_value=test_user),
        ):
            response = self.client.post(
                '/auth/login',
                json={
                    'email': 'test@example.com',
                    'password': 'password123',
                    'mfa_code': '000000',  # Invalid code
                },
            )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()['detail'], 'Invalid MFA code')

    def test_login_user_not_found(self) -> None:
        """Test login with user not found."""

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        with (
            mock.patch(
                'imbi.settings.get_auth_settings', return_value=auth_settings
            ),
            mock.patch('imbi.neo4j.fetch_node', return_value=None),
        ):
            response = self.client.post(
                '/auth/login',
                json={
                    'email': 'nonexistent@example.com',
                    'password': 'password123',
                },
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn('Invalid credentials', response.json()['detail'])

    def test_login_oauth_only_user(self) -> None:
        """Test login attempt for OAuth-only user (no password)."""
        import datetime

        from imbi import models

        # User without password hash (OAuth-only)
        oauth_user = models.User(
            email='oauth@example.com',
            display_name='OAuth User',
            is_active=True,
            password_hash=None,  # No password
            created_at=datetime.datetime.now(datetime.UTC),
        )

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        with (
            mock.patch(
                'imbi.settings.get_auth_settings', return_value=auth_settings
            ),
            mock.patch('imbi.neo4j.fetch_node', return_value=oauth_user),
        ):
            response = self.client.post(
                '/auth/login',
                json={'email': 'oauth@example.com', 'password': 'anypassword'},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn(
                'Password authentication not available',
                response.json()['detail'],
            )

    def test_login_invalid_password(self) -> None:
        """Test login with invalid password."""
        import datetime

        from imbi import models
        from imbi.auth import core

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=core.hash_password('correctpassword'),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        with (
            mock.patch(
                'imbi.settings.get_auth_settings', return_value=auth_settings
            ),
            mock.patch('imbi.neo4j.fetch_node', return_value=test_user),
        ):
            response = self.client.post(
                '/auth/login',
                json={
                    'email': 'test@example.com',
                    'password': 'wrongpassword',
                },
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn('Invalid credentials', response.json()['detail'])


class OAuthCallbackSuccessTestCase(unittest.TestCase):
    """Test OAuth callback success path."""

    def setUp(self) -> None:
        """Set up test client."""
        settings._auth_settings = None
        self.client = testclient.TestClient(app.create_app())

    def tearDown(self) -> None:
        """Reset settings singleton after tests."""
        settings._auth_settings = None

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_OAUTH_GOOGLE_ENABLED': 'true',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_ID': 'test-id',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_SECRET': 'test-secret',
            # Use valid Fernet key
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
        },
    )
    def test_oauth_callback_success_existing_identity(self) -> None:
        """Test OAuth callback with existing identity."""
        import datetime

        from imbi import models
        from imbi.auth import encryption
        from imbi.auth import models as auth_models

        # Reset settings to pick up env vars
        settings._auth_settings = None
        encryption.TokenEncryption.reset_instance()

        # Create test user and OAuth identity
        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        test_identity = models.OAuthIdentity(
            provider='google',
            provider_user_id='google-123',
            email='test@example.com',
            display_name='Test User',
            avatar_url='https://example.com/avatar.jpg',
            access_token='encrypted-access-token',
            refresh_token='encrypted-refresh-token',
            token_expires_at=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(hours=1),
            linked_at=datetime.datetime.now(datetime.UTC),
            last_used=datetime.datetime.now(datetime.UTC),
            raw_profile={'id': 'google-123', 'name': 'Test User'},
            user=test_user,
        )

        # Mock OAuth state verification
        mock_state_data = auth_models.OAuthStateData(
            provider='google',
            redirect_uri='/dashboard',
            nonce='test-nonce',
            timestamp=int(datetime.datetime.now(datetime.UTC).timestamp()),
        )

        # Mock OAuth token response
        mock_token_response = {
            'access_token': 'google-access-token',
            'refresh_token': 'google-refresh-token',
            'expires_in': 3600,
        }

        # Mock OAuth profile
        mock_profile = {
            'id': 'google-123',
            'email': 'test@example.com',
            'name': 'Test User',
            'avatar_url': 'https://example.com/avatar.jpg',
        }

        with (
            mock.patch(
                'imbi.auth.oauth.verify_oauth_state',
                return_value=mock_state_data,
            ),
            mock.patch(
                'imbi.auth.oauth.exchange_oauth_code',
                return_value=mock_token_response,
            ),
            mock.patch(
                'imbi.auth.oauth.fetch_oauth_profile',
                return_value=mock_profile,
            ),
            mock.patch('imbi.neo4j.fetch_node', return_value=test_identity),
            mock.patch('imbi.neo4j.refresh_relationship') as mock_refresh,
            mock.patch('imbi.neo4j.create_node'),
            mock.patch('imbi.neo4j.upsert'),
        ):
            # Set up identity.user for refresh_relationship
            async def mock_refresh_side_effect(obj, rel_name):
                if rel_name == 'user':
                    obj.user = test_user

            mock_refresh.side_effect = mock_refresh_side_effect

            response = self.client.get(
                '/auth/oauth/google/callback?code=test-code&state=test-state',
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 307)
            location = response.headers['location']

            # Verify redirect contains tokens in fragment
            self.assertIn('/dashboard#', location)
            self.assertIn('access_token=', location)
            self.assertIn('refresh_token=', location)
            self.assertIn('token_type=bearer', location)
            self.assertIn('expires_in=', location)

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_OAUTH_GOOGLE_ENABLED': 'true',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_ID': 'test-id',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_SECRET': 'test-secret',
            # Use valid Fernet key
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
            'IMBI_AUTH_OAUTH_AUTO_CREATE_USERS': 'true',
        },
    )
    def test_oauth_callback_success_new_user(self) -> None:
        """Test OAuth callback creating new user."""
        import datetime

        from imbi import models
        from imbi.auth import encryption
        from imbi.auth import models as auth_models

        # Reset settings to pick up env vars
        settings._auth_settings = None
        encryption.TokenEncryption.reset_instance()

        # Mock OAuth state verification
        mock_state_data = auth_models.OAuthStateData(
            provider='google',
            redirect_uri='/dashboard',
            nonce='test-nonce',
            timestamp=int(datetime.datetime.now(datetime.UTC).timestamp()),
        )

        # Mock OAuth token response
        mock_token_response = {
            'access_token': 'google-access-token',
            'refresh_token': 'google-refresh-token',
            'expires_in': 3600,
        }

        # Mock OAuth profile
        mock_profile = {
            'id': 'google-456',
            'email': 'newuser@example.com',
            'name': 'New User',
            'avatar_url': 'https://example.com/avatar2.jpg',
        }

        # Mock neo4j calls to simulate no existing identity/user
        def mock_fetch_node_side_effect(model_class, constraints):
            # Return None for all fetch calls (no existing identity or user)
            return None

        # Track created objects
        created_objects = []

        async def mock_create_node_side_effect(obj):
            created_objects.append(obj)
            return 'element-id-123'

        with (
            mock.patch(
                'imbi.auth.oauth.verify_oauth_state',
                return_value=mock_state_data,
            ),
            mock.patch(
                'imbi.auth.oauth.exchange_oauth_code',
                return_value=mock_token_response,
            ),
            mock.patch(
                'imbi.auth.oauth.fetch_oauth_profile',
                return_value=mock_profile,
            ),
            mock.patch(
                'imbi.neo4j.fetch_node',
                side_effect=mock_fetch_node_side_effect,
            ),
            mock.patch(
                'imbi.neo4j.create_node',
                side_effect=mock_create_node_side_effect,
            ),
            mock.patch('imbi.neo4j.create_relationship'),
            mock.patch('imbi.neo4j.refresh_relationship') as mock_refresh,
            mock.patch('imbi.neo4j.upsert'),
        ):
            # Set up user after identity is created
            async def mock_refresh_side_effect(obj, rel_name):
                if rel_name == 'user' and created_objects:
                    # Find the user in created objects
                    user = next(
                        (
                            o
                            for o in created_objects
                            if isinstance(o, models.User)
                        ),
                        None,
                    )
                    if user:
                        obj.user = user

            mock_refresh.side_effect = mock_refresh_side_effect

            response = self.client.get(
                '/auth/oauth/google/callback?code=test-code&state=test-state',
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 307)
            location = response.headers['location']

            # Verify redirect contains tokens in fragment
            self.assertIn('/dashboard#', location)
            self.assertIn('access_token=', location)
            self.assertIn('refresh_token=', location)

            # Verify user and identity were created
            self.assertGreater(len(created_objects), 0)
            # Should have user, identity, and 2 token metadata objects
            user_created = any(
                isinstance(o, models.User) for o in created_objects
            )
            identity_created = any(
                isinstance(o, models.OAuthIdentity) for o in created_objects
            )
            self.assertTrue(user_created, 'User should be created')
            self.assertTrue(
                identity_created, 'OAuth identity should be created'
            )

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_OAUTH_GOOGLE_ENABLED': 'true',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_ID': 'test-id',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_SECRET': 'test-secret',
            'IMBI_AUTH_OAUTH_GOOGLE_ALLOWED_DOMAINS': (
                '["example.com", "test.com"]'
            ),
            # Use valid Fernet key
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
        },
    )
    def test_oauth_callback_google_domain_restriction(self) -> None:
        """Test OAuth callback with Google domain restriction."""
        import datetime

        from imbi.auth import encryption
        from imbi.auth import models as auth_models

        # Reset settings to pick up env vars
        settings._auth_settings = None
        encryption.TokenEncryption.reset_instance()

        # Mock OAuth state verification
        mock_state_data = auth_models.OAuthStateData(
            provider='google',
            redirect_uri='/dashboard',
            nonce='test-nonce',
            timestamp=int(datetime.datetime.now(datetime.UTC).timestamp()),
        )

        # Mock OAuth token response
        mock_token_response = {
            'access_token': 'google-access-token',
            'expires_in': 3600,
        }

        # Mock OAuth profile with disallowed domain
        mock_profile = {
            'id': 'google-789',
            'email': 'user@baddomaindomain.com',  # Not in allowed list
            'name': 'Bad Domain User',
        }

        with (
            mock.patch(
                'imbi.auth.oauth.verify_oauth_state',
                return_value=mock_state_data,
            ),
            mock.patch(
                'imbi.auth.oauth.exchange_oauth_code',
                return_value=mock_token_response,
            ),
            mock.patch(
                'imbi.auth.oauth.fetch_oauth_profile',
                return_value=mock_profile,
            ),
            mock.patch('imbi.neo4j.fetch_node', return_value=None),
        ):
            response = self.client.get(
                '/auth/oauth/google/callback?code=test-code&state=test-state',
                follow_redirects=False,
            )

            # Should redirect to error page
            self.assertEqual(response.status_code, 307)
            self.assertIn(
                'error=authentication_failed', response.headers['location']
            )

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_OAUTH_GOOGLE_ENABLED': 'true',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_ID': 'test-id',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_SECRET': 'test-secret',
            # Use valid Fernet key
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
            'IMBI_AUTH_OAUTH_AUTO_LINK_BY_EMAIL': 'true',
        },
    )
    def test_oauth_callback_auto_link_existing_user(self) -> None:
        """Test OAuth callback auto-linking to existing user by email."""
        import datetime

        from imbi import models
        from imbi.auth import encryption
        from imbi.auth import models as auth_models

        # Reset settings to pick up env vars
        settings._auth_settings = None
        encryption.TokenEncryption.reset_instance()

        # Existing user
        existing_user = models.User(
            email='existing@example.com',
            display_name='Existing User',
            is_active=True,
            password_hash='existing-hash',
            created_at=datetime.datetime.now(datetime.UTC),
        )

        # Mock OAuth state verification
        mock_state_data = auth_models.OAuthStateData(
            provider='google',
            redirect_uri='/dashboard',
            nonce='test-nonce',
            timestamp=int(datetime.datetime.now(datetime.UTC).timestamp()),
        )

        # Mock OAuth token response
        mock_token_response = {
            'access_token': 'google-access-token',
            'expires_in': 3600,
        }

        # Mock OAuth profile with existing user's email
        mock_profile = {
            'id': 'google-999',
            'email': 'existing@example.com',
            'name': 'Existing User',
        }

        # Track fetch_node calls
        fetch_calls = []

        def mock_fetch_node_side_effect(model_class, constraints):
            fetch_calls.append((model_class, constraints))
            if model_class == models.OAuthIdentity:
                return None  # No existing identity
            elif model_class == models.User and 'email' in constraints:
                return existing_user  # Found existing user by email
            return None

        with (
            mock.patch(
                'imbi.auth.oauth.verify_oauth_state',
                return_value=mock_state_data,
            ),
            mock.patch(
                'imbi.auth.oauth.exchange_oauth_code',
                return_value=mock_token_response,
            ),
            mock.patch(
                'imbi.auth.oauth.fetch_oauth_profile',
                return_value=mock_profile,
            ),
            mock.patch(
                'imbi.neo4j.fetch_node',
                side_effect=mock_fetch_node_side_effect,
            ),
            mock.patch('imbi.neo4j.create_node'),
            mock.patch('imbi.neo4j.create_relationship'),
            mock.patch('imbi.neo4j.refresh_relationship') as mock_refresh,
            mock.patch('imbi.neo4j.upsert'),
        ):
            # Set up identity.user for refresh_relationship
            async def mock_refresh_side_effect(obj, rel_name):
                if rel_name == 'user':
                    obj.user = existing_user

            mock_refresh.side_effect = mock_refresh_side_effect

            response = self.client.get(
                '/auth/oauth/google/callback?code=test-code&state=test-state',
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 307)
            location = response.headers['location']
            self.assertIn('/dashboard#', location)
            self.assertIn('access_token=', location)

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_OAUTH_GOOGLE_ENABLED': 'true',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_ID': 'test-id',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_SECRET': 'test-secret',
            # Use valid Fernet key
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
            'IMBI_AUTH_OAUTH_AUTO_CREATE_USERS': 'false',
        },
    )
    def test_oauth_callback_auto_create_disabled(self) -> None:
        """Test OAuth callback with user auto-creation disabled."""
        import datetime

        from imbi.auth import encryption
        from imbi.auth import models as auth_models

        # Reset settings to pick up env vars
        settings._auth_settings = None
        encryption.TokenEncryption.reset_instance()

        # Mock OAuth state verification
        mock_state_data = auth_models.OAuthStateData(
            provider='google',
            redirect_uri='/dashboard',
            nonce='test-nonce',
            timestamp=int(datetime.datetime.now(datetime.UTC).timestamp()),
        )

        # Mock OAuth token response
        mock_token_response = {
            'access_token': 'google-access-token',
            'expires_in': 3600,
        }

        # Mock OAuth profile
        mock_profile = {
            'id': 'google-111',
            'email': 'newuser@example.com',
            'name': 'New User',
        }

        with (
            mock.patch(
                'imbi.auth.oauth.verify_oauth_state',
                return_value=mock_state_data,
            ),
            mock.patch(
                'imbi.auth.oauth.exchange_oauth_code',
                return_value=mock_token_response,
            ),
            mock.patch(
                'imbi.auth.oauth.fetch_oauth_profile',
                return_value=mock_profile,
            ),
            mock.patch('imbi.neo4j.fetch_node', return_value=None),
        ):
            response = self.client.get(
                '/auth/oauth/google/callback?code=test-code&state=test-state',
                follow_redirects=False,
            )

            # Should redirect to error page
            self.assertEqual(response.status_code, 307)
            self.assertIn(
                'error=authentication_failed', response.headers['location']
            )


class TokenRefreshTestCase(unittest.TestCase):
    """Test token refresh endpoint."""

    def setUp(self) -> None:
        """Set up test client."""
        settings._auth_settings = None
        self.client = testclient.TestClient(app.create_app())

    def tearDown(self) -> None:
        """Reset settings singleton after tests."""
        settings._auth_settings = None

    def test_refresh_token_success(self) -> None:
        """Test successful token refresh."""
        import datetime

        from imbi import models
        from imbi.auth import core

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        # Create test user
        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        # Create refresh token
        refresh_token, refresh_jti = core.create_refresh_token(
            test_user.email, auth_settings
        )

        # Create token metadata
        token_meta = models.TokenMetadata(
            jti=refresh_jti,
            token_type='refresh',
            issued_at=datetime.datetime.now(datetime.UTC),
            expires_at=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(
                seconds=auth_settings.refresh_token_expire_seconds
            ),
            user=test_user,
            revoked=False,
        )

        with (
            mock.patch(
                'imbi.settings.get_auth_settings', return_value=auth_settings
            ),
            mock.patch('imbi.neo4j.fetch_node') as mock_fetch_node,
            mock.patch('imbi.neo4j.upsert'),
            mock.patch('imbi.neo4j.create_node'),
        ):
            # First call fetches token metadata, second fetches user
            mock_fetch_node.side_effect = [token_meta, test_user]

            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': refresh_token},
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn('access_token', data)
            self.assertIn('refresh_token', data)
            self.assertNotEqual(
                data['refresh_token'], refresh_token
            )  # Rotated

    def test_refresh_token_expired(self) -> None:
        """Test token refresh with expired token."""
        import datetime

        import jwt

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
            refresh_token_expire_seconds=1,  # Short expiration for testing
        )

        # Create expired refresh token
        payload = {
            'sub': 'testuser',
            'type': 'refresh',
            'jti': 'test-jti',
            'exp': datetime.datetime.now(datetime.UTC)
            - datetime.timedelta(seconds=10),
        }
        expired_token = jwt.encode(
            payload,
            auth_settings.jwt_secret,
            algorithm=auth_settings.jwt_algorithm,
        )

        with mock.patch(
            'imbi.settings.get_auth_settings', return_value=auth_settings
        ):
            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': expired_token},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn('expired', response.json()['detail'].lower())

    def test_refresh_token_invalid(self) -> None:
        """Test token refresh with invalid token."""
        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        with mock.patch(
            'imbi.settings.get_auth_settings', return_value=auth_settings
        ):
            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': 'invalid-token'},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn('Invalid', response.json()['detail'])

    def test_refresh_token_wrong_type(self) -> None:
        """Test token refresh with access token instead of refresh token."""
        import datetime

        from imbi import models
        from imbi.auth import core

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        # Create access token (wrong type)
        access_token, _ = core.create_access_token(
            test_user.email, auth_settings
        )

        with mock.patch(
            'imbi.settings.get_auth_settings', return_value=auth_settings
        ):
            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': access_token},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn('type', response.json()['detail'].lower())

    def test_refresh_token_revoked(self) -> None:
        """Test token refresh with revoked token."""
        import datetime

        from imbi import models
        from imbi.auth import core

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        # Create refresh token
        refresh_token, refresh_jti = core.create_refresh_token(
            test_user.email, auth_settings
        )

        # Create revoked token metadata
        token_meta = models.TokenMetadata(
            jti=refresh_jti,
            token_type='refresh',
            issued_at=datetime.datetime.now(datetime.UTC),
            expires_at=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(
                seconds=auth_settings.refresh_token_expire_seconds
            ),
            user=test_user,
            revoked=True,  # Token is revoked
        )

        with (
            mock.patch(
                'imbi.settings.get_auth_settings', return_value=auth_settings
            ),
            mock.patch('imbi.neo4j.fetch_node', return_value=token_meta),
        ):
            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': refresh_token},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn('revoked', response.json()['detail'].lower())

    def test_refresh_token_user_inactive(self) -> None:
        """Test token refresh with inactive user."""
        import datetime

        from imbi import models
        from imbi.auth import core

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=False,  # Inactive user
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        # Create refresh token
        refresh_token, refresh_jti = core.create_refresh_token(
            test_user.email, auth_settings
        )

        # Create token metadata
        token_meta = models.TokenMetadata(
            jti=refresh_jti,
            token_type='refresh',
            issued_at=datetime.datetime.now(datetime.UTC),
            expires_at=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(
                seconds=auth_settings.refresh_token_expire_seconds
            ),
            user=test_user,
            revoked=False,
        )

        with (
            mock.patch(
                'imbi.settings.get_auth_settings', return_value=auth_settings
            ),
            mock.patch('imbi.neo4j.fetch_node') as mock_fetch_node,
            mock.patch('imbi.neo4j.upsert'),
        ):
            # First call returns token metadata, second returns inactive user
            mock_fetch_node.side_effect = [token_meta, test_user]

            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': refresh_token},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn('inactive', response.json()['detail'].lower())


class LogoutTestCase(unittest.TestCase):
    """Test logout endpoint."""

    def setUp(self) -> None:
        """Set up test client."""
        settings._auth_settings = None
        self.client = testclient.TestClient(app.create_app())

    def tearDown(self) -> None:
        """Reset settings singleton after tests."""
        settings._auth_settings = None

    def test_logout_single_session(self) -> None:
        """Test logout with revoke_all_sessions=False."""
        import datetime

        from imbi import models
        from imbi.auth import core, permissions

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        # Create test user
        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        # Create access token
        access_token, access_jti = core.create_access_token(
            test_user.email, auth_settings
        )

        # Create mock auth context
        mock_auth = permissions.AuthContext(
            user=test_user,
            session_id=access_jti,
            auth_method='jwt',
            permissions=set(),
        )

        # Track neo4j queries executed
        queries_executed = []

        def mock_run_side_effect(query: str, **params):
            queries_executed.append((query, params))
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()

            # For issued_at query, return a timestamp
            if 'RETURN t.issued_at' in query:
                mock_result.data = mock.AsyncMock(
                    return_value=[
                        {'issued_at': datetime.datetime.now(datetime.UTC)}
                    ]
                )
            else:
                mock_result.data = mock.AsyncMock(return_value=[])

            return mock_result

        # Override FastAPI dependency
        async def override_get_current_user():
            return mock_auth

        self.client.app.dependency_overrides[permissions.get_current_user] = (
            override_get_current_user
        )

        try:
            with (
                mock.patch(
                    'imbi.settings.get_auth_settings',
                    return_value=auth_settings,
                ),
                mock.patch('imbi.neo4j.run', side_effect=mock_run_side_effect),
            ):
                response = self.client.post(
                    '/auth/logout',
                    headers={'Authorization': f'Bearer {access_token}'},
                )

                self.assertEqual(response.status_code, 204)

                # Verify queries were executed
                # Expect: revoke current, get issued_at, revoke refresh
                self.assertGreaterEqual(len(queries_executed), 3)

                # Verify current token revocation query
                first_query = queries_executed[0][0]
                self.assertIn('SET t.revoked = true', first_query)
                self.assertIn('jti', queries_executed[0][1])
        finally:
            # Clean up dependency override
            self.client.app.dependency_overrides.clear()

    def test_logout_all_sessions(self) -> None:
        """Test logout with revoke_all_sessions=True."""
        import datetime

        from imbi import models
        from imbi.auth import core, permissions

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        # Create test user
        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        # Create access token
        access_token, access_jti = core.create_access_token(
            test_user.email, auth_settings
        )

        # Create mock auth context
        mock_auth = permissions.AuthContext(
            user=test_user,
            session_id=access_jti,
            auth_method='jwt',
            permissions=set(),
        )

        # Track neo4j queries executed
        queries_executed = []

        def mock_run_side_effect(query: str, **params):
            queries_executed.append((query, params))
            mock_result = mock.AsyncMock()
            mock_result.__aenter__ = mock.AsyncMock(return_value=mock_result)
            mock_result.__aexit__ = mock.AsyncMock(return_value=None)
            mock_result.consume = mock.AsyncMock()
            mock_result.data = mock.AsyncMock(return_value=[])
            return mock_result

        # Override FastAPI dependency
        async def override_get_current_user():
            return mock_auth

        self.client.app.dependency_overrides[permissions.get_current_user] = (
            override_get_current_user
        )

        try:
            with (
                mock.patch(
                    'imbi.settings.get_auth_settings',
                    return_value=auth_settings,
                ),
                mock.patch('imbi.neo4j.run', side_effect=mock_run_side_effect),
            ):
                response = self.client.post(
                    '/auth/logout?revoke_all_sessions=true',
                    headers={'Authorization': f'Bearer {access_token}'},
                )

                self.assertEqual(response.status_code, 204)

                # Verify queries were executed
                # Expect: revoke current, revoke all, delete sessions
                self.assertEqual(len(queries_executed), 3)

                # Verify current token revocation
                self.assertIn('SET t.revoked = true', queries_executed[0][0])

                # Verify all tokens revocation
                self.assertIn(
                    'WHERE t.revoked = false', queries_executed[1][0]
                )
                self.assertIn('email', queries_executed[1][1])

                # Verify all sessions deletion
                self.assertIn('DETACH DELETE', queries_executed[2][0])
                self.assertIn('Session', queries_executed[2][0])
        finally:
            # Clean up dependency override
            self.client.app.dependency_overrides.clear()
