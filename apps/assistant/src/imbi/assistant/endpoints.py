"""FastAPI endpoints for the AI assistant."""

import asyncio
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
    external_mcp,
    mcp,
    models,
    settings,
    system_prompt,
)

if typing.TYPE_CHECKING:
    import collections.abc

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


def _build_assistant_message(
    state: dict[str, typing.Any],
    tool_use_blocks: list[dict[str, typing.Any]],
) -> dict[str, typing.Any]:
    """Build the ``assistant`` API message for a tool-use round."""
    content: list[dict[str, typing.Any]] = []
    if state['text']:
        content.append({'type': 'text', 'text': state['text']})
    content.extend(
        {
            'type': 'tool_use',
            'id': tb['id'],
            'name': tb['name'],
            'input': tb['input'],
        }
        for tb in tool_use_blocks
    )
    return {'role': 'assistant', 'content': content}


def _build_tools_and_system(
    mcp_manager: mcp.MCPManager,
    auth_ctx: auth.AuthContext,
) -> tuple[list[dict[str, typing.Any]] | None, str]:
    """Build the Anthropic tool payload and system prompt from
    the current MCP, server, and client tool sets.
    """
    ext_manager = external_mcp.get_manager()
    all_tools = (
        mcp_manager.get_tools()
        + mcp.get_server_tools()
        + client_tools.get_tools()
        + ext_manager.get_tools()
    )
    system = system_prompt.build_system_prompt(
        auth_ctx,
        tool_names=[
            *mcp_manager.get_tool_names(),
            mcp.REFRESH_TOOL_NAME,
            *client_tools.get_tool_names(),
            *ext_manager.get_tool_names(),
        ],
    )
    return (all_tools or None), system


async def _run_external_tool(
    ext_manager: external_mcp.ExternalMCPManager,
    tb: dict[str, typing.Any],
    tool_results: list[dict[str, typing.Any]],
) -> collections.abc.AsyncIterator[str]:
    """Execute an external MCP tool, appending its result."""
    yield _sse_event(
        'tool_executing',
        {'id': tb['id'], 'name': tb['name']},
    )
    result_text, is_error = await ext_manager.execute_tool(
        tb['name'], tb['input']
    )
    tool_results.append(_tool_result_block(tb['id'], result_text, is_error))
    yield _sse_event(
        'tool_result',
        {'id': tb['id'], 'name': tb['name']},
    )


async def _run_openapi_tool(
    mcp_manager: mcp.MCPManager,
    tb: dict[str, typing.Any],
    tool_results: list[dict[str, typing.Any]],
    auth_token: str | None,
) -> collections.abc.AsyncIterator[str]:
    """Execute an OpenAPI-backed tool, appending its result."""
    yield _sse_event(
        'tool_executing',
        {'id': tb['id'], 'name': tb['name']},
    )
    result_text, is_error = await mcp_manager.execute_tool(
        tb['name'], tb['input'], auth_token
    )
    tool_results.append(_tool_result_block(tb['id'], result_text, is_error))
    yield _sse_event(
        'tool_result',
        {'id': tb['id'], 'name': tb['name']},
    )


def _truncate_tool_result(content: str) -> str:
    """Bound a tool result to ``max_tool_result_chars``.

    A tool that returns more than the configured limit — e.g. an
    unpaginated ``list_projects`` for a large org, which the API
    documents as "megabytes" — would otherwise be embedded verbatim,
    overflow the model's context window (HTTP 400), and, because the
    round is persisted before the next request runs, permanently brick
    the conversation. Keeping the head of the payload and appending a
    notice lets the model recover by narrowing its next call.
    """
    limit = settings.get_assistant_settings().max_tool_result_chars
    if limit <= 0 or len(content) <= limit:
        return content
    approx_tokens = len(content) // 4
    notice = (
        '\n\n[Tool result truncated: the full result was '
        f'{len(content)} characters (~{approx_tokens} tokens), '
        f'exceeding the {limit}-character limit; only the first '
        f'{limit} characters are shown. Re-run with a narrower query '
        '— pass slim=true, add filter predicates, or request a single '
        'item or page instead of the full collection.]'
    )
    return content[:limit] + notice


