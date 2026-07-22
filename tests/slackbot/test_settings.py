from imbi.slackbot import settings
from tests.slackbot import helpers


class SettingsTests(helpers.TestCase):
    def setUp(self) -> None:
        super().setUp()
        settings._slackbot_settings = None

    def tearDown(self) -> None:
        settings._slackbot_settings = None
        super().tearDown()

    def test_defaults_disabled(self) -> None:
        with self.override_environment(
            ANTHROPIC_API_KEY=None,
            SLACK_BOT_TOKEN=None,
            SLACK_APP_TOKEN=None,
            IMBI_SLACKBOT_ENABLED=None,
            IMBI_INTERNAL_API_URL=None,
        ):
            # ``_env_file=None`` ignores the developer's local .env so the
            # popped variables resolve to their defaults, not .env values.
            cfg = settings.Slackbot(_env_file=None)
        self.assertFalse(cfg.enabled)
        self.assertEqual('claude-sonnet-4-6', cfg.model)
        self.assertEqual('http://localhost:8000', cfg.api_url)
        self.assertEqual('', cfg.slack_bot_token)
        self.assertEqual(900, cfg.identity_cache_ttl)

    def test_auto_enable(self) -> None:
        with self.override_environment(
            ANTHROPIC_API_KEY='sk-test',
            SLACK_BOT_TOKEN='xoxb-test',
            SLACK_APP_TOKEN='xapp-test',
            IMBI_SLACKBOT_ENABLED=None,
        ):
            cfg = settings.Slackbot()
            # api_key is read live from the environment, so assert it
            # while the override is still active.
            self.assertEqual('sk-test', cfg.api_key)
        self.assertTrue(cfg.enabled)
        self.assertEqual('xoxb-test', cfg.slack_bot_token)
        self.assertEqual('xapp-test', cfg.slack_app_token)

    def test_no_auto_enable_without_slack_tokens(self) -> None:
        with self.override_environment(
            ANTHROPIC_API_KEY='sk-test',
            SLACK_BOT_TOKEN=None,
            SLACK_APP_TOKEN=None,
            IMBI_SLACKBOT_ENABLED=None,
        ):
            cfg = settings.Slackbot(_env_file=None)
        self.assertFalse(cfg.enabled)

    def test_api_url_override(self) -> None:
        with self.override_environment(
            IMBI_INTERNAL_API_URL='http://imbi-api:8000',
        ):
            cfg = settings.Slackbot()
        self.assertEqual('http://imbi-api:8000', cfg.api_url)

    def test_singleton(self) -> None:
        first = settings.get_slackbot_settings()
        second = settings.get_slackbot_settings()
        self.assertIs(first, second)
