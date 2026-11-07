"""Tests for the Anthropic exchanger and the ``anthropic_wif`` provider.

The token endpoint is an httpx mock transport: no call leaves the test.
"""

import datetime
import functools
import json
import unittest
import uuid
from unittest import mock

import httpx

from imbi.common.plugins import identity, secrets
from imbi.plugins.anthropic import plugin, wif

TARGET = {
    'organization_id': 'org_1',
    'federation_rule_id': 'fdrl_1',
    'service_account_id': 'svac_1',
}


def _context(agent_id: str | None = 'agent-1') -> secrets.ResolveContext:
    return secrets.ResolveContext(
        organization_id='org',
        task_id=uuid.uuid4(),
        project_id=None,
        purpose='model_inference',
        ttl_seconds=900,
        credential_class='dynamic',
        agent_id=agent_id,
    )


class ExchangerTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.requests: list[httpx.Request] = []
        self.reply: httpx.Response | Exception = httpx.Response(
            200,
            json={
                'access_token': 'sk-ant-oat01-secret',
                'expires_in': 3600,
                'scope': 'workspace:inference',
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
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    async def _error(self) -> identity.IdentityError:
        with self.assertRaises(identity.IdentityError) as ctx:
            await wif.EXCHANGER.exchange(TARGET, 'eyJ.jwt')
        return ctx.exception

    async def test_exchange(self) -> None:
        before = datetime.datetime.now(datetime.UTC)
        token = await wif.EXCHANGER.exchange(TARGET, 'eyJ.jwt')
        self.assertEqual(token.token, 'sk-ant-oat01-secret')
        self.assertEqual(token.scope, 'workspace:inference')
        self.assertGreaterEqual(
            token.expires_at, before + datetime.timedelta(seconds=3600)
        )
        request = self.requests[0]
        self.assertEqual(str(request.url), wif.TOKEN_URL)
        self.assertEqual(
            request.headers['anthropic-beta'],
            'oauth-2025-04-20,oidc-federation-2026-04-01',
        )
        self.assertEqual(
            json.loads(request.content),
            {
                'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                'assertion': 'eyJ.jwt',
                **TARGET,
            },
        )

    async def test_errors(self) -> None:
        for reply, reason, retryable in (
            (
                httpx.Response(401, text='Authentication failed'),
                'exchange_refused',
                False,
            ),
            (
                httpx.Response(302, headers={'Location': 'https://x'}),
                'exchange_refused',
                False,
            ),
            (httpx.Response(429), 'unavailable', True),
            (httpx.Response(503), 'unavailable', True),
            (httpx.ConnectError('down'), 'unreachable', True),
            (httpx.Response(200, text='not json'), 'provider_error', False),
            (
                httpx.Response(200, json={'access_token': ''}),
                'provider_error',
                False,
            ),
            (
                httpx.Response(
                    200, json={'access_token': 't', 'expires_in': 1e20}
                ),
                'provider_error',
                False,
            ),
        ):
            with self.subTest(reason=reason, reply=reply):
                self.reply = reply
                error = await self._error()
                self.assertEqual(error.reason, reason)
                self.assertEqual(error.retryable, retryable)
        # Redirects are not followed.
        self.assertNotIn('https://x', [str(r.url) for r in self.requests])

    def test_target(self) -> None:
        self.assertEqual(wif.EXCHANGER.validate_target(TARGET), TARGET)
        for bad in (
            {**TARGET, 'extra': 'x'},
            {'organization_id': 'org_1'},
            {**TARGET, 'service_account_id': '../x'},
        ):
            with self.assertRaises(identity.InvalidConfiguration):
                wif.EXCHANGER.validate_target(bad)


class ProviderTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.host = mock.Mock()
        self.expires = datetime.datetime.now(datetime.UTC)
        self.host.vendor_token = mock.AsyncMock(
            return_value=identity.AccessToken('sk-ant-oat01-x', self.expires)
        )
        self.provider = wif.AnthropicWif(self.host)

    async def _resolve(self, **kwargs: object) -> secrets.Material:
        return await self.provider.resolve(
            {},
            TARGET,
            kwargs.get('field'),
            kwargs.get('context') or _context(),  # type: ignore[arg-type]
        )

    async def test_resolve_mints_for_the_agent(self) -> None:
        material = await self._resolve()
        self.assertEqual(material.value, b'sk-ant-oat01-x')
        self.assertEqual(material.credential_expires_at, self.expires)
        self.assertTrue(material.bearer)
        self.host.vendor_token.assert_awaited_once_with(
            'org', wif.EXCHANGER, TARGET, agent_id='agent-1'
        )

    async def test_resolve_refusals(self) -> None:
        for kwargs, code in (
            ({'field': 'api-key'}, 'secret_field_not_allowed'),
            ({'context': _context(None)}, 'secret_access_denied'),
        ):
            with self.subTest(code=code):
                with self.assertRaises(secrets.BrokerError) as ctx:
                    await self._resolve(**kwargs)
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
        manifest = plugin.AnthropicPlugin.manifest
        self.assertEqual(manifest.capabilities, [])
        self.assertEqual(manifest.secret_providers, [wif.AnthropicWif])
