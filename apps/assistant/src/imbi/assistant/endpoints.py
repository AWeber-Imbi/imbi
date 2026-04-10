"""FastAPI endpoints for the AI assistant."""

import collections.abc
import json
import logging
import typing

import anthropic
import fastapi
import fastapi.security
from fastapi import responses
from imbi_common import graph

from imbi_assistant import (
    age_ops,
    auth,
    client,
    client_tools,
    mcp,
    models,
    settings,
    system_prompt,
)

LOGGER = logging.getLogger(__name__)

assistant_router = fastapi.APIRouter(
    tags=['Assistant'],
)

AuthDep = typing.Annotated[
    auth.AuthContext,
    fastapi.Depends(auth.get_current_user),
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
    response_model=models.ConversationResponse,
    status_code=201,
)
async def create_conversation(
    db: graph.Pool,
    auth_ctx: AuthDep,
    body: models.CreateConversationRequest | None = None,
) -> models.ConversationResponse:
    """Create a new conversation."""
    _require_assistant()
    assistant_settings = settings.get_assistant_settings()
    model = body.model if body and body.model else assistant_settings.model
    conv = await age_ops.create_conversation(
        db,
        user_email=auth_ctx.require_user.email,
        model=model,
    )
    return models.conversation_to_response(conv)


@assistant_router.get(
    '/conversations',
    response_model=list[models.ConversationResponse],
)
async def list_conversations(
    db: graph.Pool,
    auth_ctx: AuthDep,
    limit: int = 20,
    offset: int = 0,
    include_archived: bool = False,
) -> list[models.ConversationResponse]:
    """List the current user's conversations."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    convs = await age_ops.list_conversations(
        db,
        user_email=auth_ctx.require_user.email,
        limit=limit,
        offset=offset,
        include_archived=include_archived,
    )
    return [models.conversation_to_response(c) for c in convs]


@assistant_router.get(
    '/conversations/{conversation_id}',
    response_model=models.ConversationWithMessagesResponse,
)
async def get_conversation(
    conversation_id: str,
    db: graph.Pool,
    auth_ctx: AuthDep,
) -> models.ConversationWithMessagesResponse:
    """Get a conversation with its messages."""
    conv = await age_ops.get_conversation(
        db, conversation_id, auth_ctx.require_user.email
    )
    if not conv:
        raise fastapi.HTTPException(
            status_code=404,
            detail='Conversation not found',
        )
    msgs = await age_ops.get_messages(db, conversation_id)
    resp = models.conversation_to_response(conv)
    return models.ConversationWithMessagesResponse(
        **resp.model_dump(),
        messages=[models.message_to_response(m) for m in msgs],
    )


@assistant_router.delete(
    '/conversations/{conversation_id}',
    status_code=204,
)
async def delete_conversation(
    conversation_id: str,
    db: graph.Pool,
    auth_ctx: AuthDep,
) -> None:
    """Delete a conversation and its messages."""
    deleted = await age_ops.delete_conversation(
        db, conversation_id, auth_ctx.require_user.email
    )
    if not deleted:
        raise fastapi.HTTPException(
            status_code=404,
            detail='Conversation not found',
        )


@assistant_router.patch(
    '/conversations/{conversation_id}',
    response_model=models.ConversationResponse,
)
async def update_conversation(
    conversation_id: str,
    body: models.UpdateConversationRequest,
    db: graph.Pool,
    auth_ctx: AuthDep,
) -> models.ConversationResponse:
    """Update a conversation's title or archive status."""
    if body.title is not None:
        await age_ops.update_conversation_title(
            db,
            conversation_id,
            auth_ctx.require_user.email,
            body.title,
        )
    if body.is_archived is True:
        await age_ops.archive_conversation(
            db,
            conversation_id,
            auth_ctx.require_user.email,
        )

    conv = await age_ops.get_conversation(
        db, conversation_id, auth_ctx.require_user.email
    )
    if not conv:
        raise fastapi.HTTPException(
            status_code=404,
            detail='Conversation not found',
        )
    return models.conversation_to_response(conv)


# --- SSE Streaming ---


