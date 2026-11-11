"""Tests for the ``github_app`` secret provider (ADR 0022, plan 9.8).

GitHub is mocked with respx: no request leaves the test. The broker
path (provider keys, release, fencing) is tested in imbi-api
(``apps/api/tests/test_secret_github_app.py``).
"""

import datetime
import json
import os
import typing
import unittest
import uuid
from unittest import mock

import httpx
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from imbi.common.plugins import secrets
from imbi.plugins.github import plugin
from imbi.plugins.github import secret_provider as github_app

PEM = (
    rsa.generate_private_key(public_exponent=65537, key_size=2048)
    .private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    .decode()
)
TOKEN = 'ghs_' + uuid.uuid4().hex
BASE = 'https://api.github.com'
INSTALLATION_URL = f'{BASE}/app/installations/42'
TOKENS_URL = f'{INSTALLATION_URL}/access_tokens'
REVOKE_URL = f'{BASE}/installation/token'
APP = github_app.GitHubApp(mock.Mock())
CONFIG = {'host': 'github.com'}
KEY_REFERENCE = 'secret://production/github/app_key'
LOCATOR = {
    'app_id': '7',
    'installation_id': '42',
    'private_key': KEY_REFERENCE,
    'repositories': ['octo/plugins'],
}
INSTALLATION = {
    'id': 42,
    'app_slug': 'imbi-agent',
    'account': {'login': 'Octo'},
    'permissions': {'contents': 'write', 'metadata': 'read'},
    'repository_selection': 'selected',
}
LEASE = json.dumps({'host': 'github.com', 'token': TOKEN})


def _context(
    purpose: str,
    binding_id: uuid.UUID | None = None,
    repository: str | None = None,
) -> secrets.ResolveContext:
    return secrets.ResolveContext(
        organization_id='org',
        task_id=uuid.uuid4(),
        project_id='project',
        purpose=purpose,
        ttl_seconds=300,
        credential_class='dynamic',
        binding_id=binding_id,
        repository=repository,
    )


def _mock_github() -> respx.Route:
    respx.get(INSTALLATION_URL).mock(
        return_value=httpx.Response(200, json=INSTALLATION)
    )
    return respx.post(TOKENS_URL).mock(
        return_value=httpx.Response(
            201, json={'token': TOKEN, 'expires_at': '2099-01-01T00:00:00Z'}
        )
    )


class HostAllowlistTestCase(unittest.TestCase):
    def test_hosts(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                github_app.GHES_HOSTS_ENV: (
                    'ghes.example.com, 10.1.2.3, 127.0.0.1, 169.254.169.254,'
                    ' [::1], 8.8.8.8'
                )
            },
        ):
            self.assertEqual(
                github_app.ghes_hosts(),
                frozenset({'ghes.example.com', '8.8.8.8'}),
            )
            for host in ('github.com', 'aweber.ghe.com', 'ghes.example.com'):
                self.assertTrue(github_app.allowed_host(host), host)
            for host in (
                'evil.example',
                'api.github.com',
                'api.aweber.ghe.com',
                'a.b.ghe.com',
                '10.1.2.3',
                '169.254.169.254',
            ):
                self.assertFalse(github_app.allowed_host(host), host)
        with mock.patch.dict(os.environ, {github_app.GHES_HOSTS_ENV: ''}):
            self.assertFalse(github_app.allowed_host('ghes.example.com'))


class ExpiryTestCase(unittest.TestCase):
    def test_expiry_is_always_aware(self) -> None:
        expiry = github_app._expiry  # pyright: ignore[reportPrivateUsage]
        utc = datetime.UTC
        self.assertEqual(
            expiry('2099-01-01T00:00:00'),
            datetime.datetime(2099, 1, 1, tzinfo=utc),
        )
        self.assertEqual(
            expiry('2099-01-01T00:00:00Z'),
            datetime.datetime(2099, 1, 1, tzinfo=utc),
        )
        self.assertEqual(
            expiry('2099-01-01T02:00:00+02:00'),
            datetime.datetime(2099, 1, 1, tzinfo=utc),
        )
        for value in ('not a date', None):
            self.assertIsNotNone(expiry(value).tzinfo)


class GitHubAppTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.private_key = mock.AsyncMock(
            return_value=secrets.Material(PEM.encode())
        )
        for target, name, value in (
            (APP, 'host', mock.Mock(provider_key=self.private_key)),
            (
                APP,
                'project_repository_ids',
                mock.AsyncMock(return_value=[101]),
            ),
        ):
            patcher = mock.patch.object(target, name, value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def test_declared_by_the_plugin(self) -> None:
        self.assertEqual(
            plugin.GitHubPlugin.manifest.secret_providers,
            [github_app.GitHubApp],
        )

    def test_repository(self) -> None:
        self.assertEqual(
            APP.repository({}, 'https://github.com/octo/demo.git'),
            ('github.com', 'octo/demo'),
        )
        self.assertEqual(
            APP.repository(
                {'host': 'aweber.ghe.com'}, 'https://aweber.ghe.com/a/b'
            ),
            ('aweber.ghe.com', 'a/b'),
        )
        for config, url in (
            ({}, 'https://aweber.ghe.com/a/b'),
            ({}, 'https://github.com/orgs/octo'),
            ({}, 'https://github.com/octo'),
        ):
            self.assertIsNone(APP.repository(config, url), url)

    def test_check_key_host(self) -> None:
        self.assertEqual(
            APP.check_key_host('https://AWeber.ghe.com'), 'aweber.ghe.com'
        )
        with self.assertRaises(ValueError):
            APP.check_key_host('evil.example')

    @respx.mock
    async def test_scope_by_purpose(self) -> None:
        route = _mock_github()
        binding_id = uuid.uuid4()
        expected = {
            'workspace_checkout': (
                {'repository_ids': [101]},
                {'contents': 'read'},
            ),
            'github_write': (
                {'repository_ids': [101]},
                {
                    'contents': 'write',
                    'issues': 'write',
                    'pull_requests': 'write',
                },
            ),
            'marketplace_fetch': (
                {'repositories': ['plugins']},
                {'contents': 'read'},
            ),
        }
        for purpose, (repositories, permissions) in expected.items():
            material = await APP.resolve(
                CONFIG, LOCATOR, None, _context(purpose, binding_id)
            )
            body = json.loads(route.calls.last.request.content)
            self.assertEqual(
                body, {'permissions': permissions} | repositories, purpose
            )
            self.assertEqual(material.value, TOKEN.encode())
            assert material.lease_id is not None
            self.assertEqual(
                json.loads(material.lease_id),
                {'host': 'github.com', 'token': TOKEN},
            )
            self.assertTrue(material.revocable)
            self.assertFalse(material.renewable)
            assert material.credential_expires_at is not None
            self.assertEqual(material.credential_expires_at.year, 2099)
            self.assertNotIn(TOKEN, repr(material))
        # The key is read for this binding, host, and App only.
        call = self.private_key.call_args
        self.assertEqual(call.args, ('org', KEY_REFERENCE))
        self.assertEqual(call.kwargs['consumer'], binding_id)
        self.assertEqual(call.kwargs['host'], 'github.com')
        self.assertEqual(call.kwargs['app_id'], '7')
        auth = route.calls.last.request.headers['Authorization']
        self.assertTrue(auth.startswith('Bearer ey'))

    @respx.mock
    async def test_unknown_purpose_is_refused(self) -> None:
        route = _mock_github()
        with self.assertRaises(secrets.BrokerError) as ctx:
            await APP.resolve(CONFIG, LOCATOR, None, _context('deploy'))
        self.assertEqual(
            (ctx.exception.code, ctx.exception.reason),
            ('secret_access_denied', 'purpose_not_supported'),
        )
        self.assertFalse(route.called)

    @respx.mock
    async def test_no_repositories_is_refused(self) -> None:
        route = _mock_github()
        with self.assertRaises(secrets.BrokerError) as ctx:
            await APP.resolve(
                CONFIG,
                LOCATOR | {'repositories': []},
                None,
                _context('marketplace_fetch'),
            )
        self.assertEqual(ctx.exception.reason, 'no_repositories')
        self.assertFalse(route.called)

    @respx.mock
    async def test_repository_of_another_owner_is_refused(self) -> None:
        route = _mock_github()
        with self.assertRaises(secrets.BrokerError) as ctx:
            await APP.resolve(
                CONFIG,
                LOCATOR | {'repositories': ['someone-else/plugins']},
                None,
                _context('marketplace_fetch'),
            )
        self.assertEqual(
            ctx.exception.reason, 'repository_outside_installation'
        )
        self.assertFalse(route.called)

    @respx.mock
    async def test_marketplace_fetch_for_one_repository(self) -> None:
        route = _mock_github()
        locator = LOCATOR | {'repositories': ['octo/plugins', 'Octo/Lint']}
        await APP.resolve(
            CONFIG,
            locator,
            None,
            _context('marketplace_fetch', repository='octo/lint'),
        )
        body = json.loads(route.calls.last.request.content)
        self.assertEqual(body['repositories'], ['lint'])
        with self.assertRaises(secrets.BrokerError) as ctx:
            await APP.resolve(
                CONFIG,
                locator,
                None,
                _context('marketplace_fetch', repository='octo/other'),
            )
        self.assertEqual(ctx.exception.reason, 'repository_not_allowed')

    @respx.mock
    async def test_marketplace_fetch_with_no_list_allows_any_one(self) -> None:
        route = _mock_github()
        await APP.resolve(
            CONFIG,
            LOCATOR | {'repositories': []},
            None,
            _context('marketplace_fetch', repository='octo/lint'),
        )
        body = json.loads(route.calls.last.request.content)
        self.assertEqual(body['repositories'], ['lint'])

    @respx.mock
    async def test_finds_the_installation_of_the_repositories(self) -> None:
        """A binding without an installation_id works in each org."""
        tools = {'id': 77, 'account': {'login': 'tools'}}
        respx.get(f'{BASE}/repos/tools/lint/installation').mock(
            return_value=httpx.Response(200, json=tools)
        )
        respx.get(f'{BASE}/repositories/101/installation').mock(
            return_value=httpx.Response(200, json=INSTALLATION)
        )
        tokens = respx.post(url__regex=rf'{BASE}/app/installations/\d+/.*')
        tokens.mock(
            return_value=httpx.Response(
                201,
                json={'token': TOKEN, 'expires_at': '2099-01-01T00:00:00Z'},
            )
        )
        locator = {
            k: v for k, v in LOCATOR.items() if k != 'installation_id'
        } | {'repositories': ['octo/plugins', 'tools/lint']}
        await APP.resolve(
            CONFIG,
            locator,
            None,
            _context('marketplace_fetch', repository='tools/lint'),
        )
        self.assertEqual(
            str(tokens.calls.last.request.url),
            f'{BASE}/app/installations/77/access_tokens',
        )
        self.assertEqual(
            json.loads(tokens.calls.last.request.content)['repositories'],
            ['lint'],
        )
        await APP.resolve(CONFIG, locator, None, _context('github_write'))
        self.assertEqual(str(tokens.calls.last.request.url), f'{TOKENS_URL}')
        # Two installations cannot share one token.
        self.project_repository_ids.return_value = [101, 202]
        respx.get(f'{BASE}/repositories/202/installation').mock(
            return_value=httpx.Response(200, json=tools)
        )
        with self.assertRaises(secrets.BrokerError) as ctx:
            await APP.resolve(CONFIG, locator, None, _context('github_write'))
        self.assertEqual(
            ctx.exception.reason, 'repositories_span_installations'
        )
        # An App that is not installed for the repository.
        respx.get(f'{BASE}/repos/tools/lint/installation').mock(
            return_value=httpx.Response(404)
        )
        with self.assertRaises(secrets.BrokerError) as ctx:
            await APP.resolve(
                CONFIG,
                locator,
                None,
                _context('marketplace_fetch', repository='tools/lint'),
            )
        self.assertEqual(ctx.exception.reason, 'installation_not_found')

    @respx.mock
    async def test_disallowed_host_gets_no_jwt(self) -> None:
        """A host that left the allowlist after the provider was saved."""
        route = respx.route().mock(return_value=httpx.Response(200))
        with self.assertRaises(secrets.BrokerError) as ctx:
            await APP.resolve(
                {'host': 'evil.example'},
                LOCATOR,
                None,
                _context('github_write'),
            )
        self.assertEqual(ctx.exception.reason, 'host_not_allowed')
        self.assertFalse(route.called)
        self.private_key.assert_not_called()

    @respx.mock
    async def test_github_errors_are_translated(self) -> None:
        respx.get(INSTALLATION_URL).mock(
            return_value=httpx.Response(200, json=INSTALLATION)
        )
        route = respx.post(TOKENS_URL)
        for status, code, reason in (
            (
                422,
                'secret_materialization_failed',
                'permission_or_repository_not_granted',
            ),
            (
                401,
                'secret_materialization_failed',
                'app_authentication_failed',
            ),
            (503, 'secret_provider_unavailable', 'throttled'),
        ):
            route.mock(
                return_value=httpx.Response(
                    status, json={'message': 'raw provider text'}
                )
            )
            with self.assertRaises(secrets.BrokerError) as ctx:
                await APP.resolve(
                    CONFIG, LOCATOR, None, _context('github_write')
                )
            self.assertEqual(
                (ctx.exception.code, ctx.exception.reason), (code, reason)
            )
            self.assertNotIn('raw provider text', str(ctx.exception))
        route.mock(side_effect=httpx.ConnectError('down'))
        with self.assertRaises(secrets.BrokerError) as ctx:
            await APP.resolve(CONFIG, LOCATOR, None, _context('github_write'))
        self.assertEqual(ctx.exception.reason, 'unreachable')

    async def test_bad_key_is_refused(self) -> None:
        self.private_key.return_value = secrets.Material(b'not a key')
        with self.assertRaises(secrets.BrokerError) as ctx:
            await APP.resolve(CONFIG, LOCATOR, None, _context('github_write'))
        self.assertEqual(ctx.exception.reason, 'invalid_private_key')

    async def test_field_is_refused(self) -> None:
        with self.assertRaises(secrets.BrokerError) as ctx:
            await APP.resolve(
                CONFIG, LOCATOR, 'token', _context('github_write')
            )
        self.assertEqual(ctx.exception.code, 'secret_field_not_allowed')

    @respx.mock
    async def test_revoke(self) -> None:
        route = respx.delete(REVOKE_URL).mock(return_value=httpx.Response(204))
        await APP.revoke(CONFIG, LEASE)
        self.assertEqual(
            route.calls.last.request.headers['Authorization'],
            f'Bearer {TOKEN}',
        )
        # A token that no longer works is revoked already.
        route.mock(return_value=httpx.Response(401))
        await APP.revoke(CONFIG, LEASE)
        route.mock(return_value=httpx.Response(500))
        with self.assertRaises(secrets.BrokerError) as ctx:
            await APP.revoke(CONFIG, LEASE)
        self.assertEqual(ctx.exception.code, 'provider_revocation_failed')
        route.mock(side_effect=httpx.ConnectError('down'))
        with self.assertRaises(secrets.BrokerError) as ctx:
            await APP.revoke(CONFIG, LEASE)
        self.assertEqual(ctx.exception.reason, 'unreachable')
        with self.assertRaises(secrets.BrokerError) as ctx:
            await APP.revoke(CONFIG, TOKEN)
        self.assertEqual(ctx.exception.reason, 'invalid_lease')

    @respx.mock
    async def test_revoke_uses_the_host_of_the_lease(self) -> None:
        """The provider host changed after the mint: the token goes back
        to the host that issued it, and never to a host off the list."""
        tenant = respx.delete('https://api.aweber.ghe.com/installation/token')
        tenant.mock(return_value=httpx.Response(204))
        other = respx.delete(REVOKE_URL).mock(return_value=httpx.Response(204))
        lease = json.dumps({'host': 'aweber.ghe.com', 'token': TOKEN})
        await APP.revoke(CONFIG, lease)
        self.assertTrue(tenant.called)
        self.assertFalse(other.called)
        with self.assertRaises(secrets.BrokerError) as ctx:
            await APP.revoke(
                CONFIG, json.dumps({'host': 'evil.example', 'token': TOKEN})
            )
        self.assertEqual(ctx.exception.reason, 'host_not_allowed')

    @respx.mock
    async def test_binding_test_returns_metadata_only(self) -> None:
        mint = _mock_github()
        respx.get(f'{BASE}/installation/repositories').mock(
            return_value=httpx.Response(
                200,
                json={
                    'total_count': 1,
                    'repositories': [{'full_name': 'octo/demo'}],
                },
            )
        )
        revoke = respx.delete(REVOKE_URL).mock(
            return_value=httpx.Response(204)
        )
        binding_id = uuid.uuid4()
        metadata = await APP.validate_binding(
            CONFIG, LOCATOR, 'org', binding_id=binding_id
        )
        self.assertEqual(
            self.private_key.call_args.kwargs['consumer'], binding_id
        )
        self.assertNotIn(TOKEN, json.dumps(metadata))
        self.assertEqual(
            json.loads(mint.calls.last.request.content),
            {'permissions': {'metadata': 'read'}},
        )
        self.assertTrue(revoke.called)
        self.assertEqual(
            metadata,
            {
                'app_slug': 'imbi-agent',
                'installation_id': '42',
                'account': 'Octo',
                'permissions': INSTALLATION['permissions'],
                'repository_selection': 'selected',
                'repository_count': 1,
                'repositories': ['octo/demo'],
                'token_expires_at': '2099-01-01T00:00:00+00:00',
            },
        )

    @respx.mock
    async def test_binding_test_without_installation_lists_them(self) -> None:
        respx.get(f'{BASE}/app').mock(
            return_value=httpx.Response(200, json={'slug': 'imbi-agent'})
        )
        respx.get(f'{BASE}/app/installations').mock(
            return_value=httpx.Response(
                200, json=[INSTALLATION, {'id': 77, 'account': {'login': 'x'}}]
            )
        )
        mint = respx.post(url__regex=rf'{BASE}/app/installations/.*')
        locator = {k: v for k, v in LOCATOR.items() if k != 'installation_id'}
        self.assertEqual(
            await APP.validate_binding(CONFIG, locator, 'org'),
            {
                'app_slug': 'imbi-agent',
                'installation_id': None,
                'installations': [
                    {'id': '42', 'account': 'Octo'},
                    {'id': '77', 'account': 'x'},
                ],
            },
        )
        self.assertFalse(mint.called)

    @respx.mock
    async def test_health(self) -> None:
        respx.get(f'{BASE}/meta').mock(return_value=httpx.Response(200))
        health = await APP.health(CONFIG, 'org')
        self.assertEqual(health.status, 'healthy')
        health = await APP.health({'host': 'evil.example'}, 'org')
        self.assertEqual(
            (health.status, health.reason), ('unhealthy', 'host_not_allowed')
        )

    def test_validation(self) -> None:
        self.assertEqual(APP.validate_config({}), {'host': 'github.com'})
        self.assertEqual(
            APP.validate_config({'host': 'https://AWeber.ghe.com'}),
            {'host': 'aweber.ghe.com'},
        )
        for config in (
            {'host': 'evil.example'},
            {'host': '10.0.0.1'},
            {'host': 'github.com', 'private_key': 'x'},
        ):
            with self.assertRaises(secrets.InvalidConfiguration):
                APP.validate_config(config)
        self.assertEqual(APP.validate_locator(LOCATOR, 'dynamic'), LOCATOR)
        for locator, credential_class in (
            (LOCATOR, 'static'),
            (LOCATOR | {'private_key': 'arn:aws:...'}, 'dynamic'),
            (LOCATOR | {'repositories': ['no-owner']}, 'dynamic'),
            (LOCATOR | {'installation_id': 'abc'}, 'dynamic'),
        ):
            with self.assertRaises(secrets.InvalidConfiguration):
                APP.validate_locator(
                    locator,
                    typing.cast(secrets.CredentialClass, credential_class),
                )


class ProjectRepositoryTestCase(unittest.IsolatedAsyncioTestCase):
    """Only a verified id of a GitHub Integration on the host counts."""

    async def _ids(self, rows: list[dict[str, typing.Any]]) -> list[int]:
        db = mock.Mock(execute=mock.AsyncMock(return_value=rows))
        app = github_app.GitHubApp(mock.Mock(graph=mock.Mock(return_value=db)))
        return await app.project_repository_ids('github.com', 'p')

    async def test_only_verified_ids_on_the_host(self) -> None:
        github = json.dumps({'flavor': 'github'})
        self.assertEqual(
            await self._ids(
                [
                    {'options': github, 'repository_id': 101},
                    {'options': github, 'repository_id': '101'},
                    # Another host does not count.
                    {
                        'options': json.dumps(
                            {'flavor': 'ghec', 'host': 'acme.ghe.com'}
                        ),
                        'repository_id': 202,
                    },
                ]
            ),
            [101],
        )
        for rows in (
            # A manual edge: no verified id.
            [{'options': github, 'repository_id': None}],
            [{'options': github, 'repository_id': 'octo/demo'}],
            [{'options': '{}', 'repository_id': 101}],
            [],
        ):
            with self.assertRaises(secrets.BrokerError) as ctx:
                await self._ids(rows)
            self.assertEqual(
                ctx.exception.reason, 'project_repository_unverified'
            )
        self.assertEqual(
            await APP.project_repository_ids('github.com', None), []
        )
