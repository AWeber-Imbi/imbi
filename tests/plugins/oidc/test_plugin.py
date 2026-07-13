"""Smoke tests for the OIDC identity plugin."""

import datetime
import unittest

import httpx
import respx
from imbi_common.plugins.base import (
    IdentityCapability,
    PluginContext,
    PluginManifest,
)

from imbi_plugin_oidc import PLUGIN
from imbi_plugin_oidc.plugin import OIDCIdentity, OIDCPlugin

_DISCOVERY = {
    'authorization_endpoint': 'https://idp.example.com/authorize',
    'token_endpoint': 'https://idp.example.com/token',
    'userinfo_endpoint': 'https://idp.example.com/userinfo',
    'revocation_endpoint': 'https://idp.example.com/revoke',
}


def _mock_discovery(payload: dict[str, str] | None = None) -> None:
    respx.get('https://idp.example.com/.well-known/openid-configuration').mock(
        return_value=httpx.Response(200, json=payload or _DISCOVERY),
    )


def _ctx(options: dict[str, object]) -> PluginContext:
    return PluginContext(
        project_id='p',
        project_slug='proj',
        org_slug='org',
        integration_options=options,
        actor_user_id='u-1',
    )


class ManifestTestCase(unittest.TestCase):
    def test_plugin_registration(self) -> None:
        self.assertIs(PLUGIN, OIDCPlugin)
        self.assertIsInstance(OIDCPlugin.manifest, PluginManifest)

    def test_manifest_basics(self) -> None:
        manifest = OIDCPlugin.manifest
        self.assertEqual(manifest.slug, 'oidc')
        self.assertEqual(manifest.api_version, 2)
        self.assertEqual(manifest.auth_type, 'oidc')

    def test_identity_capability(self) -> None:
        manifest = OIDCPlugin.manifest
        capability = manifest.get_capability('identity')
        self.assertIsNotNone(capability)
        assert capability is not None
        self.assertIs(capability.handler, OIDCIdentity)
        self.assertTrue(issubclass(capability.handler, IdentityCapability))
        self.assertFalse(capability.project_scoped)
        self.assertFalse(capability.default_enabled)
        self.assertTrue(capability.hints['login_capable'])
        self.assertEqual(
            capability.hints['default_scopes'],
            ['openid', 'profile', 'email'],
        )

    def test_credentials_declared_on_manifest(self) -> None:
        names = {c.name for c in OIDCPlugin.manifest.credentials}
        self.assertEqual(names, {'client_id', 'client_secret'})


class FlowTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        OIDCIdentity._discovery_cache.clear()

    @respx.mock
    async def test_authorization_request_pkce(self) -> None:
        respx.get(
            'https://idp.example.com/.well-known/openid-configuration'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'authorization_endpoint': 'https://idp.example.com/authorize',
                    'token_endpoint': 'https://idp.example.com/token',
                    'userinfo_endpoint': 'https://idp.example.com/userinfo',
                },
            )
        )
        plugin = OIDCIdentity()
        ctx = _ctx({'issuer_url': 'https://idp.example.com'})
        request = await plugin.authorization_request(
            ctx,
            {'client_id': 'cid'},
            'https://app.example.com/cb',
            None,
        )
        self.assertIn('idp.example.com/authorize', request.authorization_url)
        self.assertIn('code_challenge_method=S256', request.authorization_url)
        self.assertIsNotNone(request.code_verifier)

    @respx.mock
    async def test_exchange_code_round_trip(self) -> None:
        respx.get(
            'https://idp.example.com/.well-known/openid-configuration'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'authorization_endpoint': 'https://idp.example.com/authorize',
                    'token_endpoint': 'https://idp.example.com/token',
                    'userinfo_endpoint': 'https://idp.example.com/userinfo',
                },
            )
        )
        respx.post('https://idp.example.com/token').mock(
            return_value=httpx.Response(
                200,
                json={
                    'access_token': 'at',
                    'token_type': 'Bearer',
                    'refresh_token': 'rt',
                    'expires_in': 3600,
                    'scope': 'openid email',
                },
            )
        )
        respx.get('https://idp.example.com/userinfo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'sub': 'u-1',
                    'email': 'u@example.com',
                    'name': 'User One',
                    'email_verified': True,
                },
            )
        )
        plugin = OIDCIdentity()
        ctx = _ctx({'issuer_url': 'https://idp.example.com'})
        profile, credentials = await plugin.exchange_code(
            ctx,
            {'client_id': 'cid', 'client_secret': 'sec'},
            'auth-code',
            'https://app.example.com/cb',
            'verifier',
        )
        self.assertEqual(profile.subject, 'u-1')
        self.assertEqual(profile.email, 'u@example.com')
        self.assertTrue(profile.email_verified)
        self.assertEqual(credentials.access_token, 'at')
        self.assertEqual(credentials.refresh_token, 'rt')
        self.assertIsNotNone(credentials.expires_at)
        if credentials.expires_at:
            now = datetime.datetime.now(datetime.UTC)
            self.assertGreater(credentials.expires_at, now)
        self.assertIn('openid', credentials.scopes)

    @respx.mock
    async def test_refresh(self) -> None:
        respx.get(
            'https://idp.example.com/.well-known/openid-configuration'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'authorization_endpoint': 'https://idp.example.com/a',
                    'token_endpoint': 'https://idp.example.com/token',
                    'userinfo_endpoint': 'https://idp.example.com/u',
                },
            )
        )
        respx.post('https://idp.example.com/token').mock(
            return_value=httpx.Response(
                200,
                json={
                    'access_token': 'at-2',
                    'token_type': 'Bearer',
                    'refresh_token': 'rt-2',
                    'expires_in': 3600,
                },
            )
        )
        plugin = OIDCIdentity()
        ctx = _ctx({'issuer_url': 'https://idp.example.com'})
        credentials = await plugin.refresh(
            ctx,
            {'client_id': 'cid', 'client_secret': 'sec'},
            'rt-1',
        )
        self.assertEqual(credentials.access_token, 'at-2')
        self.assertEqual(credentials.refresh_token, 'rt-2')

    @respx.mock
    async def test_revoke_no_endpoint_is_noop(self) -> None:
        respx.get(
            'https://idp.example.com/.well-known/openid-configuration'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'authorization_endpoint': 'https://idp.example.com/a',
                    'token_endpoint': 'https://idp.example.com/t',
                    'userinfo_endpoint': 'https://idp.example.com/u',
                },
            )
        )
        plugin = OIDCIdentity()
        ctx = _ctx({'issuer_url': 'https://idp.example.com'})
        await plugin.revoke(ctx, {'client_id': 'cid'}, 'token-to-revoke')

    @respx.mock
    async def test_revoke_posts_to_endpoint(self) -> None:
        _mock_discovery()
        route = respx.post('https://idp.example.com/revoke').mock(
            return_value=httpx.Response(200)
        )
        plugin = OIDCIdentity()
        ctx = _ctx({'issuer_url': 'https://idp.example.com'})
        await plugin.revoke(
            ctx,
            {'client_id': 'cid', 'client_secret': 'sec'},
            'token-to-revoke',
        )
        self.assertTrue(route.called)

    @respx.mock
    async def test_revoke_swallows_http_errors(self) -> None:
        _mock_discovery()
        respx.post('https://idp.example.com/revoke').mock(
            side_effect=httpx.ConnectError('boom')
        )
        plugin = OIDCIdentity()
        ctx = _ctx({'issuer_url': 'https://idp.example.com'})
        await plugin.revoke(ctx, {'client_id': 'cid'}, 'token-to-revoke')

    @respx.mock
    async def test_authorization_request_without_pkce_with_audience(
        self,
    ) -> None:
        _mock_discovery()
        plugin = OIDCIdentity()
        ctx = _ctx(
            {
                'issuer_url': 'https://idp.example.com',
                'pkce_required': False,
                'audience': 'aud-1',
                'default_scopes': 'openid email',
            }
        )
        request = await plugin.authorization_request(
            ctx,
            {'client_id': 'cid'},
            'https://app.example.com/cb',
            None,
        )
        self.assertIsNone(request.code_verifier)
        self.assertIn('audience=aud-1', request.authorization_url)
        self.assertNotIn('code_challenge_method', request.authorization_url)

    @respx.mock
    async def test_authorization_request_default_scopes_list(self) -> None:
        _mock_discovery()
        plugin = OIDCIdentity()
        ctx = _ctx(
            {
                'issuer_url': 'https://idp.example.com',
                'default_scopes': ['openid', 'email'],
            }
        )
        request = await plugin.authorization_request(
            ctx,
            {'client_id': 'cid'},
            'https://app.example.com/cb',
            None,
        )
        self.assertIn('scope=openid+email', request.authorization_url)

    async def test_resolve_endpoints_requires_issuer(self) -> None:
        plugin = OIDCIdentity()
        ctx = _ctx({})
        with self.assertRaises(ValueError):
            await plugin.authorization_request(
                ctx,
                {'client_id': 'cid'},
                'https://app.example.com/cb',
                None,
            )

    @respx.mock
    async def test_discovery_failure_raises(self) -> None:
        respx.get(
            'https://idp.example.com/.well-known/openid-configuration'
        ).mock(return_value=httpx.Response(500))
        plugin = OIDCIdentity()
        ctx = _ctx({'issuer_url': 'https://idp.example.com'})
        with self.assertRaises(ValueError):
            await plugin.authorization_request(
                ctx,
                {'client_id': 'cid'},
                'https://app.example.com/cb',
                None,
            )

    @respx.mock
    async def test_exchange_code_token_failure_raises(self) -> None:
        _mock_discovery()
        respx.post('https://idp.example.com/token').mock(
            return_value=httpx.Response(401, text='bad creds')
        )
        plugin = OIDCIdentity()
        ctx = _ctx({'issuer_url': 'https://idp.example.com'})
        with self.assertRaises(ValueError):
            await plugin.exchange_code(
                ctx,
                {'client_id': 'cid'},
                'auth-code',
                'https://app.example.com/cb',
                None,
            )

    @respx.mock
    async def test_exchange_code_userinfo_failure_raises(self) -> None:
        _mock_discovery()
        respx.post('https://idp.example.com/token').mock(
            return_value=httpx.Response(
                200,
                json={'access_token': 'at', 'token_type': 'Bearer'},
            )
        )
        respx.get('https://idp.example.com/userinfo').mock(
            return_value=httpx.Response(500, text='nope')
        )
        plugin = OIDCIdentity()
        ctx = _ctx({'issuer_url': 'https://idp.example.com'})
        with self.assertRaises(ValueError):
            await plugin.exchange_code(
                ctx,
                {'client_id': 'cid'},
                'auth-code',
                'https://app.example.com/cb',
                'verifier',
            )

    @respx.mock
    async def test_refresh_failure_raises(self) -> None:
        _mock_discovery()
        respx.post('https://idp.example.com/token').mock(
            return_value=httpx.Response(400, text='expired')
        )
        plugin = OIDCIdentity()
        ctx = _ctx({'issuer_url': 'https://idp.example.com'})
        with self.assertRaises(ValueError):
            await plugin.refresh(ctx, {'client_id': 'cid'}, 'rt-1')