def _build_api_message(
    msg: models.Message,
) -> dict[str, typing.Any]:
    """Reconstruct Anthropic API message format."""
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
        return {
            'role': 'user',
            'content': msg.tool_results,
        }
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
    """Generate a short conversation title."""
    try:
        response = await api_client.messages.create(
            model=model,
            max_tokens=50,
            messages=[
                {
                    'role': 'user',
                    'content': (
                        'Generate a short title (max 6 '
                        'words) for this conversation. '
                        'Reply with ONLY the title, no '
                        'quotes or punctuation.'
                        f'\n\nUser: {user_message[:200]}'
                        f'\nAssistant:'
                        f' {assistant_response[:200]}'
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
) -> collections.abc.AsyncIterator[str]:
    """Process streaming events from the Anthropic API."""
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
                        'partial_json': (delta.partial_json),
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
    db: graph.Graph,
    conversation_id: str,
    auth_ctx: auth.AuthContext,
    api_messages: list[dict[str, typing.Any]],
    system: str,
    model: str,
    max_tokens: int,
    is_first_exchange: bool,
    user_message_content: str,
    tools: list[dict[str, typing.Any]] | None = None,
    auth_token: str | None = None,
) -> collections.abc.AsyncIterator[str]:
    """Stream an SSE response from the Anthropic API."""
    api_client = client.get_client()
    assistant_settings = settings.get_assistant_settings()
    max_rounds = assistant_settings.max_tool_rounds
    mcp_manager = mcp.get_manager()
    accumulated_text = ''

    state: dict[str, typing.Any] = {
        'text': '',
        'stop_reason': None,
        'usage': {},
    }
    tool_use_blocks: list[dict[str, typing.Any]] = []

    for _round in range(max_rounds):
        state = {
            'text': '',
            'stop_reason': None,
            'usage': {},
        }
        tool_use_blocks = []

        kwargs: dict[str, typing.Any] = {
            'model': model,
            'max_tokens': max_tokens,
            'system': system,
            'messages': api_messages,
        }
        if tools:
            kwargs['tools'] = tools

        try:
            async with api_client.messages.stream(
                **kwargs,
            ) as stream:
                async for chunk in _process_stream_events(
                    stream, tool_use_blocks, state
                ):
                    yield chunk
        except anthropic.APIError as exc:
            LOGGER.exception('Anthropic API error')
            yield _sse_event(
                'error',
                {'message': str(exc)},
            )
            return

        accumulated_text += state['text']

        if state['stop_reason'] != 'tool_use' or not tool_use_blocks:
            break

        await age_ops.add_message(
            db,
            conversation_id=conversation_id,
            role='assistant',
            content=state['text'],
            tool_use=tool_use_blocks,
            token_usage=(state['usage'] or None),
        )

        assistant_content: list[dict[str, typing.Any]] = []
        if state['text']:
            assistant_content.append(
                {'type': 'text', 'text': state['text']},
            )
        assistant_content.extend(
            {
                'type': 'tool_use',
                'id': tb['id'],
                'name': tb['name'],
                'input': tb['input'],
            }
            for tb in tool_use_blocks
        )
        api_messages.append(
            {
                'role': 'assistant',
                'content': assistant_content,
            },
        )

        tool_results: list[dict[str, typing.Any]] = []
        for tb in tool_use_blocks:
            if client_tools.is_client_tool(tb['name']):
                yield _sse_event(
                    'client_action',
                    {
                        'id': tb['id'],
                        'action': tb['name'],
                        'params': tb['input'],
                    },
                )
                tool_results.append(
                    {
                        'type': 'tool_result',
                        'tool_use_id': tb['id'],
                        'content': json.dumps(
                            {
                                'success': True,
                                'action': tb['name'],
                            }
                        ),
                    }
                )
            else:
                yield _sse_event(
                    'tool_executing',
                    {
                        'id': tb['id'],
                        'name': tb['name'],
                    },
                )
                result_text = await mcp_manager.execute_tool(
                    tb['name'],
                    tb['input'],
                    auth_token,
                )
                tool_results.append(
                    {
                        'type': 'tool_result',
                        'tool_use_id': tb['id'],
                        'content': result_text,
                    }
                )
                yield _sse_event(
                    'tool_result',
                    {
                        'id': tb['id'],
                        'name': tb['name'],
                    },
                )

        await age_ops.add_message(
            db,
            conversation_id=conversation_id,
            role='user',
            content='',
            tool_results=tool_results,
        )
        api_messages.append(
            {'role': 'user', 'content': tool_results},
        )

    msg = await age_ops.add_message(
        db,
        conversation_id=conversation_id,
        role='assistant',
        content=state['text'],
        tool_use=(tool_use_blocks or None),
        token_usage=(state['usage'] or None),
    )

    yield _sse_event(
        'done',
        {
            'message_id': msg.id,
            'usage': state['usage'],
        },
    )

    if is_first_exchange and accumulated_text:
        title = await _generate_title(
            api_client,
            user_message_content,
            accumulated_text,
            model,
        )
        await age_ops.update_conversation_title(
            db,
            conversation_id,
            auth_ctx.require_user.email,
            title,
        )
        yield _sse_event('title_updated', {'title': title})


@assistant_router.post(
    '/conversations/{conversation_id}/messages',
)
async def send_message(
    conversation_id: str,
    body: models.SendMessageRequest,
    db: graph.Pool,
    auth_ctx: AuthDep,
    credentials: (
        fastapi.security.HTTPAuthorizationCredentials | None
    ) = fastapi.Depends(auth.oauth2_scheme),  # noqa: B008
) -> responses.StreamingResponse:
    """Send a message and stream the response via SSE."""
    _require_assistant()

    conv = await age_ops.get_conversation(
        db, conversation_id, auth_ctx.require_user.email
    )
    if not conv:
        raise fastapi.HTTPException(
            status_code=404,
            detail='Conversation not found',
        )

    assistant_settings = settings.get_assistant_settings()
    msg_count = await age_ops.count_messages(db, conversation_id)
    max_turns = assistant_settings.max_conversation_turns
    if msg_count >= max_turns:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                'Conversation has reached the maximum '
                'number of turns. Start a new'
                ' conversation.'
            ),
        )

    await age_ops.add_message(
        db,
        conversation_id=conversation_id,
        role='user',
        content=body.content,
    )

    all_msgs = await age_ops.get_messages(db, conversation_id)
    api_messages: list[dict[str, typing.Any]] = [
        _build_api_message(m) for m in all_msgs
    ]

    mcp_manager = mcp.get_manager()
    mcp_tool_list = mcp_manager.get_tools()
    all_tools = (mcp_tool_list or []) + (client_tools.get_tools())
    tools = all_tools or None
    tool_names = mcp_manager.get_tool_names() + client_tools.get_tool_names()
    system = system_prompt.build_system_prompt(
        auth_ctx,
        tool_names=tool_names,
    )

    is_first_exchange = len(all_msgs) <= 2
    auth_token = credentials.credentials if credentials else None

    return responses.StreamingResponse(
        _stream_response(
            db=db,
            conversation_id=conversation_id,
            auth_ctx=auth_ctx,
            api_messages=api_messages,
            system=system,
            model=conv.model,
            max_tokens=assistant_settings.max_tokens,
            is_first_exchange=is_first_exchange,
            user_message_content=body.content,
            tools=tools,
            auth_token=auth_token,
        ),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )
