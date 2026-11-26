"""One JSON answer from a model, with a prompt that Imbi ships."""

import pydantic

from imbi.api.auth import permissions
from imbi.common import graph
from imbi.common.llm import AnthropicClient, CompletionResult
from imbi.common.prompts import system as system_prompts


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
    """
    schema = type(fallback)
    (key,) = schema.model_fields
    prompt = await system_prompts.load_system_prompt(
        db,
        f'{default.ref}@stable',
        {},
        default,
        email=auth.user.email if auth.user else None,
    )
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
