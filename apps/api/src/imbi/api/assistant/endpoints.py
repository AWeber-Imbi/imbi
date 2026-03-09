"""FastAPI endpoints for the AI assistant."""

import asyncio
import json
import logging
import typing

import anthropic
import fastapi
from fastapi import responses

from imbi_api.assistant import (
    client,
    neo4j_ops,
    settings,
    system_prompt,
    tools,
)
from imbi_api.assistant import models as assistant_models
from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

assistant_router = fastapi.APIRouter(
    prefix='/assistant',
    tags=['Assistant'],
)

# Auth dependency using Annotated pattern (avoids B008)
AuthDep = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.get_current_user),
]


def _require_assistant() -> None:
    """Raise 503 if the assistant is not available."""
    if not client.is_available():
        raise fastapi.HTTPException(
            status_code=503,
            detail='AI assistant is not available',
        )


# --- Conversation CRUD ---


@assistant_router.post(
    '/conversations',
    response_model=assistant_models.ConversationResponse,
    status_code=201,
)
async def create_conversation(
    auth: AuthDep,
    body: assistant_models.CreateConversationRequest | None = None,
) -> assistant_models.ConversationResponse:
    """Create a new conversation."""
    _require_assistant()
    assistant_settings = settings.get_assistant_settings()
    model = body.model if body and body.model else assistant_settings.model
    conv = await neo4j_ops.create_conversation(
        user_email=auth.require_user.email, model=model
    )
    return assistant_models.conversation_to_response(conv)


@assistant_router.get(
    '/conversations',
    response_model=list[assistant_models.ConversationResponse],
)
async def list_conversations(
    auth: AuthDep,
    limit: int = 20,
    offset: int = 0,
    include_archived: bool = False,
) -> list[assistant_models.ConversationResponse]:
    """List the current user's conversations."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    convs = await neo4j_ops.list_conversations(
        user_email=auth.require_user.email,
        limit=limit,
        offset=offset,
        include_archived=include_archived,
    )
    return [assistant_models.conversation_to_response(c) for c in convs]


@assistant_router.get(
    '/conversations/{conversation_id}',
    response_model=(assistant_models.ConversationWithMessagesResponse),
)
async def get_conversation(
    conversation_id: str,
    auth: AuthDep,
) -> assistant_models.ConversationWithMessagesResponse:
    """Get a conversation with its messages."""
    conv = await neo4j_ops.get_conversation(
        conversation_id, auth.require_user.email
    )
    if not conv:
        raise fastapi.HTTPException(
            status_code=404, detail='Conversation not found'
        )
    msgs = await neo4j_ops.get_messages(conversation_id)
    resp = assistant_models.conversation_to_response(conv)
    return assistant_models.ConversationWithMessagesResponse(
        **resp.model_dump(),
        messages=[assistant_models.message_to_response(m) for m in msgs],
    )


@assistant_router.delete(
    '/conversations/{conversation_id}',
    status_code=204,
)
async def delete_conversation(
    conversation_id: str,
    auth: AuthDep,
) -> None:
    """Delete a conversation and its messages."""
    deleted = await neo4j_ops.delete_conversation(
        conversation_id, auth.require_user.email
    )
    if not deleted:
        raise fastapi.HTTPException(
            status_code=404, detail='Conversation not found'
        )


@assistant_router.patch(
    '/conversations/{conversation_id}',
    response_model=assistant_models.ConversationResponse,
)
async def update_conversation(
    conversation_id: str,
    body: assistant_models.UpdateConversationRequest,
    auth: AuthDep,
) -> assistant_models.ConversationResponse:
    """Update a conversation's title or archive status."""
    if body.title is not None:
        await neo4j_ops.update_conversation_title(
            conversation_id, auth.require_user.email, body.title
        )
    if body.is_archived is True:
        await neo4j_ops.archive_conversation(
            conversation_id, auth.require_user.email
        )

    conv = await neo4j_ops.get_conversation(
        conversation_id, auth.require_user.email
    )
    if not conv:
        raise fastapi.HTTPException(
            status_code=404, detail='Conversation not found'
        )
    return assistant_models.conversation_to_response(conv)


# --- SSE Streaming ---


def _build_api_message(
    msg: assistant_models.Message,
) -> dict[str, typing.Any]:
    """Reconstruct Anthropic API message format with tool blocks."""
    if msg.role == 'assistant' and msg.tool_use:
        content: list[dict[str, typing.Any]] = []
        if msg.content:
            content.append({'type': 'text', 'text': msg.content})
        content.extend(
            {
                'type': 'tool_use',
                'id': tb['id'],
                'name': tb['name'],
                'input': tb['input'],
            }
            for tb in msg.tool_use
        )
        return {'role': 'assistant', 'content': content}
    if msg.role == 'user' and msg.tool_results:
        return {'role': 'user', 'content': msg.tool_results}
    return {'role': msg.role, 'content': msg.content}


