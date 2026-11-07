"""Tests for the AI Provider token renewal (WIF plan 4.6)."""

import datetime
import functools
import json
import time
import unittest
from unittest import mock

import httpx

from imbi.common.llm import tokens
from imbi.common.plugins.identity import AccessToken, IdentityError


def _in(seconds: float) -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        seconds=seconds
    )


class TokenCacheTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.cache = tokens.TokenCache()
        self.now = 1000.0
        self.minted = 0
        self.fail: IdentityError | None = None
        # Replace the module references in tokens only: the event loop
        # must keep the real clock.
        clock = mock.patch('imbi.common.llm.tokens.time', wraps=time)
        clock.start().monotonic.side_effect = lambda: self.now
        self.addCleanup(clock.stop)
        jitter = mock.patch('imbi.common.llm.tokens.random')
        jitter.start().uniform.return_value = 0
        self.addCleanup(jitter.stop)

    async def _mint(self) -> AccessToken:
        if self.fail is not None:
            raise self.fail
        self.minted += 1
        return AccessToken(f'token-{self.minted}', _in(600))

    async def _get(self, key: str = 'k') -> str:
        return (await self.cache.get('slot', key, self._mint)).token

    async def test_reuses_then_renews_before_expiry(self) -> None:
        self.assertEqual(await self._get(), 'token-1')
        self.now += 400
        self.assertEqual(await self._get(), 'token-1')
        # 600 s lifetime: renew 120 s (20 percent) before expiry.
        self.now += 81
        self.assertEqual(await self._get(), 'token-2')

    async def test_failed_renewal_keeps_the_valid_token(self) -> None:
        await self._get()
        self.now += 500
        self.fail = IdentityError('unavailable', retryable=True)
        self.assertEqual(await self._get(), 'token-1')
        self.fail = None
        # The backoff (1 s) holds the next attempt.
        self.assertEqual(await self._get(), 'token-1')
        self.now += 1
        self.assertEqual(await self._get(), 'token-2')

    async def test_expired_token_is_not_returned(self) -> None:
        await self._get()
        self.now += 600
        self.fail = IdentityError('unavailable', retryable=True)
        with self.assertRaises(IdentityError):
            await self._get()

    async def test_invalidate_drops_only_the_current_token(self) -> None:
        await self._get()
        self.cache.invalidate('slot', 'token-0')
        self.assertEqual(await self._get(), 'token-1')
        self.cache.invalidate('slot', 'token-1')
        self.assertEqual(await self._get(), 'token-2')

    async def test_a_new_key_mints_again(self) -> None:
        await self._get()
        self.assertEqual(await self._get('other'), 'token-2')


class _Source:
    def __init__(self) -> None:
        self.tokens = iter(['t1', 't2'])
        self.current = ''
        self.invalidated: list[str] = []

    async def get(self) -> str:
        if not self.current:
            self.current = next(self.tokens)
        return self.current

    def invalidate(self, failed: str) -> None:
        self.invalidated.append(failed)
        self.current = ''


class BearerAuthTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_signs_and_retries_once_after_401(self) -> None:
        # The retry sends the same request object: copy the headers.
        seen: list[dict[str, str]] = []

        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(dict(request.headers))
            return httpx.Response(401 if len(seen) == 1 else 200)

        source = _Source()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle),
            auth=tokens.BearerAuth(source),
        ) as client:
            response = await client.post(
                'https://api.anthropic.com/v1/messages',
                headers={'x-api-key': 'sk-env', 'anthropic-beta': 'x-1'},
                content=b'{}',
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [h['authorization'] for h in seen],
            ['Bearer t1', 'Bearer t2'],
        )
        self.assertEqual(source.invalidated, ['t1'])
        self.assertNotIn('x-api-key', seen[0])
        self.assertEqual(seen[1]['anthropic-beta'], f'x-1,{tokens.OAUTH_BETA}')

    async def test_bearer_client_sends_the_token(self) -> None:
        seen: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={'data': [], 'has_more': False})

        with mock.patch.object(
            tokens.anthropic,
            'DefaultAsyncHttpxClient',
            functools.partial(
                tokens.anthropic.DefaultAsyncHttpxClient,
                transport=httpx.MockTransport(handle),
            ),
        ):
            client = tokens.bearer_client(_Source(), max_retries=0)
        async with client:
            await client.models.list()
        self.assertEqual(seen[0].headers['authorization'], 'Bearer t1')
        self.assertEqual(seen[0].headers['anthropic-beta'], tokens.OAUTH_BETA)


class ServiceTokenTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.requests: list[httpx.Request] = []
        self.reply: httpx.Response | Exception = httpx.Response(
            200, json={'token': 'tok', 'expires_at': _in(3600).isoformat()}
        )
        patcher = mock.patch.object(
            tokens.httpx,
            'AsyncClient',
            functools.partial(
                httpx.AsyncClient, transport=httpx.MockTransport(self._handle)
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.source = tokens.ServiceToken('http://imbi-api:8000/', 'ik_1_s')

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    async def test_get_then_renew_after_401(self) -> None:
        self.assertEqual(await self.source.get(), 'tok')
        self.assertEqual(await self.source.get(), 'tok')
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(
            str(request.url), 'http://imbi-api:8000/ai-providers/token'
        )
        self.assertEqual(request.headers['authorization'], 'Bearer ik_1_s')
        self.assertEqual(json.loads(request.content), {'failed': None})
        self.source.invalidate('tok')
        await self.source.get()
        self.assertEqual(
            json.loads(self.requests[1].content), {'failed': 'tok'}
        )

    async def test_errors(self) -> None:
        for reply, reason, retryable in (
            (httpx.ConnectError('down'), 'unreachable', True),
            (httpx.Response(503), 'unavailable', True),
            (httpx.Response(404), 'token_refused', False),
            (
                httpx.Response(200, json={'token': 't'}),
                'provider_error',
                False,
            ),
        ):
            with self.subTest(reason=reason):
                self.reply = reply
                with self.assertRaises(IdentityError) as ctx:
                    await tokens.ServiceToken('http://x', 'k').get()
                self.assertEqual(ctx.exception.reason, reason)
                self.assertEqual(ctx.exception.retryable, retryable)
