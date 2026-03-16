"""Tests for assistant settings module."""

import os
import unittest
from unittest import mock

from imbi_assistant import settings


class AssistantSettingsTestCase(unittest.TestCase):
    """Test cases for Assistant settings model."""

    def setUp(self) -> None:
        settings._assistant_settings = None

    def tearDown(self) -> None:
        settings._assistant_settings = None

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_default_settings(self) -> None:
        """Test default settings values."""
        s = settings.Assistant(
            _env_file=None,
        )
        self.assertFalse(s.enabled)
        self.assertIsNone(s.api_key)
        self.assertEqual(s.model, 'claude-sonnet-4-6')
        self.assertEqual(s.max_tokens, 16384)
        self.assertEqual(s.max_conversation_turns, 100)
        self.assertIsNone(s.system_prompt)
        self.assertEqual(s.api_url, 'http://localhost:8000')
        self.assertEqual(s.max_tool_rounds, 10)

    @mock.patch.dict(
        os.environ,
        {'ANTHROPIC_API_KEY': 'sk-test-123'},
        clear=True,
    )
    def test_auto_enable_with_api_key(self) -> None:
        """Test that providing an API key auto-enables."""
        s = settings.Assistant(
            _env_file=None,
        )
        self.assertTrue(s.enabled)
        self.assertEqual(s.api_key, 'sk-test-123')

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_disabled_without_api_key(self) -> None:
        """Test assistant stays disabled without API key."""
        s = settings.Assistant(
            _env_file=None,
        )
        self.assertFalse(s.enabled)
        self.assertIsNone(s.api_key)

    @mock.patch.dict(
        os.environ,
        {
            'ANTHROPIC_API_KEY': 'sk-test',
            'IMBI_ASSISTANT_ENABLED': 'true',
        },
        clear=True,
    )
    def test_explicit_enable(self) -> None:
        """Test explicit enable with API key."""
        s = settings.Assistant(
            _env_file=None,
        )
        self.assertTrue(s.enabled)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_get_assistant_settings_singleton(self) -> None:
        """Test singleton pattern for get_assistant_settings."""
        with (
            mock.patch.object(
                settings.Assistant,
                '__init__',
                return_value=None,
            ),
            mock.patch.object(
                settings.Assistant,
                'model_post_init',
                return_value=None,
            ),
        ):
            s1 = settings.get_assistant_settings()
            s2 = settings.get_assistant_settings()
            self.assertIs(s1, s2)

    @mock.patch.dict(
        os.environ,
        {'IMBI_ASSISTANT_MODEL': 'claude-opus-4-20250514'},
        clear=True,
    )
    def test_custom_model(self) -> None:
        """Test custom model configuration."""
        s = settings.Assistant(
            _env_file=None,
        )
        self.assertEqual(s.model, 'claude-opus-4-20250514')
