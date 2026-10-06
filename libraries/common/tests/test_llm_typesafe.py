"""Tests for the TypeSafe decision client."""

import json
import typing
import unittest

import httpx

from imbi.common.llm import typesafe

KEY = 'ts-secret-key-1234'
QUESTIONS = {'urgent': {'type': 'noul', 'instructions': 'Is it urgent?'}}
ANSWER = {
    'model': 'jev-latest',
    'answers': {'urgent': {'type': 'noul', 'noul': 0.82}},
    'usage': {'input_tokens': 12, 'output_tokens': 1},
}


def transport(
    handler: typing.Callable[[httpx.Request], httpx.Response],
) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


class DecideTestCase(unittest.IsolatedAsyncioTestCase):
    async def decide(
        self, handler: typing.Callable[[httpx.Request], httpx.Response]
    ) -> typesafe.DecisionResult:
        return await typesafe.decide(
            KEY,
            'https://api.typesafe.ai/v1/',
            'jev-latest',
            {'ticket': 'down'},
            QUESTIONS,
            transport=transport(handler),
        )

    async def test_sends_the_request_and_parses_answers(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=ANSWER)

        result = await self.decide(handler)
        self.assertEqual(result['answers']['urgent']['noul'], 0.82)
        self.assertEqual(result['usage']['input_tokens'], 12)
        request = seen[0]
        self.assertEqual(
            str(request.url), 'https://api.typesafe.ai/v1/systemone'
        )
        self.assertEqual(request.headers['authorization'], f'Bearer {KEY}')
        self.assertEqual(
            json.loads(request.content),
            {
                'model': 'jev-latest',
                'state': {'ticket': 'down'},
                'questions': QUESTIONS,
            },
        )

    async def test_errors_never_carry_the_key_or_body(self) -> None:
        cases: list[httpx.Response | Exception] = [
            httpx.Response(401, text=f'bad key {KEY}'),
            httpx.Response(429, text='slow down'),
            httpx.Response(529, text='overloaded'),
            httpx.Response(200, text='not json'),
            httpx.Response(200, json={'no': 'answers'}),
            httpx.ConnectError(f'boom {KEY}'),
            httpx.ReadTimeout('slow'),
        ]
        for case in cases:
            with self.subTest(case=repr(case)[:40]):

                def handler(
                    _request: httpx.Request,
                    case: httpx.Response | Exception = case,
                ) -> httpx.Response:
                    if isinstance(case, Exception):
                        raise case
                    return case

                with self.assertRaises(typesafe.DecisionError) as ctx:
                    await self.decide(handler)
                self.assertNotIn(KEY, str(ctx.exception))
                self.assertNotIn('slow down', str(ctx.exception))

    async def test_caps_the_response_size(self) -> None:
        big = b'x' * (typesafe.MAX_RESPONSE_BYTES + 1)
        with self.assertRaisesRegex(typesafe.DecisionError, 'too large'):
            await self.decide(lambda _r: httpx.Response(200, content=big))
