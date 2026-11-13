import hashlib
from unittest import mock

import anthropic
import posthog

from apps.slackbot.tests import helpers
from imbi.slackbot import client, settings


class ClientTests(helpers.TestCase):
    def setUp(self) -> None:
        super().setUp()
        settings._slackbot_settings = None
        client._client = None

    async def asyncTearDown(self) -> None:
        await client.aclose()
        settings._slackbot_settings = None
        await super().asyncTearDown()

    async def test_disabled(self) -> None:
        with self.override_environment(
            ANTHROPIC_API_KEY=None,
            SLACK_BOT_TOKEN=None,
            SLACK_APP_TOKEN=None,
            IMBI_SLACKBOT_ENABLED=None,
        ):
            await client.initialize()
        self.assertFalse(client.is_available())

    async def test_enabled_without_key(self) -> None:
        with self.override_environment(
            ANTHROPIC_API_KEY=None,
            IMBI_SLACKBOT_ENABLED='true',
        ):
            await client.initialize()
        self.assertFalse(client.is_available())

    async def test_enabled_with_key(self) -> None:
        with self.override_environment(
            ANTHROPIC_API_KEY='sk-test',
            SLACK_BOT_TOKEN='xoxb',
            SLACK_APP_TOKEN='xapp',
            IMBI_SLACKBOT_ENABLED=None,
        ):
            await client.initialize()
            self.assertTrue(client.is_available())
            self.assertIsNotNone(client.get_client())
            await client.aclose()
        self.assertFalse(client.is_available())

    async def test_get_client_raises_when_unset(self) -> None:
        with self.assertRaises(RuntimeError):
            client.get_client()

    async def test_enabled_with_the_ai_provider_token(self) -> None:
        with (
            self.override_environment(
                ANTHROPIC_API_KEY=None,
                IMBI_SLACKBOT_API_TOKEN='ik_1_secret',
                SLACK_BOT_TOKEN='xoxb',
                SLACK_APP_TOKEN='xapp',
                IMBI_SLACKBOT_ENABLED=None,
            ),
            mock.patch('imbi.common.llm.tokens.bearer_client') as bearer,
        ):
            await client.initialize()
        self.assertIs(client.get_client(), bearer.return_value)
        self.assertEqual(
            bearer.call_args.args[0]._api_token,
            'ik_1_secret',
        )
        client._client = None


_ENV: dict[str, str | None] = {
    'ANTHROPIC_API_KEY': 'sk-test',
    'IMBI_SLACKBOT_API_TOKEN': None,
    'SLACK_BOT_TOKEN': 'xoxb',
    'SLACK_APP_TOKEN': 'xapp',
    'POSTHOG_API_KEY': 'phc_x',
    'POSTHOG_AI_OBSERVABILITY': None,
}


class ObservabilityTests(helpers.TestCase):
    """AI observability swaps in the PostHog wrapper (POSTHOG_*)."""

    def setUp(self) -> None:
        super().setUp()
        settings._slackbot_settings = None
        client._client = None

    async def asyncTearDown(self) -> None:
        await client.aclose()
        client._observed = False
        posthog.default_client = None  # the wrapper made a global client
        settings._slackbot_settings = None
        await super().asyncTearDown()

    async def test_plain_client_when_switch_off(self) -> None:
        with self.override_environment(**_ENV):
            await client.initialize()
        self.assertIs(type(client.get_client()), anthropic.AsyncAnthropic)
        self.assertEqual(client.tracking('a@b.c', 'thread'), {})

    @mock.patch('imbi.common.posthog.init', return_value=True)
    async def test_wrapper_when_switch_on(self, _init: mock.MagicMock) -> None:
        from posthog.ai.anthropic import AsyncAnthropic

        with self.override_environment(
            **{**_ENV, 'POSTHOG_AI_OBSERVABILITY': 'true'}
        ):
            await client.initialize()
        self.assertIsInstance(client.get_client(), AsyncAnthropic)
        self.assertEqual(
            client.tracking('A@B.c', 'thread'),
            {
                'posthog_distinct_id': hashlib.sha256(b'a@b.c').hexdigest(),
                'posthog_trace_id': 'thread',
            },
        )
