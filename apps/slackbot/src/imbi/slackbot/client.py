"""AsyncAnthropic client singleton for the Slack bot."""

import logging

import anthropic

from imbi.slackbot import settings

LOGGER = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


async def initialize() -> None:
    """Initialize the AsyncAnthropic client.

    Non-fatal if the bot is disabled or no API key is configured.

    """
    global _client

    await aclose()

    slackbot_settings = settings.get_slackbot_settings()

    if not slackbot_settings.enabled:
        LOGGER.info('Slack bot is disabled')
        return

    if not slackbot_settings.api_key:
        LOGGER.warning(
            'Slack bot enabled but no API key configured '
            '(set ANTHROPIC_API_KEY)'
        )
        return

    _client = anthropic.AsyncAnthropic(
        api_key=slackbot_settings.api_key,
    )
    LOGGER.info('Slack bot Anthropic client initialized')


async def aclose() -> None:
    """Close the AsyncAnthropic client."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
        LOGGER.debug('Slack bot Anthropic client closed')


def get_client() -> anthropic.AsyncAnthropic:
    """Get the AsyncAnthropic client singleton.

    Returns:
        The initialized AsyncAnthropic client.

    Raises:
        RuntimeError: If the client has not been initialized.

    """
    if _client is None:
        raise RuntimeError(
            'Slack bot Anthropic client not initialized. '
            'Check that ANTHROPIC_API_KEY, SLACK_BOT_TOKEN, and '
            'SLACK_APP_TOKEN are set.'
        )
    return _client


def is_available() -> bool:
    """Check if the Anthropic client is available."""
    return _client is not None
