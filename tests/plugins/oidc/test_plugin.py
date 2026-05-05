"""Smoke tests for the OIDC identity plugin."""

import datetime
import unittest
import unittest.mock

import httpx
import respx
from imbi_common.plugins.base import (
    IdentityPlugin,
    PluginContext,
)

from imbi_plugin_oidc.plugin import OIDCPlugin


def _ctx(options: dict[str, object]) -> PluginContext:
    return PluginContext(
        project_id='p',
        project_slug='proj',
        org_slug='org',
        assignment_options=options,
        actor_user_id='u-1',
    )


class ManifestTestCase(unittest.TestCase):
    def test_manifest_basics(self) -> None:
        plugin = OIDCPlugin()
        self.assertIsInstance(plugin, IdentityPlugin)
        self.assertEqual(plugin.manifest.slug, 'oidc')
        self.assertEqual(plugin.manifest.plugin_type, 'identity')
        self.assertEqual(plugin.manifest.auth_type, 'oidc')
        self.assertTrue(plugin.manifest.login_capable)


class FlowTestCase(unittest.IsolatedAsyncioTestCase):
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
        plugin = OIDCPlugin()
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
        plugin = OIDCPlugin()
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
        plugin = OIDCPlugin()
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
        plugin = OIDCPlugin()
        ctx = _ctx({'issuer_url': 'https://idp.example.com'})
        await plugin.revoke(ctx, {'client_id': 'cid'}, 'token-to-revoke')
