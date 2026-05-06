"""Smoke tests for the GitHub identity plugins."""

import unittest

import httpx
import respx
from imbi_common.plugins.base import IdentityPlugin, PluginContext

from imbi_plugin_github.plugin import (
    GitHubEnterpriseCloudPlugin,
    GitHubEnterpriseServerPlugin,
    GitHubPlugin,
)


def _ctx(options: dict[str, object] | None = None) -> PluginContext:
    return PluginContext(
        project_id='p',
        project_slug='proj',
        org_slug='org',
        assignment_options=options or {},
        actor_user_id='u-1',
    )


class ManifestTestCase(unittest.TestCase):
    def test_manifests_distinct(self) -> None:
        self.assertEqual(GitHubPlugin.manifest.slug, 'github')
        self.assertEqual(
            GitHubEnterpriseCloudPlugin.manifest.slug,
            'github-enterprise-cloud',
        )
        self.assertEqual(
            GitHubEnterpriseServerPlugin.manifest.slug,
            'github-enterprise-server',
        )

    def test_all_login_capable(self) -> None:
        for cls in (
            GitHubPlugin,
            GitHubEnterpriseCloudPlugin,
            GitHubEnterpriseServerPlugin,
        ):
            self.assertIsInstance(cls(), IdentityPlugin)
            self.assertTrue(cls.manifest.login_capable)
            self.assertEqual(cls.manifest.plugin_type, 'identity')
            self.assertEqual(cls.manifest.auth_type, 'oauth2')

    def test_ghes_host_required(self) -> None:
        plugin = GitHubEnterpriseServerPlugin()
        with self.assertRaises(ValueError):
            plugin._endpoints({})

    def test_ghec_host_required(self) -> None:
        plugin = GitHubEnterpriseCloudPlugin()
        with self.assertRaises(ValueError):
            plugin._endpoints({})


class FlowTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_authorization_request_dot_com(self) -> None:
        plugin = GitHubPlugin()
        request = await plugin.authorization_request(
            _ctx(),
            {'client_id': 'cid'},
            'https://imbi.test/cb',
        )
        self.assertIn(
            'https://github.com/login/oauth/authorize',
            request.authorization_url,
        )
        self.assertIn(
            'scope=read%3Auser+user%3Aemail', request.authorization_url
        )

    @respx.mock
    async def test_authorization_request_ghes_uses_host(self) -> None:
        plugin = GitHubEnterpriseServerPlugin()
        request = await plugin.authorization_request(
            _ctx({'host': 'github.example.com'}),
            {'client_id': 'cid'},
            'https://imbi.test/cb',
        )
        self.assertIn(
            'https://github.example.com/login/oauth/authorize',
            request.authorization_url,
        )

    @respx.mock
    async def test_exchange_code_round_trip(self) -> None:
        respx.post('https://github.com/login/oauth/access_token').mock(
            return_value=httpx.Response(
                200,
                json={
                    'access_token': 'gh-token',
                    'token_type': 'bearer',
                    'scope': 'read:user,user:email',
                },
            )
        )
        respx.get('https://api.github.com/user').mock(
            return_value=httpx.Response(
                200,
                json={
                    'id': 12345,
                    'login': 'octocat',
                    'name': 'Octo Cat',
                    'email': 'octo@example.com',
                    'avatar_url': 'https://avatars.example.com/octo',
                },
            )
        )
        plugin = GitHubPlugin()
        profile, credentials = await plugin.exchange_code(
            _ctx(),
            {'client_id': 'cid', 'client_secret': 'sec'},
            'auth-code',
            'https://imbi.test/cb',
        )
        self.assertEqual(profile.subject, '12345')
        self.assertEqual(profile.email, 'octo@example.com')
        self.assertTrue(profile.email_verified)
        self.assertEqual(profile.name, 'Octo Cat')
        self.assertEqual(credentials.access_token, 'gh-token')
        self.assertEqual(credentials.scopes, ['read:user', 'user:email'])

    @respx.mock
    async def test_exchange_code_falls_back_to_emails_endpoint(self) -> None:
        respx.post('https://github.com/login/oauth/access_token').mock(
            return_value=httpx.Response(
                200,
                json={
                    'access_token': 'gh-token',
                    'token_type': 'bearer',
                },
            )
        )
        respx.get('https://api.github.com/user').mock(
            return_value=httpx.Response(
                200,
                json={
                    'id': 1,
                    'login': 'private',
                    'name': 'Private User',
                    'email': None,
                },
            )
        )
        respx.get('https://api.github.com/user/emails').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'email': 'noreply@example.com',
                        'primary': False,
                        'verified': True,
                    },
                    {
                        'email': 'real@example.com',
                        'primary': True,
                        'verified': True,
                    },
                ],
            )
        )
        plugin = GitHubPlugin()
        profile, _ = await plugin.exchange_code(
            _ctx(),
            {'client_id': 'cid', 'client_secret': 'sec'},
            'code',
            'https://imbi.test/cb',
        )
        self.assertEqual(profile.email, 'real@example.com')

    @respx.mock
    async def test_refresh(self) -> None:
        respx.post('https://github.com/login/oauth/access_token').mock(
            return_value=httpx.Response(
                200,
                json={
                    'access_token': 'gh-token-2',
                    'token_type': 'bearer',
                    'expires_in': 28800,
                    'refresh_token': 'rt-2',
                },
            )
        )
        plugin = GitHubPlugin()
        credentials = await plugin.refresh(
            _ctx(),
            {'client_id': 'cid', 'client_secret': 'sec'},
            'rt-1',
        )
        self.assertEqual(credentials.access_token, 'gh-token-2')
        self.assertEqual(credentials.refresh_token, 'rt-2')
        self.assertIsNotNone(credentials.expires_at)

    @respx.mock
    async def test_refresh_keeps_old_refresh_token_when_missing(
        self,
    ) -> None:
        respx.post('https://github.com/login/oauth/access_token').mock(
            return_value=httpx.Response(
                200,
                json={
                    'access_token': 'gh-token-3',
                    'token_type': 'bearer',
                },
            )
        )
        plugin = GitHubPlugin()
        credentials = await plugin.refresh(
            _ctx(),
            {'client_id': 'cid', 'client_secret': 'sec'},
            'rt-keep',
        )
        self.assertEqual(credentials.refresh_token, 'rt-keep')

    @respx.mock
    async def test_token_failure_raises(self) -> None:
        respx.post('https://github.com/login/oauth/access_token').mock(
            return_value=httpx.Response(400, text='bad')
        )
        plugin = GitHubPlugin()
        with self.assertRaises(ValueError):
            await plugin.exchange_code(
                _ctx(),
                {'client_id': 'cid', 'client_secret': 'sec'},
                'auth-code',
                'https://imbi.test/cb',
            )
