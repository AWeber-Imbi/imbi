import time
import typing
import unittest
from unittest import mock

import httpx
import jwt

from imbi_api import settings
from imbi_api.auth import login_providers, models, oauth


def _stub_provider(
    slug: str,
    *,
    enabled: bool = True,
    client_id: str | None = None,
    client_secret: str | None = None,
    issuer_url: str | None = None,
    name: str = 'Provider',
) -> login_providers.LoginApp:
    """Build a login-app row with a clear-text secret stand-in.

    The tests patch ``TokenEncryption.get_instance`` so the
    ``client_secret_encrypted`` value round-trips as plaintext.
    """
    return login_providers.LoginApp(
        slug=slug,
        name=name,
        oauth_app_type=slug,  # type: ignore[arg-type]
        client_id=client_id,
        client_secret_encrypted=client_secret,
        issuer_url=issuer_url,
        status='active' if enabled else 'inactive',
    )


class _FakeEncryptor:
    """Identity 'encryption' for tests."""

    def encrypt(self, value: str | None) -> str | None:
        return value

    def decrypt(self, value: str | None) -> str | None:
        return value


def _patch_encryptor() -> typing.Any:
    return mock.patch(
        'imbi_common.auth.encryption.TokenEncryption.get_instance',
        return_value=_FakeEncryptor(),
    )


class OAuthStateTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for OAuth state generation and verification."""

    def setUp(self) -> None:
        """Set up test auth settings and a fresh-nonce Valkey stub."""
        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-for-oauth-state'
        )
        # Default: ``set`` returns truthy, meaning nonce was newly recorded.
        self.valkey = mock.AsyncMock()
        self.valkey.set = mock.AsyncMock(return_value=True)

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

    async def test_verify_oauth_state_success(self) -> None:
        """Test verifying valid OAuth state token."""
        # Generate state
        state_token, original_data = oauth.generate_oauth_state(
            'github', '/projects', self.auth_settings
        )

        # Verify state
        verified_data = await oauth.verify_oauth_state(
            state_token, self.auth_settings, valkey_client=self.valkey
        )

        # Should match original data
        self.assertEqual(verified_data.provider, original_data.provider)
        self.assertEqual(
            verified_data.redirect_uri, original_data.redirect_uri
        )
        self.assertEqual(verified_data.nonce, original_data.nonce)
        self.assertEqual(verified_data.timestamp, original_data.timestamp)
        # Nonce was consumed via SET NX EX.
        self.valkey.set.assert_awaited_once()
        args, kwargs = self.valkey.set.await_args
        self.assertTrue(args[0].startswith('imbi:oauth:state-nonce:'))
        self.assertEqual(kwargs.get('nx'), True)

    async def test_verify_oauth_state_expired(self) -> None:
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

        # Verify should fail due to age, before any nonce consume.
        with self.assertRaises(ValueError) as context:
            await oauth.verify_oauth_state(
                state_token, self.auth_settings, valkey_client=self.valkey
            )

        self.assertIn('expired', str(context.exception).lower())
        self.valkey.set.assert_not_awaited()

    async def test_verify_oauth_state_invalid_signature(self) -> None:
        """Test verifying OAuth state with wrong secret."""
        wrong_settings = settings.Auth(jwt_secret='wrong-secret')
        state_token, _ = oauth.generate_oauth_state(
            'google', '/dashboard', wrong_settings
        )

        with self.assertRaises(ValueError) as context:
            await oauth.verify_oauth_state(
                state_token, self.auth_settings, valkey_client=self.valkey
            )

        self.assertIn('invalid', str(context.exception).lower())

    async def test_verify_oauth_state_malformed(self) -> None:
        """Test verifying malformed OAuth state token."""
        with self.assertRaises(ValueError):
            await oauth.verify_oauth_state(
                'not-a-valid-jwt',
                self.auth_settings,
                valkey_client=self.valkey,
            )

    async def test_verify_oauth_state_replay_rejected(self) -> None:
        """Second use of the same state token must be rejected."""
        self.valkey.set = mock.AsyncMock(return_value=None)
        state_token, _ = oauth.generate_oauth_state(
            'google', '/dashboard', self.auth_settings
        )
        with self.assertRaises(ValueError) as context:
            await oauth.verify_oauth_state(
                state_token, self.auth_settings, valkey_client=self.valkey
            )
        self.assertIn('replay', str(context.exception).lower())

    async def test_verify_oauth_state_requires_valkey(self) -> None:
        """No Valkey client -> fail closed."""
        state_token, _ = oauth.generate_oauth_state(
            'google', '/dashboard', self.auth_settings
        )
        with self.assertRaises(RuntimeError):
            await oauth.verify_oauth_state(
                state_token, self.auth_settings, valkey_client=None
            )


class OAuthProfileNormalizationTestCase(unittest.TestCase):
    """Test cases for OAuth profile normalization."""

    def test_normalize_google_profile(self) -> None:
        """Test normalizing Google OAuth profile."""
        raw_profile = {
            'id': '12345',
            'email': 'user@example.com',
            'verified_email': True,
            'name': 'Test User',
            'picture': 'https://example.com/avatar.jpg',
        }

        normalized = oauth.normalize_oauth_profile('google', raw_profile)

        self.assertEqual(normalized['id'], '12345')
        self.assertEqual(normalized['email'], 'user@example.com')
        self.assertTrue(normalized['email_verified'])
        self.assertEqual(normalized['name'], 'Test User')
        self.assertEqual(
            normalized['avatar_url'], 'https://example.com/avatar.jpg'
        )

    def test_normalize_google_profile_unverified_email(self) -> None:
        """Google profile without verified_email returns False."""
        raw_profile = {
            'id': '12345',
            'email': 'user@example.com',
            'name': 'Test User',
        }
        normalized = oauth.normalize_oauth_profile('google', raw_profile)
        self.assertFalse(normalized['email_verified'])

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
        self.assertTrue(normalized['email_verified'])
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
            'email_verified': True,
            'name': 'Test User',
            'picture': 'https://example.com/avatar.jpg',
        }

        normalized = oauth.normalize_oauth_profile('oidc', raw_profile)

        self.assertEqual(normalized['id'], 'oidc-user-123')
        self.assertEqual(normalized['email'], 'user@example.com')
        self.assertTrue(normalized['email_verified'])
        self.assertEqual(normalized['name'], 'Test User')
        self.assertEqual(
            normalized['avatar_url'], 'https://example.com/avatar.jpg'
        )

    def test_normalize_oidc_profile_unverified_email(self) -> None:
        """OIDC profile without email_verified claim returns False."""
        raw_profile = {
            'sub': 'oidc-user-123',
            'email': 'user@example.com',
            'name': 'Test User',
        }
        normalized = oauth.normalize_oauth_profile('oidc', raw_profile)
        self.assertFalse(normalized['email_verified'])

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
        """Clear cache and short-circuit SSRF validation for fake hostnames.

        ``_validate_external_url`` does a real DNS lookup, which fails
        for ``*.example.com`` fixtures used here. The standalone
        ``URLValidationTestCase`` below exercises the validator itself.
        """
        oauth._oidc_discovery_cache.clear()
        self._validate_patcher = mock.patch(
            'imbi_api.auth.oauth._validate_external_url',
            new=mock.AsyncMock(return_value=None),
        )
        self._validate_mock = self._validate_patcher.start()
        self.addCleanup(self._validate_patcher.stop)

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

        # SSRF defense was invoked on the happy path; removal would fail
        # this test rather than silently disabling the hook.
        self._validate_mock.assert_awaited()

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

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_discover_oidc_cache_is_bounded(
        self, mock_client_class: mock.Mock
    ) -> None:
        """Test that the OIDC discovery cache evicts oldest entries."""
        fresh = {
            'token_endpoint': 'https://new.example.com/token',
            'userinfo_endpoint': 'https://new.example.com/userinfo',
        }
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = fresh
        mock_client = mock.AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        # Pre-load the cache with one more than the max so the next
        # successful discovery has to evict.
        max_entries = oauth._OIDC_CACHE_MAX_ENTRIES
        for i in range(max_entries):
            oauth._oidc_discovery_cache[f'https://idp-{i}.example.com'] = (
                {'token_endpoint': 't', 'userinfo_endpoint': 'u'},
                time.time() - (max_entries - i),  # idp-0 is the oldest
            )
        self.assertEqual(len(oauth._oidc_discovery_cache), max_entries)

        await oauth._discover_oidc_endpoints('https://new.example.com')

        self.assertEqual(len(oauth._oidc_discovery_cache), max_entries)
        # The oldest pre-loaded entry should have been evicted.
        self.assertNotIn(
            'https://idp-0.example.com', oauth._oidc_discovery_cache
        )
        self.assertIn('https://new.example.com', oauth._oidc_discovery_cache)


class _DBProviderTestBase(unittest.IsolatedAsyncioTestCase):
    """Base class for tests that need a stub DB returning provider rows."""

    def setUp(self) -> None:
        oauth._oidc_discovery_cache.clear()
        login_providers.invalidate_cache()
        self.providers_by_slug: dict[str, login_providers.LoginApp | None] = {}
        self.db = mock.AsyncMock()

        async def _fake_get(
            db: typing.Any, slug: str
        ) -> login_providers.LoginApp | None:
            return self.providers_by_slug.get(slug)

        async def _fake_list(
            db: typing.Any, *, enabled_only: bool = False
        ) -> list[login_providers.LoginApp]:
            rows = [p for p in self.providers_by_slug.values() if p]
            if enabled_only:
                rows = [r for r in rows if r.status == 'active']
            return rows

        self._patch = mock.patch.multiple(
            login_providers,
            get_login_app=_fake_get,
            list_login_apps=_fake_list,
        )
        self._patch.start()
        self._validate_patcher = mock.patch(
            'imbi_api.auth.oauth._validate_external_url',
            new=mock.AsyncMock(return_value=None),
        )
        self._validate_mock = self._validate_patcher.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._validate_patcher.stop()

    def seed(self, slug: str, **kwargs: typing.Any) -> None:
        self.providers_by_slug[slug] = _stub_provider(slug, **kwargs)


class OAuthProviderConfigTestCase(_DBProviderTestBase):
    """Test cases for OAuth provider configuration."""

    async def test_get_provider_config_google(self) -> None:
        self.seed(
            'google',
            client_id='test-client-id',
            client_secret='test-client-secret',
        )
        with _patch_encryptor():
            (
                token_url,
                client_id,
                client_secret,
            ) = await oauth._get_provider_config('google', self.db)
        self.assertEqual(token_url, 'https://oauth2.googleapis.com/token')
        self.assertEqual(client_id, 'test-client-id')
        self.assertEqual(client_secret, 'test-client-secret')

    async def test_get_provider_config_github(self) -> None:
        self.seed(
            'github',
            client_id='github-client-id',
            client_secret='github-client-secret',
        )
        with _patch_encryptor():
            (
                token_url,
                client_id,
                client_secret,
            ) = await oauth._get_provider_config('github', self.db)
        self.assertEqual(
            token_url, 'https://github.com/login/oauth/access_token'
        )
        self.assertEqual(client_id, 'github-client-id')
        self.assertEqual(client_secret, 'github-client-secret')

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_get_provider_config_oidc(
        self, mock_client_class: mock.Mock
    ) -> None:
        self.seed(
            'oidc',
            client_id='oidc-client-id',
            client_secret='oidc-client-secret',
            issuer_url='https://auth.example.com',
        )
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'issuer': 'https://auth.example.com',
            'token_endpoint': 'https://auth.example.com/oauth/token',
            'userinfo_endpoint': 'https://auth.example.com/userinfo',
            'authorization_endpoint': 'https://auth.example.com/authorize',
        }
        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock()
        mock_client_class.return_value = mock_client

        with _patch_encryptor():
            (
                token_url,
                client_id,
                client_secret,
            ) = await oauth._get_provider_config('oidc', self.db)

        self.assertEqual(token_url, 'https://auth.example.com/oauth/token')
        self.assertEqual(client_id, 'oidc-client-id')
        self.assertEqual(client_secret, 'oidc-client-secret')

        # SSRF defense was invoked on the happy path; removal would fail
        # this test rather than silently disabling the hook.
        self._validate_mock.assert_awaited()

    async def test_get_provider_config_disabled(self) -> None:
        self.seed('google', enabled=False)
        with self.assertRaises(ValueError) as context:
            await oauth._get_provider_config('google', self.db)
        self.assertIn('not enabled', str(context.exception).lower())

    async def test_get_provider_config_missing(self) -> None:
        with self.assertRaises(ValueError) as context:
            await oauth._get_provider_config('google', self.db)
        self.assertIn('not enabled', str(context.exception).lower())

    async def test_get_provider_config_unsupported(self) -> None:
        with self.assertRaises(ValueError) as context:
            await oauth._get_provider_config('unsupported', self.db)
        self.assertIn('not enabled', str(context.exception).lower())

    async def test_get_provider_config_oidc_missing_issuer(self) -> None:
        self.seed('oidc', client_id='x', client_secret='y', issuer_url=None)
        with _patch_encryptor():
            with self.assertRaises(ValueError) as context:
                await oauth._get_provider_config('oidc', self.db)
        self.assertIn('issuer', str(context.exception).lower())


class OAuthUserinfoUrlTestCase(_DBProviderTestBase):
    """Test cases for getting userinfo URLs."""

    async def test_get_userinfo_url_google(self) -> None:
        self.seed('google')
        url = await oauth._get_userinfo_url('google', self.db)
        self.assertEqual(url, 'https://www.googleapis.com/oauth2/v2/userinfo')

    async def test_get_userinfo_url_github(self) -> None:
        self.seed('github')
        url = await oauth._get_userinfo_url('github', self.db)
        self.assertEqual(url, 'https://api.github.com/user')

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_get_userinfo_url_oidc(
        self, mock_client_class: mock.Mock
    ) -> None:
        self.seed('oidc', issuer_url='https://auth.example.com')
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'issuer': 'https://auth.example.com',
            'token_endpoint': 'https://auth.example.com/oauth/token',
            'userinfo_endpoint': 'https://auth.example.com/userinfo',
        }
        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock()
        mock_client_class.return_value = mock_client

        url = await oauth._get_userinfo_url('oidc', self.db)
        self.assertEqual(url, 'https://auth.example.com/userinfo')

    async def test_get_userinfo_url_oidc_missing_issuer(self) -> None:
        self.seed('oidc', issuer_url=None)
        with self.assertRaises(ValueError) as context:
            await oauth._get_userinfo_url('oidc', self.db)
        self.assertIn('issuer', str(context.exception).lower())

    async def test_get_userinfo_url_unsupported(self) -> None:
        with self.assertRaises(ValueError) as context:
            await oauth._get_userinfo_url('unsupported', self.db)
        self.assertIn('not enabled', str(context.exception).lower())


class OAuthTokenExchangeTestCase(_DBProviderTestBase):
    """Test cases for OAuth token exchange."""

    def setUp(self) -> None:
        super().setUp()
        self.seed(
            'google',
            client_id='test-client-id',
            client_secret='test-client-secret',
        )

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_exchange_oauth_code_success(
        self, mock_client_class: mock.Mock
    ) -> None:
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'access_token': 'test-access-token',
            'refresh_token': 'test-refresh-token',
            'expires_in': 3600,
        }
        mock_client = mock.AsyncMock()
        mock_client.post = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock()
        mock_client_class.return_value = mock_client

        with _patch_encryptor():
            tokens = await oauth.exchange_oauth_code(
                'google',
                'test-auth-code',
                'http://localhost:8000/auth/oauth/google/callback',
                self.db,
            )

        self.assertEqual(tokens['access_token'], 'test-access-token')
        self.assertEqual(tokens['refresh_token'], 'test-refresh-token')
        self.assertEqual(tokens['expires_in'], 3600)
        mock_client.post.assert_called_once()


class OAuthProfileFetchTestCase(_DBProviderTestBase):
    """Test cases for OAuth profile fetching."""

    def setUp(self) -> None:
        super().setUp()
        self.seed('google')

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_fetch_oauth_profile_success(
        self, mock_client_class: mock.Mock
    ) -> None:
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'id': '12345',
            'email': 'user@example.com',
            'name': 'Test User',
            'picture': 'https://example.com/avatar.jpg',
        }
        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock()
        mock_client_class.return_value = mock_client

        profile = await oauth.fetch_oauth_profile(
            'google', 'test-access-token', self.db
        )

        self.assertEqual(profile['id'], '12345')
        self.assertEqual(profile['email'], 'user@example.com')
        self.assertEqual(profile['name'], 'Test User')

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_exchange_oauth_code_failure(
        self, mock_client_class: mock.Mock
    ) -> None:
        mock_response = mock.Mock()
        mock_response.status_code = 400
        mock_response.text = 'invalid_grant'
        mock_client = mock.AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        with mock.patch.object(
            oauth,
            '_get_provider_config',
            return_value=(
                'https://token-url.com',
                'client-id',
                'secret',
            ),
        ):
            with self.assertRaises(ValueError) as context:
                await oauth.exchange_oauth_code(
                    'google',
                    'bad-code',
                    'http://localhost/callback',
                    self.db,
                )
            self.assertIn(
                'token exchange failed', str(context.exception).lower()
            )

    @mock.patch('imbi_api.auth.oauth.httpx.AsyncClient')
    async def test_fetch_oauth_profile_failure(
        self, mock_client_class: mock.Mock
    ) -> None:
        mock_response = mock.Mock()
        mock_response.status_code = 401
        mock_response.text = 'Unauthorized'
        mock_client = mock.AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        with mock.patch.object(
            oauth, '_get_userinfo_url', return_value='https://userinfo-url.com'
        ):
            with self.assertRaises(ValueError) as context:
                await oauth.fetch_oauth_profile('google', 'bad-token', self.db)
            self.assertIn(
                'profile fetch failed', str(context.exception).lower()
            )

    def test_normalize_oidc_profile_missing_identity(self) -> None:
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
        self.seed('github', enabled=False)
        with self.assertRaises(ValueError) as context:
            await oauth._get_provider_config('github', self.db)
        self.assertIn('not enabled', str(context.exception).lower())

    async def test_get_provider_config_oidc_disabled(self) -> None:
        self.seed('oidc', enabled=False)
        with self.assertRaises(ValueError) as context:
            await oauth._get_provider_config('oidc', self.db)
        self.assertIn('not enabled', str(context.exception).lower())


class URLValidationTestCase(unittest.IsolatedAsyncioTestCase):
    """H2: SSRF defense around OIDC/OAuth URL fetches."""

    async def test_rejects_non_https_scheme(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await oauth._validate_external_url(
                'http://auth.example.com', field='issuer'
            )
        self.assertIn('https://', str(ctx.exception))

    async def test_rejects_missing_hostname(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await oauth._validate_external_url('https://', field='issuer')
        self.assertIn('hostname', str(ctx.exception))

    async def test_rejects_loopback(self) -> None:
        with mock.patch(
            'imbi_api.auth.oauth.socket.getaddrinfo',
            return_value=[
                (0, 0, 0, '', ('127.0.0.1', 0)),
            ],
        ):
            with self.assertRaises(ValueError) as ctx:
                await oauth._validate_external_url(
                    'https://localhost-aliased.example', field='issuer'
                )
        self.assertIn('non-public', str(ctx.exception))

    async def test_rejects_link_local(self) -> None:
        with mock.patch(
            'imbi_api.auth.oauth.socket.getaddrinfo',
            return_value=[
                (0, 0, 0, '', ('169.254.169.254', 0)),
            ],
        ):
            with self.assertRaises(ValueError) as ctx:
                await oauth._validate_external_url(
                    'https://metadata.attacker.example', field='issuer'
                )
        self.assertIn('non-public', str(ctx.exception))

    async def test_rejects_rfc1918(self) -> None:
        for private_ip in ('10.0.0.1', '172.16.0.1', '192.168.1.1'):
            with mock.patch(
                'imbi_api.auth.oauth.socket.getaddrinfo',
                return_value=[
                    (0, 0, 0, '', (private_ip, 0)),
                ],
            ):
                with self.assertRaises(ValueError) as ctx:
                    await oauth._validate_external_url(
                        'https://internal.attacker.example', field='issuer'
                    )
            self.assertIn(
                'non-public', str(ctx.exception), f'failed for {private_ip}'
            )

    async def test_rejects_ipv6_loopback(self) -> None:
        with mock.patch(
            'imbi_api.auth.oauth.socket.getaddrinfo',
            return_value=[
                (0, 0, 0, '', ('::1', 0, 0, 0)),
            ],
        ):
            with self.assertRaises(ValueError) as ctx:
                await oauth._validate_external_url(
                    'https://v6.attacker.example', field='issuer'
                )
        self.assertIn('non-public', str(ctx.exception))

    async def test_rejects_unresolvable_host(self) -> None:
        import socket as _socket

        with mock.patch(
            'imbi_api.auth.oauth.socket.getaddrinfo',
            side_effect=_socket.gaierror('no such host'),
        ):
            with self.assertRaises(ValueError) as ctx:
                await oauth._validate_external_url(
                    'https://nope.example.invalid', field='issuer'
                )
        self.assertIn('does not resolve', str(ctx.exception))

    async def test_allows_public_address(self) -> None:
        with mock.patch(
            'imbi_api.auth.oauth.socket.getaddrinfo',
            return_value=[
                (0, 0, 0, '', ('8.8.8.8', 0)),
            ],
        ):
            await oauth._validate_external_url(
                'https://auth.example.com', field='issuer'
            )

    async def test_dev_escape_hatch_skips_validation(self) -> None:
        with mock.patch.dict(
            'os.environ',
            {'IMBI_OAUTH_ALLOW_INSECURE_URLS': 'true'},
            clear=False,
        ):
            await oauth._validate_external_url(
                'http://localhost:9000', field='issuer'
            )

    async def test_rejects_one_bad_ip_in_multi_result(self) -> None:
        """If any resolved IP is private, fail closed."""
        with mock.patch(
            'imbi_api.auth.oauth.socket.getaddrinfo',
            return_value=[
                (0, 0, 0, '', ('8.8.8.8', 0)),
                (0, 0, 0, '', ('127.0.0.1', 0)),
            ],
        ):
            with self.assertRaises(ValueError) as ctx:
                await oauth._validate_external_url(
                    'https://dns-rebinding.example', field='issuer'
                )
        self.assertIn('non-public', str(ctx.exception))

    async def test_rejects_multicast_reserved_and_unspecified(self) -> None:
        """Multicast, reserved, and unspecified IP categories fail closed."""
        for blocked_ip in ('224.0.0.1', '240.0.0.1', '0.0.0.0'):
            with self.subTest(blocked_ip=blocked_ip):
                with mock.patch(
                    'imbi_api.auth.oauth.socket.getaddrinfo',
                    return_value=[(0, 0, 0, '', (blocked_ip, 0))],
                ):
                    with self.assertRaises(ValueError) as ctx:
                        await oauth._validate_external_url(
                            'https://blocked.example', field='issuer'
                        )
                self.assertIn('non-public', str(ctx.exception))

    async def test_dev_escape_hatch_does_not_bypass_non_localhost(
        self,
    ) -> None:
        """Escape hatch must only short-circuit ``localhost``-style hosts.

        For any other hostname the regular scheme/IP-range checks still
        apply even when ``IMBI_OAUTH_ALLOW_INSECURE_URLS`` is set.
        """
        with mock.patch.dict(
            'os.environ',
            {'IMBI_OAUTH_ALLOW_INSECURE_URLS': 'true'},
            clear=False,
        ):
            with self.assertRaises(ValueError) as ctx:
                await oauth._validate_external_url(
                    'http://auth.example.com', field='issuer'
                )
        self.assertIn('https://', str(ctx.exception))
