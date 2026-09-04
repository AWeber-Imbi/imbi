"""Tests for the provider model-discovery client and driver catalog."""

import datetime
import typing
import unittest
import unittest.mock

import anthropic
import anthropic.types
import httpx

from imbi.common import models
from imbi.common.llm import discovery, drivers


class DriverCatalogTestCase(unittest.TestCase):
    """The static driver catalog."""

    def test_catalog_matches_the_model_literal(self) -> None:
        """A driver added to one must be added to the other."""
        self.assertEqual(
            set(typing.get_args(models.AIProviderDriver)),
            set(drivers.DRIVERS_BY_SLUG),
        )

    def test_get_driver_returns_none_for_unknown(self) -> None:
        """An unknown slug is not an error."""
        self.assertIsNone(drivers.get_driver('nope'))

    def test_resolve_base_url_prefers_the_provider(self) -> None:
        """A configured base URL wins over the driver default."""
        self.assertEqual(
            drivers.resolve_base_url('openai', 'https://proxy.local/v1/'),
            'https://proxy.local/v1',
        )

    def test_resolve_base_url_falls_back_to_the_default(self) -> None:
        """An unset base URL uses the driver's own endpoint."""
        self.assertEqual(
            drivers.resolve_base_url('anthropic', None),
            'https://api.anthropic.com',
        )

    def test_resolve_base_url_is_none_without_a_default(self) -> None:
        """Bedrock addresses no single HTTP endpoint."""
        self.assertIsNone(drivers.resolve_base_url('bedrock', None))


def _transport(
    handler: typing.Callable[[httpx.Request], httpx.Response],
) -> unittest.mock._patch[typing.Any]:
    """Patch ``httpx.AsyncClient`` to answer from ``handler``."""
    original = httpx.AsyncClient

    def factory(**kwargs: typing.Any) -> httpx.AsyncClient:
        kwargs.pop('timeout', None)
        return original(transport=httpx.MockTransport(handler), **kwargs)

    return unittest.mock.patch('httpx.AsyncClient', factory)


def _model_json(
    model_id: str, display_name: str | None = None, **extra: typing.Any
) -> dict[str, typing.Any]:
    """Build one ``/v1/models`` entry as the API returns it."""
    entry: dict[str, typing.Any] = {
        'id': model_id,
        'type': 'model',
        'display_name': display_name or model_id,
        'created_at': '2026-03-01T00:00:00Z',
    }
    entry.update(extra)
    return entry


class AnthropicAPI:
    """A minimal ``/v1/models`` server for ``httpx.MockTransport``.

    Serves ``entries`` in pages of ``page_size`` using the real
    ``has_more``/``last_id`` protocol, so the SDK's own paginator does
    the walking and the ``after_id`` cursor is genuinely exercised.
    """

    def __init__(
        self,
        entries: list[dict[str, typing.Any]],
        page_size: int = 2,
        status_code: int = 200,
        raise_transport: bool = False,
    ) -> None:
        self.entries = entries
        self.page_size = page_size
        self.status_code = status_code
        self.raise_transport = raise_transport
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raise_transport:
            raise httpx.ConnectError('no route to host', request=request)
        if self.status_code >= 400:
            return httpx.Response(
                self.status_code,
                json={'error': {'message': 'sk-test leaked in the body'}},
            )
        after_id = request.url.params.get('after_id')
        start = 0
        if after_id:
            ids = [entry['id'] for entry in self.entries]
            start = ids.index(after_id) + 1
        page = self.entries[start : start + self.page_size]
        has_more = start + self.page_size < len(self.entries)
        return httpx.Response(
            200,
            json={
                'data': page,
                'has_more': has_more,
                'first_id': page[0]['id'] if page else None,
                'last_id': page[-1]['id'] if page else None,
            },
        )


def _real_sdk(api: AnthropicAPI) -> tuple[typing.Any, list[dict[str, object]]]:
    """Run the real ``AsyncAnthropic`` against ``api``.

    Only the HTTP transport is swapped, via the SDK's supported
    ``http_client`` argument, so ``async with``, ``models.list(limit=…)``
    and the paginator are the production code paths.
    """
    real = anthropic.AsyncAnthropic
    constructed: list[dict[str, object]] = []

    def factory(**kwargs: typing.Any) -> anthropic.AsyncAnthropic:
        constructed.append(dict(kwargs))
        return real(
            **kwargs,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(api)),
        )

    return (
        unittest.mock.patch.object(
            discovery.anthropic, 'AsyncAnthropic', factory
        ),
        constructed,
    )


