"""Tests for the LiteLLM price lookup."""

import decimal
import json
import typing
import unittest
import unittest.mock

import httpx

from imbi.common.llm import discovery, prices

D = decimal.Decimal

#: Trimmed from the LiteLLM price file.
TABLE: dict[str, typing.Any] = {
    'sample_spec': {'litellm_provider': 'one of https://docs.litellm.ai'},
    'claude-sonnet-5-5': {
        'cache_creation_input_token_cost': 0.0000025,
        'cache_read_input_token_cost': 1e-07,
        'input_cost_per_token': 0.000002,
        'litellm_provider': 'anthropic',
        'output_cost_per_token': 0.00001,
    },
    'gpt-5.6-luna': {
        'cache_read_input_token_cost': 2e-08,
        'input_cost_per_token': 2e-07,
        'litellm_provider': 'openai',
        'output_cost_per_token': 0.0000012,
    },
    'openai/gpt-prefixed': {
        'input_cost_per_token': 1e-08,
        'litellm_provider': 'openai',
    },
    'text-embedding-free': {'litellm_provider': 'openai', 'mode': 'embed'},
}
PRICED = prices._priced(TABLE)


class LookupTestCase(unittest.TestCase):
    def test_exact_key(self) -> None:
        self.assertEqual(
            prices.lookup(PRICED, 'claude-sonnet-5-5', 'anthropic'),
            (
                'claude-sonnet-5-5',
                {
                    'input_cost_per_million': D('2'),
                    'output_cost_per_million': D('10'),
                    'cache_read_cost_per_million': D('0.1'),
                    'cache_write_cost_per_million': D('2.5'),
                },
            ),
        )

    def test_missing_price_is_none(self) -> None:
        match = prices.lookup(PRICED, 'gpt-5.6-luna', 'openai')
        assert match is not None
        self.assertEqual(match[1]['cache_read_cost_per_million'], D('0.02'))
        self.assertIsNone(match[1]['cache_write_cost_per_million'])

    def test_provider_prefixed_key(self) -> None:
        match = prices.lookup(PRICED, 'gpt-prefixed', 'openai')
        assert match is not None
        self.assertEqual(match[0], 'openai/gpt-prefixed')
        self.assertEqual(match[1]['input_cost_per_million'], D('0.01'))
        self.assertEqual(str(match[1]['input_cost_per_million']), '0.01')

    def test_prefix_only_for_its_own_driver(self) -> None:
        self.assertIsNone(prices.lookup(PRICED, 'gpt-prefixed', 'anthropic'))
        self.assertIsNone(prices.lookup(PRICED, 'gpt-prefixed', 'bedrock'))

    def test_unmatched(self) -> None:
        self.assertIsNone(prices.lookup(PRICED, 'nope', 'anthropic'))

    def test_entries_without_input_price_do_not_match(self) -> None:
        self.assertIsNone(prices.lookup(PRICED, 'sample_spec', 'openai'))
        self.assertIsNone(
            prices.lookup(PRICED, 'text-embedding-free', 'openai')
        )

    def test_conversion_is_exact_and_plain(self) -> None:
        cases = {
            1e-08: '0.01',
            0.00001: '10',
            3e-06: '3',
            1.25e-07: '0.125',
            1e-13: '0',
            0: '0',
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(str(prices._per_million(raw)), expected)

    def test_junk_prices_are_none(self) -> None:
        for raw in (
            None,
            'x',
            True,
            -1e-06,
            float('inf'),
            float('nan'),
            100,
            1e30,
            10**400,
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(prices._per_million(raw))


class PlanUpdateTestCase(unittest.TestCase):
    current: typing.ClassVar[prices.Prices] = {
        'input_cost_per_million': D('3'),
        'output_cost_per_million': None,
        'cache_read_cost_per_million': D('0.3'),
        'cache_write_cost_per_million': D('3.75'),
    }
    synced: typing.ClassVar[prices.Prices] = {
        'input_cost_per_million': D('2'),
        'output_cost_per_million': D('10'),
        'cache_read_cost_per_million': D('0.30'),
        'cache_write_cost_per_million': None,
    }

    def test_fills_only_missing_prices(self) -> None:
        self.assertEqual(
            prices.plan_update(self.current, self.synced, overwrite=False),
            {'output_cost_per_million': D('10')},
        )

    def test_overwrite_changes_differing_prices(self) -> None:
        self.assertEqual(
            prices.plan_update(self.current, self.synced, overwrite=True),
            {
                'input_cost_per_million': D('2'),
                'output_cost_per_million': D('10'),
            },
        )


def _patch_client(
    handler: typing.Callable[[httpx.Request], httpx.Response],
) -> unittest.mock._patch[typing.Any]:
    original = httpx.AsyncClient

    def factory(**kwargs: typing.Any) -> httpx.AsyncClient:
        kwargs.pop('timeout', None)
        return original(transport=httpx.MockTransport(handler), **kwargs)

    return unittest.mock.patch('httpx.AsyncClient', factory)


class FetchTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        cache = unittest.mock.patch.object(prices, '_cache', None)
        cache.start()
        self.addCleanup(cache.stop)

    async def test_fetch_is_cached(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(200, content=json.dumps(TABLE))

        with _patch_client(handler):
            self.assertEqual(await prices.fetch(), PRICED)
            self.assertEqual(await prices.fetch(), PRICED)
        self.assertEqual(calls, [prices.URL])

    async def test_http_error(self) -> None:
        with (
            _patch_client(lambda _: httpx.Response(503, content=b'secret')),
            self.assertRaises(discovery.DiscoveryError) as ctx,
        ):
            await prices.fetch()
        self.assertEqual(ctx.exception.status, 503)
        self.assertNotIn('secret', str(ctx.exception))

    async def test_not_an_object(self) -> None:
        with (
            _patch_client(lambda _: httpx.Response(200, content=b'[]')),
            self.assertRaises(discovery.DiscoveryError),
        ):
            await prices.fetch()
