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


def _stub_identity_plugin_provider(
    slug: str,
    *,
    plugin_id: str | None = 'plug-1',
    enabled: bool = True,
    name: str | None = None,
) -> login_providers.LoginApp:
    """Build a LoginApp representing an identity-plugin login row."""
    return login_providers.LoginApp(
        slug=slug,
        name=name or slug,
        oauth_app_type='identity_plugin',
        source='identity_plugin',
        plugin_id=plugin_id,
        plugin_slug=slug,
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


class RedactEmailTestCase(unittest.TestCase):
    """Test cases for the _redact_email log helper."""

    def test_keeps_first_char_and_domain(self) -> None:
        from imbi_api.endpoints.auth import _redact_email

        self.assertEqual(
            _redact_email('admin@example.com'), 'a***@example.com'
        )

    def test_handles_single_char_local(self) -> None:
        from imbi_api.endpoints.auth import _redact_email

        self.assertEqual(_redact_email('x@example.com'), 'x***@example.com')

    def test_handles_empty_local(self) -> None:
        from imbi_api.endpoints.auth import _redact_email

        self.assertEqual(_redact_email('@example.com'), '***@example.com')

    def test_handles_no_at_sign(self) -> None:
        from imbi_api.endpoints.auth import _redact_email

        self.assertEqual(_redact_email('not-an-email'), '<redacted>')

    def test_handles_empty_string(self) -> None:
        from imbi_api.endpoints.auth import _redact_email

        self.assertEqual(_redact_email(''), '<redacted>')


class AuthProvidersEndpointTestCase(unittest.TestCase):
    """Test cases for GET /auth/providers endpoint."""

    def setUp(self) -> None:
        """Set up test client and mock settings."""
        settings._auth_settings = None
        self.test_app = app.create_app()
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
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
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
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
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
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
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
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
        # execute(): TOTP fetch, atomic backup-code consume (returns the
        # remaining count post-removal so the caller knows the hash
        # really was still present), then the atomic MATCH/CREATE inside
        # issue_token_pair that returns principal_count.
        self.mock_db.execute.side_effect = [
            [{'n': totp_data}],
            [{'remaining': 1}],
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

    def test_login_mfa_backup_code_race_returns_401(self) -> None:
        """Argon2 verifies but the atomic SET says the hash is gone.

        Simulates the H6 race: another concurrent login consumed the
        same backup code between our read and our SET. The atomic
        ``WHERE {used_hash} IN t.backup_codes`` filter excludes the row
        on this side, so ``db.execute`` returns no rows and login must
        fail with the same 401 the user would have seen if they'd
        raced themselves.
        """
        from imbi_api import models
        from imbi_api.auth import password

        test_user = models.User(
            email='test@example.com',
            display_name='Test User',
            is_active=True,
            password_hash=password.hash_password('password123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        backup_code = 'racy-bk1'
        hashed_backup = password.hash_password(backup_code)
        totp_data = {
            'secret': 'JBSWY3DPEHPK3PXP',
            'enabled': True,
            'backup_codes': [hashed_backup],
        }
        self.mock_db.match.return_value = [test_user]
        # TOTP fetch returns the row containing the hash; the atomic
        # update returns no rows (race lost).
        self.mock_db.execute.side_effect = [
            [{'n': totp_data}],
            [],
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
                    'mfa_code': backup_code,
                },
            )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['detail'], 'Invalid MFA code')

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

    def test_login_unknown_user_still_runs_argon2(self) -> None:
        """H4: verify_password runs against the dummy hash on unknown email.

        Without this, response time leaks user existence.
        """
        self.mock_db.match.return_value = []

        with mock.patch(
            'imbi_api.auth.password.verify_password',
            return_value=False,
        ) as mock_verify:
            response = self.client.post(
                '/auth/login',
                json={
                    'email': 'unknown@example.com',
                    'password': 'whatever',
                },
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(mock_verify.call_count, 1)
        # The supplied password is verified against *some* hash (the
        # module-level dummy) so timing matches the real-user path.
        called_password, called_hash = mock_verify.call_args.args
        self.assertEqual(called_password, 'whatever')
        self.assertTrue(called_hash.startswith('$argon2'))

    def test_login_oauth_only_user(self) -> None:
        """Test login for OAuth-only user (no password).

        Returns a generic 401 instead of leaking that the user exists
        but has no password configured (H4 — login timing/user-existence
        oracle defense).
        """
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
            'Invalid credentials',
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
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)

        # Default-role auto-assignment is exercised separately in
        # tests/auth/test_membership.py; patch it out here so its
        # ``db.execute`` calls do not consume the tightly-sized
        # ``side_effect`` lists each test below configures.
        self._membership_patch = mock.patch(
            'imbi_api.auth.tokens.membership.ensure_user_membership',
            return_value=None,
        )
        self._membership_patch.start()

    def tearDown(self) -> None:
        """Reset settings singleton after tests."""
        self._membership_patch.stop()
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
            provider_slug='google',
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
                new=mock.AsyncMock(return_value=mock_state_data),
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
                new=mock.AsyncMock(return_value=mock_state_data),
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
                new=mock.AsyncMock(return_value=mock_state_data),
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
                new=mock.AsyncMock(return_value=mock_state_data),
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
                new=mock.AsyncMock(return_value=mock_state_data),
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
                new=mock.AsyncMock(return_value=mock_state_data),
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
                new=mock.AsyncMock(return_value=mock_state_data),
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
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
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
        # (returns the parent's family_id so the rotated pair can
        # inherit it), then for the MATCH/CREATE inside
        # issue_token_pair that persists token metadata and returns
        # principal_count.
        self.mock_db.execute.side_effect = [
            [{'family_id': 'fam-test'}],
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
            # The rotated pair must inherit the parent's family_id;
            # otherwise the chain would split and a cascade revoke on
            # reuse would miss every descendant minted from this call.
            second_call_params = self.mock_db.execute.call_args_list[1][0][1]
            self.assertEqual(second_call_params['family_id'], 'fam-test')

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

        # Atomic revoke returns no rows when the token is already
        # revoked or unknown. The reuse-detect handler then issues a
        # lookup (returns the token's revoked/family_id) followed by
        # the family cascade (returns the count of sibling tokens it
        # revoked).
        self.mock_db.execute.side_effect = [
            [],
            [{'revoked': True, 'family_id': 'fam-test'}],
            [{'revoked_count': 0}],
        ]

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

        # Atomic revoke succeeds (returns the parent's family_id),
        # then the user match returns the inactive user.
        self.mock_db.match.return_value = [test_user]
        self.mock_db.execute.return_value = [{'family_id': 'fam-test'}]

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

    def test_refresh_token_reuse_cascades_family_revocation(self) -> None:
        """Reusing a revoked refresh kills every sibling in the family.

        Simulates the H1 reuse scenario: an attacker (or honest client
        replaying a stale token) presents a refresh whose ``revoked =
        false`` MATCH yields no rows. The handler then queries the
        token's stored state, sees it's already revoked, and fans a
        family-wide cascade SET that turns every un-revoked
        ``TokenMetadata`` for the chain into revoked rows.
        """
        from imbi_common.auth import core

        auth_settings = settings.Auth(
            jwt_secret='test-secret-key-min-32-chars-long',
        )
        refresh_token = core.create_refresh_token(
            'test@example.com',
            auth_settings=auth_settings,
        )

        self.mock_db.execute.side_effect = [
            # Atomic revoke matches nothing (already revoked).
            [],
            # Reuse lookup finds the row revoked w/ family_id.
            [{'revoked': True, 'family_id': 'fam-leak'}],
            # Family cascade reports the count of siblings revoked.
            [{'revoked_count': 3}],
        ]

        with mock.patch(
            'imbi_api.settings.get_auth_settings',
            return_value=auth_settings,
        ):
            response = self.client.post(
                '/auth/token/refresh',
                json={'refresh_token': refresh_token},
            )

        self.assertEqual(response.status_code, 401)
        self.assertIn('revoked', response.json()['detail'].lower())
        # 3 execute() calls: atomic SET, reuse lookup, family cascade.
        self.assertEqual(self.mock_db.execute.call_count, 3)
        # The third call carries the family_id we returned from the
        # lookup, proving the cascade fired with the right scope.
        third_call_params = self.mock_db.execute.call_args_list[2][0][1]
        self.assertEqual(third_call_params['family_id'], 'fam-leak')


class LogoutTestCase(unittest.TestCase):
    """Test logout endpoint."""

    def setUp(self) -> None:
        """Set up test client."""

        settings._auth_settings = None
        self.test_app = app.create_app()

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
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
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
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
        """POST /auth/login with a service account returns generic 401.

        After H4 we collapse every login failure mode to a single 401
        with constant timing so an attacker can't distinguish service
        accounts (or any other category) from unknown emails.
        """
        self.mock_db.match.return_value = [self.sa_user]

        response = self.client.post(
            '/auth/login',
            json={
                'email': 'sa@example.com',
                'password': 'SomePass123!@#',
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn(
            'Invalid credentials',
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


class IdentityPluginLoginFlowTestCase(unittest.TestCase):
    """Cover the identity-plugin branch of /auth/oauth/{provider}.

    Exercises both the start (``oauth_login``) and callback
    (``_identity_plugin_login_callback``) paths so the new code in
    ``endpoints/auth.py`` is reached without standing up a real plugin
    registry.
    """

    def setUp(self) -> None:
        from imbi_common.plugins import base as plugin_base

        from imbi_api.identity import flows as identity_flows
        from imbi_api.identity import repository as identity_repository

        self._plugin_base = plugin_base
        self._identity_flows = identity_flows
        self._identity_repository = identity_repository

        settings._auth_settings = None
        self.test_app = app.create_app()
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )
        self.client = testclient.TestClient(self.test_app)

    def tearDown(self) -> None:
        settings._auth_settings = None

    def test_oauth_login_redirects_through_identity_flow(self) -> None:
        """Identity-plugin LoginApp triggers identity_flows.start_flow."""
        provider = _stub_identity_plugin_provider('okta', plugin_id='p-1')
        with (
            _patch_providers([provider]),
            mock.patch.object(
                self._identity_flows,
                'start_flow',
                new=mock.AsyncMock(
                    return_value=(
                        'https://idp.example.com/authorize?x=1',
                        'state-token',
                        None,
                    )
                ),
            ) as start_mock,
        ):
            response = self.client.get(
                '/auth/oauth/okta',
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 307)
        self.assertEqual(
            response.headers['location'],
            'https://idp.example.com/authorize?x=1',
        )
        start_mock.assert_awaited_once()
        kwargs = start_mock.await_args.kwargs
        self.assertEqual(kwargs['plugin_id'], 'p-1')
        self.assertEqual(kwargs['intent'], 'login')

    def test_oauth_login_missing_plugin_id_returns_500(self) -> None:
        """Identity-plugin row without plugin_id is a server error."""
        provider = _stub_identity_plugin_provider('okta', plugin_id=None)
        with _patch_providers([provider]):
            response = self.client.get(
                '/auth/oauth/okta',
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 500)
        self.assertIn('missing plugin_id', response.json()['detail'])

    def test_oauth_login_plugin_not_loaded_returns_503(self) -> None:
        """PluginNotFoundError from start_flow surfaces as 503."""
        from imbi_common.plugins.errors import PluginNotFoundError

        provider = _stub_identity_plugin_provider('okta', plugin_id='p-1')
        with (
            _patch_providers([provider]),
            mock.patch.object(
                self._identity_flows,
                'start_flow',
                new=mock.AsyncMock(side_effect=PluginNotFoundError('okta')),
            ),
        ):
            response = self.client.get(
                '/auth/oauth/okta',
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn('not loaded', response.json()['detail'])

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
            'IMBI_AUTH_OAUTH_AUTO_CREATE_USERS': 'true',
        },
    )
    def test_oauth_callback_creates_new_user_via_identity_plugin(
        self,
    ) -> None:
        """Identity-plugin callback provisions a new user + JWT pair."""
        from imbi_common.auth import encryption

        from imbi_api import models as api_models

        encryption.TokenEncryption.reset_instance()
        settings._auth_settings = None

        provider = _stub_identity_plugin_provider('okta', plugin_id='p-1')

        profile = self._plugin_base.IdentityProfile(
            subject='okta-sub-1',
            email='new@example.com',
            email_verified=True,
            name='New User',
        )
        credentials = self._plugin_base.IdentityCredentials(
            access_token='at-1',
            refresh_token='rt-1',
        )

        # No existing user
        self.mock_db.match.return_value = []
        self.mock_db.merge.return_value = None
        # execute(): the principal_count query inside issue_token_pair
        # then the SET last_login update — both for the new user.
        self.mock_db.execute.side_effect = [
            [{'principal_count': 1}],
            [],
        ]

        with (
            _patch_providers([provider]),
            mock.patch.object(
                self._identity_flows,
                'complete_login_flow',
                new=mock.AsyncMock(
                    return_value=(profile, credentials, 'p-1', '/projects')
                ),
            ),
            mock.patch.object(
                self._identity_repository,
                'upsert_connection',
                new=mock.AsyncMock(return_value=None),
            ) as upsert_mock,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.get(
                '/auth/oauth/okta/callback?code=c&state=s',
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 307)
        location = response.headers['location']
        # Tokens land in the URL fragment, not the query string.
        self.assertIn('/projects#', location)
        self.assertIn('access_token=', location)
        self.assertIn('refresh_token=', location)
        upsert_mock.assert_awaited_once()
        # Verify the new user was upserted into the graph.
        merged = [c.args[0] for c in self.mock_db.merge.call_args_list]
        self.assertTrue(any(isinstance(m, api_models.User) for m in merged))

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
        },
    )
    def test_oauth_callback_links_existing_user_via_identity_plugin(
        self,
    ) -> None:
        """Identity-plugin callback links to an existing user by email."""
        from imbi_common.auth import encryption

        from imbi_api import models as api_models

        encryption.TokenEncryption.reset_instance()
        settings._auth_settings = None

        provider = _stub_identity_plugin_provider('okta', plugin_id='p-1')

        existing = api_models.User(
            email='existing@example.com',
            display_name='Existing User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        profile = self._plugin_base.IdentityProfile(
            subject='okta-sub-99',
            email='existing@example.com',
            email_verified=True,
            name='Existing User',
        )
        credentials = self._plugin_base.IdentityCredentials(
            access_token='at-1',
        )

        self.mock_db.match.return_value = [existing]
        self.mock_db.merge.return_value = None
        self.mock_db.execute.side_effect = [
            [{'principal_count': 1}],
            [],
        ]

        with (
            _patch_providers([provider]),
            mock.patch.object(
                self._identity_flows,
                'complete_login_flow',
                new=mock.AsyncMock(
                    return_value=(profile, credentials, 'p-1', None)
                ),
            ),
            mock.patch.object(
                self._identity_repository,
                'upsert_connection',
                new=mock.AsyncMock(return_value=None),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.get(
                '/auth/oauth/okta/callback?code=c&state=s',
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 307)
        # Default redirect when return_to is None is /dashboard, and
        # tokens are appended in the URL fragment.
        location = response.headers['location']
        self.assertTrue(location.startswith('/dashboard#'))
        self.assertIn('access_token=', location)
        self.assertIn('token_type=bearer', location)

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
            'IMBI_AUTH_OAUTH_AUTO_LINK_BY_EMAIL': 'false',
        },
    )
    def test_oauth_callback_refuses_link_when_auto_link_disabled(
        self,
    ) -> None:
        """Existing user + auto-link disabled => authentication_failed."""
        from imbi_common.auth import encryption

        from imbi_api import models as api_models

        encryption.TokenEncryption.reset_instance()
        settings._auth_settings = None

        provider = _stub_identity_plugin_provider('okta', plugin_id='p-1')
        existing = api_models.User(
            email='existing@example.com',
            display_name='Existing User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        profile = self._plugin_base.IdentityProfile(
            subject='okta-sub-1',
            email='existing@example.com',
            email_verified=True,
        )
        credentials = self._plugin_base.IdentityCredentials(access_token='a')

        self.mock_db.match.return_value = [existing]

        with (
            _patch_providers([provider]),
            mock.patch.object(
                self._identity_flows,
                'complete_login_flow',
                new=mock.AsyncMock(
                    return_value=(profile, credentials, 'p-1', None)
                ),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.get(
                '/auth/oauth/okta/callback?code=c&state=s',
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 307)
        self.assertIn(
            'error=authentication_failed', response.headers['location']
        )

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
        },
    )
    def test_oauth_callback_refuses_unverified_email(self) -> None:
        """Auto-link refuses when provider does not assert email_verified."""
        from imbi_common.auth import encryption

        from imbi_api import models as api_models

        encryption.TokenEncryption.reset_instance()
        settings._auth_settings = None

        provider = _stub_identity_plugin_provider('okta', plugin_id='p-1')
        existing = api_models.User(
            email='existing@example.com',
            display_name='Existing User',
            is_active=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        profile = self._plugin_base.IdentityProfile(
            subject='okta-sub-1',
            email='existing@example.com',
            email_verified=False,
        )
        credentials = self._plugin_base.IdentityCredentials(access_token='a')

        self.mock_db.match.return_value = [existing]

        with (
            _patch_providers([provider]),
            mock.patch.object(
                self._identity_flows,
                'complete_login_flow',
                new=mock.AsyncMock(
                    return_value=(profile, credentials, 'p-1', None)
                ),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.get(
                '/auth/oauth/okta/callback?code=c&state=s',
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 307)
        self.assertIn(
            'error=authentication_failed', response.headers['location']
        )

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
            'IMBI_AUTH_OAUTH_AUTO_CREATE_USERS': 'false',
        },
    )
    def test_oauth_callback_refuses_create_when_disabled(self) -> None:
        """Auto-create disabled + no user => authentication_failed."""
        from imbi_common.auth import encryption

        encryption.TokenEncryption.reset_instance()
        settings._auth_settings = None

        provider = _stub_identity_plugin_provider('okta', plugin_id='p-1')
        profile = self._plugin_base.IdentityProfile(
            subject='okta-sub-1',
            email='nobody@example.com',
            email_verified=True,
        )
        credentials = self._plugin_base.IdentityCredentials(access_token='a')

        self.mock_db.match.return_value = []

        with (
            _patch_providers([provider]),
            mock.patch.object(
                self._identity_flows,
                'complete_login_flow',
                new=mock.AsyncMock(
                    return_value=(profile, credentials, 'p-1', None)
                ),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.get(
                '/auth/oauth/okta/callback?code=c&state=s',
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 307)
        self.assertIn(
            'error=authentication_failed', response.headers['location']
        )

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
        },
    )
    def test_oauth_callback_rejects_service_account(self) -> None:
        """Service-account users cannot complete identity-plugin login."""
        from imbi_common.auth import encryption

        from imbi_api import models as api_models

        encryption.TokenEncryption.reset_instance()
        settings._auth_settings = None

        provider = _stub_identity_plugin_provider('okta', plugin_id='p-1')
        sa_user = api_models.User(
            email='svc@example.com',
            display_name='Service',
            is_active=True,
            is_service_account=True,
            password_hash=None,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        profile = self._plugin_base.IdentityProfile(
            subject='okta-sub-1',
            email='svc@example.com',
            email_verified=True,
        )
        credentials = self._plugin_base.IdentityCredentials(access_token='a')

        self.mock_db.match.return_value = [sa_user]

        with (
            _patch_providers([provider]),
            mock.patch.object(
                self._identity_flows,
                'complete_login_flow',
                new=mock.AsyncMock(
                    return_value=(profile, credentials, 'p-1', None)
                ),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.get(
                '/auth/oauth/okta/callback?code=c&state=s',
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 307)
        self.assertIn(
            'error=authentication_failed', response.headers['location']
        )

    @mock.patch.dict(
        'os.environ',
        {
            'IMBI_AUTH_ENCRYPTION_KEY': (
                'nhia5yBgff552rNZAvT4GGu-IE0dMVsXQaM2auHNXRo='
            ),
        },
    )
    def test_oauth_callback_rejects_profile_without_email(self) -> None:
        """Identity plugin must return an email or callback fails."""
        from imbi_common.auth import encryption

        encryption.TokenEncryption.reset_instance()
        settings._auth_settings = None

        provider = _stub_identity_plugin_provider('okta', plugin_id='p-1')
        profile = self._plugin_base.IdentityProfile(
            subject='okta-sub-1',
            email=None,
        )
        credentials = self._plugin_base.IdentityCredentials(access_token='a')

        with (
            _patch_providers([provider]),
            mock.patch.object(
                self._identity_flows,
                'complete_login_flow',
                new=mock.AsyncMock(
                    return_value=(profile, credentials, 'p-1', None)
                ),
            ),
        ):
            response = self.client.get(
                '/auth/oauth/okta/callback?code=c&state=s',
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 307)
        self.assertIn(
            'error=authentication_failed', response.headers['location']
        )
