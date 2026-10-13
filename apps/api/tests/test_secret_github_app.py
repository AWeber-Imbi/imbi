"""Tests for the ``github_app`` secret provider (ADR 0022, plan 9.8).

GitHub is mocked with respx: no request leaves the test.
"""

import json
import typing
import unittest
import uuid
from unittest import mock

import httpx
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from apps.api.tests import secret_support
from imbi.api import secret_broker
from imbi.api.secret_broker import github_app, providers
from imbi.common.auth import encryption

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
APP = github_app.GitHubApp()
CONFIG = {'host': 'github.com'}
LOCATOR = {
    'app_id': '7',
    'installation_id': '42',
    'private_key': 'secret://production/github/app_key',
    'repositories': ['octo/plugins'],
}
INSTALLATION = {
    'id': 42,
    'app_slug': 'imbi-agent',
    'account': {'login': 'Octo'},
    'permissions': {'contents': 'write', 'metadata': 'read'},
    'repository_selection': 'selected',
}


def _context(purpose: str) -> providers.ResolveContext:
    return providers.ResolveContext(
        organization_id='org',
        task_id=uuid.uuid4(),
        project_id='project',
        purpose=purpose,
        ttl_seconds=300,
        credential_class='dynamic',
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


class GitHubAppTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        super().setUp()
        for name, value in (
            ('private_key', mock.AsyncMock(return_value=PEM)),
            (
                'project_repositories',
                mock.AsyncMock(return_value=['octo/demo']),
            ),
        ):
            patcher = mock.patch.object(github_app, name, value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def test_registered(self) -> None:
        self.assertIsInstance(
            providers.get('github_app'), github_app.GitHubApp
        )

    @respx.mock
    async def test_scope_by_purpose(self) -> None:
        route = _mock_github()
        expected = {
            'workspace_checkout': (['demo'], {'contents': 'read'}),
            'github_write': (
                ['demo'],
                {
                    'contents': 'write',
                    'issues': 'write',
                    'pull_requests': 'write',
                },
            ),
            'marketplace_fetch': (['plugins'], {'contents': 'read'}),
        }
        for purpose, (repositories, permissions) in expected.items():
            material = await APP.resolve(
                CONFIG, LOCATOR, None, _context(purpose)
            )
            body = json.loads(route.calls.last.request.content)
            self.assertEqual(
                body,
                {'permissions': permissions, 'repositories': repositories},
                purpose,
            )
            self.assertEqual(material.value, TOKEN.encode())
            self.assertEqual(material.lease_id, TOKEN)
            self.assertTrue(material.revocable)
            self.assertFalse(material.renewable)
            self.assertEqual(material.credential_expires_at.year, 2099)  # type: ignore[union-attr]
            self.assertNotIn(TOKEN, repr(material))
        # The App signs with the key from the binding reference.
        self.assertEqual(
            self.private_key.call_args.args[:2],
            ('org', LOCATOR['private_key']),
        )
        auth = route.calls.last.request.headers['Authorization']
        self.assertTrue(auth.startswith('Bearer ey'))

    @respx.mock
    async def test_unknown_purpose_is_refused(self) -> None:
        route = _mock_github()
        with self.assertRaises(providers.BrokerError) as ctx:
            await APP.resolve(CONFIG, LOCATOR, None, _context('deploy'))
        self.assertEqual(
            (ctx.exception.code, ctx.exception.reason),
            ('secret_access_denied', 'purpose_not_supported'),
        )
        self.assertFalse(route.called)

    @respx.mock
    async def test_no_repositories_is_refused(self) -> None:
        route = _mock_github()
        self.project_repositories.return_value = []
        with self.assertRaises(providers.BrokerError) as ctx:
            await APP.resolve(
                CONFIG, LOCATOR, None, _context('workspace_checkout')
            )
        self.assertEqual(ctx.exception.reason, 'no_repositories')
        with self.assertRaises(providers.BrokerError) as ctx:
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
        self.project_repositories.return_value = ['someone-else/demo']
        with self.assertRaises(providers.BrokerError) as ctx:
            await APP.resolve(CONFIG, LOCATOR, None, _context('github_write'))
        self.assertEqual(
            ctx.exception.reason, 'repository_outside_installation'
        )
        self.assertFalse(route.called)

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
            with self.assertRaises(providers.BrokerError) as ctx:
                await APP.resolve(
                    CONFIG, LOCATOR, None, _context('github_write')
                )
            self.assertEqual(
                (ctx.exception.code, ctx.exception.reason), (code, reason)
            )
            self.assertNotIn('raw provider text', str(ctx.exception))
        route.mock(side_effect=httpx.ConnectError('down'))
        with self.assertRaises(providers.BrokerError) as ctx:
            await APP.resolve(CONFIG, LOCATOR, None, _context('github_write'))
        self.assertEqual(ctx.exception.reason, 'unreachable')

    async def test_bad_key_is_refused(self) -> None:
        self.private_key.return_value = 'not a key'
        with self.assertRaises(providers.BrokerError) as ctx:
            await APP.resolve(CONFIG, LOCATOR, None, _context('github_write'))
        self.assertEqual(ctx.exception.reason, 'invalid_private_key')

    async def test_field_is_refused(self) -> None:
        with self.assertRaises(providers.BrokerError) as ctx:
            await APP.resolve(
                CONFIG, LOCATOR, 'token', _context('github_write')
            )
        self.assertEqual(ctx.exception.code, 'secret_field_not_allowed')

    @respx.mock
    async def test_revoke(self) -> None:
        route = respx.delete(REVOKE_URL).mock(return_value=httpx.Response(204))
        await APP.revoke(CONFIG, TOKEN)
        self.assertEqual(
            route.calls.last.request.headers['Authorization'],
            f'Bearer {TOKEN}',
        )
        # A token that no longer works is revoked already.
        route.mock(return_value=httpx.Response(401))
        await APP.revoke(CONFIG, TOKEN)
        route.mock(return_value=httpx.Response(500))
        with self.assertRaises(providers.BrokerError) as ctx:
            await APP.revoke(CONFIG, TOKEN)
        self.assertEqual(ctx.exception.code, 'provider_revocation_failed')
        route.mock(side_effect=httpx.ConnectError('down'))
        with self.assertRaises(providers.BrokerError) as ctx:
            await APP.revoke(CONFIG, TOKEN)
        self.assertEqual(ctx.exception.reason, 'unreachable')

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
        metadata = await APP.validate_binding(CONFIG, LOCATOR, 'org')
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
    async def test_health(self) -> None:
        respx.get(f'{BASE}/meta').mock(return_value=httpx.Response(200))
        health = await APP.health(CONFIG, 'org')
        self.assertEqual(health.status, 'healthy')
        respx.get('https://ghes.example.com/api/v3/meta').mock(
            side_effect=httpx.ConnectError('down')
        )
        health = await APP.health({'host': 'ghes.example.com'}, 'org')
        self.assertEqual(
            (health.status, health.reason), ('unhealthy', 'unreachable')
        )

    def test_validation(self) -> None:
        self.assertEqual(APP.validate_config({}), {'host': 'github.com'})
        self.assertEqual(
            APP.validate_config({'host': 'https://Acme.ghe.com'}),
            {'host': 'acme.ghe.com'},
        )
        with self.assertRaises(providers.InvalidConfiguration):
            APP.validate_config({'host': 'github.com', 'private_key': 'x'})
        self.assertEqual(APP.validate_locator(LOCATOR, 'dynamic'), LOCATOR)
        for locator, credential_class in (
            (LOCATOR, 'static'),
            (LOCATOR | {'private_key': 'arn:aws:...'}, 'dynamic'),
            (LOCATOR | {'repositories': ['no-owner']}, 'dynamic'),
            (LOCATOR | {'installation_id': 'abc'}, 'dynamic'),
        ):
            with self.assertRaises(providers.InvalidConfiguration):
                APP.validate_locator(
                    locator,
                    typing.cast(providers.CredentialClass, credential_class),
                )


class GitHubAppBrokerTestCase(secret_support.SecretCase):
    """The broker path: key binding, materialize, release, fencing."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.fake.values['app_key'] = PEM.encode()
        await self.add_binding(
            reference='secret://production/github/app_key',
            locator={'key': 'app_key'},
        )
        provider = await self.store.create(
            'providers',
            self.org,
            {
                'name': 'github',
                'type': 'github_app',
                'config': CONFIG,
                'capabilities': sorted(APP.capabilities),
                'created_by': 'test',
            },
        )
        binding = await self.add_binding(
            reference='secret://production/github/app',
            provider_id=provider['id'],
            credential_class='dynamic',
            locator=LOCATOR,
        )
        await self.store.update(
            'grants',
            self.org,
            self.grant['id'],
            {'binding_ids': [self.binding['id'], binding['id']]},
        )
        for target, name, value in (
            (secret_broker, '_broker', self.broker),
            (
                github_app,
                'project_repositories',
                mock.AsyncMock(return_value=['octo/demo']),
            ),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _materialized(self) -> uuid.UUID:
        created = await self.broker.create_resolution(
            self.context(),
            self.request(reference='secret://production/github/app'),
        )
        result = await self.broker.materialize(
            self.executor(), self.materialize_request(created.handle)
        )
        self.assertEqual(result.material, TOKEN)
        return created.resolution_id

    @respx.mock
    async def test_release_revokes_the_token(self) -> None:
        _mock_github()
        revoke = respx.delete(REVOKE_URL).mock(
            return_value=httpx.Response(204)
        )
        resolution_id = await self._materialized()
        row = await self.broker.get(resolution_id)
        assert row is not None
        self.assertNotIn(TOKEN, str(row))
        self.assertEqual(encryption.decrypt_token(row['lease_id']), TOKEN)
        released = await self.broker.release(
            resolution_id, reason='child_exited', actor='runner:x'
        )
        self.assertEqual(released['revocation_state'], 'succeeded')
        self.assertEqual(revoke.call_count, 1)
        # The key was read through the broker, and audited without it.
        key_events = [e for e in self.events if e.purpose == 'provider_key']
        self.assertEqual(len(key_events), 1)
        self.assertEqual(key_events[0].result, 'succeeded')
        for event in self.events:
            self.assertNotIn(TOKEN, event.model_dump_json())
            self.assertNotIn('PRIVATE KEY', event.model_dump_json())

    @respx.mock
    async def test_fencing_revokes_the_token(self) -> None:
        _mock_github()
        revoke = respx.delete(REVOKE_URL).mock(
            return_value=httpx.Response(204)
        )
        await self._materialized()
        self.assertTrue(
            await self.broker.release_runner_resolutions(self.runner)
        )
        self.assertEqual(revoke.call_count, 1)

    async def test_dynamic_key_binding_is_refused(self) -> None:
        with self.assertRaises(providers.BrokerError) as ctx:
            await self.broker.provider_key(
                self.org, 'secret://production/github/app'
            )
        self.assertEqual(ctx.exception.reason, 'dynamic_key_binding')
        with self.assertRaises(providers.BrokerError) as ctx:
            await self.broker.provider_key(
                'another-org', 'secret://production/github/app_key'
            )
        self.assertEqual(ctx.exception.code, 'secret_binding_not_found')
