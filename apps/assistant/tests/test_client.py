"""Tests for assistant client module."""

import hashlib
import os
import unittest
from unittest import mock

import anthropic
import posthog

from imbi.assistant import client, settings


class ClientInitializeTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for client initialization."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        client._client = None
        settings._assistant_settings = None

    async def asyncTearDown(self) -> None:
        client._client = None
        settings._assistant_settings = None
        await super().asyncTearDown()

    @mock.patch.dict(os.environ, {}, clear=True)
    async def test_initialize_disabled(self) -> None:
        """Test initialize when assistant is disabled."""
        await client.initialize()
        self.assertIsNone(client._client)
        self.assertFalse(client.is_available())

    @mock.patch.dict(
        os.environ,
        {'IMBI_ASSISTANT_ENABLED': 'true'},
        clear=True,
    )
    async def test_initialize_no_api_key(self) -> None:
        """Test initialize with no API key logs warning."""
        await client.initialize()
        self.assertIsNone(client._client)
        self.assertFalse(client.is_available())

    @mock.patch('anthropic.AsyncAnthropic')
    @mock.patch.dict(
        os.environ,
        {'ANTHROPIC_API_KEY': 'sk-test-key'},
        clear=True,
    )
    async def test_initialize_success(
        self, mock_anthropic: mock.MagicMock
    ) -> None:
        """Test successful client initialization."""
        await client.initialize()
        self.assertIsNotNone(client._client)
        self.assertTrue(client.is_available())
        mock_anthropic.assert_called_once_with(api_key='sk-test-key')

    @mock.patch('imbi.common.llm.tokens.bearer_client')
    @mock.patch.dict(
        os.environ,
        {
            'ANTHROPIC_API_KEY': 'sk-test-key',
            'IMBI_ASSISTANT_API_TOKEN': 'ik_1_secret',
            'IMBI_INTERNAL_API_URL': 'http://imbi-api:8000',
        },
        clear=True,
    )
    async def test_initialize_with_the_ai_provider_token(
        self, bearer_client: mock.MagicMock
    ) -> None:
        """The service token takes precedence over the key."""
        await client.initialize()
        self.assertIs(client._client, bearer_client.return_value)
        source = bearer_client.call_args.args[0]
        self.assertEqual(
            source._url, 'http://imbi-api:8000/ai-providers/token'
        )
        self.assertEqual(source._api_token, 'ik_1_secret')

    @mock.patch('imbi.common.llm.tokens.bearer_client')
    @mock.patch.dict(
        os.environ, {'IMBI_ASSISTANT_API_TOKEN': 'ik_1_secret'}, clear=True
    )
    async def test_initialize_with_only_the_ai_provider_token(
        self, bearer_client: mock.MagicMock
    ) -> None:
        """The service token alone enables the client."""
        await client.initialize()
        bearer_client.assert_called_once()
        self.assertIs(client._client, bearer_client.return_value)

    @mock.patch('anthropic.AsyncAnthropic')
    @mock.patch.dict(
        os.environ,
        {'ANTHROPIC_API_KEY': 'sk-test-key'},
        clear=True,
    )
    async def test_aclose(self, mock_anthropic: mock.MagicMock) -> None:
        """Test closing the client."""
        mock_instance = mock.AsyncMock()
        mock_anthropic.return_value = mock_instance

        await client.initialize()
        self.assertTrue(client.is_available())

        await client.aclose()
        self.assertFalse(client.is_available())
        mock_instance.close.assert_awaited_once()

    async def test_aclose_when_not_initialized(self) -> None:
        """Test aclose when client is not initialized."""
        await client.aclose()  # Should not raise
        self.assertFalse(client.is_available())


class GetClientTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for get_client."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        client._client = None
        settings._assistant_settings = None

    async def asyncTearDown(self) -> None:
        client._client = None
        settings._assistant_settings = None
        await super().asyncTearDown()

    def test_get_client_raises_when_not_initialized(
        self,
    ) -> None:
        """Test get_client raises RuntimeError."""
        with self.assertRaises(RuntimeError) as ctx:
            client.get_client()
        self.assertIn('not initialized', str(ctx.exception))
        self.assertIn('ANTHROPIC_API_KEY', str(ctx.exception))

    @mock.patch('anthropic.AsyncAnthropic')
    @mock.patch.dict(
        os.environ,
        {'ANTHROPIC_API_KEY': 'sk-test'},
        clear=True,
    )
    async def test_get_client_returns_client(
        self, mock_anthropic: mock.MagicMock
    ) -> None:
        """Test get_client returns the initialized client."""
        mock_instance = mock.AsyncMock()
        mock_anthropic.return_value = mock_instance

        await client.initialize()
        result = client.get_client()
        self.assertIs(result, mock_instance)


class IsAvailableTestCase(unittest.TestCase):
    """Test cases for is_available."""

    def setUp(self) -> None:
        self._original = client._client

    def tearDown(self) -> None:
        client._client = self._original

    def test_not_available(self) -> None:
        """Test is_available returns False."""
        client._client = None
        self.assertFalse(client.is_available())

    def test_available(self) -> None:
        """Test is_available returns True."""
        client._client = mock.MagicMock()
        self.assertTrue(client.is_available())


class ObservabilityTestCase(unittest.IsolatedAsyncioTestCase):
    """AI observability swaps in the PostHog wrapper (POSTHOG_*)."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        client._client = None
        settings._assistant_settings = None

    async def asyncTearDown(self) -> None:
        if client._client is not None:
            await client._client.close()
        client._client = None
        client._observed = False
        posthog.default_client = None  # the wrapper made a global client
        settings._assistant_settings = None
        await super().asyncTearDown()

    @mock.patch.dict(
        os.environ,
        {'ANTHROPIC_API_KEY': 'sk-test-key', 'POSTHOG_API_KEY': 'phc_x'},
        clear=True,
    )
    async def test_plain_client_when_switch_off(self) -> None:
        await client.initialize()
        self.assertIs(type(client._client), anthropic.AsyncAnthropic)
        self.assertEqual(client.tracking('a@b.c', 'conv'), {})

    @mock.patch('imbi.common.posthog.init', return_value=True)
    @mock.patch.dict(
        os.environ,
        {
            'ANTHROPIC_API_KEY': 'sk-test-key',
            'POSTHOG_API_KEY': 'phc_x',
            'POSTHOG_AI_OBSERVABILITY': 'true',
        },
        clear=True,
    )
    async def test_wrapper_when_switch_on(self, _init: mock.MagicMock) -> None:
        from posthog.ai.anthropic import AsyncAnthropic

        await client.initialize()
        self.assertIsInstance(client._client, AsyncAnthropic)
        self.assertEqual(
            client.tracking('A@B.c', 'conv'),
            {
                'posthog_distinct_id': hashlib.sha256(b'a@b.c').hexdigest(),
                'posthog_trace_id': 'conv',
            },
        )
