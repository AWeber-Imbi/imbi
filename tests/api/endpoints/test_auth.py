import datetime
import typing
import unittest
from unittest import mock

import jwt
import pydantic
from fastapi import testclient
from imbi_common import graph

from imbi_api import app, settings
from imbi_api.auth import local_auth, login_providers
from imbi_api.auth import models as auth_models
from imbi_api.domain import models as domain_models
from imbi_api.middleware import rate_limit


def _stub_provider(
    slug: str,
    *,
    enabled: bool = True,
    client_id: str | None = None,
    client_secret: str | None = None,
    issuer_url: str | None = None,
    name: str | None = None,
    icon: str | None = None,
    allowed_domains: list[str] | None = None,
) -> login_providers.LoginApp:
    names = {'google': 'Google', 'github': 'GitHub', 'oidc': 'OIDC'}
    return login_providers.LoginApp(
        slug=slug,
        name=name or names.get(slug, slug),
        oauth_app_type=slug,  # type: ignore[arg-type]
        client_id=client_id,
        client_secret_encrypted=client_secret,
        issuer_url=issuer_url,
        allowed_domains=allowed_domains or [],
        scopes=[],
        status='active' if enabled else 'inactive',
        callback_url=f'http://localhost:8000/auth/oauth/{slug}/callback',
    )


def _patch_providers(
    rows: list[login_providers.LoginApp],
) -> typing.Any:
    """Stub the login_providers repository helpers for endpoint tests."""
    by_slug = {r.slug: r for r in rows}

    async def fake_list(
        db: typing.Any, *, enabled_only: bool = False
    ) -> list[login_providers.LoginApp]:
        if enabled_only:
            return [r for r in rows if r.status == 'active']
        return list(rows)

    async def fake_get(
        db: typing.Any, slug: str
    ) -> login_providers.LoginApp | None:
        return by_slug.get(slug)

    return mock.patch.multiple(
        login_providers,
        list_login_apps=fake_list,
        get_login_app=fake_get,
    )


class AuthProvidersEndpointTestCase(unittest.TestCase):
    """Test cases for GET /auth/providers endpoint."""

    def setUp(self) -> None:
        """Set up test client and mock settings."""
        settings._auth_settings = None
        self.test_app = app.create_app()
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )
        self.client = testclient.TestClient(self.test_app)
        login_providers.invalidate_cache()
        local_auth._invalidate_cache()
        # Default: no LocalAuthConfig row -> enabled by default
        self.mock_db.match.return_value = []

    def tearDown(self) -> None:
        settings._auth_settings = None
        login_providers.invalidate_cache()
        local_auth._invalidate_cache()

    def test_get_providers_default_config(self) -> None:
        with _patch_providers([]):
            response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['default_redirect'], '/dashboard')
        self.assertEqual(len(data['providers']), 1)
        local_provider = data['providers'][0]
        self.assertEqual(local_provider['id'], 'local')
        self.assertEqual(local_provider['type'], 'password')
        self.assertEqual(local_provider['icon'], 'lock')

    def test_get_providers_google_enabled(self) -> None:
        with _patch_providers([_stub_provider('google')]):
            response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['providers']), 2)
        google = next(p for p in data['providers'] if p['id'] == 'google')
        self.assertEqual(google['type'], 'oauth')
        self.assertEqual(google['auth_url'], '/auth/oauth/google')
        self.assertEqual(google['icon'], 'si-google')

    def test_get_providers_github_enabled(self) -> None:
        with _patch_providers([_stub_provider('github')]):
            response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['providers']), 2)
        github = next(p for p in data['providers'] if p['id'] == 'github')
        self.assertEqual(github['auth_url'], '/auth/oauth/github')
        self.assertEqual(github['icon'], 'si-github')

    def test_get_providers_oidc_enabled(self) -> None:
        with _patch_providers([_stub_provider('oidc', name='Custom OIDC')]):
            response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['providers']), 2)
        oidc = next(p for p in data['providers'] if p['id'] == 'oidc')
        self.assertEqual(oidc['name'], 'Custom OIDC')
        self.assertEqual(oidc['icon'], 'key-round')

    def test_get_providers_all_enabled(self) -> None:
        with _patch_providers(
            [
                _stub_provider('google'),
                _stub_provider('github'),
                _stub_provider('oidc'),
            ]
        ):
            response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            {p['id'] for p in data['providers']},
            {'local', 'google', 'github', 'oidc'},
        )

    def test_get_providers_local_auth_disabled(self) -> None:
        # DB returns a disabled LocalAuthConfig row
        self.mock_db.match.return_value = [
            domain_models.LocalAuthConfig(enabled=False),
        ]
        with _patch_providers([]):
            response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['providers']), 0)

    def test_get_providers_response_model(self) -> None:
        with _patch_providers([]):
            response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)
        providers_response = auth_models.AuthProvidersResponse(
            **response.json()
        )
        self.assertIsInstance(
            providers_response, auth_models.AuthProvidersResponse
        )