class ListModelsTestCase(unittest.IsolatedAsyncioTestCase):
    """:func:`imbi.common.llm.discovery.list_models`."""

    async def test_anthropic_maps_token_limits(self) -> None:
        """Display name and both token limits come through the SDK."""
        api = AnthropicAPI(
            [
                _model_json(
                    'claude-opus-5',
                    'Claude Opus 5',
                    max_input_tokens=200000,
                    max_tokens=64000,
                )
            ]
        )
        patcher, constructed = _real_sdk(api)
        with patcher:
            found = await discovery.list_models(
                'anthropic', 'sk-test', 'https://api.anthropic.com'
            )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].model_id, 'claude-opus-5')
        self.assertEqual(found[0].display_name, 'Claude Opus 5')
        self.assertEqual(found[0].context_window, 200000)
        self.assertEqual(found[0].max_output_tokens, 64000)
        self.assertEqual(
            found[0].created_at,
            datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC),
        )
        self.assertEqual(constructed[0]['api_key'], 'sk-test')
        self.assertEqual(constructed[0]['timeout'], discovery.TIMEOUT)
        request = api.requests[0]
        self.assertEqual(request.url.path, '/v1/models')
        self.assertEqual(request.headers['x-api-key'], 'sk-test')
        self.assertEqual(request.url.params.get('limit'), '100')

    async def test_anthropic_without_token_limits(self) -> None:
        """Both limits are optional on older published models."""
        patcher, _ = _real_sdk(AnthropicAPI([_model_json('claude-x')]))
        with patcher:
            found = await discovery.list_models('anthropic', 'k', None)
        self.assertIsNone(found[0].context_window)
        self.assertIsNone(found[0].max_output_tokens)

    async def test_anthropic_uses_the_sdk_default_base_url(self) -> None:
        """An unset base URL leaves the SDK's own endpoint in place."""
        api = AnthropicAPI([_model_json('claude-x')])
        patcher, constructed = _real_sdk(api)
        with patcher:
            await discovery.list_models('anthropic', 'k', None)
        self.assertIsNone(constructed[0]['base_url'])
        self.assertEqual(api.requests[0].url.host, 'api.anthropic.com')

    async def test_anthropic_follows_the_paginator(self) -> None:
        """Models past the first page are collected via ``after_id``."""
        api = AnthropicAPI(
            [_model_json(f'claude-{n}') for n in range(5)], page_size=2
        )
        patcher, _ = _real_sdk(api)
        with patcher:
            found = await discovery.list_models('anthropic', 'k', None)
        self.assertEqual(
            [entry.model_id for entry in found],
            [f'claude-{n}' for n in range(5)],
        )
        self.assertEqual(len(api.requests), 3)
        self.assertIsNone(api.requests[0].url.params.get('after_id'))
        self.assertEqual(
            api.requests[1].url.params.get('after_id'), 'claude-1'
        )

    async def test_anthropic_stops_at_the_ceiling(self) -> None:
        """An endless paginator cannot spin forever."""
        api = AnthropicAPI(
            [
                _model_json(f'claude-{n}')
                for n in range(discovery.MAX_MODELS + 20)
            ],
            page_size=250,
        )
        patcher, _ = _real_sdk(api)
        with patcher:
            found = await discovery.list_models('anthropic', 'k', None)
        self.assertEqual(len(found), discovery.MAX_MODELS)

    async def test_anthropic_status_error_hides_the_body(self) -> None:
        """A 401 is reported by status alone."""
        patcher, _ = _real_sdk(AnthropicAPI([], status_code=401))
        with patcher, self.assertRaises(discovery.DiscoveryError) as ctx:
            await discovery.list_models('anthropic', 'sk-test', None)
        self.assertIn('401', str(ctx.exception))
        self.assertNotIn('sk-test', str(ctx.exception))

    async def test_anthropic_connection_error_is_normalised(self) -> None:
        """A transport failure becomes a DiscoveryError, not a 500."""
        patcher, _ = _real_sdk(AnthropicAPI([], raise_transport=True))
        with patcher, self.assertRaises(discovery.DiscoveryError) as ctx:
            await discovery.list_models('anthropic', 'sk-test', None)
        self.assertIn('APIConnectionError', str(ctx.exception))
        self.assertNotIn('sk-test', str(ctx.exception))

    async def test_openai_sends_a_bearer_token(self) -> None:
        """The OpenAI-compatible shape uses ``Authorization``."""

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(
                request.headers['authorization'], 'Bearer sk-test'
            )
            self.assertEqual(
                str(request.url), 'https://api.openai.com/v1/models'
            )
            return httpx.Response(
                200,
                json={'data': [{'id': 'gpt-5', 'created': 1772323200}]},
            )

        with _transport(handler):
            found = await discovery.list_models(
                'openai', 'sk-test', 'https://api.openai.com/v1'
            )
        self.assertEqual(found[0].model_id, 'gpt-5')
        self.assertEqual(found[0].display_name, 'gpt-5')
        self.assertIsNotNone(found[0].created_at)

    async def test_entries_without_an_id_are_dropped(self) -> None:
        """A malformed entry does not abort the whole list."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={'data': [{'object': 'model'}, {'id': 'gpt-5'}]}
            )

        with _transport(handler):
            found = await discovery.list_models(
                'openai', 'k', 'https://api.openai.com/v1'
            )
        self.assertEqual([entry.model_id for entry in found], ['gpt-5'])

    async def test_unexpected_payload_yields_no_models(self) -> None:
        """A body without a ``data`` array is not an exception."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={'error': 'nope'})

        with _transport(handler):
            found = await discovery.list_models(
                'openai', 'k', 'https://api.openai.com/v1'
            )
        self.assertEqual(found, [])

    async def test_http_error_names_the_status_only(self) -> None:
        """A 401 is reported without the response body or the key."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={'error': {'message': 'sk-test'}})

        with (
            _transport(handler),
            self.assertRaises(discovery.DiscoveryError) as ctx,
        ):
            await discovery.list_models(
                'openai', 'sk-test', 'https://api.openai.com/v1'
            )
        self.assertIn('401', str(ctx.exception))
        self.assertNotIn('sk-test', str(ctx.exception))

    async def test_transport_error_is_a_discovery_error(self) -> None:
        """A connection failure is normalised, not leaked."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError('no route to host')

        with (
            _transport(handler),
            self.assertRaises(discovery.DiscoveryError) as ctx,
        ):
            await discovery.list_models(
                'openai', 'sk-test', 'https://api.openai.com/v1'
            )
        self.assertIn('ConnectError', str(ctx.exception))

    async def test_non_json_body_is_a_discovery_error(self) -> None:
        """An HTML error page is reported as such."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text='<html>hi</html>')

        with _transport(handler), self.assertRaises(discovery.DiscoveryError):
            await discovery.list_models(
                'openai', 'k', 'https://api.openai.com/v1'
            )

    async def test_unsupported_driver(self) -> None:
        """Bedrock discovery is not implemented yet."""
        with self.assertRaises(discovery.DiscoveryError):
            await discovery.list_models('bedrock', 'k', None)

    async def test_openai_compatible_without_an_endpoint(self) -> None:
        """There is nothing to call without a base URL."""
        with self.assertRaises(discovery.DiscoveryError):
            await discovery.list_models('openai_compatible', 'k', None)


class TimestampTestCase(unittest.TestCase):
    """Provider timestamps arrive in two shapes and neither is trusted."""

    def test_parses_iso_and_epoch(self) -> None:
        """Both an ISO string and a Unix epoch are accepted."""
        self.assertIsNotNone(
            discovery._parse_timestamp('2026-03-01T00:00:00Z')
        )
        self.assertIsNotNone(discovery._parse_timestamp(1772323200))

    def test_rejects_junk(self) -> None:
        """Anything unparseable becomes ``None``."""
        for value in ('not-a-date', True, None, {}, 10**20):
            with self.subTest(value=value):
                self.assertIsNone(discovery._parse_timestamp(value))
