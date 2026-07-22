"""Tests for the shared Anthropic client wrapper."""

import unittest
import unittest.mock

import pydantic

from imbi.common.llm import (
    AnthropicClient,
    AnthropicSettings,
    CompletionResult,
    _extract_json,
)


class _ReleaseNotes(pydantic.BaseModel):
    bump: str
    version: str
    reasoning: str
    notes_markdown: str


def _fallback() -> _ReleaseNotes:
    return _ReleaseNotes(
        bump='patch',
        version='0.0.0',
        reasoning='fallback',
        notes_markdown='_AI unavailable._',
    )


class ExtractJsonTestCase(unittest.TestCase):
    def test_pulls_first_object(self) -> None:
        payload = 'preamble {"a": 1, "b": "two"} trailing'
        self.assertEqual(_extract_json(payload), {'a': 1, 'b': 'two'})

    def test_handles_nested_object(self) -> None:
        payload = '{"a": {"b": 1}, "c": 2}'
        self.assertEqual(_extract_json(payload), {'a': {'b': 1}, 'c': 2})

    def test_returns_none_when_missing(self) -> None:
        self.assertIsNone(_extract_json('no json here'))

    def test_returns_none_when_invalid_json(self) -> None:
        self.assertIsNone(_extract_json('{"oops":}'))


class SettingsTestCase(unittest.TestCase):
    def test_defaults(self) -> None:
        with unittest.mock.patch.dict('os.environ', {}, clear=True):
            settings = AnthropicSettings(_env_file=None)  # type: ignore[call-arg]
        self.assertEqual(settings.default_model, 'claude-haiku-4-5-20251001')
        self.assertEqual(settings.timeout, 30.0)
        self.assertIsNone(settings.api_key)

    def test_picks_up_env_api_key(self) -> None:
        with unittest.mock.patch.dict(
            'os.environ', {'ANTHROPIC_API_KEY': 'sk-test'}, clear=True
        ):
            settings = AnthropicSettings(_env_file=None)  # type: ignore[call-arg]
        self.assertIsNotNone(settings.api_key)
        assert settings.api_key is not None
        self.assertEqual(settings.api_key.get_secret_value(), 'sk-test')


class CompleteJsonTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_returns_fallback_when_unavailable(self) -> None:
        with unittest.mock.patch.dict('os.environ', {}, clear=True):
            client = AnthropicClient(
                settings=AnthropicSettings(_env_file=None),  # type: ignore[call-arg]
            )
        self.assertFalse(client.available)
        result = await client.complete_json(
            'prompt',
            schema=_ReleaseNotes,
            fallback=_fallback(),
        )
        self.assertTrue(result.degraded)
        self.assertEqual(result.data.version, '0.0.0')

    async def test_happy_path_returns_parsed_payload(self) -> None:
        fake = unittest.mock.MagicMock()
        fake.messages.create = unittest.mock.AsyncMock(
            return_value=unittest.mock.MagicMock(
                content=[
                    unittest.mock.MagicMock(
                        type='text',
                        text=(
                            'thinking…\n'
                            '{"bump": "minor", "version": "1.1.0", '
                            '"reasoning": "added foo", '
                            '"notes_markdown": "## Foo"}'
                        ),
                    )
                ]
            )
        )
        client = AnthropicClient(
            settings=AnthropicSettings(_env_file=None),  # type: ignore[call-arg]
            client=fake,
        )
        self.assertTrue(client.available)
        result = await client.complete_json(
            'draft notes',
            schema=_ReleaseNotes,
            fallback=_fallback(),
            system='You are a release-notes writer.',
            cache_system_prompt=True,
        )
        self.assertFalse(result.degraded)
        self.assertEqual(result.data.bump, 'minor')
        self.assertEqual(result.data.version, '1.1.0')
        kwargs = fake.messages.create.call_args.kwargs
        self.assertEqual(kwargs['model'], 'claude-haiku-4-5-20251001')
        # cache_system_prompt converts the string into a cache-control block.
        self.assertIsInstance(kwargs['system'], list)
        self.assertEqual(
            kwargs['system'][0]['cache_control'], {'type': 'ephemeral'}
        )

    async def test_returns_fallback_when_response_has_no_json(self) -> None:
        fake = unittest.mock.MagicMock()
        fake.messages.create = unittest.mock.AsyncMock(
            return_value=unittest.mock.MagicMock(
                content=[unittest.mock.MagicMock(type='text', text='hello')]
            )
        )
        client = AnthropicClient(
            settings=AnthropicSettings(_env_file=None),  # type: ignore[call-arg]
            client=fake,
        )
        result = await client.complete_json(
            'p', schema=_ReleaseNotes, fallback=_fallback()
        )
        self.assertTrue(result.degraded)

    async def test_returns_fallback_on_validation_error(self) -> None:
        fake = unittest.mock.MagicMock()
        fake.messages.create = unittest.mock.AsyncMock(
            return_value=unittest.mock.MagicMock(
                content=[
                    unittest.mock.MagicMock(
                        type='text',
                        text='{"bump": "minor"}',
                    )
                ]
            )
        )
        client = AnthropicClient(
            settings=AnthropicSettings(_env_file=None),  # type: ignore[call-arg]
            client=fake,
        )
        result = await client.complete_json(
            'p', schema=_ReleaseNotes, fallback=_fallback()
        )
        self.assertTrue(result.degraded)

    async def test_returns_fallback_on_api_exception(self) -> None:
        fake = unittest.mock.MagicMock()
        fake.messages.create = unittest.mock.AsyncMock(
            side_effect=RuntimeError('boom')
        )
        client = AnthropicClient(
            settings=AnthropicSettings(_env_file=None),  # type: ignore[call-arg]
            client=fake,
        )
        result = await client.complete_json(
            'p', schema=_ReleaseNotes, fallback=_fallback()
        )
        self.assertTrue(result.degraded)

    async def test_aclose_closes_underlying_client(self) -> None:
        fake = unittest.mock.MagicMock()
        fake.close = unittest.mock.AsyncMock()
        client = AnthropicClient(
            settings=AnthropicSettings(_env_file=None),  # type: ignore[call-arg]
            client=fake,
        )
        await client.aclose()
        fake.close.assert_awaited_once()
        self.assertFalse(client.available)


class CompletionResultTestCase(unittest.TestCase):
    def test_default_not_degraded(self) -> None:
        result: CompletionResult[_ReleaseNotes] = CompletionResult(
            data=_fallback()
        )
        self.assertFalse(result.degraded)
