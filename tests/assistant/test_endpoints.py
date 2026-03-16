"""Tests for assistant endpoints module."""

import datetime
import unittest
from unittest import mock

import fastapi

from imbi_assistant import auth, client, endpoints, mcp, models, settings


def _make_user() -> auth.User:
    """Create a test User model."""
    return auth.User(
        email='test@example.com',
        display_name='Test User',
        is_admin=False,
    )


def _make_auth_context(
    is_admin: bool = False,
    perms: set[str] | None = None,
) -> auth.AuthContext:
    """Create a test AuthContext."""
    user = _make_user()
    user.is_admin = is_admin
    return auth.AuthContext(
        user=user,
        auth_method='jwt',
        permissions=perms or {'project:read'},
    )


def _make_conversation(
    conv_id: str = 'conv-123',
) -> models.Conversation:
    """Create a test Conversation model."""
    now = datetime.datetime.now(datetime.UTC)
    return models.Conversation(
        id=conv_id,
        user_email='test@example.com',
        title='Test Conversation',
        created_at=now,
        updated_at=now,
        model='claude-sonnet-4-20250514',
    )


class RequireAssistantTestCase(unittest.TestCase):
    """Test cases for _require_assistant."""

    def setUp(self) -> None:
        self._original = client._client

    def tearDown(self) -> None:
        client._client = self._original

    def test_raises_503_when_unavailable(self) -> None:
        client._client = None
        with self.assertRaises(fastapi.HTTPException) as ctx:
            endpoints._require_assistant()
        self.assertEqual(ctx.exception.status_code, 503)

    def test_no_error_when_available(self) -> None:
        client._client = mock.MagicMock()
        endpoints._require_assistant()


class SSEEventTestCase(unittest.TestCase):
    """Test cases for _sse_event."""

    def test_format_text_event(self) -> None:
        result = endpoints._sse_event('text', {'text': 'hello'})
        self.assertTrue(result.startswith('event: text\n'))
        self.assertIn('"text": "hello"', result)
        self.assertTrue(result.endswith('\n\n'))

    def test_format_done_event(self) -> None:
        result = endpoints._sse_event(
            'done', {'message_id': 'msg-1', 'usage': {}}
        )
        self.assertIn('event: done', result)
        self.assertIn('msg-1', result)


class GenerateTitleTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for _generate_title."""

    async def test_generate_title_success(self) -> None:
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

    async def test_generate_title_error_fallback(
        self,
    ) -> None:
        mock_client = mock.AsyncMock()
        mock_client.messages.create.side_effect = RuntimeError('API error')
        title = await endpoints._generate_title(
            mock_client, 'msg', 'resp', 'model'
        )
        self.assertEqual(title, 'New conversation')


class BuildApiMessageTestCase(unittest.TestCase):
    """Test cases for _build_api_message."""

    def test_plain_user_message(self) -> None:
        now = datetime.datetime.now(datetime.UTC)
        msg = models.Message(
            conversation_id='c1',
            role='user',
            content='Hello',
            created_at=now,
            sequence=0,
        )
        result = endpoints._build_api_message(msg)
        self.assertEqual(result['role'], 'user')
        self.assertEqual(result['content'], 'Hello')

    def test_assistant_with_tool_use(self) -> None:
        now = datetime.datetime.now(datetime.UTC)
        msg = models.Message(
            conversation_id='c1',
            role='assistant',
            content='Let me check.',
            tool_use=[
                {
                    'id': 't1',
                    'name': 'list_projects',
                    'input': {},
                }
            ],
            created_at=now,
            sequence=1,
        )
        result = endpoints._build_api_message(msg)
        self.assertEqual(result['role'], 'assistant')
        self.assertIsInstance(result['content'], list)
        self.assertEqual(len(result['content']), 2)
        self.assertEqual(result['content'][0]['type'], 'text')
        self.assertEqual(result['content'][1]['type'], 'tool_use')

    def test_user_with_tool_results(self) -> None:
        now = datetime.datetime.now(datetime.UTC)
        tool_results = [
            {
                'type': 'tool_result',
                'tool_use_id': 't1',
                'content': 'ok',
            }
        ]
        msg = models.Message(
            conversation_id='c1',
            role='user',
            content='',
            tool_results=tool_results,
            created_at=now,
            sequence=2,
        )
        result = endpoints._build_api_message(msg)
        self.assertEqual(result['role'], 'user')
        self.assertEqual(result['content'], tool_results)


class ProcessStreamEventsTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for _process_stream_events."""

    async def test_text_delta(self) -> None:
        event = mock.MagicMock()
        event.type = 'content_block_delta'
        event.delta.type = 'text_delta'
        event.delta.text = 'Hello'

        async def fake_stream():
            yield event

        state = {
            'text': '',
            'stop_reason': None,
            'usage': {},
        }
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

        state = {
            'text': '',
            'stop_reason': None,
            'usage': {},
        }
        tool_blocks: list[dict] = []
        chunks = []
        async for chunk in endpoints._process_stream_events(
            fake_stream(), tool_blocks, state
        ):
            chunks.append(chunk)
        self.assertEqual(len(tool_blocks), 1)
        self.assertEqual(tool_blocks[0]['name'], 'list_projects')
        self.assertEqual(tool_blocks[0]['input'], {'limit': 10})

    async def test_message_delta_with_stop_reason(
        self,
    ) -> None:
        event = mock.MagicMock()
        event.type = 'message_delta'
        event.delta.stop_reason = 'end_turn'
        event.usage = mock.MagicMock()
        event.usage.input_tokens = 100
        event.usage.output_tokens = 50

        async def fake_stream():
            yield event

        state = {
            'text': '',
            'stop_reason': None,
            'usage': {},
        }
        tool_blocks: list[dict] = []
        async for _ in endpoints._process_stream_events(
            fake_stream(), tool_blocks, state
        ):
            pass
        self.assertEqual(state['stop_reason'], 'end_turn')
        self.assertEqual(state['usage']['input_tokens'], 100)

    async def test_content_block_start_non_tool(
        self,
    ) -> None:
        event = mock.MagicMock()
        event.type = 'content_block_start'
        event.content_block.type = 'text'

        async def fake_stream():
            yield event

        state = {
            'text': '',
            'stop_reason': None,
            'usage': {},
        }
        tool_blocks: list[dict] = []
        chunks = []
        async for chunk in endpoints._process_stream_events(
            fake_stream(), tool_blocks, state
        ):
            chunks.append(chunk)
        self.assertEqual(len(tool_blocks), 0)

    async def test_content_block_stop_without_tool(
        self,
    ) -> None:
        event = mock.MagicMock()
        event.type = 'content_block_stop'

        async def fake_stream():
            yield event

        state = {
            'text': '',
            'stop_reason': None,
            'usage': {},
        }
        tool_blocks: list[dict] = []
        chunks = []
        async for chunk in endpoints._process_stream_events(
            fake_stream(), tool_blocks, state
        ):
            chunks.append(chunk)
        self.assertEqual(len(tool_blocks), 0)
        self.assertEqual(len(chunks), 1)

    async def test_tool_use_invalid_json(self) -> None:
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

        state = {
            'text': '',
            'stop_reason': None,
            'usage': {},
        }
        tool_blocks: list[dict] = []
        async for _ in endpoints._process_stream_events(
            fake_stream(), tool_blocks, state
        ):
            pass
        self.assertEqual(len(tool_blocks), 1)
        self.assertEqual(tool_blocks[0]['input'], {})

    async def test_message_delta_without_usage(
        self,
    ) -> None:
        event = mock.MagicMock()
        event.type = 'message_delta'
        event.delta.stop_reason = 'end_turn'
        event.usage = None

        async def fake_stream():
            yield event

        state = {
            'text': '',
            'stop_reason': None,
            'usage': {},
        }
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
    def setUp(self) -> None:
        self._original_client = client._client
        settings._assistant_settings = None

    def tearDown(self) -> None:
        client._client = self._original_client
        settings._assistant_settings = None

    @mock.patch(
        'imbi_assistant.neo4j_ops.create_conversation',
    )
    async def test_create_conversation(
        self,
        mock_create: mock.AsyncMock,
    ) -> None:
        client._client = mock.MagicMock()
        auth_ctx = _make_auth_context()
        conv = _make_conversation()
        mock_create.return_value = conv
        with mock.patch.dict('os.environ', {}, clear=True):
            result = await endpoints.create_conversation(
                auth_ctx=auth_ctx, body=None
            )
        self.assertEqual(result.id, 'conv-123')

    @mock.patch(
        'imbi_assistant.neo4j_ops.create_conversation',
    )
    async def test_create_conversation_custom_model(
        self,
        mock_create: mock.AsyncMock,
    ) -> None:
        client._client = mock.MagicMock()
        auth_ctx = _make_auth_context()
        conv = _make_conversation()
        mock_create.return_value = conv
        body = models.CreateConversationRequest(
            model='claude-opus-4-20250514',
        )
        with mock.patch.dict('os.environ', {}, clear=True):
            await endpoints.create_conversation(auth_ctx=auth_ctx, body=body)
        mock_create.assert_called_once_with(
            user_email='test@example.com',
            model='claude-opus-4-20250514',
        )


class ListConversationsEndpointTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    @mock.patch(
        'imbi_assistant.neo4j_ops.list_conversations',
    )
    async def test_list_conversations(
        self,
        mock_list: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_list.return_value = [_make_conversation()]
        result = await endpoints.list_conversations(auth_ctx=auth_ctx)
        self.assertEqual(len(result), 1)

    @mock.patch(
        'imbi_assistant.neo4j_ops.list_conversations',
    )
    async def test_list_conversations_limit_capped(
        self,
        mock_list: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_list.return_value = []
        await endpoints.list_conversations(auth_ctx=auth_ctx, limit=500)
        mock_list.assert_called_once_with(
            user_email='test@example.com',
            limit=100,
            offset=0,
            include_archived=False,
        )

    @mock.patch(
        'imbi_assistant.neo4j_ops.list_conversations',
    )
    async def test_list_conversations_negative_values(
        self,
        mock_list: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_list.return_value = []
        await endpoints.list_conversations(
            auth_ctx=auth_ctx, limit=-5, offset=-10
        )
        mock_list.assert_called_once_with(
            user_email='test@example.com',
            limit=1,
            offset=0,
            include_archived=False,
        )


class GetConversationEndpointTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    @mock.patch(
        'imbi_assistant.neo4j_ops.get_messages',
    )
    @mock.patch(
        'imbi_assistant.neo4j_ops.get_conversation',
    )
    async def test_get_conversation(
        self,
        mock_get: mock.AsyncMock,
        mock_msgs: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_get.return_value = _make_conversation()
        mock_msgs.return_value = []
        result = await endpoints.get_conversation(
            conversation_id='conv-123', auth_ctx=auth_ctx
        )
        self.assertEqual(result.id, 'conv-123')
        self.assertEqual(result.messages, [])

    @mock.patch(
        'imbi_assistant.neo4j_ops.get_conversation',
    )
    async def test_get_conversation_not_found(
        self,
        mock_get: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_get.return_value = None
        with self.assertRaises(fastapi.HTTPException) as ctx:
            await endpoints.get_conversation(
                conversation_id='missing',
                auth_ctx=auth_ctx,
            )
        self.assertEqual(ctx.exception.status_code, 404)


class DeleteConversationEndpointTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    @mock.patch(
        'imbi_assistant.neo4j_ops.delete_conversation',
    )
    async def test_delete_conversation(
        self,
        mock_delete: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_delete.return_value = True
        await endpoints.delete_conversation(
            conversation_id='conv-123', auth_ctx=auth_ctx
        )
        mock_delete.assert_called_once_with('conv-123', 'test@example.com')

    @mock.patch(
        'imbi_assistant.neo4j_ops.delete_conversation',
    )
    async def test_delete_conversation_not_found(
        self,
        mock_delete: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_delete.return_value = False
        with self.assertRaises(fastapi.HTTPException) as ctx:
            await endpoints.delete_conversation(
                conversation_id='missing',
                auth_ctx=auth_ctx,
            )
        self.assertEqual(ctx.exception.status_code, 404)


class UpdateConversationEndpointTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    @mock.patch(
        'imbi_assistant.neo4j_ops.get_conversation',
    )
    @mock.patch(
        'imbi_assistant.neo4j_ops.update_conversation_title',
    )
    async def test_update_title(
        self,
        mock_update: mock.AsyncMock,
        mock_get: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_update.return_value = True
        conv = _make_conversation()
        conv.title = 'Updated Title'
        mock_get.return_value = conv
        body = models.UpdateConversationRequest(title='Updated Title')
        result = await endpoints.update_conversation(
            conversation_id='conv-123',
            body=body,
            auth_ctx=auth_ctx,
        )
        self.assertEqual(result.title, 'Updated Title')
        mock_update.assert_called_once()

    @mock.patch(
        'imbi_assistant.neo4j_ops.get_conversation',
    )
    @mock.patch(
        'imbi_assistant.neo4j_ops.archive_conversation',
    )
    async def test_archive(
        self,
        mock_archive: mock.AsyncMock,
        mock_get: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_archive.return_value = True
        mock_get.return_value = _make_conversation()
        body = models.UpdateConversationRequest(
            is_archived=True,
        )
        await endpoints.update_conversation(
            conversation_id='conv-123',
            body=body,
            auth_ctx=auth_ctx,
        )
        mock_archive.assert_called_once()

    @mock.patch(
        'imbi_assistant.neo4j_ops.get_conversation',
    )
    @mock.patch(
        'imbi_assistant.neo4j_ops.update_conversation_title',
    )
    async def test_update_not_found(
        self,
        mock_update: mock.AsyncMock,
        mock_get: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_get.return_value = None
        mock_update.return_value = False
        body = models.UpdateConversationRequest(
            title='New Title',
        )
        with self.assertRaises(fastapi.HTTPException) as ctx:
            await endpoints.update_conversation(
                conversation_id='missing',
                body=body,
                auth_ctx=auth_ctx,
            )
        self.assertEqual(ctx.exception.status_code, 404)


def _make_mock_mcp_manager() -> mock.MagicMock:
    """Create a mock MCPManager."""
    manager = mock.MagicMock(spec=mcp.MCPManager)
    manager.get_tools.return_value = []
    manager.get_tool_names.return_value = []
    manager.execute_tool = mock.AsyncMock(return_value='{}')
    manager.is_initialized = False
    return manager


class SendMessageEndpointTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    def setUp(self) -> None:
        self._original_client = client._client
        self._original_manager = mcp._manager
        mcp._manager = _make_mock_mcp_manager()
        settings._assistant_settings = None

    def tearDown(self) -> None:
        client._client = self._original_client
        mcp._manager = self._original_manager
        settings._assistant_settings = None

    async def test_send_message_assistant_unavailable(
        self,
    ) -> None:
        client._client = None
        auth_ctx = _make_auth_context()
        body = models.SendMessageRequest(content='Hello')
        with self.assertRaises(fastapi.HTTPException) as ctx:
            await endpoints.send_message(
                conversation_id='conv-123',
                body=body,
                auth_ctx=auth_ctx,
            )
        self.assertEqual(ctx.exception.status_code, 503)

    @mock.patch(
        'imbi_assistant.neo4j_ops.get_conversation',
    )
    async def test_send_message_conversation_not_found(
        self,
        mock_get: mock.AsyncMock,
    ) -> None:
        client._client = mock.MagicMock()
        auth_ctx = _make_auth_context()
        mock_get.return_value = None
        body = models.SendMessageRequest(content='Hello')
        with self.assertRaises(fastapi.HTTPException) as ctx:
            await endpoints.send_message(
                conversation_id='missing',
                body=body,
                auth_ctx=auth_ctx,
            )
        self.assertEqual(ctx.exception.status_code, 404)

    @mock.patch.dict('os.environ', {}, clear=True)
    @mock.patch(
        'imbi_assistant.neo4j_ops.count_messages',
    )
    @mock.patch(
        'imbi_assistant.neo4j_ops.get_conversation',
    )
    async def test_send_message_turn_limit_reached(
        self,
        mock_get: mock.AsyncMock,
        mock_count: mock.AsyncMock,
    ) -> None:
        client._client = mock.MagicMock()
        auth_ctx = _make_auth_context()
        mock_get.return_value = _make_conversation()
        mock_count.return_value = 100
        body = models.SendMessageRequest(content='Hello')
        with self.assertRaises(fastapi.HTTPException) as ctx:
            await endpoints.send_message(
                conversation_id='conv-123',
                body=body,
                auth_ctx=auth_ctx,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn('maximum', str(ctx.exception.detail))

    @mock.patch.dict('os.environ', {}, clear=True)
    @mock.patch(
        'imbi_assistant.neo4j_ops.get_messages',
    )
    @mock.patch(
        'imbi_assistant.neo4j_ops.add_message',
    )
    @mock.patch(
        'imbi_assistant.neo4j_ops.count_messages',
    )
    @mock.patch(
        'imbi_assistant.neo4j_ops.get_conversation',
    )
    async def test_send_message_returns_streaming_response(
        self,
        mock_get_conv: mock.AsyncMock,
        mock_count: mock.AsyncMock,
        mock_add: mock.AsyncMock,
        mock_get_msgs: mock.AsyncMock,
    ) -> None:
        client._client = mock.MagicMock()
        auth_ctx = _make_auth_context()
        mock_get_conv.return_value = _make_conversation()
        mock_count.return_value = 0
        now = datetime.datetime.now(datetime.UTC)
        mock_add.return_value = models.Message(
            id='msg-1',
            conversation_id='conv-123',
            role='user',
            content='Hello',
            created_at=now,
            sequence=0,
        )
        mock_get_msgs.return_value = [
            models.Message(
                id='msg-1',
                conversation_id='conv-123',
                role='user',
                content='Hello',
                created_at=now,
                sequence=0,
            ),
        ]
        body = models.SendMessageRequest(content='Hello')
        from fastapi import responses

        result = await endpoints.send_message(
            conversation_id='conv-123',
            body=body,
            auth_ctx=auth_ctx,
            credentials=None,
        )
        self.assertIsInstance(result, responses.StreamingResponse)
        self.assertEqual(result.media_type, 'text/event-stream')


class StreamResponseTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    def setUp(self) -> None:
        self._original_client = client._client
        self._original_manager = mcp._manager
        mcp._manager = _make_mock_mcp_manager()
        settings._assistant_settings = None

    def tearDown(self) -> None:
        client._client = self._original_client
        mcp._manager = self._original_manager
        settings._assistant_settings = None

    @staticmethod
    def _make_stream_ctx(events: list) -> mock.MagicMock:
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

        auth_ctx = _make_auth_context()
        msg = models.Message(
            id='msg-resp',
            conversation_id='conv-123',
            role='assistant',
            content='Hello world',
            created_at=now,
            sequence=1,
        )
        with mock.patch(
            'imbi_assistant.neo4j_ops.add_message',
            return_value=msg,
        ):
            chunks = []
            async for chunk in endpoints._stream_response(
                conversation_id='conv-123',
                auth_ctx=auth_ctx,
                api_messages=[
                    {'role': 'user', 'content': 'Hi'},
                ],
                system='System prompt',
                model='claude-sonnet-4-20250514',
                max_tokens=4096,
                is_first_exchange=False,
                user_message_content='Hi',
            ):
                chunks.append(chunk)

        self.assertTrue(any('event: text' in c for c in chunks))
        self.assertTrue(any('event: done' in c for c in chunks))

    async def test_stream_with_first_exchange_title(
        self,
    ) -> None:
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

        auth_ctx = _make_auth_context()
        msg = models.Message(
            id='msg-resp',
            conversation_id='conv-123',
            role='assistant',
            content='Response text',
            created_at=now,
            sequence=1,
        )
        with (
            mock.patch(
                'imbi_assistant.neo4j_ops.add_message',
                return_value=msg,
            ),
            mock.patch(
                'imbi_assistant.endpoints._generate_title',
                return_value='Generated Title',
            ) as mock_gen,
            mock.patch(
                'imbi_assistant.neo4j_ops.update_conversation_title',
            ) as mock_update,
        ):
            chunks = []
            async for chunk in endpoints._stream_response(
                conversation_id='conv-123',
                auth_ctx=auth_ctx,
                api_messages=[
                    {'role': 'user', 'content': 'Hello'},
                ],
                system='System prompt',
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

        auth_ctx = _make_auth_context()
        chunks = []
        async for chunk in endpoints._stream_response(
            conversation_id='conv-123',
            auth_ctx=auth_ctx,
            api_messages=[
                {'role': 'user', 'content': 'Hello'},
            ],
            system='System prompt',
            model='claude-sonnet-4-20250514',
            max_tokens=4096,
            is_first_exchange=False,
            user_message_content='Hello',
        ):
            chunks.append(chunk)

        self.assertEqual(len(chunks), 1)
        self.assertIn('event: error', chunks[0])
