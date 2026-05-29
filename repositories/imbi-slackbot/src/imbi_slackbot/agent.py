"""Non-streaming Claude tool loop for the Slack bot.

Given a reconstructed conversation, run Claude with the Imbi toolset,
executing any tool calls in a loop (up to ``max_rounds``) until Claude
stops requesting tools, and return the final assistant text.

"""

from __future__ import annotations

import logging
import typing

import anthropic

from imbi_slackbot import client, mcp

LOGGER = logging.getLogger(__name__)


def _collect(
    content: list[typing.Any],
) -> tuple[str, list[dict[str, typing.Any]], list[dict[str, typing.Any]]]:
    """Split a response's content into text, assistant blocks, tool uses.

    Returns:
        ``(text, assistant_blocks, tool_uses)`` where ``assistant_blocks``
        is the content to echo back as the assistant turn and ``tool_uses``
        are the ``tool_use`` blocks to execute.

    """
    text_parts: list[str] = []
    assistant_blocks: list[dict[str, typing.Any]] = []
    tool_uses: list[dict[str, typing.Any]] = []
    for block in content:
        if block.type == 'text':
            text_parts.append(block.text)
            assistant_blocks.append({'type': 'text', 'text': block.text})
        elif block.type == 'tool_use':
            tool_block = {
                'type': 'tool_use',
                'id': block.id,
                'name': block.name,
                'input': block.input,
            }
            assistant_blocks.append(tool_block)
            tool_uses.append(tool_block)
    return '\n'.join(text_parts), assistant_blocks, tool_uses


def _tool_result_block(
    tool_use_id: str,
    content: str,
    *,
    is_error: bool,
) -> dict[str, typing.Any]:
    """Build an Anthropic ``tool_result`` block, flagged on failure."""
    block: dict[str, typing.Any] = {
        'type': 'tool_result',
        'tool_use_id': tool_use_id,
        'content': content,
    }
    if is_error:
        block['is_error'] = True
    return block


async def run_turn(
    *,
    messages: list[dict[str, typing.Any]],
    system: str,
    tools: list[dict[str, typing.Any]] | None,
    auth_token: str,
    model: str,
    max_tokens: int,
    max_rounds: int,
) -> str:
    """Run one user turn through Claude and the tool loop.

    Args:
        messages: Conversation history in Anthropic message format. The
            final message must be the user's latest input.
        system: The system prompt.
        tools: Anthropic tool definitions, or ``None`` for no tools.
        auth_token: Per-user bearer token forwarded on every tool call.
        model: Claude model id.
        max_tokens: Max output tokens per response.
        max_rounds: Max tool-use rounds before giving up.

    Returns:
        The assistant's final text (concatenated across rounds).

    """
    api_client = client.get_client()
    manager = mcp.get_manager()
    accumulated: list[str] = []

    for _round in range(max_rounds):
        kwargs: dict[str, typing.Any] = {
            'model': model,
            'max_tokens': max_tokens,
            'system': system,
            'messages': messages,
        }
        if tools:
            kwargs['tools'] = tools

        try:
            response = typing.cast(
                'anthropic.types.Message',
                await api_client.messages.create(**kwargs),
            )
        except anthropic.APIError:
            LOGGER.exception('Anthropic API error')
            return (
                'Sorry — I hit an error talking to the model. '
                'Please try again.'
            )

        text, assistant_blocks, tool_uses = _collect(response.content)
        if text:
            accumulated.append(text)

        if response.stop_reason != 'tool_use' or not tool_uses:
            break

        messages.append({'role': 'assistant', 'content': assistant_blocks})

        tool_results: list[dict[str, typing.Any]] = []
        for tool_use in tool_uses:
            result_text, is_error = await manager.execute_tool(
                tool_use['name'],
                tool_use['input'],
                auth_token,
            )
            tool_results.append(
                _tool_result_block(
                    tool_use['id'], result_text, is_error=is_error
                )
            )
        messages.append({'role': 'user', 'content': tool_results})
    else:
        accumulated.append('_(Reached the tool-call limit before finishing.)_')

    return '\n\n'.join(part for part in accumulated if part).strip()
