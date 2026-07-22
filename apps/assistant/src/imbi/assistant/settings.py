"""Settings for the AI assistant."""

import logging
import os
import urllib.parse

import pydantic
import pydantic_settings

from imbi.common import settings as common_settings

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
    # Hard cap on the size (in characters) of a single tool result
    # embedded into the conversation. A tool that returns more than this
    # — e.g. an unpaginated ``list_projects`` for a large org, which the
    # API itself documents as "megabytes" — is truncated with a notice
    # telling the model to narrow its query. Without this bound one
    # oversized result overflows the model's context window (HTTP 400)
    # and, because the round is persisted before the next request runs,
    # bricks the conversation permanently. Roughly 4 chars/token, so the
    # default is about 30k tokens per result.
    max_tool_result_chars: int = 120_000
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
    # Public base URL of the Imbi UI (no path component), used to build
    # absolute deep links to resources in responses. Shares the
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

    @pydantic.field_validator('url', 'ui_url', 'internal_ui_url')
    @classmethod
    def _normalize_url(cls, value: str) -> str:
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
