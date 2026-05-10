"""Settings for the AI assistant."""

import logging
import os
import urllib.parse

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
    model: str = 'claude-sonnet-4-6'
    max_tokens: int = 16384
    max_conversation_turns: int = 100
    max_tool_rounds: int = 10
    system_prompt: str | None = None
    # Where the assistant reaches the Imbi REST API. Distinct from
    # ``IMBI_API_URL`` (which carries the API's *public* URL for OAuth
    # redirect URIs and hypermedia links) — this is the in-cluster /
    # internal address used for service-to-service calls. ``imbi-mcp``
    # reads the same env var for the same role.
    api_url: str = pydantic.Field(
        default='http://localhost:8000',
        validation_alias='IMBI_INTERNAL_API_URL',
    )
    # Public URL where the assistant is reachable (e.g.
    # ``https://imbi.example.com/assistant``). The path component is used
    # as the route prefix so routes match the Okteto ingress path.
    url: str = pydantic.Field(
        default='', validation_alias='IMBI_ASSISTANT_URL'
    )

    @pydantic.field_validator('url')
    @classmethod
    def _normalize_url(cls, value: str) -> str:
        return value.rstrip('/')

    @property
    def api_prefix(self) -> str:
        """Path prefix derived from the public URL's path component."""
        if not self.url:
            return ''
        path = urllib.parse.urlparse(self.url).path.rstrip('/')
        if not path:
            return ''
        if not path.startswith('/'):
            msg = (
                'IMBI_ASSISTANT_URL must include an absolute path '
                "(e.g. 'https://imbi.example.com/assistant' or "
                "'/assistant'); got "
                f'{self.url!r}.'
            )
            raise ValueError(msg)
        return path

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