def _sse_event(event_type: str, data: typing.Any) -> str:
    """Format an SSE event string."""
    return f'event: {event_type}\ndata: {json.dumps(data)}\n\n'


async def _generate_title(
    api_client: anthropic.AsyncAnthropic,
    user_message: str,
    assistant_response: str,
    model: str,
) -> str:
    """Generate a short conversation title.

    Args:
        api_client: The Anthropic client.
        user_message: The first user message.
        assistant_response: The assistant's response.
        model: The Claude model to use.

    Returns:
        A short title string.

    """
    try:
        response = await api_client.messages.create(
            model=model,
            max_tokens=50,
            messages=[
                {
                    'role': 'user',
                    'content': (
                        'Generate a short title (max 6 words) '
                        'for this conversation. Reply with ONLY '
                        'the title, no quotes or punctuation.'
                        f'\n\nUser: {user_message[:200]}\n'
                        f'Assistant: {assistant_response[:200]}'
                    ),
                },
            ],
        )
        block = response.content[0]
        title = str(getattr(block, 'text', '')).strip()
        return title[:100]
    except Exception:
        LOGGER.exception('Failed to generate conversation title')
        return 'New conversation'


async def _process_stream_events(
    stream: typing.Any,
    tool_use_blocks: list[dict[str, typing.Any]],
    state: dict[str, typing.Any],
) -> typing.AsyncIterator[str]:
    """Process streaming events from the Anthropic API.

    Yields SSE-formatted strings for each event.

    """
    current_tool_id: str | None = None
    current_tool_name: str | None = None
    current_tool_input = ''

    async for event in stream:
        if event.type == 'content_block_start':
            block = event.content_block
            if block.type == 'tool_use':
                current_tool_id = block.id
                current_tool_name = block.name
                current_tool_input = ''
                yield _sse_event(
                    'tool_use_start',
                    {
                        'id': block.id,
                        'name': block.name,
                    },
                )
        elif event.type == 'content_block_delta':
            delta = event.delta
            if delta.type == 'text_delta':
                state['text'] += delta.text
                yield _sse_event('text', {'text': delta.text})
            elif delta.type == 'input_json_delta':
                current_tool_input += delta.partial_json
                yield _sse_event(
                    'tool_input',
                    {
                        'partial_json': delta.partial_json,
                    },
                )
        elif event.type == 'content_block_stop':
            if current_tool_id and current_tool_name:
                try:
                    parsed = json.loads(current_tool_input or '{}')
                except json.JSONDecodeError:
                    parsed = {}
                tool_use_blocks.append(
                    {
                        'id': current_tool_id,
                        'name': current_tool_name,
                        'input': parsed,
                    }
                )
                current_tool_id = None
                current_tool_name = None
                current_tool_input = ''
            yield _sse_event('content_block_stop', {})
        elif event.type == 'message_delta':
            state['stop_reason'] = event.delta.stop_reason
            if hasattr(event, 'usage') and event.usage:
                state['usage'] = {
                    'input_tokens': (event.usage.input_tokens),
                    'output_tokens': (event.usage.output_tokens),
                }


async def _stream_response(
    conversation_id: str,
    auth: permissions.AuthContext,
    api_messages: list[dict[str, typing.Any]],
    system: str,
    user_tools: list[dict[str, typing.Any]],
    model: str,
    max_tokens: int,
    is_first_exchange: bool,
    user_message_content: str,
) -> typing.AsyncIterator[str]:
    """Stream an SSE response from the Anthropic API.

    Handles tool use loops: when the model calls a tool,
    executes it, appends the result, and streams the follow-up.

    Yields:
        SSE-formatted strings.

    """
    api_client = client.get_client()
    tool_result_blocks: list[dict[str, typing.Any]] = []
    state: dict[str, typing.Any] = {
        'text': '',
        'stop_reason': None,
        'usage': {},
    }

    while True:
        tool_use_blocks: list[dict[str, typing.Any]] = []
        kwargs: dict[str, typing.Any] = {
            'model': model,
            'max_tokens': max_tokens,
            'system': system,
            'messages': api_messages,
        }
        if user_tools:
            kwargs['tools'] = user_tools

        try:
            async with api_client.messages.stream(**kwargs) as stream:
                async for chunk in _process_stream_events(
                    stream, tool_use_blocks, state
                ):
                    yield chunk
        except anthropic.APIError as exc:
            LOGGER.exception('Anthropic API error')
            yield _sse_event(
                'error',
                {
                    'message': str(exc),
                },
            )
            return

        # Handle tool use loop
        if state['stop_reason'] == 'tool_use' and tool_use_blocks:
            results = await _execute_tools(tool_use_blocks, auth)
            tool_result_blocks.extend(results)

            _append_tool_messages(
                api_messages,
                state['text'],
                tool_use_blocks,
                results,
            )
            # Reset text for the next iteration
            state['text'] = ''
            tool_use_blocks = []
            continue

        # Done streaming; save assistant message
        msg = await neo4j_ops.add_message(
            conversation_id=conversation_id,
            role='assistant',
            content=state['text'],
            tool_use=(tool_use_blocks if tool_use_blocks else None),
            tool_results=(tool_result_blocks if tool_result_blocks else None),
            token_usage=(state['usage'] if state['usage'] else None),
        )

        # Emit done event immediately (title gen is async)
        yield _sse_event(
            'done',
            {
                'message_id': msg.id,
                'usage': state['usage'],
            },
        )

        # Generate title after done event, non-blocking
        if is_first_exchange and state['text']:
            title = await _generate_title(
                api_client,
                user_message_content,
                state['text'],
                model,
            )
            await neo4j_ops.update_conversation_title(
                conversation_id, auth.require_user.email, title
            )
            yield _sse_event('title_updated', {'title': title})
        return