def _tool_result_block(
    tool_use_id: str,
    content: str,
    is_error: bool,
) -> dict[str, typing.Any]:
    """Build an Anthropic ``tool_result`` block, flagged on failure.

    Setting ``is_error: true`` is what tells Claude the tool call
    failed so it can react (e.g. correct its inputs) instead of
    consuming the error payload as a successful result.

    Oversized results are truncated (see :func:`_truncate_tool_result`)
    so a single large payload cannot overflow the context window.
    """
    block: dict[str, typing.Any] = {
        'type': 'tool_result',
        'tool_use_id': tool_use_id,
        'content': _truncate_tool_result(content),
    }
    if is_error:
        block['is_error'] = True
    return block


async def _run_server_tool(
    mcp_manager: mcp.MCPManager,
    tb: dict[str, typing.Any],
    tool_results: list[dict[str, typing.Any]],
    auth_ctx: auth.AuthContext,
    rebuild: dict[str, typing.Any],
    db: graph.Graph,
) -> collections.abc.AsyncIterator[str]:
    """Handle the refresh-all-tool-sources server tool.

    Refreshes both the Imbi API OpenAPI surface and the external MCP
    server connections, then rebuilds the combined tool list. The two
    refreshes are independent: a failure on one is reported but does
    not abort the other.
    """
    yield _sse_event(
        'tool_executing',
        {'id': tb['id'], 'name': tb['name']},
    )
    # OpenAPI refresh.
    openapi_success: bool
    openapi_count: int
    openapi_error: str | None = None
    try:
        openapi_success, openapi_count = await mcp_manager.reinitialize()
    except Exception as exc:
        LOGGER.exception('OpenAPI tool refresh failed')
        openapi_success, openapi_count = False, 0
        openapi_error = str(exc)
    # External MCP refresh.
    external_success: bool
    external_count: int
    external_error: str | None = None
    try:
        external_success, external_count = await external_mcp.reinitialize(db)
    except Exception as exc:
        LOGGER.exception('External MCP refresh failed')
        external_success, external_count = False, 0
        external_error = str(exc)
    # Rebuild the combined tools/system so subsequent rounds see the
    # union of refreshed sources, even if only one source refreshed
    # cleanly.
    if openapi_success or external_success:
        tools, system = _build_tools_and_system(mcp_manager, auth_ctx)
        rebuild['tools'], rebuild['system'] = tools, system
    payload: dict[str, typing.Any] = {
        'success': openapi_success and external_success,
        'tool_count': openapi_count + external_count,
        'openapi': {'success': openapi_success, 'tool_count': openapi_count},
        'external_mcp': {
            'success': external_success,
            'tool_count': external_count,
        },
    }
    if openapi_error is not None:
        payload['openapi']['error'] = openapi_error
    if external_error is not None:
        payload['external_mcp']['error'] = external_error
    is_error = not payload['success']
    tool_results.append(
        _tool_result_block(tb['id'], json.dumps(payload), is_error)
    )
    yield _sse_event(
        'tool_result',
        {'id': tb['id'], 'name': tb['name']},
    )


def _client_tool_event(
    tb: dict[str, typing.Any],
    tool_results: list[dict[str, typing.Any]],
) -> str:
    """Emit a client-action event and record its tool result."""
    tool_results.append(
        {
            'type': 'tool_result',
            'tool_use_id': tb['id'],
            'content': json.dumps({'success': True, 'action': tb['name']}),
        }
    )
    return _sse_event(
        'client_action',
        {'id': tb['id'], 'action': tb['name'], 'params': tb['input']},
    )