class OAuthFlowTestCase(unittest.TestCase):
    """Test cases for OAuth login flow endpoints."""

    def setUp(self) -> None:
        """Set up test client."""
        settings._auth_settings = None
        self.test_app = app.create_app()

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)

    def tearDown(self) -> None:
        """Reset settings singleton after tests."""
        settings._auth_settings = None

    def test_oauth_login_invalid_provider(self) -> None:
        """Test OAuth login with unknown provider slug."""
        with _patch_providers([]):
            response = self.client.get('/auth/oauth/invalid')
        self.assertEqual(response.status_code, 404)
        self.assertIn(
            'Invalid provider',
            response.json()['detail'],
        )

    def test_oauth_login_disabled_provider(self) -> None:
        """Test OAuth login with disabled provider."""
        with _patch_providers([_stub_provider('google', enabled=False)]):
            response = self.client.get('/auth/oauth/google')
        self.assertEqual(response.status_code, 404)
        self.assertIn(
            'Invalid provider',
            response.json()['detail'],
        )

    def test_oauth_login_google_redirect(self) -> None:
        """Test OAuth login redirects to Google."""
        with _patch_providers([_stub_provider('google', client_id='test-id')]):
            response = self.client.get(
                '/auth/oauth/google',
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 307)
        location = response.headers['location']
        self.assertIn('accounts.google.com/o/oauth2/v2/auth', location)
        self.assertIn('client_id=test-id', location)
        self.assertIn('response_type=code', location)
        self.assertIn('state=', location)

    def test_oauth_login_github_redirect(self) -> None:
        """Test OAuth login redirects to GitHub."""
        with _patch_providers(
            [_stub_provider('github', client_id='github-id')]
        ):
            response = self.client.get(
                '/auth/oauth/github',
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 307)
        location = response.headers['location']
        self.assertIn('github.com/login/oauth/authorize', location)
        self.assertIn('client_id=github-id', location)

    def test_oauth_callback_error_handling(self) -> None:
        """Test OAuth callback handles provider errors."""
        url = (
            '/auth/oauth/google/callback'
            '?error=access_denied'
            '&error_description=User denied'
        )
        response = self.client.get(
            url,
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 307)

        location = response.headers['location']
        self.assertIn('error=access_denied', location)

    def test_oauth_callback_missing_code(self) -> None:
        """Test OAuth callback with missing code."""
        url = '/auth/oauth/google/callback?state=test-state'
        response = self.client.get(
            url,
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 307)
        location = response.headers['location']
        self.assertIn(
            'error=authentication_failed',
            location,
        )

    def test_oauth_callback_missing_state(self) -> None:
        """Test OAuth callback with missing state."""
        url = '/auth/oauth/google/callback?code=test-code'
        response = self.client.get(
            url,
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 307)
        location = response.headers['location']
        self.assertIn(
            'error=authentication_failed',
            location,
        )

    def test_oauth_login_oidc_redirect(self) -> None:
        """Test OAuth login redirects to OIDC."""
        with _patch_providers(
            [
                _stub_provider(
                    'oidc',
                    client_id='oidc-id',
                    issuer_url='https://auth.example.com',
                )
            ]
        ):
            response = self.client.get(
                '/auth/oauth/oidc',
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 307)
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
        self.test_app = app.create_app()

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)
        rate_limit.limiter.reset()

    def tearDown(self) -> None:
        """Reset settings singleton after tests."""
        settings._auth_settings = None

    def test_login_with_password_rehash(self) -> None:
        """Test login rehashes password if needed."""
        from imbi_api import models

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash='old-hash-format',
            created_at=datetime.datetime.now(datetime.UTC),
        )

        # db.match returns user
        self.mock_db.match.return_value = [test_user]
        # db.execute is called for the MFA/TOTP check (no TOTP -> [])
        # and for the atomic MATCH/CREATE inside issue_token_pair that
        # both persists token metadata and returns principal_count.
        self.mock_db.execute.side_effect = [
            [],
            [{'principal_count': 1}],
        ]
        # db.merge returns None (void)
        self.mock_db.merge.return_value = None

        with (
            mock.patch(
                'imbi_api.auth.password.verify_password',
                return_value=True,
            ),
            mock.patch(
                'imbi_api.auth.password.needs_rehash',
                return_value=True,
            ) as mock_needs_rehash,
            mock.patch(
                'imbi_api.auth.password.hash_password',
                return_value='new-hashed-password',
            ) as mock_hash,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.post(
                '/auth/login',
                json={
                    'email': 'test@example.com',
                    'password': 'password123',
                },
            )

            self.assertEqual(response.status_code, 200)
            mock_needs_rehash.assert_called_once()
            mock_hash.assert_called_once_with('password123')
            # Verify merge was called (for rehash + tokens)
            self.assertTrue(
                self.mock_db.merge.called,
            )


class LoginMFATestCase(unittest.TestCase):
    """Test MFA integration in login endpoint."""

    def setUp(self) -> None:
        """Set up test client."""
        settings._auth_settings = None
        self.test_app = app.create_app()

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)
        rate_limit.limiter.reset()

        # Mock encryption for MFA tests
        from imbi_common.auth.encryption import TokenEncryption

        mock_encryptor = mock.Mock()
        mock_encryptor.decrypt = mock.Mock(
            side_effect=lambda x: x,
        )
        mock_encryptor.encrypt = mock.Mock(
            side_effect=lambda x: x,
        )

        self.encryption_patcher = mock.patch.object(
            TokenEncryption,
            'get_instance',
            return_value=mock_encryptor,
        )
        self.encryption_patcher.start()

    def tearDown(self) -> None:
        """Reset settings singleton after tests."""
        self.encryption_patcher.stop()
        settings._auth_settings = None

    def test_login_mfa_required_no_code(self) -> None:
        """Test login with MFA enabled but no code."""
        from imbi_api import models
        from imbi_api.auth import password

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=password.hash_password('password123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        totp_data = {
            'secret': 'JBSWY3DPEHPK3PXP',
            'enabled': True,
            'backup_codes': [],
        }

        self.mock_db.match.return_value = [test_user]
        # TOTP query returns enabled MFA
        self.mock_db.execute.return_value = [
            {'n': totp_data},
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/auth/login',
                json={
                    'email': 'test@example.com',
                    'password': 'password123',
                },
            )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()['detail'],
                'MFA code required',
            )
            self.assertEqual(
                response.headers.get('X-MFA-Required'),
                'true',
            )

    def test_login_mfa_valid_totp(self) -> None:
        """Test login with valid TOTP code."""
        import pyotp

        from imbi_api import models
        from imbi_api.auth import password

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=password.hash_password('password123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        secret = 'JBSWY3DPEHPK3PXP'
        totp = pyotp.TOTP(secret)
        valid_code = totp.now()

        totp_data = {
            'secret': secret,
            'enabled': True,
            'backup_codes': [],
        }

        self.mock_db.match.return_value = [test_user]
        # execute(): TOTP fetch, TOTP last_used update, then the
        # atomic MATCH/CREATE inside issue_token_pair that returns
        # principal_count.
        self.mock_db.execute.side_effect = [
            [{'n': totp_data}],
            [],
            [{'principal_count': 1}],
        ]
        self.mock_db.merge.return_value = None

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
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
        from imbi_api import models
        from imbi_api.auth import password

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=password.hash_password('password123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        backup_code = 'backup123'
        hashed_backup = password.hash_password(backup_code)

        totp_data = {
            'secret': 'JBSWY3DPEHPK3PXP',
            'enabled': True,
            'backup_codes': [hashed_backup, 'other-hash'],
        }

        self.mock_db.match.return_value = [test_user]
        # execute(): TOTP fetch, backup_codes update, then the atomic
        # MATCH/CREATE inside issue_token_pair that returns
        # principal_count.
        self.mock_db.execute.side_effect = [
            [{'n': totp_data}],
            [],
            [{'principal_count': 1}],
        ]
        self.mock_db.merge.return_value = None

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
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
        from imbi_api import models
        from imbi_api.auth import password

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=password.hash_password('password123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        totp_data = {
            'secret': 'JBSWY3DPEHPK3PXP',
            'enabled': True,
            'backup_codes': [],
        }

        self.mock_db.match.return_value = [test_user]
        self.mock_db.execute.return_value = [
            {'n': totp_data},
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/auth/login',
                json={
                    'email': 'test@example.com',
                    'password': 'password123',
                    'mfa_code': '000000',
                },
            )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()['detail'],
                'Invalid MFA code',
            )

    def test_login_user_not_found(self) -> None:
        """Test login with user not found."""
        self.mock_db.match.return_value = []

        response = self.client.post(
            '/auth/login',
            json={
                'email': 'nonexistent@example.com',
                'password': 'password123',
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn(
            'Invalid credentials',
            response.json()['detail'],
        )

    def test_login_oauth_only_user(self) -> None:
        """Test login for OAuth-only user (no password)."""
        from imbi_api import models

        oauth_user = models.User(
            email='oauth@example.com',
            display_name='OAuth User',
            is_active=True,
            password_hash=None,
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
        self.assertIn(
            'Password authentication not available',
            response.json()['detail'],
        )

    def test_login_invalid_password(self) -> None:
        """Test login with invalid password."""
        from imbi_api import models
        from imbi_api.auth import password

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=password.hash_password('correctpassword'),
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.mock_db.match.return_value = [test_user]

        response = self.client.post(
            '/auth/login',
            json={
                'email': 'test@example.com',
                'password': 'wrongpassword',
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn(
            'Invalid credentials',
            response.json()['detail'],
        )


class OAuthCallbackSuccessTestCase(unittest.TestCase):
    """Test OAuth callback success path."""

    def setUp(self) -> None:
        """Set up test client."""
        settings._auth_settings = None
        self.test_app = app.create_app()

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)

    def tearDown(self) -> None:
        """Reset settings singleton after tests."""
        settings._auth_settings = None

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_OAUTH_GOOGLE_ENABLED': 'true',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_ID': 'test-id',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_SECRET': ('test-secret'),
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
        },
    )
    def test_oauth_callback_success_existing_identity(
        self,
    ) -> None:
        """Test OAuth callback with existing identity."""
        from imbi_common.auth import encryption

        from imbi_api import models

        settings._auth_settings = None
        encryption.TokenEncryption.reset_instance()

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
            avatar_url=pydantic.HttpUrl('https://example.com/avatar.jpg'),
            access_token='encrypted-access-token',
            refresh_token='encrypted-refresh-token',
            token_expires_at=(
                datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(hours=1)
            ),
            linked_at=datetime.datetime.now(datetime.UTC),
            last_used=datetime.datetime.now(datetime.UTC),
            raw_profile={
                'id': 'google-123',
                'name': 'Test User',
            },
            user=test_user,
        )

        mock_state_data = auth_models.OAuthStateData(
            provider='google',
            redirect_uri='/dashboard',
            nonce='test-nonce',
            timestamp=int(
                datetime.datetime.now(
                    datetime.UTC,
                ).timestamp()
            ),
        )

        mock_token_response = {
            'access_token': 'google-access-token',
            'refresh_token': 'google-refresh-token',
            'expires_in': 3600,
        }

        mock_profile = {
            'id': 'google-123',
            'email': 'test@example.com',
            'name': 'Test User',
            'avatar_url': 'https://example.com/avatar.jpg',
        }

        # db.match returns identity, then user data
        self.mock_db.match.return_value = [test_identity]
        self.mock_db.merge.return_value = None
        # For user query after identity found
        user_data = {
            'email': 'test@example.com',
            'display_name': 'Test User',
            'is_active': True,
            'password_hash': None,
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ).isoformat(),
        }
        # execute(): SET tokens on the existing identity, user fetch,
        # the atomic MATCH/CREATE inside issue_token_pair
        # (principal_count), then the SET last_used update.
        self.mock_db.execute.side_effect = [
            [],
            [{'u': user_data}],
            [{'principal_count': 1}],
            [],
        ]

        with (
            _patch_providers([_stub_provider('google')]),
            mock.patch(
                'imbi_api.auth.oauth.verify_oauth_state',
                return_value=mock_state_data,
            ),
            mock.patch(
                'imbi_api.auth.oauth.exchange_oauth_code',
                return_value=mock_token_response,
            ),
            mock.patch(
                'imbi_api.auth.oauth.fetch_oauth_profile',
                return_value=mock_profile,
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.get(
                '/auth/oauth/google/callback?code=test-code&state=test-state',
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 307)
            location = response.headers['location']
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
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_SECRET': ('test-secret'),
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
            'IMBI_AUTH_OAUTH_AUTO_CREATE_USERS': 'true',
        },
    )
    def test_oauth_callback_success_new_user(self) -> None:
        """Test OAuth callback creating new user."""
        from imbi_common.auth import encryption

        settings._auth_settings = None
        encryption.TokenEncryption.reset_instance()

        mock_state_data = auth_models.OAuthStateData(
            provider='google',
            redirect_uri='/dashboard',
            nonce='test-nonce',
            timestamp=int(
                datetime.datetime.now(
                    datetime.UTC,
                ).timestamp()
            ),
        )

        mock_token_response = {
            'access_token': 'google-access-token',
            'refresh_token': 'google-refresh-token',
            'expires_in': 3600,
        }

        mock_profile = {
            'id': 'google-456',
            'email': 'newuser@example.com',
            'name': 'New User',
            'avatar_url': 'https://example.com/avatar2.jpg',
        }

        # No existing identity or user
        self.mock_db.match.return_value = []
        self.mock_db.merge.return_value = None
        # User query after identity creation
        user_data = {
            'email': 'newuser@example.com',
            'display_name': 'New User',
            'is_active': True,
            'password_hash': None,
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ).isoformat(),
        }
        # execute(): OAUTH_IDENTITY MERGE, user fetch, the atomic
        # MATCH/CREATE inside issue_token_pair (principal_count), then
        # the SET last_used update.
        self.mock_db.execute.side_effect = [
            [],
            [{'u': user_data}],
            [{'principal_count': 1}],
            [],
        ]

        with (
            _patch_providers([_stub_provider('google')]),
            mock.patch(
                'imbi_api.auth.oauth.verify_oauth_state',
                return_value=mock_state_data,
            ),
            mock.patch(
                'imbi_api.auth.oauth.exchange_oauth_code',
                return_value=mock_token_response,
            ),
            mock.patch(
                'imbi_api.auth.oauth.fetch_oauth_profile',
                return_value=mock_profile,
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.get(
                '/auth/oauth/google/callback?code=test-code&state=test-state',
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 307)
            location = response.headers['location']
            self.assertIn('/dashboard#', location)
            self.assertIn('access_token=', location)
            self.assertIn('refresh_token=', location)

            # Verify merge was called for user + identity
            self.assertTrue(self.mock_db.merge.called)

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_OAUTH_GOOGLE_ENABLED': 'true',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_ID': 'test-id',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_SECRET': ('test-secret'),
            'IMBI_AUTH_OAUTH_GOOGLE_ALLOWED_DOMAINS': (
                '["example.com", "test.com"]'
            ),
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
        },
    )
    def test_oauth_callback_google_domain_restriction(
        self,
    ) -> None:
        """Test OAuth callback with domain restriction."""
        from imbi_common.auth import encryption

        settings._auth_settings = None
        encryption.TokenEncryption.reset_instance()

        mock_state_data = auth_models.OAuthStateData(
            provider='google',
            redirect_uri='/dashboard',
            nonce='test-nonce',
            timestamp=int(
                datetime.datetime.now(
                    datetime.UTC,
                ).timestamp()
            ),
        )

        mock_token_response = {
            'access_token': 'google-access-token',
            'expires_in': 3600,
        }

        mock_profile = {
            'id': 'google-789',
            'email': 'user@baddomaindomain.com',
            'name': 'Bad Domain User',
        }

        self.mock_db.match.return_value = []

        with (
            _patch_providers(
                [
                    _stub_provider(
                        'google',
                        allowed_domains=['example.com', 'test.com'],
                    )
                ]
            ),
            mock.patch(
                'imbi_api.auth.oauth.verify_oauth_state',
                return_value=mock_state_data,
            ),
            mock.patch(
                'imbi_api.auth.oauth.exchange_oauth_code',
                return_value=mock_token_response,
            ),
            mock.patch(
                'imbi_api.auth.oauth.fetch_oauth_profile',
                return_value=mock_profile,
            ),
        ):
            response = self.client.get(
                '/auth/oauth/google/callback?code=test-code&state=test-state',
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 307)
            self.assertIn(
                'error=authentication_failed',
                response.headers['location'],
            )

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
            'IMBI_AUTH_OAUTH_AUTO_LINK_BY_EMAIL': 'true',
        },
    )
    def test_oauth_callback_auto_link_existing_user(
        self,
    ) -> None:
        """Test OAuth callback auto-linking to existing user."""
        from imbi_common.auth import encryption

        from imbi_api import models

        settings._auth_settings = None
        encryption.TokenEncryption.reset_instance()

        existing_user = models.User(
            email='existing@example.com',
            display_name='Existing User',
            is_active=True,
            password_hash='existing-hash',
            created_at=datetime.datetime.now(datetime.UTC),
        )

        mock_state_data = auth_models.OAuthStateData(
            provider='google',
            redirect_uri='/dashboard',
            nonce='test-nonce',
            timestamp=int(
                datetime.datetime.now(
                    datetime.UTC,
                ).timestamp()
            ),
        )

        mock_token_response = {
            'access_token': 'google-access-token',
            'expires_in': 3600,
        }

        mock_profile = {
            'id': 'google-999',
            'email': 'existing@example.com',
            'email_verified': True,
            'name': 'Existing User',
        }

        # First match: identity not found
        # Second match: user found by email
        self.mock_db.match.side_effect = [
            [],
            [existing_user],
        ]
        self.mock_db.merge.return_value = None
        # User query after identity creation
        user_data = {
            'email': 'existing@example.com',
            'display_name': 'Existing User',
            'is_active': True,
            'password_hash': 'existing-hash',
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ).isoformat(),
        }
        # execute(): OAUTH_IDENTITY MERGE, user fetch, the atomic
        # MATCH/CREATE inside issue_token_pair (principal_count), then
        # the SET last_used update.
        self.mock_db.execute.side_effect = [
            [],
            [{'u': user_data}],
            [{'principal_count': 1}],
            [],
        ]

        with (
            _patch_providers([_stub_provider('google')]),
            mock.patch(
                'imbi_api.auth.oauth.verify_oauth_state',
                return_value=mock_state_data,
            ),
            mock.patch(
                'imbi_api.auth.oauth.exchange_oauth_code',
                return_value=mock_token_response,
            ),
            mock.patch(
                'imbi_api.auth.oauth.fetch_oauth_profile',
                return_value=mock_profile,
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
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
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
            'IMBI_AUTH_OAUTH_AUTO_LINK_BY_EMAIL': 'true',
        },
    )
    def test_oauth_callback_refuses_auto_link_unverified_email(
        self,
    ) -> None:
        """Auto-link must refuse profiles without email_verified=True."""
        from imbi_common.auth import encryption

        from imbi_api import models

        settings._auth_settings = None
        encryption.TokenEncryption.reset_instance()

        existing_user = models.User(
            email='existing@example.com',
            display_name='Existing User',
            is_active=True,
            password_hash='existing-hash',
            created_at=datetime.datetime.now(datetime.UTC),
        )
        mock_state_data = auth_models.OAuthStateData(
            provider='google',
            redirect_uri='/dashboard',
            nonce='test-nonce',
            timestamp=int(datetime.datetime.now(datetime.UTC).timestamp()),
        )
        mock_token_response = {
            'access_token': 'google-access-token',
            'expires_in': 3600,
        }
        # No email_verified key → falsy → auto-link must be refused.
        mock_profile = {
            'id': 'google-999',
            'email': 'existing@example.com',
            'name': 'Existing User',
        }
        self.mock_db.match.side_effect = [[], [existing_user]]

        with (
            _patch_providers([_stub_provider('google')]),
            mock.patch(
                'imbi_api.auth.oauth.verify_oauth_state',
                return_value=mock_state_data,
            ),
            mock.patch(
                'imbi_api.auth.oauth.exchange_oauth_code',
                return_value=mock_token_response,
            ),
            mock.patch(
                'imbi_api.auth.oauth.fetch_oauth_profile',
                return_value=mock_profile,
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.get(
                '/auth/oauth/google/callback?code=test-code&state=test-state',
                follow_redirects=False,
            )

        # Callback redirects to error URL on failure.
        self.assertEqual(response.status_code, 307)
        location = response.headers['location']
        self.assertIn('error=authentication_failed', location)
        # The auto-link must NOT have run: no merge against the user
        # record, no token issuance (issue_token_pair uses
        # db.execute), no graph writes at all.
        self.mock_db.merge.assert_not_called()
        self.mock_db.execute.assert_not_called()
        self.mock_db.merge.reset_mock()
        self.mock_db.execute.reset_mock()
        # Repeat with email_verified explicitly False to confirm the
        # truthy check (not just absence) gates the link.
        self.mock_db.match.side_effect = [[], [existing_user]]
        mock_profile_explicit = {**mock_profile, 'email_verified': False}
        with (
            _patch_providers([_stub_provider('google')]),
            mock.patch(
                'imbi_api.auth.oauth.verify_oauth_state',
                return_value=mock_state_data,
            ),
            mock.patch(
                'imbi_api.auth.oauth.exchange_oauth_code',
                return_value=mock_token_response,
            ),
            mock.patch(
                'imbi_api.auth.oauth.fetch_oauth_profile',
                return_value=mock_profile_explicit,
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.get(
                '/auth/oauth/google/callback?code=test-code&state=test-state',
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 307)
        self.assertIn(
            'error=authentication_failed', response.headers['location']
        )
        self.mock_db.merge.assert_not_called()
        self.mock_db.execute.assert_not_called()

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_OAUTH_GOOGLE_ENABLED': 'true',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_ID': 'test-id',
            'IMBI_AUTH_OAUTH_GOOGLE_CLIENT_SECRET': ('test-secret'),
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
            'IMBI_AUTH_OAUTH_AUTO_CREATE_USERS': 'false',
        },
    )
    def test_oauth_callback_auto_create_disabled(
        self,
    ) -> None:
        """Test OAuth callback with auto-creation off."""
        from imbi_common.auth import encryption

        settings._auth_settings = None
        encryption.TokenEncryption.reset_instance()

        mock_state_data = auth_models.OAuthStateData(
            provider='google',
            redirect_uri='/dashboard',
            nonce='test-nonce',
            timestamp=int(
                datetime.datetime.now(
                    datetime.UTC,
                ).timestamp()
            ),
        )

        mock_token_response = {
            'access_token': 'google-access-token',
            'expires_in': 3600,
        }

        mock_profile = {
            'id': 'google-111',
            'email': 'newuser@example.com',
            'name': 'New User',
        }

        self.mock_db.match.return_value = []

        with (
            mock.patch(
                'imbi_api.auth.oauth.verify_oauth_state',
                return_value=mock_state_data,
            ),
            mock.patch(
                'imbi_api.auth.oauth.exchange_oauth_code',
                return_value=mock_token_response,
            ),
            mock.patch(
                'imbi_api.auth.oauth.fetch_oauth_profile',
                return_value=mock_profile,
            ),
        ):
            response = self.client.get(
                '/auth/oauth/google/callback?code=test-code&state=test-state',
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 307)
            self.assertIn(
                'error=authentication_failed',
                response.headers['location'],
            )


class TokenRefreshTestCase(unittest.TestCase):
    """Test token refresh endpoint."""

    def setUp(self) -> None:
        """Set up test client."""
        settings._auth_settings = None
        self.test_app = app.create_app()

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)

    def tearDown(self) -> None:
        """Reset settings singleton after tests."""
        settings._auth_settings = None

    def test_refresh_token_success(self) -> None:
        """Test successful token refresh."""
        from imbi_common.auth import core

        from imbi_api import models

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

        refresh_token = core.create_refresh_token(
            test_user.email,
            auth_settings=auth_settings,
        )

        # Token metadata lookup is folded into the atomic revoke, so
        # only the user match remains.
        self.mock_db.match.return_value = [test_user]
        # execute() is called twice: first for the atomic revoke
        # (revoked_count=1 means the row was unrevoked and is now
        # revoked), then for the MATCH/CREATE inside issue_token_pair
        # that persists token metadata and returns principal_count.
        self.mock_db.execute.side_effect = [
            [{'revoked_count': 1}],
            [{'principal_count': 1}],
        ]

        with mock.patch(
            'imbi_api.settings.get_auth_settings',
            return_value=auth_settings,
        ):
            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': refresh_token},
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn('access_token', data)
            self.assertIn('refresh_token', data)
            self.assertNotEqual(
                data['refresh_token'],
                refresh_token,
            )

    def test_refresh_token_expired(self) -> None:
        """Test token refresh with expired token."""
        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
            refresh_token_expire_seconds=1,
        )

        payload = {
            'sub': 'testuser',
            'type': 'refresh',
            'jti': 'test-jti',
            'exp': (
                datetime.datetime.now(datetime.UTC)
                - datetime.timedelta(seconds=10)
            ),
        }
        expired_token = jwt.encode(
            payload,
            auth_settings.jwt_secret,
            algorithm=auth_settings.jwt_algorithm,
        )

        with mock.patch(
            'imbi_api.settings.get_auth_settings',
            return_value=auth_settings,
        ):
            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': expired_token},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn(
                'expired',
                response.json()['detail'].lower(),
            )

    def test_refresh_token_invalid(self) -> None:
        """Test token refresh with invalid token."""
        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        with mock.patch(
            'imbi_api.settings.get_auth_settings',
            return_value=auth_settings,
        ):
            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': 'invalid-token'},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn(
                'Invalid',
                response.json()['detail'],
            )

    def test_refresh_token_wrong_type(self) -> None:
        """Test refresh with access token instead."""
        from imbi_common.auth import core

        from imbi_api import models

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

        access_token = core.create_access_token(
            test_user.email,
            auth_settings=auth_settings,
        )

        with mock.patch(
            'imbi_api.settings.get_auth_settings',
            return_value=auth_settings,
        ):
            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': access_token},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn(
                'type',
                response.json()['detail'].lower(),
            )

    def test_refresh_token_revoked(self) -> None:
        """Test token refresh with revoked token."""
        from imbi_common.auth import core

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        refresh_token = core.create_refresh_token(
            'test@example.com',
            auth_settings=auth_settings,
        )

        # Atomic revoke returns 0 when the token is already revoked
        # (or the jti doesn't match any TokenMetadata vertex).
        self.mock_db.execute.return_value = [{'revoked_count': 0}]

        with mock.patch(
            'imbi_api.settings.get_auth_settings',
            return_value=auth_settings,
        ):
            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': refresh_token},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn(
                'revoked',
                response.json()['detail'].lower(),
            )

    def test_refresh_token_user_inactive(self) -> None:
        """Test token refresh with inactive user."""
        from imbi_common.auth import core

        from imbi_api import models

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=False,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        refresh_token = core.create_refresh_token(
            test_user.email,
            auth_settings=auth_settings,
        )

        # Atomic revoke succeeds (token is valid), then the user
        # match returns the inactive user.
        self.mock_db.match.return_value = [test_user]
        self.mock_db.execute.return_value = [{'revoked_count': 1}]

        with mock.patch(
            'imbi_api.settings.get_auth_settings',
            return_value=auth_settings,
        ):
            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': refresh_token},
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn(
                'inactive',
                response.json()['detail'].lower(),
            )


