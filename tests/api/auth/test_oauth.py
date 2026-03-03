import time
import unittest
from unittest import mock

import httpx
import jwt

from imbi_api import settings
from imbi_api.auth import models, oauth


class OAuthStateTestCase(unittest.TestCase):
    """Test cases for OAuth state generation and verification."""

    def setUp(self) -> None:
        """Set up test auth settings."""
        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-for-oauth-state'
        )

    def test_generate_oauth_state(self) -> None:
        """Test generating OAuth state token."""
        state_token, state_data = oauth.generate_oauth_state(
            'google', '/dashboard', self.auth_settings
        )

        # Verify state token is a string (JWT)
        self.assertIsInstance(state_token, str)
        self.assertTrue(len(state_token) > 0)

        # Verify state data
        self.assertEqual(state_data.provider, 'google')
        self.assertEqual(state_data.redirect_uri, '/dashboard')
        self.assertTrue(len(state_data.nonce) > 0)
        self.assertIsInstance(state_data.timestamp, int)

    def test_verify_oauth_state_success(self) -> None:
        """Test verifying valid OAuth state token."""
        # Generate state
        state_token, original_data = oauth.generate_oauth_state(
            'github', '/projects', self.auth_settings
        )

        # Verify state
        verified_data = oauth.verify_oauth_state(
            state_token, self.auth_settings
        )

        # Should match original data
        self.assertEqual(verified_data.provider, original_data.provider)
        self.assertEqual(
            verified_data.redirect_uri, original_data.redirect_uri
        )
        self.assertEqual(verified_data.nonce, original_data.nonce)
        self.assertEqual(verified_data.timestamp, original_data.timestamp)

    def test_verify_oauth_state_expired(self) -> None:
        """Test verifying expired OAuth state token."""
        # Generate state with old timestamp
        state_data = models.OAuthStateData(
            provider='google',
            nonce='test-nonce',
            redirect_uri='/dashboard',
            timestamp=int(time.time()) - 700,  # 11 minutes ago
        )

        state_token = jwt.encode(
            state_data.model_dump(),
            self.auth_settings.jwt_secret,
            algorithm=self.auth_settings.jwt_algorithm,
        )

        # Verify should fail due to age
        with self.assertRaises(ValueError) as context:
            oauth.verify_oauth_state(state_token, self.auth_settings)

        self.assertIn('expired', str(context.exception).lower())

    def test_verify_oauth_state_invalid_signature(self) -> None:
        """Test verifying OAuth state with wrong secret."""
        # Generate state with different secret
        wrong_settings = settings.Auth(jwt_secret='wrong-secret')
        state_token, _ = oauth.generate_oauth_state(
            'google', '/dashboard', wrong_settings
        )

        # Verify with correct secret should fail
        with self.assertRaises(ValueError) as context:
            oauth.verify_oauth_state(state_token, self.auth_settings)

        self.assertIn('invalid', str(context.exception).lower())

    def test_verify_oauth_state_malformed(self) -> None:
        """Test verifying malformed OAuth state token."""
        with self.assertRaises(ValueError):
            oauth.verify_oauth_state('not-a-valid-jwt', self.auth_settings)