async def _dispatch_tool_uses(
    tool_use_blocks: list[dict[str, typing.Any]],
    tool_results: list[dict[str, typing.Any]],
    mcp_manager: mcp.MCPManager,
    ext_manager: external_mcp.ExternalMCPManager,
    auth_ctx: auth.AuthContext,
    auth_token: str | None,
    rebuild: dict[str, typing.Any],
    db: graph.Graph,
) -> collections.abc.AsyncIterator[str]:
    """Dispatch each tool_use block to the owning handler.

    Populates ``tool_results`` and, on a refresh, stores the rebuilt
    ``tools``/``system`` in ``rebuild``. ``db`` is forwarded to the
    refresh handler so the external MCP server list can be reread.
    """
    for tb in tool_use_blocks:
        if mcp.is_server_tool(tb['name']):
            async for chunk in _run_server_tool(
                mcp_manager, tb, tool_results, auth_ctx, rebuild, db
            ):
                yield chunk
            # external_mcp.reinitialize() replaces the module singleton,
            # so re-read it before routing any later tool_use blocks in
            # this same dispatch.
            ext_manager = external_mcp.get_manager()
        elif client_tools.is_client_tool(tb['name']):
            yield _client_tool_event(tb, tool_results)
        elif ext_manager.has_tool(tb['name']):
            async for chunk in _run_external_tool(
                ext_manager, tb, tool_results
            ):
                yield chunk
        else:
            async for chunk in _run_openapi_tool(
                mcp_manager, tb, tool_results, auth_token
            ):
                yield chunk


async def _persist_tool_round(
    db: graph.Graph,
    conversation_id: str,
    state: dict[str, typing.Any],
    tool_use_blocks: list[dict[str, typing.Any]],
    tool_results: list[dict[str, typing.Any]],
) -> None:
    """Write the assistant ``tool_use`` message and its matching
    ``tool_result`` user message in order, with no awaitable in
    between that could be cancelled.

    Called inside ``asyncio.shield`` from ``_stream_response`` so a
    client disconnect during the surrounding SSE stream can't leave
    the conversation with an orphan ``tool_use`` — which would make
    every future ``send_message`` 400 with "tool_use ids were found
    without tool_result blocks immediately after".
    """
    await age_ops.add_message(
        db,
        conversation_id=conversation_id,
        role='assistant',
        content=state['text'],
        tool_use=tool_use_blocks,
        token_usage=(state['usage'] or None),
    )
    await age_ops.add_message(
        db,
        conversation_id=conversation_id,
        role='user',
        content='',
        tool_results=tool_results,
    )


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
        # Re-read each round in case a prior refresh replaced the
        # external MCP singleton.
        ext_manager = external_mcp.get_manager()
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

        api_messages.append(
            _build_assistant_message(state, tool_use_blocks),
        )

        tool_results: list[dict[str, typing.Any]] = []
        rebuild: dict[str, typing.Any] = {}
        async for chunk in _dispatch_tool_uses(
            tool_use_blocks,
            tool_results,
            mcp_manager,
            ext_manager,
            auth_ctx,
            auth_token,
            rebuild,
            db,
        ):
            yield chunk
        if 'tools' in rebuild:
            tools, system = rebuild['tools'], rebuild['system']

        api_messages.append(
            {'role': 'user', 'content': tool_results},
        )
        # Persist the assistant tool_use and its matching tool_results
        # as a pair. Anthropic rejects a conversation where a tool_use
        # is not followed by a tool_result in the next message, so a
        # client disconnect between these two writes would permanently
        # break the conversation. ``asyncio.shield`` keeps the pair
        # alive even if our async generator is cancelled at the next
        # ``yield``; running them in a single coroutine keeps the
        # write order intact.
        await asyncio.shield(
            _persist_tool_round(
                db,
                conversation_id,
                state,
                tool_use_blocks,
                tool_results,
            )
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
    tools, system = _build_tools_and_system(mcp_manager, auth_ctx)

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