class LogoutTestCase(unittest.TestCase):
    """Test logout endpoint."""

    def setUp(self) -> None:
        """Set up test client."""

        settings._auth_settings = None
        self.test_app = app.create_app()

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)

        self.auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )

        self.test_user = None  # Set per-test

    def tearDown(self) -> None:
        """Reset settings singleton after tests."""
        settings._auth_settings = None

    def test_logout_single_session(self) -> None:
        """Test logout with revoke_all_sessions=False."""
        from imbi_common.auth import core

        from imbi_api import models
        from imbi_api.auth import permissions

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        access_token = core.create_access_token(
            test_user.email,
            auth_settings=self.auth_settings,
        )
        payload = jwt.decode(
            access_token,
            self.auth_settings.jwt_secret,
            algorithms=[
                self.auth_settings.jwt_algorithm,
            ],
        )
        access_jti = payload['jti']

        mock_auth = permissions.AuthContext(
            user=test_user,
            session_id=access_jti,
            auth_method='jwt',
            permissions=set(),
        )

        async def override_get_current_user():
            return mock_auth

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            override_get_current_user
        )

        # execute returns issued_at for first call
        self.mock_db.execute.side_effect = [
            [],  # revoke current
            [
                {
                    'issued_at': datetime.datetime.now(
                        datetime.UTC,
                    ),
                },
            ],  # get issued_at
            [],  # revoke refresh
        ]

        with (
            mock.patch(
                'imbi_api.settings.get_auth_settings',
                return_value=self.auth_settings,
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.post(
                '/auth/logout',
                headers={
                    'Authorization': (f'Bearer {access_token}'),
                },
            )

            self.assertEqual(response.status_code, 204)
            self.assertGreaterEqual(
                self.mock_db.execute.call_count,
                3,
            )

    def test_logout_all_sessions(self) -> None:
        """Test logout with revoke_all_sessions=True."""
        from imbi_common.auth import core

        from imbi_api import models
        from imbi_api.auth import permissions

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        access_token = core.create_access_token(
            test_user.email,
            auth_settings=self.auth_settings,
        )
        payload = jwt.decode(
            access_token,
            self.auth_settings.jwt_secret,
            algorithms=[
                self.auth_settings.jwt_algorithm,
            ],
        )
        access_jti = payload['jti']

        mock_auth = permissions.AuthContext(
            user=test_user,
            session_id=access_jti,
            auth_method='jwt',
            permissions=set(),
        )

        async def override_get_current_user():
            return mock_auth

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            override_get_current_user
        )

        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_api.settings.get_auth_settings',
            return_value=self.auth_settings,
        ):
            response = self.client.post(
                '/auth/logout?revoke_all_sessions=true',
                headers={
                    'Authorization': (f'Bearer {access_token}'),
                },
            )

            self.assertEqual(response.status_code, 204)
            # revoke current, revoke all, delete sessions
            self.assertEqual(
                self.mock_db.execute.call_count,
                3,
            )


