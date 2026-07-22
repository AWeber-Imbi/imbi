"""Smoke tests for the Google identity plugin."""

import datetime
import unittest

import httpx
import respx
from imbi_common.plugins.base import (
    IdentityCapability,
    PluginContext,
    PluginManifest,
)

from imbi_plugin_google import PLUGIN
from imbi_plugin_google.plugin import (
    REVOCATION_ENDPOINT,
    TOKEN_ENDPOINT,
    USERINFO_ENDPOINT,
    GoogleIdentity,
    GooglePlugin,
)


def _ctx(options: dict[str, object] | None = None) -> PluginContext:
    return PluginContext(
        project_id='p',
        project_slug='proj',
        org_slug='org',
        integration_options=options or {},
        actor_user_id='u-1',
    )


def _mock_token(**overrides: object) -> None:
    payload: dict[str, object] = {
        'access_token': 'at',
        'token_type': 'Bearer',
        'refresh_token': 'rt',
        'expires_in': 3600,
        'scope': 'openid email',
    }
    payload.update(overrides)
    respx.post(TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(200, json=payload)
    )


def _mock_userinfo(**overrides: object) -> None:
    payload: dict[str, object] = {
        'sub': 'g-1',
        'email': 'u@example.com',
        'email_verified': True,
        'name': 'User One',
        'picture': 'https://example.com/a.png',
    }
    payload.update(overrides)
    respx.get(USERINFO_ENDPOINT).mock(
        return_value=httpx.Response(200, json=payload)
    )


class ManifestTestCase(unittest.TestCase):
    def test_plugin_registration(self) -> None:
        self.assertIs(PLUGIN, GooglePlugin)
        self.assertIsInstance(GooglePlugin.manifest, PluginManifest)

    def test_manifest_basics(self) -> None:
        manifest = GooglePlugin.manifest
        self.assertEqual(manifest.slug, 'google')
        self.assertEqual(manifest.api_version, 2)

    def test_identity_capability(self) -> None:
        capability = GooglePlugin.manifest.get_capability('identity')
        self.assertIsNotNone(capability)
        assert capability is not None
        self.assertIs(capability.handler, GoogleIdentity)
        self.assertTrue(issubclass(capability.handler, IdentityCapability))
        self.assertFalse(capability.project_scoped)
        self.assertFalse(capability.default_enabled)
        self.assertTrue(capability.hints['login_capable'])
        self.assertEqual(
            capability.hints['widget_text'], 'Sign in with Google'
        )
        self.assertEqual(
            capability.hints['default_scopes'],
            ['openid', 'profile', 'email'],
        )

    def test_credentials_declared_on_manifest(self) -> None:
        creds = {c.name: c for c in GooglePlugin.manifest.credentials}
        self.assertEqual(set(creds), {'client_id', 'client_secret'})
        # The client id is a public identifier, not a secret.
        self.assertFalse(creds['client_id'].secret)
        self.assertTrue(creds['client_secret'].secret)


class FlowTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_authorization_request_pkce(self) -> None:
        plugin = GoogleIdentity()
        request = await plugin.authorization_request(
            _ctx(), {'client_id': 'cid'}, 'https://app.example.com/cb', None
        )
        self.assertIn(
            'accounts.google.com/o/oauth2', request.authorization_url
        )
        self.assertIn('code_challenge_method=S256', request.authorization_url)
        self.assertIn('access_type=offline', request.authorization_url)
        self.assertIn('scope=openid+profile+email', request.authorization_url)
        self.assertIsNotNone(request.code_verifier)

    async def test_authorization_request_hosted_domain(self) -> None:
        plugin = GoogleIdentity()
        request = await plugin.authorization_request(
            _ctx({'hosted_domain': 'example.com'}),
            {'client_id': 'cid'},
            'https://app.example.com/cb',
            None,
        )
        self.assertIn('hd=example.com', request.authorization_url)

    async def test_authorization_request_without_pkce(self) -> None:
        plugin = GoogleIdentity()
        request = await plugin.authorization_request(
            _ctx({'pkce_required': False, 'default_scopes': 'openid email'}),
            {'client_id': 'cid'},
            'https://app.example.com/cb',
            None,
        )
        self.assertIsNone(request.code_verifier)
        self.assertNotIn('code_challenge_method', request.authorization_url)
        self.assertIn('scope=openid+email', request.authorization_url)

    async def test_authorization_request_default_scopes_list(self) -> None:
        plugin = GoogleIdentity()
        request = await plugin.authorization_request(
            _ctx({'default_scopes': ['openid', 'email']}),
            {'client_id': 'cid'},
            'https://app.example.com/cb',
            None,
        )
        self.assertIn('scope=openid+email', request.authorization_url)

    async def test_authorization_request_explicit_scopes(self) -> None:
        plugin = GoogleIdentity()
        request = await plugin.authorization_request(
            _ctx(),
            {'client_id': 'cid'},
            'https://app.example.com/cb',
            ['openid', 'profile'],
        )
        self.assertIn('scope=openid+profile', request.authorization_url)

    @respx.mock
    async def test_exchange_code_round_trip(self) -> None:
        _mock_token()
        _mock_userinfo()
        plugin = GoogleIdentity()
        profile, credentials = await plugin.exchange_code(
            _ctx(),
            {'client_id': 'cid', 'client_secret': 'sec'},
            'auth-code',
            'https://app.example.com/cb',
            'verifier',
        )
        self.assertEqual(profile.subject, 'g-1')
        self.assertEqual(profile.email, 'u@example.com')
        self.assertTrue(profile.email_verified)
        self.assertEqual(profile.avatar_url, 'https://example.com/a.png')
        self.assertEqual(credentials.access_token, 'at')
        self.assertEqual(credentials.refresh_token, 'rt')
        self.assertIsNotNone(credentials.expires_at)
        if credentials.expires_at:
            now = datetime.datetime.now(datetime.UTC)
            self.assertGreater(credentials.expires_at, now)
        self.assertIn('openid', credentials.scopes)

    @respx.mock
    async def test_refresh_keeps_refresh_token(self) -> None:
        # Google omits refresh_token on refresh; the old one is retained.
        respx.post(TOKEN_ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    'access_token': 'at-2',
                    'token_type': 'Bearer',
                    'expires_in': 3600,
                },
            )
        )
        plugin = GoogleIdentity()
        credentials = await plugin.refresh(
            _ctx(),
            {'client_id': 'cid', 'client_secret': 'sec'},
            'rt-1',
        )
        self.assertEqual(credentials.access_token, 'at-2')
        self.assertEqual(credentials.refresh_token, 'rt-1')

    @respx.mock
    async def test_revoke_posts_to_endpoint(self) -> None:
        route = respx.post(REVOCATION_ENDPOINT).mock(
            return_value=httpx.Response(200)
        )
        plugin = GoogleIdentity()
        await plugin.revoke(_ctx(), {'client_id': 'cid'}, 'token-to-revoke')
        self.assertTrue(route.called)

    @respx.mock
    async def test_revoke_swallows_http_errors(self) -> None:
        respx.post(REVOCATION_ENDPOINT).mock(
            side_effect=httpx.ConnectError('boom')
        )
        plugin = GoogleIdentity()
        await plugin.revoke(_ctx(), {'client_id': 'cid'}, 'token-to-revoke')

    @respx.mock
    async def test_exchange_code_token_failure_raises(self) -> None:
        respx.post(TOKEN_ENDPOINT).mock(
            return_value=httpx.Response(401, text='bad creds')
        )
        plugin = GoogleIdentity()
        with self.assertRaises(ValueError):
            await plugin.exchange_code(
                _ctx(),
                {'client_id': 'cid'},
                'auth-code',
                'https://app.example.com/cb',
                None,
            )

    @respx.mock
    async def test_exchange_code_userinfo_failure_raises(self) -> None:
        _mock_token()
        respx.get(USERINFO_ENDPOINT).mock(
            return_value=httpx.Response(500, text='nope')
        )
        plugin = GoogleIdentity()
        with self.assertRaises(ValueError):
            await plugin.exchange_code(
                _ctx(),
                {'client_id': 'cid', 'client_secret': 'sec'},
                'auth-code',
                'https://app.example.com/cb',
                'verifier',
            )

    @respx.mock
    async def test_refresh_failure_raises(self) -> None:
        respx.post(TOKEN_ENDPOINT).mock(
            return_value=httpx.Response(400, text='expired')
        )
        plugin = GoogleIdentity()
        with self.assertRaises(ValueError):
            await plugin.refresh(_ctx(), {'client_id': 'cid'}, 'rt-1')
