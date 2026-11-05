"""Tests for workload identity minting and its registry (WIF plan 4.4).

The store runs against the live Postgres that ``root:services`` boots.
The graph is a mock: only the agent ownership query reaches it.
"""

import datetime
import pickle
import unittest
from unittest import mock

from apps.api.tests import secret_support
from imbi.api.secret_broker import identity
from imbi.common.plugins import base
from imbi.common.plugins import identity as contract


class VendorTokenTestCase(secret_support.SecretCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        source = identity.SOURCES['fake']
        assert isinstance(source, identity.FakeIdentitySource)
        self.source = source
        source.requests = []
        source.fail = None
        self.exchanger = identity.FakeExchanger()
        self.db = mock.Mock()
        self.db.execute = mock.AsyncMock(return_value=[{'id': self.agent}])
        self.target = {'service_account_id': 'svcacct_1'}

    async def _mint(self, **target: str) -> contract.AccessToken:
        return await identity.vendor_token(
            self.db,
            self.store,
            self.org,
            self.exchanger,
            target or self.target,
            agent_id=self.agent,
        )

    async def _reason(self, **target: str) -> str:
        with self.assertRaises(contract.IdentityError) as ctx:
            await self._mint(**target)
        return ctx.exception.reason

    async def test_not_configured(self) -> None:
        self.assertEqual(
            await self._reason(), 'workload_identity_not_configured'
        )

    async def test_mints_with_core_claims_and_a_new_jwt(self) -> None:
        await self.store.put_identity_source(self.org, 'fake', {}, 'test')
        first = await self._mint()
        second = await self._mint()
        self.assertNotEqual(first.token, second.token)
        # A new JWT for each exchange: the fake refuses a reused one.
        self.assertEqual(len(set(self.exchanger.seen)), 2)
        request = self.source.requests[0]
        self.assertEqual(request.audience, self.exchanger.audience)
        self.assertEqual(request.duration_seconds, 300)
        self.assertEqual(request.signing_algorithm, 'RS256')
        self.assertEqual(
            request.tags, {'imbi_org': self.org, 'imbi_agent': self.agent}
        )

    async def test_refusals(self) -> None:
        await self.store.put_identity_source(self.org, 'fake', {}, 'test')
        self.assertEqual(await self._reason(other='x'), 'invalid_target')
        self.source.fail = 'access_denied'
        self.assertEqual(await self._reason(), 'access_denied')
        self.db.execute.return_value = []
        self.assertEqual(await self._reason(), 'agent_not_in_organization')
        self.assertEqual(self.source.requests, [])

    async def test_unknown_source(self) -> None:
        await self.store.put_identity_source(self.org, 'gone', {}, 'test')
        self.assertEqual(await self._reason(), 'unknown_identity_source')


class _Source(contract.IdentitySource):
    type = 'test_source'
    label = 'Test'


class _Other(contract.IdentitySource):
    type = 'test_source'
    label = 'Other'


def _entry(slug: str, *classes: type) -> mock.Mock:
    return mock.Mock(
        **{'manifest.slug': slug, 'manifest.identity_sources': list(classes)}
    )


class RegistryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        for target in (identity.SOURCES, identity._LOADED):  # pyright: ignore[reportPrivateUsage]
            patcher = mock.patch.dict(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(identity, '_REPORTED', set())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _plugins(self, *entries: mock.Mock) -> mock._patch[mock.MagicMock]:  # pyright: ignore[reportPrivateUsage]
        return mock.patch.object(
            identity.plugin_registry, 'list_plugins', return_value=entries
        )

    def test_load_conflict_and_removal(self) -> None:
        with (
            self._plugins(_entry('a', _Source), _entry('b', _Other)),
            self.assertLogs(identity.LOGGER, 'ERROR') as logs,
        ):
            source = identity.get('test_source')
            self.assertIsInstance(source, _Source)
            identity.all_sources()
        self.assertEqual(len(logs.output), 1)
        with self._plugins():
            with self.assertRaises(contract.IdentityError):
                identity.get('test_source')

    def test_manifest_refuses_a_duplicate_type(self) -> None:
        with self.assertRaisesRegex(ValueError, 'identity source type'):
            base.PluginManifest(
                slug='x',
                name='x',
                capabilities=[],
                identity_sources=[_Source, _Other],
            )


class AccessTokenTestCase(unittest.TestCase):
    def test_token_never_shows(self) -> None:
        token = contract.AccessToken(
            'sk-ant-oat01-secret', datetime.datetime.now(datetime.UTC)
        )
        self.assertNotIn('secret', repr(token) + str(token))
        self.assertEqual(len(token.fingerprint), 12)
        with self.assertRaises(TypeError):
            pickle.dumps(token)
