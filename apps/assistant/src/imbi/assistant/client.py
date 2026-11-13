"""AsyncAnthropic client singleton for the AI assistant."""

import logging
import typing

import anthropic

from imbi.assistant import settings
from imbi.common.llm import observability, tokens

LOGGER = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None
_observed = False


def tracking(user_email: str, conversation_id: str) -> dict[str, typing.Any]:
    """Keyword arguments that link an LLM call to a user and conversation.

    Empty when AI observability is off: the plain client does not take
    them. Privacy mode is set on the PostHog client
    (``POSTHOG_AI_PRIVACY_MODE``).
    """
    if not _observed:
        return {}
    return observability.tracking(user_email, conversation_id)


async def initialize() -> None:
    """Initialize the AsyncAnthropic client.

    Non-fatal if the assistant is disabled or no API key is
    configured.

    """
    global _client, _observed

    if _client is not None:
        existing_client = _client
        _client = None
        await existing_client.close()

    assistant_settings = settings.get_assistant_settings()

    if not assistant_settings.enabled:
        LOGGER.info('AI assistant is disabled')
        return

    client_class = observability.client_class()
    _observed = client_class is not anthropic.AsyncAnthropic

    if assistant_settings.api_token:
        _client = tokens.bearer_client(
            tokens.ServiceToken(
                assistant_settings.api_base_url, assistant_settings.api_token
            ),
            client_class=client_class,
        )
        LOGGER.info('AI assistant client uses the AI provider token')
        return

    if not assistant_settings.api_key:
        LOGGER.warning(
            'AI assistant enabled but no API key configured '
            '(set IMBI_ASSISTANT_API_TOKEN or ANTHROPIC_API_KEY)'
        )
        return

    _client = client_class(
        api_key=assistant_settings.api_key,
    )
    LOGGER.info('AI assistant client initialized')


async def aclose() -> None:
    """Close the AsyncAnthropic client."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
        LOGGER.debug('AI assistant client closed')


def get_client() -> anthropic.AsyncAnthropic:
    """Get the AsyncAnthropic client singleton.

    Returns:
        The initialized AsyncAnthropic client.

    Raises:
        RuntimeError: If the client has not been initialized.

    """
    if _client is None:
        raise RuntimeError(
            'AI assistant client not initialized. '
            'Check that IMBI_ASSISTANT_ENABLED=true '
            'and IMBI_ASSISTANT_API_TOKEN or ANTHROPIC_API_KEY is set.'
        )
    return _client


def is_available() -> bool:
    """Check if the AI assistant client is available."""
    return _client is not None
