"""Tests for the OpenAI exchanger and the ``openai_wif`` provider.

The token endpoint is an httpx mock transport: no call leaves the test.
The error mapping is tested with the Anthropic exchanger, which uses
the same :func:`identity.post_exchange`.
"""

import datetime
import functools
import json
import unittest
import uuid
from unittest import mock

import httpx

from imbi.common.plugins import identity, secrets
from imbi.plugins.openai import plugin, wif

TARGET = {'identity_provider_id': 'idp_1', 'service_account_id': 'sa_1'}


class ExchangerTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.requests: list[httpx.Request] = []
        self.reply = httpx.Response(
            200,
            json={
                'access_token': 'openai-token',
                'issued_token_type': (
                    'urn:ietf:params:oauth:token-type:access_token'
                ),
                'token_type': 'Bearer',
                'expires_in': 3600,
                'expires_at': 1_800_000_000,
            },
        )
        patcher = mock.patch.object(
            identity.httpx,
            'AsyncClient',
            functools.partial(
                httpx.AsyncClient, transport=httpx.MockTransport(self._handle)
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.reply

    async def test_exchange(self) -> None:
        before = datetime.datetime.now(datetime.UTC)
        token = await wif.EXCHANGER.exchange(TARGET, 'eyJ.jwt')
        self.assertEqual(token.token, 'openai-token')
        self.assertIsNone(token.scope)
        self.assertGreaterEqual(
            token.expires_at, before + datetime.timedelta(seconds=3600)
        )
        request = self.requests[0]
        self.assertEqual(str(request.url), wif.TOKEN_URL)
        self.assertEqual(request.headers['content-type'], 'application/json')
        self.assertEqual(
            json.loads(request.content),
            {
                'grant_type': (
                    'urn:ietf:params:oauth:grant-type:token-exchange'
                ),
                'subject_token': 'eyJ.jwt',
                'subject_token_type': 'urn:ietf:params:oauth:token-type:jwt',
                **TARGET,
            },
        )

    async def test_refused(self) -> None:
        self.reply = httpx.Response(400, json={'error': 'invalid_grant'})
        with self.assertRaises(identity.IdentityError) as ctx:
            await wif.EXCHANGER.exchange(TARGET, 'eyJ.jwt')
        self.assertEqual(ctx.exception.reason, 'exchange_refused')

    def test_target(self) -> None:
        self.assertEqual(wif.EXCHANGER.validate_target(TARGET), TARGET)
        for bad in (
            {**TARGET, 'extra': 'x'},
            {'identity_provider_id': 'idp_1'},
            {**TARGET, 'service_account_id': '../x'},
        ):
            with self.assertRaises(identity.InvalidConfiguration):
                wif.EXCHANGER.validate_target(bad)

    def test_claims(self) -> None:
        self.assertEqual(wif.EXCHANGER.audience, 'https://api.openai.com/v1')
        self.assertEqual(wif.EXCHANGER.jwt_seconds, 3300)


class ProviderTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.host = mock.Mock()
        self.expires = datetime.datetime.now(datetime.UTC)
        self.host.vendor_token = mock.AsyncMock(
            return_value=identity.AccessToken('openai-token', self.expires)
        )
        self.provider = wif.OpenAIWif(self.host)

    def _context(self, agent_id: str | None) -> secrets.ResolveContext:
        return secrets.ResolveContext(
            organization_id='org',
            task_id=uuid.uuid4(),
            project_id=None,
            purpose='model_inference',
            ttl_seconds=900,
            credential_class='dynamic',
            agent_id=agent_id,
        )

    async def test_resolve_mints_for_the_agent(self) -> None:
        material = await self.provider.resolve(
            {}, TARGET, None, self._context('agent-1')
        )
        self.assertEqual(material.value, b'openai-token')
        self.assertEqual(material.credential_expires_at, self.expires)
        self.assertTrue(material.bearer)
        self.host.vendor_token.assert_awaited_once_with(
            'org', wif.EXCHANGER, TARGET, agent_id='agent-1'
        )

    async def test_resolve_refusals(self) -> None:
        for field, agent_id, code in (
            ('api-key', 'agent-1', 'secret_field_not_allowed'),
            (None, None, 'secret_access_denied'),
        ):
            with self.subTest(code=code):
                with self.assertRaises(secrets.BrokerError) as ctx:
                    await self.provider.resolve(
                        {}, TARGET, field, self._context(agent_id)
                    )
                self.assertEqual(ctx.exception.code, code)
        self.host.vendor_token.assert_not_awaited()

    def test_config_and_locator(self) -> None:
        self.assertEqual(self.provider.validate_config({}), {})
        with self.assertRaises(secrets.InvalidConfiguration):
            self.provider.validate_config({'api_key': 'x'})
        self.assertEqual(
            self.provider.validate_locator(TARGET, 'dynamic'), TARGET
        )
        with self.assertRaises(secrets.InvalidConfiguration):
            self.provider.validate_locator(TARGET, 'static')

    def test_manifest(self) -> None:
        manifest = plugin.OpenAIPlugin.manifest
        self.assertEqual(manifest.capabilities, [])
        self.assertEqual(manifest.secret_providers, [wif.OpenAIWif])
        self.assertEqual(manifest.token_exchangers, [wif.OpenAIExchanger])
