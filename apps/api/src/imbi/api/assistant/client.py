"""AsyncAnthropic client singleton for the AI assistant."""

import logging

import anthropic

from imbi_api.assistant import settings

LOGGER = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


async def initialize() -> None:
    """Initialize the AsyncAnthropic client.

    Non-fatal if the assistant is disabled or no API key is configured.

    """
    global _client
    assistant_settings = settings.get_assistant_settings()

    if not assistant_settings.enabled:
        LOGGER.info('AI assistant is disabled')
        return

    if not assistant_settings.api_key:
        LOGGER.warning(
            'AI assistant enabled but no API key configured '
            '(set ANTHROPIC_API_KEY)'
        )
        return

    _client = anthropic.AsyncAnthropic(
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
            'and ANTHROPIC_API_KEY is set.'
        )
    return _client


def is_available() -> bool:
    """Check if the AI assistant client is available."""
    return _client is not None
