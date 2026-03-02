"""Tests for assistant endpoints module."""

import datetime
import unittest
from unittest import mock

import fastapi
from imbi_common import models

from imbi_api.assistant import (
    client,
    endpoints,
    settings,
)
from imbi_api.assistant import (
    models as assistant_models,
)
from imbi_api.auth import permissions


def _make_user() -> models.User:
    """Create a test User model."""
    return models.User(
        email='test@example.com',
        display_name='Test User',
        is_admin=False,
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _make_auth(
    is_admin: bool = False,
    perms: set[str] | None = None,
) -> permissions.AuthContext:
    """Create a test AuthContext."""
    user = _make_user()
    user.is_admin = is_admin
    return permissions.AuthContext(
        user=user,
        auth_method='jwt',
        permissions=perms or {'project:read'},
    )


def _make_conversation(
    conv_id: str = 'conv-123',
) -> assistant_models.Conversation:
    """Create a test Conversation model."""
    now = datetime.datetime.now(datetime.UTC)
    return assistant_models.Conversation(
        id=conv_id,
        user_email='test@example.com',
        title='Test Conversation',
        created_at=now,
        updated_at=now,
        model='claude-sonnet-4-20250514',
    )


def _create_test_app() -> fastapi.FastAPI:
    """Create a test FastAPI app with assistant router."""
    app = fastapi.FastAPI()
    app.include_router(endpoints.assistant_router)
    return app


class RequireAssistantTestCase(unittest.TestCase):
    """Test cases for _require_assistant."""

    def setUp(self) -> None:
        self._original = client._client

    def tearDown(self) -> None:
        client._client = self._original

    def test_raises_503_when_unavailable(self) -> None:
        """Test that 503 is raised when client is unavailable."""
        client._client = None
        with self.assertRaises(fastapi.HTTPException) as ctx:
            endpoints._require_assistant()
        self.assertEqual(ctx.exception.status_code, 503)

    def test_no_error_when_available(self) -> None:
        """Test no error when client is available."""
        client._client = mock.MagicMock()
        endpoints._require_assistant()  # Should not raise


class SSEEventTestCase(unittest.TestCase):
    """Test cases for _sse_event."""

    def test_format_text_event(self) -> None:
        """Test formatting an SSE text event."""
        result = endpoints._sse_event('text', {'text': 'hello'})
        self.assertTrue(result.startswith('event: text\n'))
        self.assertIn('"text": "hello"', result)
        self.assertTrue(result.endswith('\n\n'))

    def test_format_done_event(self) -> None:
        """Test formatting a done event."""
        result = endpoints._sse_event(
            'done', {'message_id': 'msg-1', 'usage': {}}
        )
        self.assertIn('event: done', result)
        self.assertIn('msg-1', result)


class GenerateTitleTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for _generate_title."""

    async def test_generate_title_success(self) -> None:
        """Test successful title generation."""
        mock_client = mock.AsyncMock()
        mock_response = mock.MagicMock()
        mock_block = mock.MagicMock()
        mock_block.text = 'Short Title'
        mock_response.content = [mock_block]
        mock_client.messages.create.return_value = mock_response

        title = await endpoints._generate_title(
            mock_client,
            'What projects exist?',
            'Here are the projects...',
            'claude-sonnet-4-20250514',
        )
        self.assertEqual(title, 'Short Title')

    async def test_generate_title_truncates(self) -> None:
        """Test title truncation at 100 chars."""
        mock_client = mock.AsyncMock()
        mock_response = mock.MagicMock()
        mock_block = mock.MagicMock()
        mock_block.text = 'A' * 150
        mock_response.content = [mock_block]
        mock_client.messages.create.return_value = mock_response

        title = await endpoints._generate_title(
            mock_client, 'msg', 'resp', 'model'
        )
        self.assertEqual(len(title), 100)

    async def test_generate_title_error_fallback(self) -> None:
        """Test fallback title on API error."""
        mock_client = mock.AsyncMock()
        mock_client.messages.create.side_effect = RuntimeError('API error')

        title = await endpoints._generate_title(
            mock_client, 'msg', 'resp', 'model'
        )
        self.assertEqual(title, 'New conversation')


class AppendToolMessagesTestCase(unittest.TestCase):
    """Test cases for _append_tool_messages."""

    def test_append_with_text_and_tools(self) -> None:
        """Test appending messages with text and tool blocks."""
        api_messages: list[dict] = []
        tool_blocks = [
            {'id': 'tool-1', 'name': 'list_projects', 'input': {}},
        ]
        tool_results = [
            {'type': 'tool_result', 'tool_use_id': 'tool-1', 'content': 'ok'},
        ]
        endpoints._append_tool_messages(
            api_messages, 'Some text', tool_blocks, tool_results
        )
        self.assertEqual(len(api_messages), 2)
        # First should be assistant message
        self.assertEqual(api_messages[0]['role'], 'assistant')
        # Should have text + tool_use blocks
        self.assertEqual(len(api_messages[0]['content']), 2)
        self.assertEqual(api_messages[0]['content'][0]['type'], 'text')
        self.assertEqual(api_messages[0]['content'][1]['type'], 'tool_use')
        # Second should be user message with tool results
        self.assertEqual(api_messages[1]['role'], 'user')

    def test_append_without_text(self) -> None:
        """Test appending messages without response text."""
        api_messages: list[dict] = []
        tool_blocks = [
            {'id': 'tool-1', 'name': 'test', 'input': {}},
        ]
        tool_results = [
            {'type': 'tool_result', 'tool_use_id': 'tool-1', 'content': 'ok'},
        ]
        endpoints._append_tool_messages(
            api_messages, '', tool_blocks, tool_results
        )
        # Only tool_use blocks, no text block
        self.assertEqual(len(api_messages[0]['content']), 1)
        self.assertEqual(api_messages[0]['content'][0]['type'], 'tool_use')


class ExecuteToolsTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for _execute_tools."""

    async def test_execute_single_tool(self) -> None:
        """Test executing a single tool."""
        auth = _make_auth(is_admin=True)
        tool_blocks = [
            {'id': 'tool-1', 'name': 'list_projects', 'input': {}},
        ]
        with mock.patch(
            'imbi_api.assistant.tools.execute_tool',
            return_value='Projects found',
        ):
            results = await endpoints._execute_tools(tool_blocks, auth)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['type'], 'tool_result')
        self.assertEqual(results[0]['tool_use_id'], 'tool-1')
        self.assertEqual(results[0]['content'], 'Projects found')

    async def test_execute_multiple_tools(self) -> None:
        """Test executing multiple tools concurrently."""
        auth = _make_auth(is_admin=True)
        tool_blocks = [
            {'id': 't1', 'name': 'list_projects', 'input': {}},
            {'id': 't2', 'name': 'list_teams', 'input': {}},
        ]
        with mock.patch(
            'imbi_api.assistant.tools.execute_tool',
            side_effect=['projects', 'teams'],
        ):
            results = await endpoints._execute_tools(tool_blocks, auth)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['content'], 'projects')
        self.assertEqual(results[1]['content'], 'teams')


class ProcessStreamEventsTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for _process_stream_events."""

    async def test_text_delta(self) -> None:
        """Test processing text delta events."""
        event = mock.MagicMock()
        event.type = 'content_block_delta'
        event.delta.type = 'text_delta'
        event.delta.text = 'Hello'

        async def fake_stream():
            yield event

        state = {'text': '', 'stop_reason': None, 'usage': {}}
        tool_blocks: list[dict] = []

        chunks = []
        async for chunk in endpoints._process_stream_events(
            fake_stream(), tool_blocks, state
        ):
            chunks.append(chunk)

        self.assertEqual(state['text'], 'Hello')
        self.assertEqual(len(chunks), 1)
        self.assertIn('event: text', chunks[0])

    async def test_tool_use_flow(self) -> None:
        """Test processing tool use start, input, and stop."""
        start_event = mock.MagicMock()
        start_event.type = 'content_block_start'
        start_event.content_block.type = 'tool_use'
        start_event.content_block.id = 'tool-1'
        start_event.content_block.name = 'list_projects'

        input_event = mock.MagicMock()
        input_event.type = 'content_block_delta'
        input_event.delta.type = 'input_json_delta'
        input_event.delta.partial_json = '{"limit": 10}'

        stop_event = mock.MagicMock()
        stop_event.type = 'content_block_stop'

        async def fake_stream():
            yield start_event
            yield input_event
            yield stop_event

        state = {'text': '', 'stop_reason': None, 'usage': {}}
        tool_blocks: list[dict] = []

        chunks = []
        async for chunk in endpoints._process_stream_events(
            fake_stream(), tool_blocks, state
        ):
            chunks.append(chunk)

        self.assertEqual(len(tool_blocks), 1)
        self.assertEqual(tool_blocks[0]['name'], 'list_projects')
        self.assertEqual(tool_blocks[0]['input'], {'limit': 10})

    async def test_message_delta_with_stop_reason(self) -> None:
        """Test processing message_delta with stop reason."""
        event = mock.MagicMock()
        event.type = 'message_delta'
        event.delta.stop_reason = 'end_turn'
        event.usage = mock.MagicMock()
        event.usage.input_tokens = 100
        event.usage.output_tokens = 50

        async def fake_stream():
            yield event

        state = {'text': '', 'stop_reason': None, 'usage': {}}
        tool_blocks: list[dict] = []

        async for _ in endpoints._process_stream_events(
            fake_stream(), tool_blocks, state
        ):
            pass

        self.assertEqual(state['stop_reason'], 'end_turn')
        self.assertEqual(state['usage']['input_tokens'], 100)

    async def test_content_block_start_non_tool(self) -> None:
        """Test content_block_start with non-tool block."""
        event = mock.MagicMock()
        event.type = 'content_block_start'
        event.content_block.type = 'text'

        async def fake_stream():
            yield event

        state = {'text': '', 'stop_reason': None, 'usage': {}}
        tool_blocks: list[dict] = []

        chunks = []
        async for chunk in endpoints._process_stream_events(
            fake_stream(), tool_blocks, state
        ):
            chunks.append(chunk)

        # No tool_use_start event should be emitted
        self.assertEqual(len(tool_blocks), 0)

    async def test_content_block_stop_without_tool(self) -> None:
        """Test content_block_stop when not in a tool use block."""
        event = mock.MagicMock()
        event.type = 'content_block_stop'

        async def fake_stream():
            yield event

        state = {'text': '', 'stop_reason': None, 'usage': {}}
        tool_blocks: list[dict] = []

        chunks = []
        async for chunk in endpoints._process_stream_events(
            fake_stream(), tool_blocks, state
        ):
            chunks.append(chunk)

        # Should emit content_block_stop but no tool block added
        self.assertEqual(len(tool_blocks), 0)
        self.assertEqual(len(chunks), 1)

    async def test_tool_use_invalid_json(self) -> None:
        """Test tool use with invalid JSON input."""
        start_event = mock.MagicMock()
        start_event.type = 'content_block_start'
        start_event.content_block.type = 'tool_use'
        start_event.content_block.id = 'tool-1'
        start_event.content_block.name = 'test_tool'

        input_event = mock.MagicMock()
        input_event.type = 'content_block_delta'
        input_event.delta.type = 'input_json_delta'
        input_event.delta.partial_json = '{invalid'

        stop_event = mock.MagicMock()
        stop_event.type = 'content_block_stop'

        async def fake_stream():
            yield start_event
            yield input_event
            yield stop_event

        state = {'text': '', 'stop_reason': None, 'usage': {}}
        tool_blocks: list[dict] = []

        async for _ in endpoints._process_stream_events(
            fake_stream(), tool_blocks, state
        ):
            pass

        # Invalid JSON should result in empty dict
        self.assertEqual(len(tool_blocks), 1)
        self.assertEqual(tool_blocks[0]['input'], {})

    async def test_message_delta_without_usage(self) -> None:
        """Test message_delta without usage attribute."""
        event = mock.MagicMock()
        event.type = 'message_delta'
        event.delta.stop_reason = 'end_turn'
        event.usage = None

        async def fake_stream():
            yield event

        state = {'text': '', 'stop_reason': None, 'usage': {}}
        tool_blocks: list[dict] = []

        async for _ in endpoints._process_stream_events(
            fake_stream(), tool_blocks, state
        ):
            pass

        self.assertEqual(state['stop_reason'], 'end_turn')
        self.assertEqual(state['usage'], {})


class CreateConversationEndpointTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for create_conversation endpoint."""

    def setUp(self) -> None:
        self._original_client = client._client
        settings._assistant_settings = None

    def tearDown(self) -> None:
        client._client = self._original_client
        settings._assistant_settings = None

    @mock.patch(
        'imbi_api.assistant.neo4j_ops.create_conversation',
    )
    async def test_create_conversation(
        self,
        mock_create: mock.AsyncMock,
    ) -> None:
        """Test creating a conversation via endpoint."""
        client._client = mock.MagicMock()
        auth = _make_auth()
        conv = _make_conversation()
        mock_create.return_value = conv

        with mock.patch.dict('os.environ', {}, clear=True):
            result = await endpoints.create_conversation(auth=auth, body=None)
        self.assertEqual(result.id, 'conv-123')

    @mock.patch(
        'imbi_api.assistant.neo4j_ops.create_conversation',
    )
    async def test_create_conversation_custom_model(
        self,
        mock_create: mock.AsyncMock,
    ) -> None:
        """Test creating a conversation with custom model."""
        client._client = mock.MagicMock()
        auth = _make_auth()
        conv = _make_conversation()
        mock_create.return_value = conv

        body = assistant_models.CreateConversationRequest(
            model='claude-opus-4-20250514',
        )
        with mock.patch.dict('os.environ', {}, clear=True):
            await endpoints.create_conversation(auth=auth, body=body)
        mock_create.assert_called_once_with(
            user_email='test@example.com',
            model='claude-opus-4-20250514',
        )


class ListConversationsEndpointTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for list_conversations endpoint."""

    @mock.patch(
        'imbi_api.assistant.neo4j_ops.list_conversations',
    )
    async def test_list_conversations(
        self,
        mock_list: mock.AsyncMock,
    ) -> None:
        """Test listing conversations."""
        auth = _make_auth()
        mock_list.return_value = [_make_conversation()]

        result = await endpoints.list_conversations(auth=auth)
        self.assertEqual(len(result), 1)

    @mock.patch(
        'imbi_api.assistant.neo4j_ops.list_conversations',
    )
    async def test_list_conversations_limit_capped(
        self,
        mock_list: mock.AsyncMock,
    ) -> None:
        """Test that limit is capped at 100."""
        auth = _make_auth()
        mock_list.return_value = []

        await endpoints.list_conversations(auth=auth, limit=500)
        mock_list.assert_called_once_with(
            user_email='test@example.com',
            limit=100,
            offset=0,
            include_archived=False,
        )

    @mock.patch(
        'imbi_api.assistant.neo4j_ops.list_conversations',
    )
    async def test_list_conversations_negative_values(
        self,
        mock_list: mock.AsyncMock,
    ) -> None:
        """Test that negative limit/offset are clamped."""
        auth = _make_auth()
        mock_list.return_value = []

        await endpoints.list_conversations(auth=auth, limit=-5, offset=-10)
        mock_list.assert_called_once_with(
            user_email='test@example.com',
            limit=1,
            offset=0,
            include_archived=False,
        )


class GetConversationEndpointTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for get_conversation endpoint."""

    @mock.patch(
        'imbi_api.assistant.neo4j_ops.get_messages',
    )
    @mock.patch(
        'imbi_api.assistant.neo4j_ops.get_conversation',
    )
    async def test_get_conversation(
        self,
        mock_get: mock.AsyncMock,
        mock_msgs: mock.AsyncMock,
    ) -> None:
        """Test getting a conversation with messages."""
        auth = _make_auth()
        mock_get.return_value = _make_conversation()
        mock_msgs.return_value = []

        result = await endpoints.get_conversation(
            conversation_id='conv-123', auth=auth
        )
        self.assertEqual(result.id, 'conv-123')
        self.assertEqual(result.messages, [])

    @mock.patch(
        'imbi_api.assistant.neo4j_ops.get_conversation',
    )
    async def test_get_conversation_not_found(
        self,
        mock_get: mock.AsyncMock,
    ) -> None:
        """Test getting a nonexistent conversation."""
        auth = _make_auth()
        mock_get.return_value = None

        with self.assertRaises(fastapi.HTTPException) as ctx:
            await endpoints.get_conversation(
                conversation_id='missing', auth=auth
            )
        self.assertEqual(ctx.exception.status_code, 404)


class DeleteConversationEndpointTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for delete_conversation endpoint."""

    @mock.patch(
        'imbi_api.assistant.neo4j_ops.delete_conversation',
    )
    async def test_delete_conversation(
        self,
        mock_delete: mock.AsyncMock,
    ) -> None:
        """Test deleting a conversation."""
        auth = _make_auth()
        mock_delete.return_value = True

        await endpoints.delete_conversation(
            conversation_id='conv-123', auth=auth
        )
        mock_delete.assert_called_once_with('conv-123', 'test@example.com')

    @mock.patch(
        'imbi_api.assistant.neo4j_ops.delete_conversation',
    )
    async def test_delete_conversation_not_found(
        self,
        mock_delete: mock.AsyncMock,
    ) -> None:
        """Test deleting a nonexistent conversation."""
        auth = _make_auth()
        mock_delete.return_value = False

        with self.assertRaises(fastapi.HTTPException) as ctx:
            await endpoints.delete_conversation(
                conversation_id='missing', auth=auth
            )
        self.assertEqual(ctx.exception.status_code, 404)


class UpdateConversationEndpointTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for update_conversation endpoint."""

    @mock.patch(
        'imbi_api.assistant.neo4j_ops.get_conversation',
    )
    @mock.patch(
        'imbi_api.assistant.neo4j_ops.update_conversation_title',
    )
    async def test_update_title(
        self,
        mock_update: mock.AsyncMock,
        mock_get: mock.AsyncMock,
    ) -> None:
        """Test updating a conversation title."""
        auth = _make_auth()
        mock_update.return_value = True
        conv = _make_conversation()
        conv.title = 'Updated Title'
        mock_get.return_value = conv

        body = assistant_models.UpdateConversationRequest(
            title='Updated Title'
        )
        result = await endpoints.update_conversation(
            conversation_id='conv-123', body=body, auth=auth
        )
        self.assertEqual(result.title, 'Updated Title')
        mock_update.assert_called_once()

    @mock.patch(
        'imbi_api.assistant.neo4j_ops.get_conversation',
    )
    @mock.patch(
        'imbi_api.assistant.neo4j_ops.archive_conversation',
    )
    async def test_archive(
        self,
        mock_archive: mock.AsyncMock,
        mock_get: mock.AsyncMock,
    ) -> None:
        """Test archiving a conversation."""
        auth = _make_auth()
        mock_archive.return_value = True
        mock_get.return_value = _make_conversation()

        body = assistant_models.UpdateConversationRequest(
            is_archived=True,
        )
        await endpoints.update_conversation(
            conversation_id='conv-123', body=body, auth=auth
        )
        mock_archive.assert_called_once()

    @mock.patch(
        'imbi_api.assistant.neo4j_ops.get_conversation',
    )
    async def test_update_not_found(
        self,
        mock_get: mock.AsyncMock,
    ) -> None:
        """Test updating a nonexistent conversation."""
        auth = _make_auth()
        mock_get.return_value = None

        body = assistant_models.UpdateConversationRequest(
            title='New Title',
        )
        with self.assertRaises(fastapi.HTTPException) as ctx:
            await endpoints.update_conversation(
                conversation_id='missing', body=body, auth=auth
            )
        self.assertEqual(ctx.exception.status_code, 404)


class SendMessageEndpointTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for send_message endpoint."""

    def setUp(self) -> None:
        self._original_client = client._client
        settings._assistant_settings = None

    def tearDown(self) -> None:
        client._client = self._original_client
        settings._assistant_settings = None

    async def test_send_message_assistant_unavailable(self) -> None:
        """Test sending message when assistant is unavailable."""
        client._client = None
        auth = _make_auth()
        body = assistant_models.SendMessageRequest(content='Hello')

        with self.assertRaises(fastapi.HTTPException) as ctx:
            await endpoints.send_message(
                conversation_id='conv-123', body=body, auth=auth
            )
        self.assertEqual(ctx.exception.status_code, 503)

    @mock.patch(
        'imbi_api.assistant.neo4j_ops.get_conversation',
    )
    async def test_send_message_conversation_not_found(
        self,
        mock_get: mock.AsyncMock,
    ) -> None:
        """Test sending message to nonexistent conversation."""
        client._client = mock.MagicMock()
        auth = _make_auth()
        mock_get.return_value = None
        body = assistant_models.SendMessageRequest(content='Hello')

        with self.assertRaises(fastapi.HTTPException) as ctx:
            await endpoints.send_message(
                conversation_id='missing', body=body, auth=auth
            )
        self.assertEqual(ctx.exception.status_code, 404)

    @mock.patch.dict('os.environ', {}, clear=True)
    @mock.patch(
        'imbi_api.assistant.neo4j_ops.count_messages',
    )
    @mock.patch(
        'imbi_api.assistant.neo4j_ops.get_conversation',
    )
    async def test_send_message_turn_limit_reached(
        self,
        mock_get: mock.AsyncMock,
        mock_count: mock.AsyncMock,
    ) -> None:
        """Test sending message when turn limit is reached."""
        client._client = mock.MagicMock()
        auth = _make_auth()
        mock_get.return_value = _make_conversation()
        mock_count.return_value = 100  # At the limit

        body = assistant_models.SendMessageRequest(content='Hello')
        with self.assertRaises(fastapi.HTTPException) as ctx:
            await endpoints.send_message(
                conversation_id='conv-123', body=body, auth=auth
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn('maximum', str(ctx.exception.detail))

    @mock.patch.dict('os.environ', {}, clear=True)
    @mock.patch(
        'imbi_api.assistant.system_prompt.build_system_prompt',
    )
    @mock.patch(
        'imbi_api.assistant.tools.get_tools_for_user',
    )
    @mock.patch(
        'imbi_api.assistant.neo4j_ops.get_messages',
    )
    @mock.patch(
        'imbi_api.assistant.neo4j_ops.add_message',
    )
    @mock.patch(
        'imbi_api.assistant.neo4j_ops.count_messages',
    )
    @mock.patch(
        'imbi_api.assistant.neo4j_ops.get_conversation',
    )
    async def test_send_message_returns_streaming_response(
        self,
        mock_get_conv: mock.AsyncMock,
        mock_count: mock.AsyncMock,
        mock_add: mock.AsyncMock,
        mock_get_msgs: mock.AsyncMock,
        mock_get_tools: mock.MagicMock,
        mock_build_prompt: mock.MagicMock,
    ) -> None:
        """Test send_message returns a StreamingResponse."""
        client._client = mock.MagicMock()
        auth = _make_auth()
        mock_get_conv.return_value = _make_conversation()
        mock_count.return_value = 0
        now = datetime.datetime.now(datetime.UTC)
        mock_add.return_value = assistant_models.Message(
            id='msg-1',
            conversation_id='conv-123',
            role='user',
            content='Hello',
            created_at=now,
            sequence=0,
        )
        mock_get_msgs.return_value = [
            assistant_models.Message(
                id='msg-1',
                conversation_id='conv-123',
                role='user',
                content='Hello',
                created_at=now,
                sequence=0,
            ),
        ]
        mock_get_tools.return_value = ([], [])
        mock_build_prompt.return_value = 'System prompt'

        body = assistant_models.SendMessageRequest(content='Hello')
        from fastapi import responses

        result = await endpoints.send_message(
            conversation_id='conv-123', body=body, auth=auth
        )
        self.assertIsInstance(result, responses.StreamingResponse)
        self.assertEqual(result.media_type, 'text/event-stream')


class StreamResponseTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for _stream_response."""

    def setUp(self) -> None:
        self._original_client = client._client
        settings._assistant_settings = None

    def tearDown(self) -> None:
        client._client = self._original_client
        settings._assistant_settings = None

    @staticmethod
    def _make_stream_ctx(events: list) -> mock.MagicMock:
        """Create a mock stream context manager.

        The Anthropic stream() method returns a sync context
        manager (not async), so we use MagicMock for the return
        value and AsyncMock for __aenter__/__aexit__.

        """
        mock_stream = mock.MagicMock()

        async def aiter_events():
            for event in events:
                yield event

        mock_stream.__aiter__ = lambda self: aiter_events()
        mock_stream.__aenter__ = mock.AsyncMock(
            return_value=mock_stream,
        )
        mock_stream.__aexit__ = mock.AsyncMock(
            return_value=None,
        )
        return mock_stream

    async def test_stream_basic_text(self) -> None:
        """Test streaming a basic text response."""
        now = datetime.datetime.now(datetime.UTC)
        mock_api_client = mock.MagicMock()

        text_event = mock.MagicMock()
        text_event.type = 'content_block_delta'
        text_event.delta.type = 'text_delta'
        text_event.delta.text = 'Hello world'

        done_event = mock.MagicMock()
        done_event.type = 'message_delta'
        done_event.delta.stop_reason = 'end_turn'
        done_event.usage = mock.MagicMock()
        done_event.usage.input_tokens = 10
        done_event.usage.output_tokens = 5

        stream_ctx = self._make_stream_ctx([text_event, done_event])
        mock_api_client.messages.stream.return_value = stream_ctx
        client._client = mock_api_client

        auth = _make_auth()
        msg = assistant_models.Message(
            id='msg-resp',
            conversation_id='conv-123',
            role='assistant',
            content='Hello world',
            created_at=now,
            sequence=1,
        )
        with mock.patch(
            'imbi_api.assistant.neo4j_ops.add_message',
            return_value=msg,
        ):
            chunks = []
            async for chunk in endpoints._stream_response(
                conversation_id='conv-123',
                auth=auth,
                api_messages=[
                    {'role': 'user', 'content': 'Hi'},
                ],
                system='System prompt',
                user_tools=[],
                model='claude-sonnet-4-20250514',
                max_tokens=4096,
                is_first_exchange=False,
                user_message_content='Hi',
            ):
                chunks.append(chunk)

        self.assertTrue(any('event: text' in c for c in chunks))
        self.assertTrue(any('event: done' in c for c in chunks))

    async def test_stream_with_first_exchange_title(self) -> None:
        """Test title generation on first exchange."""
        now = datetime.datetime.now(datetime.UTC)
        mock_api_client = mock.MagicMock()

        text_event = mock.MagicMock()
        text_event.type = 'content_block_delta'
        text_event.delta.type = 'text_delta'
        text_event.delta.text = 'Response text'

        done_event = mock.MagicMock()
        done_event.type = 'message_delta'
        done_event.delta.stop_reason = 'end_turn'
        done_event.usage = None

        stream_ctx = self._make_stream_ctx([text_event, done_event])
        mock_api_client.messages.stream.return_value = stream_ctx
        client._client = mock_api_client

        auth = _make_auth()
        msg = assistant_models.Message(
            id='msg-resp',
            conversation_id='conv-123',
            role='assistant',
            content='Response text',
            created_at=now,
            sequence=1,
        )
        with (
            mock.patch(
                'imbi_api.assistant.neo4j_ops.add_message',
                return_value=msg,
            ),
            mock.patch(
                'imbi_api.assistant.endpoints._generate_title',
                return_value='Generated Title',
            ) as mock_gen,
            mock.patch(
                'imbi_api.assistant.neo4j_ops.update_conversation_title',
            ) as mock_update,
        ):
            chunks = []
            async for chunk in endpoints._stream_response(
                conversation_id='conv-123',
                auth=auth,
                api_messages=[
                    {'role': 'user', 'content': 'Hello'},
                ],
                system='System prompt',
                user_tools=[],
                model='claude-sonnet-4-20250514',
                max_tokens=4096,
                is_first_exchange=True,
                user_message_content='Hello',
            ):
                chunks.append(chunk)

        mock_gen.assert_called_once()
        mock_update.assert_called_once()
        self.assertTrue(any('title_updated' in c for c in chunks))

    async def test_stream_api_error(self) -> None:
        """Test handling of Anthropic API error."""
        import anthropic

        mock_api_client = mock.MagicMock()
        mock_stream_ctx = mock.MagicMock()
        mock_stream_ctx.__aenter__ = mock.AsyncMock(
            side_effect=anthropic.APIError(
                message='Rate limited',
                request=mock.MagicMock(),
                body=None,
            ),
        )
        mock_stream_ctx.__aexit__ = mock.AsyncMock(
            return_value=None,
        )
        mock_api_client.messages.stream.return_value = mock_stream_ctx
        client._client = mock_api_client

        auth = _make_auth()
        chunks = []
        async for chunk in endpoints._stream_response(
            conversation_id='conv-123',
            auth=auth,
            api_messages=[
                {'role': 'user', 'content': 'Hello'},
            ],
            system='System prompt',
            user_tools=[],
            model='claude-sonnet-4-20250514',
            max_tokens=4096,
            is_first_exchange=False,
            user_message_content='Hello',
        ):
            chunks.append(chunk)

        self.assertEqual(len(chunks), 1)
        self.assertIn('event: error', chunks[0])

    async def test_stream_with_tools(self) -> None:
        """Test streaming with tools included in kwargs."""
        now = datetime.datetime.now(datetime.UTC)
        mock_api_client = mock.MagicMock()

        done_event = mock.MagicMock()
        done_event.type = 'message_delta'
        done_event.delta.stop_reason = 'end_turn'
        done_event.usage = None

        stream_ctx = self._make_stream_ctx([done_event])
        mock_api_client.messages.stream.return_value = stream_ctx
        client._client = mock_api_client

        auth = _make_auth()
        msg = assistant_models.Message(
            id='msg-resp',
            conversation_id='conv-123',
            role='assistant',
            content='',
            created_at=now,
            sequence=1,
        )
        with mock.patch(
            'imbi_api.assistant.neo4j_ops.add_message',
            return_value=msg,
        ):
            chunks = []
            user_tools = [{'name': 'list_projects'}]
            async for chunk in endpoints._stream_response(
                conversation_id='conv-123',
                auth=auth,
                api_messages=[
                    {'role': 'user', 'content': 'List projects'},
                ],
                system='System prompt',
                user_tools=user_tools,
                model='claude-sonnet-4-20250514',
                max_tokens=4096,
                is_first_exchange=False,
                user_message_content='List projects',
            ):
                chunks.append(chunk)

        # Verify tools were passed to the stream call
        call_kwargs = mock_api_client.messages.stream.call_args[1]
        self.assertIn('tools', call_kwargs)

    async def test_stream_tool_use_loop(self) -> None:
        """Test the tool use loop in _stream_response."""
        now = datetime.datetime.now(datetime.UTC)
        mock_api_client = mock.MagicMock()

        # First call events: tool use
        tool_start = mock.MagicMock()
        tool_start.type = 'content_block_start'
        tool_start.content_block.type = 'tool_use'
        tool_start.content_block.id = 'tool-1'
        tool_start.content_block.name = 'list_projects'

        tool_input = mock.MagicMock()
        tool_input.type = 'content_block_delta'
        tool_input.delta.type = 'input_json_delta'
        tool_input.delta.partial_json = '{}'

        tool_stop = mock.MagicMock()
        tool_stop.type = 'content_block_stop'

        tool_done = mock.MagicMock()
        tool_done.type = 'message_delta'
        tool_done.delta.stop_reason = 'tool_use'
        tool_done.usage = None

        stream_ctx1 = self._make_stream_ctx(
            [tool_start, tool_input, tool_stop, tool_done]
        )

        # Second call events: final text response
        text_event = mock.MagicMock()
        text_event.type = 'content_block_delta'
        text_event.delta.type = 'text_delta'
        text_event.delta.text = 'Here are the results'

        final_done = mock.MagicMock()
        final_done.type = 'message_delta'
        final_done.delta.stop_reason = 'end_turn'
        final_done.usage = None

        stream_ctx2 = self._make_stream_ctx([text_event, final_done])

        mock_api_client.messages.stream.side_effect = [
            stream_ctx1,
            stream_ctx2,
        ]
        client._client = mock_api_client

        auth = _make_auth(is_admin=True)
        msg = assistant_models.Message(
            id='msg-resp',
            conversation_id='conv-123',
            role='assistant',
            content='Here are the results',
            created_at=now,
            sequence=1,
        )
        with (
            mock.patch(
                'imbi_api.assistant.neo4j_ops.add_message',
                return_value=msg,
            ),
            mock.patch(
                'imbi_api.assistant.tools.execute_tool',
                return_value='Projects found',
            ),
        ):
            chunks = []
            async for chunk in endpoints._stream_response(
                conversation_id='conv-123',
                auth=auth,
                api_messages=[
                    {'role': 'user', 'content': 'List projects'},
                ],
                system='System prompt',
                user_tools=[{'name': 'list_projects'}],
                model='claude-sonnet-4-20250514',
                max_tokens=4096,
                is_first_exchange=False,
                user_message_content='List projects',
            ):
                chunks.append(chunk)

        self.assertTrue(any('tool_use_start' in c for c in chunks))
        self.assertTrue(any('event: done' in c for c in chunks))
        self.assertEqual(mock_api_client.messages.stream.call_count, 2)