class OAuthProfileNormalizationTestCase(unittest.TestCase):
    """Test cases for OAuth profile normalization."""

    def test_normalize_google_profile(self) -> None:
        """Test normalizing Google OAuth profile."""
        raw_profile = {
            'id': '12345',
            'email': 'user@example.com',
            'name': 'Test User',
            'picture': 'https://example.com/avatar.jpg',
        }

        normalized = oauth.normalize_oauth_profile('google', raw_profile)

        self.assertEqual(normalized['id'], '12345')
        self.assertEqual(normalized['email'], 'user@example.com')
        self.assertEqual(normalized['name'], 'Test User')
        self.assertEqual(
            normalized['avatar_url'], 'https://example.com/avatar.jpg'
        )

    def test_normalize_github_profile(self) -> None:
        """Test normalizing GitHub OAuth profile."""
        raw_profile = {
            'id': 67890,
            'login': 'testuser',
            'email': 'user@example.com',
            'name': 'Test User',
            'avatar_url': 'https://avatars.githubusercontent.com/u/67890',
        }

        normalized = oauth.normalize_oauth_profile('github', raw_profile)

        self.assertEqual(normalized['id'], '67890')  # Converted to string
        self.assertEqual(normalized['email'], 'user@example.com')
        self.assertEqual(normalized['name'], 'Test User')
        self.assertEqual(
            normalized['avatar_url'],
            'https://avatars.githubusercontent.com/u/67890',
        )

    def test_normalize_github_profile_no_name(self) -> None:
        """Test normalizing GitHub profile without name (uses login)."""
        raw_profile = {
            'id': 67890,
            'login': 'testuser',
            'email': 'user@example.com',
            'name': None,
            'avatar_url': 'https://avatars.githubusercontent.com/u/67890',
        }

        normalized = oauth.normalize_oauth_profile('github', raw_profile)

        self.assertEqual(normalized['name'], 'testuser')

    def test_normalize_oidc_profile(self) -> None:
        """Test normalizing generic OIDC profile."""
        raw_profile = {
            'sub': 'oidc-user-123',
            'email': 'user@example.com',
            'name': 'Test User',
            'picture': 'https://example.com/avatar.jpg',
        }

        normalized = oauth.normalize_oauth_profile('oidc', raw_profile)

        self.assertEqual(normalized['id'], 'oidc-user-123')
        self.assertEqual(normalized['email'], 'user@example.com')
        self.assertEqual(normalized['name'], 'Test User')
        self.assertEqual(
            normalized['avatar_url'], 'https://example.com/avatar.jpg'
        )

    def test_normalize_oidc_profile_preferred_username(self) -> None:
        """Test OIDC profile with preferred_username instead of name."""
        raw_profile = {
            'sub': 'oidc-user-123',
            'email': 'user@example.com',
            'preferred_username': 'testuser',
        }

        normalized = oauth.normalize_oauth_profile('oidc', raw_profile)

        self.assertEqual(normalized['name'], 'testuser')

    def test_normalize_oidc_profile_fallback_to_email(self) -> None:
        """Test OIDC profile falls back to email username when no name."""
        raw_profile = {
            'sub': 'oidc-user-123',
            'email': 'user@example.com',
        }

        normalized = oauth.normalize_oauth_profile('oidc', raw_profile)

        self.assertEqual(normalized['name'], 'user')

    def test_normalize_google_profile_missing_email(self) -> None:
        """Test Google profile normalization fails without email."""
        raw_profile = {
            'id': '12345',
            'name': 'Test User',
            'picture': 'https://example.com/avatar.jpg',
        }

        with self.assertRaises(ValueError) as context:
            oauth.normalize_oauth_profile('google', raw_profile)

        self.assertIn('email', str(context.exception).lower())

    def test_normalize_github_profile_missing_email(self) -> None:
        """Test GitHub profile normalization fails without email."""
        raw_profile = {
            'id': 67890,
            'login': 'testuser',
            'email': None,  # User has private email
            'name': 'Test User',
        }

        with self.assertRaises(ValueError) as context:
            oauth.normalize_oauth_profile('github', raw_profile)

        self.assertIn('email', str(context.exception).lower())

    def test_normalize_oidc_profile_missing_email(self) -> None:
        """Test OIDC profile normalization fails without email."""
        raw_profile = {
            'sub': 'oidc-user-123',
            'name': 'Test User',
        }

        with self.assertRaises(ValueError) as context:
            oauth.normalize_oauth_profile('oidc', raw_profile)

        self.assertIn('email', str(context.exception).lower())

    def test_normalize_unsupported_provider(self) -> None:
        """Test normalizing profile for unsupported provider."""
        with self.assertRaises(ValueError) as context:
            oauth.normalize_oauth_profile('unsupported', {})

        self.assertIn('unsupported', str(context.exception).lower())


class OIDCDiscoveryTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for OIDC discovery."""

    def setUp(self) -> None:
        """Clear OIDC discovery cache before each test."""
        oauth._oidc_discovery_cache.clear()

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_discover_oidc_endpoints_success(
        self, mock_client_class: mock.Mock
    ) -> None:
        """Test successful OIDC discovery."""
        # Mock discovery response
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'issuer': 'https://auth.example.com',
            'token_endpoint': 'https://auth.example.com/oauth/token',
            'userinfo_endpoint': 'https://auth.example.com/userinfo',
            'authorization_endpoint': 'https://auth.example.com/authorize',
        }

        # Mock client
        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock()
        mock_client_class.return_value = mock_client

        # Perform discovery
        discovery = await oauth._discover_oidc_endpoints(
            'https://auth.example.com'
        )

        # Verify result
        self.assertEqual(
            discovery['token_endpoint'], 'https://auth.example.com/oauth/token'
        )
        self.assertEqual(
            discovery['userinfo_endpoint'],
            'https://auth.example.com/userinfo',
        )

        # Verify cache was populated
        self.assertIn('https://auth.example.com', oauth._oidc_discovery_cache)

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_discover_oidc_endpoints_cached(
        self, mock_client_class: mock.Mock
    ) -> None:
        """Test OIDC discovery uses cache on second call."""
        # Populate cache manually with timestamp
        cached_data = {
            'token_endpoint': 'https://cached.example.com/token',
            'userinfo_endpoint': 'https://cached.example.com/userinfo',
        }
        oauth._oidc_discovery_cache['https://cached.example.com'] = (
            cached_data,
            time.time(),
        )

        # Perform discovery - should use cache
        discovery = await oauth._discover_oidc_endpoints(
            'https://cached.example.com'
        )

        # Verify cached data was returned
        self.assertEqual(discovery, cached_data)

        # Verify no HTTP call was made
        mock_client_class.assert_not_called()

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_discover_oidc_endpoints_cache_expired(
        self, mock_client_class: mock.Mock
    ) -> None:
        """Test OIDC discovery refreshes expired cache."""
        # Populate cache with old timestamp (expired)
        cached_data = {
            'token_endpoint': 'https://expired.example.com/token',
            'userinfo_endpoint': 'https://expired.example.com/userinfo',
        }
        # Set timestamp to 25 hours ago (TTL is 24 hours)
        expired_timestamp = time.time() - (25 * 3600)
        oauth._oidc_discovery_cache['https://expired.example.com'] = (
            cached_data,
            expired_timestamp,
        )

        # Mock fresh discovery response
        mock_response = mock.Mock()
        mock_response.status_code = 200
        fresh_data = {
            'token_endpoint': 'https://expired.example.com/token-new',
            'userinfo_endpoint': 'https://expired.example.com/userinfo-new',
        }
        mock_response.json.return_value = fresh_data

        mock_client = mock.AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        # Perform discovery - should re-fetch due to expired cache
        discovery = await oauth._discover_oidc_endpoints(
            'https://expired.example.com'
        )

        # Verify fresh data was returned (not cached)
        self.assertEqual(discovery, fresh_data)

        # Verify HTTP call was made
        mock_client_class.assert_called_once()
        mock_client.get.assert_called_once_with(
            'https://expired.example.com/.well-known/openid-configuration'
        )

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_discover_oidc_endpoints_network_error(
        self, mock_client_class: mock.Mock
    ) -> None:
        """Test OIDC discovery with network error."""
        # Mock client that raises HTTPError
        mock_client = mock.AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = httpx.HTTPError('Connection failed')
        mock_client_class.return_value = mock_client

        # Perform discovery - should raise ValueError
        with self.assertRaises(ValueError) as context:
            await oauth._discover_oidc_endpoints(
                'https://network-error.example.com'
            )

        self.assertIn(
            'discovery request failed', str(context.exception).lower()
        )

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_discover_oidc_endpoints_http_error(
        self, mock_client_class: mock.Mock
    ) -> None:
        """Test OIDC discovery with HTTP error."""
        # Mock error response
        mock_response = mock.Mock()
        mock_response.status_code = 404
        mock_response.text = 'Not Found'

        # Mock client
        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock()
        mock_client_class.return_value = mock_client

        # Perform discovery - should raise ValueError
        with self.assertRaises(ValueError) as context:
            await oauth._discover_oidc_endpoints('https://bad.example.com')

        self.assertIn('discovery failed', str(context.exception).lower())

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_discover_oidc_endpoints_missing_token_endpoint(
        self, mock_client_class: mock.Mock
    ) -> None:
        """Test OIDC discovery missing required token_endpoint."""
        # Mock response missing token_endpoint
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'issuer': 'https://auth.example.com',
            'userinfo_endpoint': 'https://auth.example.com/userinfo',
        }

        # Mock client
        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock()
        mock_client_class.return_value = mock_client

        # Perform discovery - should raise ValueError
        with self.assertRaises(ValueError) as context:
            await oauth._discover_oidc_endpoints('https://bad.example.com')

        self.assertIn('token_endpoint', str(context.exception).lower())

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_discover_oidc_endpoints_missing_userinfo_endpoint(
        self, mock_client_class: mock.Mock
    ) -> None:
        """Test OIDC discovery missing required userinfo_endpoint."""
        # Mock response missing userinfo_endpoint
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'issuer': 'https://auth.example.com',
            'token_endpoint': 'https://auth.example.com/oauth/token',
        }

        # Mock client
        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock()
        mock_client_class.return_value = mock_client

        # Perform discovery - should raise ValueError
        with self.assertRaises(ValueError) as context:
            await oauth._discover_oidc_endpoints('https://bad.example.com')

        self.assertIn('userinfo_endpoint', str(context.exception).lower())


class OAuthProviderConfigTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for OAuth provider configuration."""

    def setUp(self) -> None:
        """Clear OIDC discovery cache before each test."""
        oauth._oidc_discovery_cache.clear()

    async def test_get_provider_config_google(self) -> None:
        """Test getting Google OAuth config."""
        auth_settings = settings.Auth(
            oauth_google_enabled=True,
            oauth_google_client_id='test-client-id',
            oauth_google_client_secret='test-client-secret',
        )

        token_url, client_id, client_secret = await oauth._get_provider_config(
            'google', auth_settings
        )

        self.assertEqual(token_url, 'https://oauth2.googleapis.com/token')
        self.assertEqual(client_id, 'test-client-id')
        self.assertEqual(client_secret, 'test-client-secret')

    async def test_get_provider_config_github(self) -> None:
        """Test getting GitHub OAuth config."""
        auth_settings = settings.Auth(
            oauth_github_enabled=True,
            oauth_github_client_id='github-client-id',
            oauth_github_client_secret='github-client-secret',
        )

        token_url, client_id, client_secret = await oauth._get_provider_config(
            'github', auth_settings
        )

        self.assertEqual(
            token_url, 'https://github.com/login/oauth/access_token'
        )
        self.assertEqual(client_id, 'github-client-id')
        self.assertEqual(client_secret, 'github-client-secret')

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_get_provider_config_oidc(
        self, mock_client_class: mock.Mock
    ) -> None:
        """Test getting OIDC OAuth config via discovery."""
        auth_settings = settings.Auth(
            oauth_oidc_enabled=True,
            oauth_oidc_client_id='oidc-client-id',
            oauth_oidc_client_secret='oidc-client-secret',
            oauth_oidc_issuer_url='https://auth.example.com',
        )

        # Mock discovery response
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'issuer': 'https://auth.example.com',
            'token_endpoint': 'https://auth.example.com/oauth/token',
            'userinfo_endpoint': 'https://auth.example.com/userinfo',
            'authorization_endpoint': 'https://auth.example.com/authorize',
        }

        # Mock client
        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock()
        mock_client_class.return_value = mock_client

        token_url, client_id, client_secret = await oauth._get_provider_config(
            'oidc', auth_settings
        )

        self.assertEqual(token_url, 'https://auth.example.com/oauth/token')
        self.assertEqual(client_id, 'oidc-client-id')
        self.assertEqual(client_secret, 'oidc-client-secret')

        # Verify discovery was called
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        self.assertEqual(
            call_args[0][0],
            'https://auth.example.com/.well-known/openid-configuration',
        )

    async def test_get_provider_config_disabled(self) -> None:
        """Test getting config for disabled provider."""
        auth_settings = settings.Auth(oauth_google_enabled=False)

        with self.assertRaises(ValueError) as context:
            await oauth._get_provider_config('google', auth_settings)

        self.assertIn('not enabled', str(context.exception).lower())

    async def test_get_provider_config_unsupported(self) -> None:
        """Test getting config for unsupported provider."""
        auth_settings = settings.Auth()

        with self.assertRaises(ValueError) as context:
            await oauth._get_provider_config('unsupported', auth_settings)

        self.assertIn('unsupported', str(context.exception).lower())


class OAuthUserinfoUrlTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for getting userinfo URLs."""

    def setUp(self) -> None:
        """Clear OIDC discovery cache before each test."""
        oauth._oidc_discovery_cache.clear()

    async def test_get_userinfo_url_google(self) -> None:
        """Test getting Google userinfo URL."""
        auth_settings = settings.Auth(oauth_google_enabled=True)
        url = await oauth._get_userinfo_url('google', auth_settings)
        self.assertEqual(url, 'https://www.googleapis.com/oauth2/v2/userinfo')

    async def test_get_userinfo_url_github(self) -> None:
        """Test getting GitHub userinfo URL."""
        auth_settings = settings.Auth(oauth_github_enabled=True)
        url = await oauth._get_userinfo_url('github', auth_settings)
        self.assertEqual(url, 'https://api.github.com/user')

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_get_userinfo_url_oidc(
        self, mock_client_class: mock.Mock
    ) -> None:
        """Test getting OIDC userinfo URL via discovery."""
        auth_settings = settings.Auth(
            oauth_oidc_enabled=True,
            oauth_oidc_issuer_url='https://auth.example.com',
        )

        # Mock discovery response
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'issuer': 'https://auth.example.com',
            'token_endpoint': 'https://auth.example.com/oauth/token',
            'userinfo_endpoint': 'https://auth.example.com/userinfo',
        }

        # Mock client
        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock()
        mock_client_class.return_value = mock_client

        url = await oauth._get_userinfo_url('oidc', auth_settings)
        self.assertEqual(url, 'https://auth.example.com/userinfo')

    async def test_get_userinfo_url_oidc_missing_issuer(self) -> None:
        """Test getting OIDC userinfo URL without issuer configured."""
        auth_settings = settings.Auth(oauth_oidc_enabled=True)

        with self.assertRaises(ValueError) as context:
            await oauth._get_userinfo_url('oidc', auth_settings)

        self.assertIn('issuer', str(context.exception).lower())

    async def test_get_userinfo_url_unsupported(self) -> None:
        """Test getting userinfo URL for unsupported provider."""
        auth_settings = settings.Auth()

        with self.assertRaises(ValueError) as context:
            await oauth._get_userinfo_url('unsupported', auth_settings)

        self.assertIn('unsupported', str(context.exception).lower())


class OAuthTokenExchangeTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for OAuth token exchange."""

    def setUp(self) -> None:
        """Set up test auth settings."""
        self.auth_settings = settings.Auth(
            oauth_google_enabled=True,
            oauth_google_client_id='test-client-id',
            oauth_google_client_secret='test-client-secret',
        )

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_exchange_oauth_code_success(
        self, mock_client_class: mock.Mock
    ) -> None:
        """Test successful OAuth code exchange."""
        # Mock response
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'access_token': 'test-access-token',
            'refresh_token': 'test-refresh-token',
            'expires_in': 3600,
        }

        # Mock client
        mock_client = mock.AsyncMock()
        mock_client.post = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock()
        mock_client_class.return_value = mock_client

        # Exchange code
        tokens = await oauth.exchange_oauth_code(
            'google',
            'test-auth-code',
            'http://localhost:8000/auth/oauth/google/callback',
            self.auth_settings,
        )

        # Verify tokens
        self.assertEqual(tokens['access_token'], 'test-access-token')
        self.assertEqual(tokens['refresh_token'], 'test-refresh-token')
        self.assertEqual(tokens['expires_in'], 3600)

        # Verify API call
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        self.assertEqual(
            call_args[0][0], 'https://oauth2.googleapis.com/token'
        )

    # NOTE: Error handling test removed - will be covered by integration tests
    # The httpx AsyncClient mock is complex to set up for failure scenarios


class OAuthProfileFetchTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for OAuth profile fetching."""

    def setUp(self) -> None:
        """Set up test auth settings."""
        self.auth_settings = settings.Auth(oauth_google_enabled=True)

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_fetch_oauth_profile_success(
        self, mock_client_class: mock.Mock
    ) -> None:
        """Test successful OAuth profile fetch."""
        # Mock response
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'id': '12345',
            'email': 'user@example.com',
            'name': 'Test User',
            'picture': 'https://example.com/avatar.jpg',
        }

        # Mock client
        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock()
        mock_client_class.return_value = mock_client

        # Fetch profile
        profile = await oauth.fetch_oauth_profile(
            'google', 'test-access-token', self.auth_settings
        )

        # Verify normalized profile
        self.assertEqual(profile['id'], '12345')
        self.assertEqual(profile['email'], 'user@example.com')
        self.assertEqual(profile['name'], 'Test User')

    # NOTE: Error handling test removed - will be covered by integration tests
    # The httpx AsyncClient mock is complex to set up for failure scenarios

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_exchange_oauth_code_failure(
        self, mock_client_class: mock.Mock
    ) -> None:
        """Test token exchange with error response."""
        # Mock failed token exchange response
        mock_response = mock.Mock()
        mock_response.status_code = 400
        mock_response.text = 'invalid_grant'

        mock_client = mock.AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        # Mock _get_provider_config
        with mock.patch.object(
            oauth,
            '_get_provider_config',
            return_value=(
                'https://token-url.com',
                'client-id',
                'secret',
            ),
        ):
            # Attempt exchange - should raise ValueError
            with self.assertRaises(ValueError) as context:
                await oauth.exchange_oauth_code(
                    'google',
                    'bad-code',
                    'http://localhost/callback',
                    self.auth_settings,
                )

            self.assertIn(
                'token exchange failed', str(context.exception).lower()
            )

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_fetch_oauth_profile_failure(
        self, mock_client_class: mock.Mock
    ) -> None:
        """Test profile fetch with error response."""
        # Mock failed profile fetch response
        mock_response = mock.Mock()
        mock_response.status_code = 401
        mock_response.text = 'Unauthorized'

        mock_client = mock.AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        # Mock _get_userinfo_url
        with mock.patch.object(
            oauth, '_get_userinfo_url', return_value='https://userinfo-url.com'
        ):
            # Attempt fetch - should raise ValueError
            with self.assertRaises(ValueError) as context:
                await oauth.fetch_oauth_profile(
                    'google', 'bad-token', self.auth_settings
                )

            self.assertIn(
                'profile fetch failed', str(context.exception).lower()
            )

    def test_normalize_oidc_profile_missing_identity(self) -> None:
        """Test OIDC profile normalization fails without identity field."""
        raw_profile = {
            'email': 'user@example.com',
            'name': 'Test User',
        }

        with self.assertRaises(ValueError) as context:
            oauth.normalize_oauth_profile('oidc', raw_profile)

        self.assertIn(
            'missing required identity field', str(context.exception).lower()
        )

    async def test_get_provider_config_github_disabled(self) -> None:
        """Test _get_provider_config fails when GitHub OAuth is disabled."""
        self.auth_settings.oauth_github_enabled = False

        with self.assertRaises(ValueError) as context:
            await oauth._get_provider_config('github', self.auth_settings)

        self.assertIn(
            'github oauth is not enabled', str(context.exception).lower()
        )

    async def test_get_provider_config_oidc_disabled(self) -> None:
        """Test _get_provider_config fails when OIDC OAuth is disabled."""
        self.auth_settings.oauth_oidc_enabled = False

        with self.assertRaises(ValueError) as context:
            await oauth._get_provider_config('oidc', self.auth_settings)

        self.assertIn(
            'oidc oauth is not enabled', str(context.exception).lower()
        )

    async def test_get_provider_config_oidc_missing_issuer(self) -> None:
        """Test _get_provider_config fails when OIDC issuer not set."""
        self.auth_settings.oauth_oidc_enabled = True
        self.auth_settings.oauth_oidc_issuer_url = None

        with self.assertRaises(ValueError) as context:
            await oauth._get_provider_config('oidc', self.auth_settings)

        self.assertIn(
            'issuer url not configured', str(context.exception).lower()
        )