class ServiceAccountAuthTestCase(unittest.TestCase):
    """Test service account authentication guardrails."""

    def setUp(self) -> None:
        """Set up test client and reset singletons."""
        from imbi_api import models

        settings._auth_settings = None
        self.test_app = app.create_app()

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)
        rate_limit.limiter.reset()

        self.sa_user = models.User(
            email='sa@example.com',
            display_name='Service Account User',
            is_active=True,
            is_admin=False,
            is_service_account=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.sa = models.ServiceAccount(
            slug='my-service',
            display_name='My Service',
            is_active=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )

    def tearDown(self) -> None:
        """Reset settings singleton after tests."""
        settings._auth_settings = None

    def test_service_account_blocked_from_password_login(
        self,
    ) -> None:
        """POST /auth/login with SA returns 403."""
        self.mock_db.match.return_value = [self.sa_user]

        response = self.client.post(
            '/auth/login',
            json={
                'email': 'sa@example.com',
                'password': 'SomePass123!@#',
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn(
            'Service accounts cannot use password login',
            response.json()['detail'],
        )

    def test_client_credentials_token_success(self) -> None:
        """POST /auth/token with valid credentials."""
        cred_data = {
            'client_id': 'cc_test123',
            'client_secret_hash': '$argon2id$hashed',
            'revoked': False,
            'expires_at': None,
            'scopes': ['project:read', 'project:write'],
        }
        sa_data = {
            'slug': 'my-service',
            'display_name': 'My Service',
            'is_active': True,
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ).isoformat(),
        }

        # execute(): credential+SA fetch, atomic MATCH/CREATE inside
        # issue_token_pair returning principal_count, then the
        # last_used/last_authenticated update.
        self.mock_db.execute.side_effect = [
            [{'c': cred_data, 's': sa_data}],
            [{'principal_count': 1}],
            [],
        ]

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.auth.password.verify_password',
                return_value=True,
            ),
        ):
            response = self.client.post(
                '/auth/token',
                data={
                    'grant_type': 'client_credentials',
                    'client_id': 'cc_test123',
                    'client_secret': 'secret123',
                    'scope': 'project:read',
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn('access_token', data)
            self.assertIn('refresh_token', data)
            self.assertEqual(
                data['token_type'],
                'bearer',
            )
            self.assertIn('expires_in', data)
            self.assertEqual(
                data['scope'],
                'project:read',
            )

    def test_client_credentials_bad_grant_type(
        self,
    ) -> None:
        """POST /auth/token with wrong grant_type."""
        response = self.client.post(
            '/auth/token',
            data={
                'grant_type': 'authorization_code',
                'client_id': 'cc_test123',
                'client_secret': 'secret123',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'Unsupported grant_type',
            response.json()['detail'],
        )

    def test_client_credentials_invalid_client(
        self,
    ) -> None:
        """POST /auth/token with bad client_id."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/auth/token',
                data={
                    'grant_type': 'client_credentials',
                    'client_id': 'cc_nonexistent',
                    'client_secret': 'secret123',
                },
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn(
                'Invalid client credentials',
                response.json()['detail'],
            )

    def test_client_credentials_revoked(self) -> None:
        """POST /auth/token with revoked credential."""
        cred_data = {
            'client_id': 'cc_revoked',
            'client_secret_hash': '$argon2id$hashed',
            'revoked': True,
            'expires_at': None,
            'scopes': [],
        }
        sa_data = {
            'slug': 'my-service',
            'display_name': 'My Service',
            'is_active': True,
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ).isoformat(),
        }

        self.mock_db.execute.return_value = [
            {'c': cred_data, 's': sa_data},
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/auth/token',
                data={
                    'grant_type': 'client_credentials',
                    'client_id': 'cc_revoked',
                    'client_secret': 'secret123',
                },
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn(
                'revoked',
                response.json()['detail'].lower(),
            )

    def test_client_credentials_expired(self) -> None:
        """POST /auth/token with expired credential."""
        cred_data = {
            'client_id': 'cc_expired',
            'client_secret_hash': '$argon2id$hashed',
            'revoked': False,
            'expires_at': datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
            'scopes': [],
        }
        sa_data = {
            'slug': 'my-service',
            'display_name': 'My Service',
            'is_active': True,
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ).isoformat(),
        }

        self.mock_db.execute.return_value = [
            {'c': cred_data, 's': sa_data},
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/auth/token',
                data={
                    'grant_type': 'client_credentials',
                    'client_id': 'cc_expired',
                    'client_secret': 'secret123',
                },
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn(
                'expired',
                response.json()['detail'].lower(),
            )

    def test_client_credentials_inactive_sa(self) -> None:
        """POST /auth/token with inactive SA returns 401."""
        cred_data = {
            'client_id': 'cc_inactive',
            'client_secret_hash': '$argon2id$hashed',
            'revoked': False,
            'expires_at': None,
            'scopes': [],
        }
        sa_data = {
            'slug': 'inactive-sa',
            'display_name': 'Inactive SA',
            'is_active': False,
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ).isoformat(),
        }

        self.mock_db.execute.return_value = [
            {'c': cred_data, 's': sa_data},
        ]

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.auth.password.verify_password',
                return_value=True,
            ),
        ):
            response = self.client.post(
                '/auth/token',
                data={
                    'grant_type': 'client_credentials',
                    'client_id': 'cc_inactive',
                    'client_secret': 'secret123',
                },
            )

            self.assertEqual(response.status_code, 401)
            self.assertIn(
                'inactive',
                response.json()['detail'].lower(),
            )

    def test_client_credentials_scope_intersection(
        self,
    ) -> None:
        """Requested scopes intersected with cred scopes."""
        cred_data = {
            'client_id': 'cc_scoped',
            'client_secret_hash': '$argon2id$hashed',
            'revoked': False,
            'expires_at': None,
            'scopes': [
                'project:read',
                'project:write',
                'user:read',
            ],
        }
        sa_data = {
            'slug': 'scoped-sa',
            'display_name': 'Scoped SA',
            'is_active': True,
            'created_at': datetime.datetime.now(
                datetime.UTC,
            ).isoformat(),
        }

        # execute(): credential+SA fetch, atomic MATCH/CREATE inside
        # issue_token_pair returning principal_count, then the
        # last_used/last_authenticated update.
        self.mock_db.execute.side_effect = [
            [{'c': cred_data, 's': sa_data}],
            [{'principal_count': 1}],
            [],
        ]

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.auth.password.verify_password',
                return_value=True,
            ),
        ):
            response = self.client.post(
                '/auth/token',
                data={
                    'grant_type': 'client_credentials',
                    'client_id': 'cc_scoped',
                    'client_secret': 'secret123',
                    'scope': ('project:read blueprint:read'),
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(
                data['scope'],
                'project:read',
            )