async def _execute_tools(
    tool_blocks: list[dict[str, typing.Any]],
    auth: permissions.AuthContext,
) -> list[dict[str, typing.Any]]:
    """Execute tool calls concurrently and return results."""
    tasks = [
        tools.execute_tool(b['name'], b['input'], auth) for b in tool_blocks
    ]
    texts = await asyncio.gather(*tasks)
    return [
        {
            'type': 'tool_result',
            'tool_use_id': block['id'],
            'content': text,
        }
        for block, text in zip(tool_blocks, texts, strict=True)
    ]


def _append_tool_messages(
    api_messages: list[dict[str, typing.Any]],
    response_text: str,
    tool_blocks: list[dict[str, typing.Any]],
    tool_results: list[dict[str, typing.Any]],
) -> None:
    """Append assistant tool use and user tool results."""
    assistant_content: list[dict[str, typing.Any]] = []
    if response_text:
        assistant_content.append(
            {
                'type': 'text',
                'text': response_text,
            }
        )
    for tb in tool_blocks:
        assistant_content.append(
            {
                'type': 'tool_use',
                'id': tb['id'],
                'name': tb['name'],
                'input': tb['input'],
            }
        )
    api_messages.append(
        {
            'role': 'assistant',
            'content': assistant_content,
        }
    )
    api_messages.append(
        {
            'role': 'user',
            'content': tool_results,
        }
    )


@assistant_router.post(
    '/conversations/{conversation_id}/messages',
)
async def send_message(
    conversation_id: str,
    body: assistant_models.SendMessageRequest,
    auth: AuthDep,
) -> responses.StreamingResponse:
    """Send a message and stream the response via SSE."""
    _require_assistant()

    # Verify conversation ownership
    conv = await neo4j_ops.get_conversation(
        conversation_id, auth.require_user.email
    )
    if not conv:
        raise fastapi.HTTPException(
            status_code=404, detail='Conversation not found'
        )

    # Check turn limit using count query (avoids loading
    # all messages just to count them)
    assistant_settings = settings.get_assistant_settings()
    msg_count = await neo4j_ops.count_messages(conversation_id)
    max_turns = assistant_settings.max_conversation_turns
    if msg_count >= max_turns:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                'Conversation has reached the maximum '
                'number of turns. Start a new conversation.'
            ),
        )

    # Save user message
    await neo4j_ops.add_message(
        conversation_id=conversation_id,
        role='user',
        content=body.content,
    )

    # Build API messages from conversation history (single
    # fetch, includes the user message just saved)
    all_msgs = await neo4j_ops.get_messages(conversation_id)
    api_messages: list[dict[str, typing.Any]] = [
        _build_api_message(m) for m in all_msgs
    ]

    # Build tools and system prompt (single pass)
    user_tools, tool_names = tools.get_tools_for_user(
        auth.permissions, auth.require_user.is_admin
    )
    system = system_prompt.build_system_prompt(auth, tool_names)

    is_first_exchange = len(all_msgs) <= 2

    return responses.StreamingResponse(
        _stream_response(
            conversation_id=conversation_id,
            auth=auth,
            api_messages=api_messages,
            system=system,
            user_tools=user_tools,
            model=conv.model,
            max_tokens=assistant_settings.max_tokens,
            is_first_exchange=is_first_exchange,
            user_message_content=body.content,
        ),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )
