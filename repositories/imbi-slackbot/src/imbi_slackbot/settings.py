"""Settings for the Imbi Slack bot."""

import logging
import os

import pydantic
import pydantic_settings
from imbi_common import settings as common_settings

LOGGER = logging.getLogger(__name__)


class Slackbot(pydantic_settings.BaseSettings):
    """Slack bot configuration."""

    model_config = common_settings.base_settings_config(
        env_prefix='IMBI_SLACKBOT_',
    )

    enabled: bool = False
    model: str = 'claude-sonnet-4-6'
    max_tokens: int = 16384
    max_tool_rounds: int = 10
    # How many of a Slack thread's most recent messages to replay to
    # Claude when reconstructing conversation context.
    max_thread_messages: int = 30
    # How long (seconds) to cache a Slack -> Imbi user resolution before
    # re-checking the directory and graph.
    identity_cache_ttl: int = 900
    system_prompt: str | None = None

    # Slack credentials. These use the conventional ``SLACK_`` env names
    # rather than the ``IMBI_SLACKBOT_`` prefix.
    slack_bot_token: str = pydantic.Field(
        default='', validation_alias='SLACK_BOT_TOKEN'
    )
    slack_app_token: str = pydantic.Field(
        default='', validation_alias='SLACK_APP_TOKEN'
    )

    # Where the bot reaches the Imbi REST API. Distinct from
    # ``IMBI_API_URL`` (the API's *public* URL); this is the in-cluster
    # address used for service-to-service calls. ``imbi-assistant`` and
    # ``imbi-mcp`` read the same env var for the same role.
    api_url: str = pydantic.Field(
        default='http://localhost:8000',
        validation_alias='IMBI_INTERNAL_API_URL',
    )

    # Public base URL of the Imbi UI (no path component), used to build
    # absolute deep links to resources in replies. Shares the
    # ``IMBI_UI_URL`` env var with imbi-api.
    ui_url: str = pydantic.Field(default='', validation_alias='IMBI_UI_URL')

    # In-cluster address of the Imbi UI used to fetch its ``llms.txt`` for
    # URL-pattern guidance. Distinct from ``IMBI_UI_URL`` (the UI's
    # *public* URL, used for deep links): fetching ``llms.txt`` is a
    # service-to-service call that should stay in-cluster rather than
    # round-trip through the public ingress. Mirrors
    # ``IMBI_INTERNAL_API_URL``; falls back to ``ui_url`` when unset.
    internal_ui_url: str = pydantic.Field(
        default='', validation_alias='IMBI_INTERNAL_UI_URL'
    )

    @pydantic.field_validator('ui_url', 'internal_ui_url')
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip('/')

    @property
    def llms_base_url(self) -> str:
        """Base URL for fetching the UI's ``llms.txt``.

        Prefers the in-cluster ``IMBI_INTERNAL_UI_URL`` and falls back to
        the public ``IMBI_UI_URL`` so existing single-URL deployments keep
        working.
        """
        return self.internal_ui_url or self.ui_url

    @property
    def api_key(self) -> str | None:
        """Read the Anthropic API key from ANTHROPIC_API_KEY."""
        return os.environ.get('ANTHROPIC_API_KEY')

    @pydantic.model_validator(mode='after')
    def auto_enable(self) -> 'Slackbot':
        """Auto-enable when an API key and Slack tokens are available."""
        if (
            self.api_key
            and self.slack_bot_token
            and self.slack_app_token
            and not self.enabled
        ):
            self.enabled = True
        return self


_slackbot_settings: Slackbot | None = None


def get_slackbot_settings() -> Slackbot:
    """Get the singleton Slackbot settings instance.

    Returns:
        The singleton Slackbot settings instance.

    """
    global _slackbot_settings
    if _slackbot_settings is None:
        _slackbot_settings = Slackbot()
    return _slackbot_settings
