"""AsyncAnthropic client singleton for the Slack bot."""

import logging
import typing

import anthropic

from imbi.common.llm import observability, tokens
from imbi.slackbot import settings

LOGGER = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None
_observed = False


def tracking(user_email: str, trace_id: str) -> dict[str, typing.Any]:
    """Keyword arguments that link an LLM call to a user and thread.

    Empty when AI observability is off: the plain client does not take
    them. Privacy mode is set on the PostHog client
    (``POSTHOG_AI_PRIVACY_MODE``).
    """
    if not _observed:
        return {}
    return observability.tracking(user_email, trace_id)


async def initialize() -> None:
    """Initialize the AsyncAnthropic client.

    Non-fatal if the bot is disabled or no API key is configured.

    """
    global _client, _observed

    await aclose()

    slackbot_settings = settings.get_slackbot_settings()

    if not slackbot_settings.enabled:
        LOGGER.info('Slack bot is disabled')
        return

    client_class = observability.client_class()
    _observed = client_class is not anthropic.AsyncAnthropic

    if slackbot_settings.api_token:
        _client = tokens.bearer_client(
            tokens.ServiceToken(
                slackbot_settings.api_base_url, slackbot_settings.api_token
            ),
            client_class=client_class,
        )
        LOGGER.info('Slack bot client uses the AI provider token')
        return

    if not slackbot_settings.api_key:
        LOGGER.warning(
            'Slack bot enabled but no API key configured '
            '(set IMBI_SLACKBOT_API_TOKEN or ANTHROPIC_API_KEY)'
        )
        return

    _client = client_class(
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
            'Check that IMBI_SLACKBOT_API_TOKEN or ANTHROPIC_API_KEY, '
            'SLACK_BOT_TOKEN, and '
            'SLACK_APP_TOKEN are set.'
        )
    return _client


def is_available() -> bool:
    """Check if the Anthropic client is available."""
    return _client is not None
