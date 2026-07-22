"""FastAPI dependency injection for the shared Anthropic client."""

import typing

import fastapi

from imbi.api import lifespans
from imbi.common.lifespan import InjectLifespan
from imbi.common.llm import AnthropicClient


def _get_anthropic_client(
    context: InjectLifespan,
) -> AnthropicClient:
    return context.get_state(lifespans.anthropic_hook)


InjectAnthropicClient = typing.Annotated[
    AnthropicClient, fastapi.Depends(_get_anthropic_client)
]
