"""Anthropic LLM client wrapper shared across Imbi services.

Centralises the ``AsyncAnthropic`` setup and a small
:meth:`AnthropicClient.complete_json` helper that:

1. Issues a single non-streaming completion against a configurable model.
2. Extracts the first JSON object from the response.
3. Validates it against a caller-provided Pydantic schema.
4. Returns ``(parsed_model, degraded=False)`` on success or
   ``(fallback, degraded=True)`` when the API is unavailable, the
   response is unparseable, or validation fails — so a Claude outage
   doesn't 500 the calling endpoint.

Designed to be initialised once per process via the FastAPI / ASGI
lifespan and reused across requests.  Plugins can opt into prompt
caching by passing a static ``cache_system_prompt`` argument.
"""

from __future__ import annotations

import json
import logging
import re
import typing

import pydantic
import pydantic_settings

from imbi_common import settings as common_settings

if typing.TYPE_CHECKING:
    import anthropic

LOGGER = logging.getLogger(__name__)

# Default to a fast, cheap model.  Release-note drafting and similar
# structured-output tasks don't need Opus.
DEFAULT_MODEL = 'claude-haiku-4-5-20251001'


class AnthropicSettings(pydantic_settings.BaseSettings):
    """Anthropic client configuration.

    Reads ``ANTHROPIC_API_KEY`` plus the ``IMBI_ANTHROPIC_*`` namespace
    so the same env-var conventions used elsewhere in the codebase
    apply (set ``IMBI_ANTHROPIC_DEFAULT_MODEL`` to override the model
    org-wide, ``IMBI_ANTHROPIC_TIMEOUT`` for the request timeout).
    """

    model_config = common_settings.base_settings_config(
        env_prefix='IMBI_ANTHROPIC_',
    )

    api_key: pydantic.SecretStr | None = pydantic.Field(
        default=None,
        validation_alias='ANTHROPIC_API_KEY',
    )
    default_model: str = DEFAULT_MODEL
    timeout: float = 30.0
    max_retries: int = 2


class CompletionResult[T: pydantic.BaseModel](pydantic.BaseModel):
    """Outcome of a :meth:`AnthropicClient.complete_json` call.

    ``degraded=True`` signals that the underlying API call failed and
    the caller-provided fallback was returned in its place.  Endpoints
    typically forward this flag to the UI so the user can be told
    "AI unavailable".
    """

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    data: T
    degraded: bool = False


_JSON_OBJECT = re.compile(r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}', re.DOTALL)


def _extract_json(text: str) -> dict[str, typing.Any] | None:
    """Pull the first JSON object out of a free-form response."""
    match = _JSON_OBJECT.search(text)
    if not match:
        return None
    try:
        parsed: typing.Any = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return typing.cast(dict[str, typing.Any], parsed)


class AnthropicClient:
    """Thin wrapper around :class:`anthropic.AsyncAnthropic`.

    A single instance is created at startup; callers reuse it across
    requests.  When :attr:`available` is ``False`` (no API key, or the
    SDK is not installed), :meth:`complete_json` returns the caller's
    ``fallback`` with ``degraded=True`` instead of raising.
    """

    def __init__(
        self,
        settings: AnthropicSettings | None = None,
        *,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self._settings = settings or AnthropicSettings()
        self._client = client
        if self._client is None and self._settings.api_key:
            self._client = self._build_client()

    def _build_client(self) -> anthropic.AsyncAnthropic | None:
        try:
            import anthropic as _anthropic
        except ImportError:
            LOGGER.warning(
                'anthropic SDK not installed; AnthropicClient disabled '
                "(install imbi-common's `llm` extra)"
            )
            return None
        api_key = (
            self._settings.api_key.get_secret_value()
            if self._settings.api_key
            else None
        )
        if not api_key:
            return None
        return _anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=self._settings.timeout,
            max_retries=self._settings.max_retries,
        )

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def default_model(self) -> str:
        return self._settings.default_model

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def complete_json[T: pydantic.BaseModel](
        self,
        prompt: str,
        *,
        schema: type[T],
        fallback: T,
        max_tokens: int = 1024,
        model: str | None = None,
        system: str | None = None,
        cache_system_prompt: bool = False,
    ) -> CompletionResult[T]:
        """Issue a JSON-shaped completion.

        ``schema`` is a Pydantic model the response is validated
        against.  ``fallback`` is returned (with ``degraded=True``) on
        any failure path.  When ``cache_system_prompt`` is ``True`` and
        ``system`` is provided, the system block is sent with prompt
        caching enabled — useful for callers that re-use the same
        instructions across many requests.
        """
        if self._client is None:
            return CompletionResult(data=fallback, degraded=True)
        chosen_model = model or self._settings.default_model
        system_blocks: typing.Any = system
        if cache_system_prompt and system:
            system_blocks = [
                {
                    'type': 'text',
                    'text': system,
                    'cache_control': {'type': 'ephemeral'},
                },
            ]
        kwargs: dict[str, typing.Any] = {
            'model': chosen_model,
            'max_tokens': max_tokens,
            'messages': [{'role': 'user', 'content': prompt}],
        }
        if system_blocks is not None:
            kwargs['system'] = system_blocks
        try:
            response = typing.cast(
                typing.Any, await self._client.messages.create(**kwargs)
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                'Anthropic completion failed (%s); returning fallback', exc
            )
            return CompletionResult(data=fallback, degraded=True)

        content_blocks: list[typing.Any] = list(
            getattr(response, 'content', None) or []
        )
        text = ''.join(
            str(getattr(block, 'text', ''))
            for block in content_blocks
            if getattr(block, 'type', None) == 'text'
        )
        payload = _extract_json(text)
        if payload is None:
            LOGGER.warning(
                'Anthropic response had no parseable JSON object; '
                'returning fallback'
            )
            return CompletionResult(data=fallback, degraded=True)
        try:
            parsed = schema.model_validate(payload)
        except pydantic.ValidationError as exc:
            LOGGER.warning(
                'Anthropic response failed schema validation (%s); '
                'returning fallback',
                exc,
            )
            return CompletionResult(data=fallback, degraded=True)
        return CompletionResult(data=parsed, degraded=False)


__all__ = [
    'DEFAULT_MODEL',
    'AnthropicClient',
    'AnthropicSettings',
    'CompletionResult',
]
