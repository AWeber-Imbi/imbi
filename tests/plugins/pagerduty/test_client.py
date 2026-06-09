"""Tests for the shared PagerDuty REST client."""

import unittest

import httpx
import respx
from imbi_common.plugins.errors import (
    PluginAuthenticationFailed,
    PluginRateLimited,
)

from imbi_plugin_pagerduty import _client

_CREDS = {'api_key': 'pd-key'}


class ApiKeyTestCase(unittest.TestCase):
    def test_returns_key(self) -> None:
        self.assertEqual(_client.api_key({'api_key': 'k'}), 'k')

    def test_missing_raises(self) -> None:
        with self.assertRaises(ValueError):
            _client.api_key({})


class ClientHeadersTestCase(unittest.TestCase):
    def test_auth_and_accept_headers(self) -> None:
        client = _client.client(_CREDS)
        self.assertEqual(client.headers['Authorization'], 'Token token=pd-key')
        self.assertIn('vnd.pagerduty+json', client.headers['Accept'])


class ErrorHookTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_401_raises_authentication_failed(self) -> None:
        respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(401, json={'error': 'unauthorized'})
        )
        async with _client.client(_CREDS) as client:
            with self.assertRaises(PluginAuthenticationFailed):
                await client.get('/services')

    @respx.mock
    async def test_429_raises_rate_limited_with_reset(self) -> None:
        respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(429, headers={'ratelimit-reset': '30'})
        )
        async with _client.client(_CREDS) as client:
            with self.assertRaises(PluginRateLimited) as cm:
                await client.get('/services')
        # retry_at is an absolute epoch in the near future
        self.assertGreater(cm.exception.retry_at, 0)
