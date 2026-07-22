"""Smoke tests for the GitHub identity capability handler."""

import unittest
import urllib.parse

import httpx
import respx
from imbi_common.plugins.base import (
    IdentityCapability,
    PluginContext,
)

from imbi_plugin_github.identity import GitHubIdentity
from imbi_plugin_github.plugin import GitHubPlugin


def _connection(flavor: str, host: str | None = None) -> dict[str, object]:
    options: dict[str, object] = {'flavor': flavor}
    if host is not None:
        options['host'] = host
    return options


def _ctx(
    options: dict[str, object] | None = None,
    connection: dict[str, object] | None = None,
) -> PluginContext:
    return PluginContext(
        project_id='p',
        project_slug='proj',
        org_slug='org',
        capability_options=options or {},
        actor_user_id='u-1',
        integration_options=connection or {},
    )


class ManifestTestCase(unittest.TestCase):
    def test_manifest_slug(self) -> None:
        self.assertEqual(GitHubPlugin.manifest.slug, 'github')

    def test_login_capable(self) -> None:
        cap = GitHubPlugin.manifest.get_capability('identity')
        assert cap is not None
        self.assertTrue(issubclass(cap.handler, IdentityCapability))
        self.assertIs(cap.handler, GitHubIdentity)
        self.assertTrue(cap.hints['login_capable'])
        self.assertFalse(cap.default_enabled)
        self.assertFalse(cap.project_scoped)
        self.assertEqual(GitHubPlugin.manifest.auth_type, 'oauth2')

    def test_dot_com_endpoints(self) -> None:
        plugin = GitHubIdentity()
        endpoints = plugin._endpoints(_ctx(connection=_connection('github')))
        self.assertEqual(
            endpoints['authorize'],
            'https://github.com/login/oauth/authorize',
        )
        self.assertEqual(
            endpoints['token'],
            'https://github.com/login/oauth/access_token',
        )
        self.assertEqual(endpoints['user'], 'https://api.github.com/user')
        self.assertEqual(
            endpoints['emails'], 'https://api.github.com/user/emails'
        )

    def test_ghec_endpoints_route_oauth_to_tenant_host(self) -> None:
        plugin = GitHubIdentity()
        endpoints = plugin._endpoints(
            _ctx(connection=_connection('ghec', 'tenant.ghe.com'))
        )
        self.assertEqual(
            endpoints['authorize'],
            'https://tenant.ghe.com/login/oauth/authorize',
        )
        self.assertEqual(
            endpoints['token'],
            'https://tenant.ghe.com/login/oauth/access_token',
        )
        self.assertEqual(endpoints['user'], 'https://api.tenant.ghe.com/user')
        self.assertEqual(
            endpoints['emails'], 'https://api.tenant.ghe.com/user/emails'
        )

    def test_ghes_endpoints_route_through_appliance(self) -> None:
        plugin = GitHubIdentity()
        endpoints = plugin._endpoints(
            _ctx(connection=_connection('ghes', 'github.example.com'))
        )
        self.assertEqual(
            endpoints['authorize'],
            'https://github.example.com/login/oauth/authorize',
        )
        self.assertEqual(
            endpoints['user'],
            'https://github.example.com/api/v3/user',
        )

    def test_missing_connection_is_rejected(self) -> None:
        plugin = GitHubIdentity()
        with self.assertRaises(ValueError):
            plugin._endpoints(_ctx())

    def test_ghes_host_required(self) -> None:
        plugin = GitHubIdentity()
        with self.assertRaises(ValueError):
            plugin._endpoints(_ctx(connection=_connection('ghes')))

    def test_ghec_rejects_non_tenant_host(self) -> None:
        plugin = GitHubIdentity()
        with self.assertRaises(ValueError):
            plugin._endpoints(
                _ctx(connection=_connection('ghec', 'github.example.com'))
            )


class FlowTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_authorization_request_dot_com(self) -> None:
        plugin = GitHubIdentity()
        request = await plugin.authorization_request(
            _ctx(connection=_connection('github')),
            {'client_id': 'cid'},
            'https://imbi.test/cb',
        )
        parsed = urllib.parse.urlsplit(request.authorization_url)
        self.assertEqual(
            f'{parsed.scheme}://{parsed.netloc}{parsed.path}',
            'https://github.com/login/oauth/authorize',
        )
        params = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(
            params['scope'],
            ['read:user user:email repo workflow'],
        )
        self.assertEqual(params['client_id'], ['cid'])

    @respx.mock
    async def test_authorization_request_ghes_uses_host(self) -> None:
        plugin = GitHubIdentity()
        request = await plugin.authorization_request(
            _ctx(connection=_connection('ghes', 'github.example.com')),
            {'client_id': 'cid'},
            'https://imbi.test/cb',
        )
        parsed = urllib.parse.urlsplit(request.authorization_url)
        self.assertEqual(
            f'{parsed.scheme}://{parsed.netloc}{parsed.path}',
            'https://github.example.com/login/oauth/authorize',
        )

    async def test_authorization_request_without_connection_raises(
        self,
    ) -> None:
        plugin = GitHubIdentity()
        with self.assertRaises(ValueError):
            await plugin.authorization_request(
                _ctx(),
                {'client_id': 'cid'},
                'https://imbi.test/cb',
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
        plugin = GitHubIdentity()
        profile, credentials = await plugin.exchange_code(
            _ctx(connection=_connection('github')),
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

    async def test_exchange_code_without_connection_raises(self) -> None:
        plugin = GitHubIdentity()
        with self.assertRaises(ValueError):
            await plugin.exchange_code(
                _ctx(),
                {'client_id': 'cid', 'client_secret': 'sec'},
                'auth-code',
                'https://imbi.test/cb',
            )

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
        plugin = GitHubIdentity()
        profile, _ = await plugin.exchange_code(
            _ctx(connection=_connection('github')),
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
        plugin = GitHubIdentity()
        credentials = await plugin.refresh(
            _ctx(connection=_connection('github')),
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
        plugin = GitHubIdentity()
        credentials = await plugin.refresh(
            _ctx(connection=_connection('github')),
            {'client_id': 'cid', 'client_secret': 'sec'},
            'rt-keep',
        )
        self.assertEqual(credentials.refresh_token, 'rt-keep')

    @respx.mock
    async def test_token_failure_raises(self) -> None:
        respx.post('https://github.com/login/oauth/access_token').mock(
            return_value=httpx.Response(400, text='bad')
        )
        plugin = GitHubIdentity()
        with self.assertRaises(ValueError):
            await plugin.exchange_code(
                _ctx(connection=_connection('github')),
                {'client_id': 'cid', 'client_secret': 'sec'},
                'auth-code',
                'https://imbi.test/cb',
            )
