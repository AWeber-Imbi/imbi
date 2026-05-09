"""FastAPI dependency injection for the shared Anthropic client."""

import typing

import fastapi
from imbi_common.lifespan import InjectLifespan
from imbi_common.llm import AnthropicClient

from imbi_api import lifespans


def _get_anthropic_client(
    context: InjectLifespan,
) -> AnthropicClient:
    return context.get_state(lifespans.anthropic_hook)


InjectAnthropicClient = typing.Annotated[
    AnthropicClient, fastapi.Depends(_get_anthropic_client)
]
