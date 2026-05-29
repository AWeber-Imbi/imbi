from imbi_slackbot import client, settings
from tests import helpers


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
