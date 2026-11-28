"""One JSON answer from a model, with a prompt that Imbi ships."""

import json
import logging
import typing

import pydantic

from imbi.api.auth import permissions
from imbi.common import graph
from imbi.common.llm import AnthropicClient, CompletionResult
from imbi.common.llm import resolve as llm_resolve
from imbi.common.prompts import system as system_prompts

LOGGER = logging.getLogger(__name__)


async def complete[T: pydantic.BaseModel](
    db: graph.Graph,
    anthropic: AnthropicClient,
    default: system_prompts.DefaultPrompt,
    text: str,
    fallback: T,
    auth: permissions.AuthContext,
) -> CompletionResult[T]:
    """Answer ``text`` with ``default``'s CMS prompt at ``@stable`` and
    its model (the packaged prompt and the default model when the CMS
    has none).

    The answer is a JSON object with the one field of ``fallback``'s
    model. The reply format is added after the prompt in code, so that
    an edit of the prompt in the CMS cannot break the parse.

    When the version names a model that cannot be used, no other model
    is called and the result is ``fallback``, degraded.
    """
    schema = type(fallback)
    (key,) = schema.model_fields
    try:
        prompt = await system_prompts.load_system_prompt(
            db,
            f'{default.ref}@stable',
            {},
            default,
            email=auth.user.email if auth.user else None,
        )
    except llm_resolve.ModelUnusable as e:
        LOGGER.warning('Not calling a model for %s: %s', default.ref, e)
        return CompletionResult(data=fallback, degraded=True)
    return await anthropic.complete_json(
        text,
        schema=schema,
        fallback=fallback,
        max_tokens=prompt.max_tokens or 200,
        model=prompt.model_id,
        system=(
            f'{prompt.text}\n\nReply with only a JSON object with one key, '
            f'"{key}", whose value is the {key}. No other text, no '
            'markdown fences.'
        ),
    )


#: The longest description that :func:`describe` returns.
MAX_DESCRIPTION_LENGTH = 300


class Description(pydantic.BaseModel):
    description: str


async def describe(
    db: graph.Graph,
    anthropic: AnthropicClient,
    default: system_prompts.DefaultPrompt,
    sent: dict[str, typing.Any],
    current: str,
    auth: permissions.AuthContext,
) -> str:
    """Write one description of ``sent`` with ``default`` (see
    :func:`complete`). Whitespace is collapsed and the text is cut to
    :data:`MAX_DESCRIPTION_LENGTH`. ``current`` is returned when no
    model answers or the answer is empty.
    """
    result = await complete(
        db,
        anthropic,
        default,
        json.dumps(sent),
        Description(description=current),
        auth,
    )
    if result.degraded:
        return current
    text = ' '.join(result.data.description.split())
    return text[:MAX_DESCRIPTION_LENGTH] or current
