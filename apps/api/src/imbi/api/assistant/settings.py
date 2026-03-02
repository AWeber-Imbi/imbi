"""Settings for the AI assistant."""

import logging
import os
import typing

import pydantic
import pydantic_settings
from imbi_common import settings as common_settings

LOGGER = logging.getLogger(__name__)


class Assistant(pydantic_settings.BaseSettings):
    """AI assistant configuration."""

    model_config = common_settings.base_settings_config(
        env_prefix='IMBI_ASSISTANT_',
    )

    enabled: bool = False
    model: str = 'claude-sonnet-4-20250514'
    max_tokens: int = 4096
    max_conversation_turns: int = 100
    system_prompt: str | None = None
    mcp_servers: list[dict[str, typing.Any]] = pydantic.Field(
        default_factory=list,
    )

    @property
    def api_key(self) -> str | None:
        """Read the API key from ANTHROPIC_API_KEY."""
        return os.environ.get('ANTHROPIC_API_KEY')

    @pydantic.model_validator(mode='after')
    def auto_enable(self) -> 'Assistant':
        """Auto-enable when an API key is available."""
        if self.api_key and not self.enabled:
            self.enabled = True
        return self


_assistant_settings: Assistant | None = None


def get_assistant_settings() -> Assistant:
    """Get the singleton Assistant settings instance.

    Returns:
        The singleton Assistant settings instance.

    """
    global _assistant_settings
    if _assistant_settings is None:
        _assistant_settings = Assistant()
    return _assistant_settings
