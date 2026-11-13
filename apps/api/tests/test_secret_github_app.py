"""The broker path of the ``github_app`` secret provider (ADR 0022, 9.8).

The provider key, materialize, release, and fencing, with the provider
of the GitHub plugin. The provider itself is tested in the plugin
(``plugins/github/tests/test_secret_provider.py``). GitHub is mocked
with respx: no request leaves the test.
"""

import json
import typing
import uuid
from unittest import mock

import httpx
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from apps.api.tests import secret_support
from imbi.api import secret_broker
from imbi.api.secret_broker import providers, store
from imbi.common.auth import encryption
from imbi.plugins.github import secret_provider

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
CONFIG = {'host': 'github.com'}
KEY_REFERENCE = 'secret://production/github/app_key'
LOCATOR = {
    'app_id': '7',
    'installation_id': '42',
    'private_key': KEY_REFERENCE,
    'repositories': ['octo/plugins'],
}


def _mock_github() -> None:
    respx.get(INSTALLATION_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                'id': 42,
                'account': {'login': 'Octo'},
                'repository_selection': 'selected',
            },
        )
    )
    respx.post(TOKENS_URL).mock(
        return_value=httpx.Response(
            201, json={'token': TOKEN, 'expires_at': '2099-01-01T00:00:00Z'}
        )
    )


class GitHubAppBrokerTestCase(secret_support.SecretCase):
    """The broker path: the provider key, materialize, release, fencing."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.app = secret_provider.GitHubApp(
            providers._Host()  # pyright: ignore[reportPrivateUsage]
        )
        patcher = mock.patch.dict(
            providers.PROVIDERS, {'github_app': self.app}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake.values['app_key'] = PEM.encode()
        provider = await self.store.create(
            'providers',
            self.org,
            {
                'name': 'github',
                'type': 'github_app',
                'config': CONFIG,
                'capabilities': sorted(self.app.capabilities),
                'created_by': 'test',
            },
        )
        self.app_binding = await self.add_binding(
            reference='secret://production/github/app',
            provider_id=provider['id'],
            credential_class='dynamic',
            locator=LOCATOR,
        )
        self.key_binding = await self.add_binding(
            reference=KEY_REFERENCE,
            locator={'key': 'app_key'},
            provider_key_usage={
                'host': 'github.com',
                'app_id': '7',
                'consumers': [str(self.app_binding['id'])],
            },
        )
        await self.store.update(
            'grants',
            self.org,
            self.grant['id'],
            {'binding_ids': [self.binding['id'], self.app_binding['id']]},
        )
        for target, name, value in (
            (secret_broker, '_broker', self.broker),
            (
                self.app,
                'project_repository_ids',
                mock.AsyncMock(return_value=[101]),
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

    async def _key(self, **changes: typing.Any) -> None:
        values: dict[str, typing.Any] = {
            'consumer': self.app_binding['id'],
            'host': 'github.com',
            'app_id': '7',
        } | changes
        await self.broker.provider_key(self.org, KEY_REFERENCE, **values)

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
        self.assertEqual(
            json.loads(encryption.decrypt_token(row['lease_id'])),
            {'host': 'github.com', 'token': TOKEN},
        )
        released = await self.broker.release(
            resolution_id, reason='child_exited', actor='runner:x'
        )
        self.assertEqual(released['revocation_state'], 'succeeded')
        self.assertEqual(revoke.call_count, 1)
        # The key was read through the broker, and audited without it.
        events = await self.audit_events()
        key_events = [e for e in events if e.purpose == 'provider_key']
        self.assertEqual(len(key_events), 1)
        self.assertEqual(key_events[0].result, 'succeeded')
        for event in events:
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

    async def test_key_needs_a_provider_key_mark(self) -> None:
        """A plain static binding of the org is not an App key."""
        await self._key()
        with self.assertRaises(providers.BrokerError) as ctx:
            await self.broker.provider_key(
                self.org,
                'secret://production/github/token',
                consumer=self.app_binding['id'],
                host='github.com',
                app_id='7',
            )
        self.assertEqual(ctx.exception.reason, 'not_a_provider_key')
        with self.assertRaises(providers.BrokerError) as ctx:
            await self.broker.provider_key(
                self.org,
                'secret://production/github/app',
                consumer=self.app_binding['id'],
                host='github.com',
                app_id='7',
            )
        self.assertEqual(ctx.exception.reason, 'not_a_provider_key')
        with self.assertRaises(providers.BrokerError) as ctx:
            await self.broker.provider_key(
                'another-org',
                KEY_REFERENCE,
                consumer=self.app_binding['id'],
                host='github.com',
                app_id='7',
            )
        self.assertEqual(ctx.exception.code, 'secret_binding_not_found')

    async def test_key_is_only_for_its_consumers_host_and_app(self) -> None:
        for changes, reason in (
            ({'consumer': uuid.uuid4()}, 'provider_key_consumer'),
            ({'consumer': None}, 'provider_key_consumer'),
            ({'host': 'aweber.ghe.com'}, 'provider_key_mismatch'),
            ({'app_id': '8'}, 'provider_key_mismatch'),
        ):
            with self.assertRaises(providers.BrokerError) as ctx:
                await self._key(**changes)
            self.assertEqual(ctx.exception.reason, reason, changes)

    async def test_key_cannot_be_granted_to_a_task(self) -> None:
        with self.assertRaises(store.ProviderKeyBinding):
            await self.store.update(
                'grants',
                self.org,
                self.grant['id'],
                {'binding_ids': [self.key_binding['id']]},
            )
        # A grant from before the store refused this still gets nothing.
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE secrets.grants SET binding_ids = %s WHERE id = %s',
                ([self.key_binding['id']], self.grant['id']),
            )
        with self.assertRaises(providers.BrokerError) as ctx:
            await self.broker.create_resolution(
                self.context(), self.request(reference=KEY_REFERENCE)
            )
        self.assertEqual(ctx.exception.reason, 'provider_key_binding')

    async def test_check_locator(self) -> None:
        await self.app.check_locator(CONFIG, LOCATOR, self.org)
        for config, locator in (
            ({'host': 'aweber.ghe.com'}, LOCATOR),
            (CONFIG, LOCATOR | {'app_id': '8'}),
            (
                CONFIG,
                LOCATOR | {'private_key': 'secret://production/github/token'},
            ),
        ):
            with self.assertRaises(providers.InvalidConfiguration):
                await self.app.check_locator(config, locator, self.org)
