"""Tests for assistant endpoints module."""

import asyncio
import datetime
import json
import typing
import unittest
from unittest import mock

import fastapi

from imbi_assistant import (
    auth,
    client,
    client_tools,
    endpoints,
    external_mcp,
    mcp,
    models,
    settings,
)


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
        with self.assertRaises(
            fastapi.HTTPException,
        ) as ctx:
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

    async def test_generate_title_truncates(
        self,
    ) -> None:
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
        'imbi_assistant.age_ops.create_conversation',
    )
    async def test_create_conversation(
        self,
        mock_create: mock.AsyncMock,
    ) -> None:
        client._client = mock.MagicMock()
        auth_ctx = _make_auth_context()
        conv = _make_conversation()
        mock_create.return_value = conv
        db = mock.AsyncMock()
        with mock.patch.dict('os.environ', {}, clear=True):
            result = await endpoints.create_conversation(
                db=db, auth_ctx=auth_ctx, body=None
            )
        self.assertEqual(result.id, 'conv-123')

    @mock.patch(
        'imbi_assistant.age_ops.create_conversation',
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
        db = mock.AsyncMock()
        with mock.patch.dict('os.environ', {}, clear=True):
            await endpoints.create_conversation(
                db=db, auth_ctx=auth_ctx, body=body
            )
        mock_create.assert_called_once_with(
            mock.ANY,
            user_email='test@example.com',
            model='claude-opus-4-20250514',
        )


class ListConversationsEndpointTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    @mock.patch(
        'imbi_assistant.age_ops.list_conversations',
    )
    async def test_list_conversations(
        self,
        mock_list: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_list.return_value = [_make_conversation()]
        db = mock.AsyncMock()
        result = await endpoints.list_conversations(db=db, auth_ctx=auth_ctx)
        self.assertEqual(len(result), 1)

    @mock.patch(
        'imbi_assistant.age_ops.list_conversations',
    )
    async def test_list_conversations_limit_capped(
        self,
        mock_list: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_list.return_value = []
        db = mock.AsyncMock()
        await endpoints.list_conversations(db=db, auth_ctx=auth_ctx, limit=500)
        mock_list.assert_called_once_with(
            mock.ANY,
            user_email='test@example.com',
            limit=100,
            offset=0,
            include_archived=False,
        )

    @mock.patch(
        'imbi_assistant.age_ops.list_conversations',
    )
    async def test_list_conversations_negative_values(
        self,
        mock_list: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_list.return_value = []
        db = mock.AsyncMock()
        await endpoints.list_conversations(
            db=db,
            auth_ctx=auth_ctx,
            limit=-5,
            offset=-10,
        )
        mock_list.assert_called_once_with(
            mock.ANY,
            user_email='test@example.com',
            limit=1,
            offset=0,
            include_archived=False,
        )


class GetConversationEndpointTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    @mock.patch(
        'imbi_assistant.age_ops.get_messages',
    )
    @mock.patch(
        'imbi_assistant.age_ops.get_conversation',
    )
    async def test_get_conversation(
        self,
        mock_get: mock.AsyncMock,
        mock_msgs: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_get.return_value = _make_conversation()
        mock_msgs.return_value = []
        db = mock.AsyncMock()
        result = await endpoints.get_conversation(
            conversation_id='conv-123',
            db=db,
            auth_ctx=auth_ctx,
        )
        self.assertEqual(result.id, 'conv-123')
        self.assertEqual(result.messages, [])

    @mock.patch(
        'imbi_assistant.age_ops.get_conversation',
    )
    async def test_get_conversation_not_found(
        self,
        mock_get: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_get.return_value = None
        db = mock.AsyncMock()
        with self.assertRaises(
            fastapi.HTTPException,
        ) as ctx:
            await endpoints.get_conversation(
                conversation_id='missing',
                db=db,
                auth_ctx=auth_ctx,
            )
        self.assertEqual(ctx.exception.status_code, 404)


class DeleteConversationEndpointTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    @mock.patch(
        'imbi_assistant.age_ops.delete_conversation',
    )
    async def test_delete_conversation(
        self,
        mock_delete: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_delete.return_value = True
        db = mock.AsyncMock()
        await endpoints.delete_conversation(
            conversation_id='conv-123',
            db=db,
            auth_ctx=auth_ctx,
        )
        mock_delete.assert_called_once_with(
            mock.ANY, 'conv-123', 'test@example.com'
        )

    @mock.patch(
        'imbi_assistant.age_ops.delete_conversation',
    )
    async def test_delete_conversation_not_found(
        self,
        mock_delete: mock.AsyncMock,
    ) -> None:
        auth_ctx = _make_auth_context()
        mock_delete.return_value = False
        db = mock.AsyncMock()
        with self.assertRaises(
            fastapi.HTTPException,
        ) as ctx:
            await endpoints.delete_conversation(
                conversation_id='missing',
                db=db,
                auth_ctx=auth_ctx,
            )
        self.assertEqual(ctx.exception.status_code, 404)


class UpdateConversationEndpointTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    @mock.patch(
        'imbi_assistant.age_ops.get_conversation',
    )
    @mock.patch(
        'imbi_assistant.age_ops.update_conversation_title',
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
        db = mock.AsyncMock()
        result = await endpoints.update_conversation(
            conversation_id='conv-123',
            body=body,
            db=db,
            auth_ctx=auth_ctx,
        )
        self.assertEqual(result.title, 'Updated Title')
        mock_update.assert_called_once()

    @mock.patch(
        'imbi_assistant.age_ops.get_conversation',
    )
    @mock.patch(
        'imbi_assistant.age_ops.archive_conversation',
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
        db = mock.AsyncMock()
        await endpoints.update_conversation(
            conversation_id='conv-123',
            body=body,
            db=db,
            auth_ctx=auth_ctx,
        )
        mock_archive.assert_called_once()

    @mock.patch(
        'imbi_assistant.age_ops.get_conversation',
    )
    @mock.patch(
        'imbi_assistant.age_ops.update_conversation_title',
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
        db = mock.AsyncMock()
        with self.assertRaises(
            fastapi.HTTPException,
        ) as ctx:
            await endpoints.update_conversation(
                conversation_id='missing',
                body=body,
                db=db,
                auth_ctx=auth_ctx,
            )
        self.assertEqual(ctx.exception.status_code, 404)


def _make_mock_mcp_manager() -> mock.MagicMock:
    """Create a mock MCPManager."""
    manager = mock.MagicMock(spec=mcp.MCPManager)
    manager.get_tools.return_value = []
    manager.get_tool_names.return_value = []
    manager.execute_tool = mock.AsyncMock(return_value=('{}', False))
    manager.is_initialized = False
    return manager


def _make_mock_external_manager() -> mock.MagicMock:
    """Create a mock ExternalMCPManager."""
    manager = mock.MagicMock(spec=external_mcp.ExternalMCPManager)
    manager.get_tools.return_value = []
    manager.get_tool_names.return_value = []
    manager.has_tool.return_value = False
    manager.execute_tool = mock.AsyncMock(return_value=('{}', False))
    manager.is_initialized = False
    return manager


class SendMessageEndpointTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    def setUp(self) -> None:
        self._original_client = client._client
        self._original_manager = mcp._manager
        self._original_ext = external_mcp._manager
        mcp._manager = _make_mock_mcp_manager()
        external_mcp._manager = _make_mock_external_manager()
        settings._assistant_settings = None

    def tearDown(self) -> None:
        client._client = self._original_client
        mcp._manager = self._original_manager
        external_mcp._manager = self._original_ext
        settings._assistant_settings = None

    async def test_send_message_assistant_unavailable(
        self,
    ) -> None:
        client._client = None
        auth_ctx = _make_auth_context()
        body = models.SendMessageRequest(content='Hello')
        db = mock.AsyncMock()
        with self.assertRaises(
            fastapi.HTTPException,
        ) as ctx:
            await endpoints.send_message(
                conversation_id='conv-123',
                body=body,
                db=db,
                auth_ctx=auth_ctx,
            )
        self.assertEqual(ctx.exception.status_code, 503)

    @mock.patch(
        'imbi_assistant.age_ops.get_conversation',
    )
    async def test_send_message_conversation_not_found(
        self,
        mock_get: mock.AsyncMock,
    ) -> None:
        client._client = mock.MagicMock()
        auth_ctx = _make_auth_context()
        mock_get.return_value = None
        body = models.SendMessageRequest(content='Hello')
        db = mock.AsyncMock()
        with self.assertRaises(
            fastapi.HTTPException,
        ) as ctx:
            await endpoints.send_message(
                conversation_id='missing',
                body=body,
                db=db,
                auth_ctx=auth_ctx,
            )
        self.assertEqual(ctx.exception.status_code, 404)

    @mock.patch.dict('os.environ', {}, clear=True)
    @mock.patch(
        'imbi_assistant.age_ops.count_messages',
    )
    @mock.patch(
        'imbi_assistant.age_ops.get_conversation',
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
        db = mock.AsyncMock()
        with self.assertRaises(
            fastapi.HTTPException,
        ) as ctx:
            await endpoints.send_message(
                conversation_id='conv-123',
                body=body,
                db=db,
                auth_ctx=auth_ctx,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn('maximum', str(ctx.exception.detail))

    @mock.patch.dict('os.environ', {}, clear=True)
    @mock.patch(
        'imbi_assistant.age_ops.get_messages',
    )
    @mock.patch(
        'imbi_assistant.age_ops.add_message',
    )
    @mock.patch(
        'imbi_assistant.age_ops.count_messages',
    )
    @mock.patch(
        'imbi_assistant.age_ops.get_conversation',
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

        db = mock.AsyncMock()
        result = await endpoints.send_message(
            conversation_id='conv-123',
            body=body,
            db=db,
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
        self._original_ext = external_mcp._manager
        mcp._manager = _make_mock_mcp_manager()
        external_mcp._manager = _make_mock_external_manager()
        settings._assistant_settings = None

    def tearDown(self) -> None:
        client._client = self._original_client
        mcp._manager = self._original_manager
        external_mcp._manager = self._original_ext
        settings._assistant_settings = None

    @staticmethod
    def _make_stream_ctx(
        events: list,
    ) -> mock.MagicMock:
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
        db = mock.AsyncMock()
        with mock.patch(
            'imbi_assistant.age_ops.add_message',
            return_value=msg,
        ):
            chunks = []
            async for chunk in endpoints._stream_response(
                db=db,
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
        db = mock.AsyncMock()
        with (
            mock.patch(
                'imbi_assistant.age_ops.add_message',
                return_value=msg,
            ),
            mock.patch(
                'imbi_assistant.endpoints._generate_title',
                return_value='Generated Title',
            ) as mock_gen,
            mock.patch(
                'imbi_assistant.age_ops.update_conversation_title',
            ) as mock_update,
        ):
            chunks = []
            async for chunk in endpoints._stream_response(
                db=db,
                conversation_id='conv-123',
                auth_ctx=auth_ctx,
                api_messages=[
                    {
                        'role': 'user',
                        'content': 'Hello',
                    },
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

    async def test_persist_tool_round_writes_pair_in_order(self) -> None:
        """``_persist_tool_round`` writes the assistant tool_use
        message and its matching tool_result user message in order,
        without any awaitable between them that could be cancelled.
        """
        db = mock.AsyncMock()
        calls: list[dict[str, typing.Any]] = []

        async def fake_add_message(
            _db: typing.Any, **kwargs: typing.Any
        ) -> None:
            calls.append(kwargs)

        with mock.patch(
            'imbi_assistant.age_ops.add_message',
            side_effect=fake_add_message,
        ):
            await endpoints._persist_tool_round(
                db,
                'conv-abc',
                {'text': 'thinking...', 'usage': None},
                [{'id': 't1', 'name': 'list', 'input': {}}],
                [
                    {
                        'type': 'tool_result',
                        'tool_use_id': 't1',
                        'content': '{}',
                    }
                ],
            )
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['role'], 'assistant')
        self.assertEqual(
            calls[0]['tool_use'], [{'id': 't1', 'name': 'list', 'input': {}}]
        )
        self.assertEqual(calls[1]['role'], 'user')
        self.assertEqual(
            calls[1]['tool_results'],
            [{'type': 'tool_result', 'tool_use_id': 't1', 'content': '{}'}],
        )

    async def test_persist_tool_round_completes_after_cancellation(
        self,
    ) -> None:
        """Cancellation of the awaiter must not tear the two writes
        apart — the inner persist coroutine completes both writes
        after its awaiter is cancelled, matching the production
        ``asyncio.shield`` contract in ``_stream_response``.
        """
        db = mock.AsyncMock()
        first_started = asyncio.Event()
        completed: list[str] = []

        async def fake_add_message(
            _db: typing.Any, **kwargs: typing.Any
        ) -> None:
            role = kwargs['role']
            if role == 'assistant':
                first_started.set()
                # Yield to the event loop so the canceller fires
                # between the two writes.
                await asyncio.sleep(0)
            completed.append(role)

        with mock.patch(
            'imbi_assistant.age_ops.add_message',
            side_effect=fake_add_message,
        ):
            inner = asyncio.create_task(
                endpoints._persist_tool_round(
                    db,
                    'conv-xyz',
                    {'text': '', 'usage': None},
                    [{'id': 't1', 'name': 'list', 'input': {}}],
                    [
                        {
                            'type': 'tool_result',
                            'tool_use_id': 't1',
                            'content': '{}',
                        }
                    ],
                )
            )

            async def awaiter() -> None:
                await asyncio.shield(inner)

            waiter = asyncio.create_task(awaiter())
            await first_started.wait()
            # Simulate the SSE client disconnecting — the awaiter is
            # cancelled but ``asyncio.shield`` keeps ``inner`` alive.
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            await inner

        # Both writes ran to completion despite the cancellation.
        self.assertEqual(completed, ['assistant', 'user'])

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
        db = mock.AsyncMock()
        chunks = []
        async for chunk in endpoints._stream_response(
            db=db,
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


class BuildToolsAndSystemTestCase(unittest.IsolatedAsyncioTestCase):
    """_build_tools_and_system aggregates external MCP tools."""

    def setUp(self) -> None:
        self._original_manager = mcp._manager
        self._original_ext = external_mcp._manager
        settings._assistant_settings = None

    def tearDown(self) -> None:
        mcp._manager = self._original_manager
        external_mcp._manager = self._original_ext
        settings._assistant_settings = None

    def test_external_tools_included(self) -> None:
        mcp_manager = _make_mock_mcp_manager()
        ext_manager = _make_mock_external_manager()
        ext_manager.get_tools.return_value = [
            {
                'name': 'mcp_svc_thing',
                'description': 'd',
                'input_schema': {},
            }
        ]
        ext_manager.get_tool_names.return_value = ['mcp_svc_thing']
        mcp._manager = mcp_manager
        external_mcp._manager = ext_manager
        with mock.patch.dict('os.environ', {}, clear=True):
            tools, system = endpoints._build_tools_and_system(
                mcp_manager, _make_auth_context()
            )
        assert tools is not None
        names = [t['name'] for t in tools]
        self.assertIn('mcp_svc_thing', names)
        self.assertIn('mcp_svc_thing', system)


class DispatchToolUsesTestCase(unittest.IsolatedAsyncioTestCase):
    """_dispatch_tool_uses routes to the external manager."""

    def setUp(self) -> None:
        self._original_ext = external_mcp._manager
        external_mcp._manager = _make_mock_external_manager()
        settings._assistant_settings = None

    def tearDown(self) -> None:
        external_mcp._manager = self._original_ext
        settings._assistant_settings = None

    async def test_external_tool_routed(self) -> None:
        mcp_manager = _make_mock_mcp_manager()
        ext_manager = _make_mock_external_manager()
        ext_manager.has_tool.return_value = True
        ext_manager.execute_tool = mock.AsyncMock(
            return_value=('{"result": 1}', False),
        )
        tool_results: list = []
        tb = {'id': 't1', 'name': 'mcp_svc_thing', 'input': {'a': 1}}
        chunks = []
        async for chunk in endpoints._dispatch_tool_uses(
            [tb],
            tool_results,
            mcp_manager,
            ext_manager,
            _make_auth_context(),
            auth_token=None,
            rebuild={},
            db=mock.MagicMock(),
        ):
            chunks.append(chunk)
        ext_manager.execute_tool.assert_awaited_once_with(
            'mcp_svc_thing', {'a': 1}
        )
        # OpenAPI manager not consulted for an external tool.
        mcp_manager.execute_tool.assert_not_called()
        self.assertEqual(len(tool_results), 1)
        self.assertEqual(tool_results[0]['content'], '{"result": 1}')
        self.assertTrue(any('event: tool_result' in c for c in chunks))

    async def test_openapi_fallback(self) -> None:
        mcp_manager = _make_mock_mcp_manager()
        mcp_manager.execute_tool = mock.AsyncMock(return_value=('{}', False))
        ext_manager = _make_mock_external_manager()
        ext_manager.has_tool.return_value = False
        tool_results: list = []
        tb = {'id': 't1', 'name': 'api_tool', 'input': {}}
        async for _ in endpoints._dispatch_tool_uses(
            [tb],
            tool_results,
            mcp_manager,
            ext_manager,
            _make_auth_context(),
            auth_token='tok',
            rebuild={},
            db=mock.MagicMock(),
        ):
            pass
        mcp_manager.execute_tool.assert_awaited_once_with(
            'api_tool', {}, 'tok'
        )

    @mock.patch(
        'imbi_assistant.endpoints.external_mcp.reinitialize',
        new_callable=mock.AsyncMock,
        return_value=(True, 2),
    )
    async def test_server_refresh_tool_rebuilds(
        self, mock_ext_reinit: mock.AsyncMock
    ) -> None:
        mcp_manager = _make_mock_mcp_manager()
        mcp_manager.reinitialize = mock.AsyncMock(return_value=(True, 3))
        ext_manager = _make_mock_external_manager()
        tool_results: list = []
        rebuild: dict = {}
        tb = {'id': 't1', 'name': mcp.REFRESH_TOOL_NAME, 'input': {}}
        with mock.patch.dict('os.environ', {}, clear=True):
            async for _ in endpoints._dispatch_tool_uses(
                [tb],
                tool_results,
                mcp_manager,
                ext_manager,
                _make_auth_context(),
                auth_token=None,
                rebuild=rebuild,
                db=mock.MagicMock(),
            ):
                pass
        mcp_manager.reinitialize.assert_awaited_once()
        mock_ext_reinit.assert_awaited_once()
        self.assertIn('tools', rebuild)
        self.assertIn('system', rebuild)
        payload = json.loads(tool_results[0]['content'])
        self.assertTrue(payload['success'])
        # Combined total + nested per-source breakdown.
        self.assertEqual(payload['tool_count'], 5)
        self.assertEqual(
            payload['openapi'], {'success': True, 'tool_count': 3}
        )
        self.assertEqual(
            payload['external_mcp'], {'success': True, 'tool_count': 2}
        )

    @mock.patch(
        'imbi_assistant.endpoints.external_mcp.reinitialize',
        new_callable=mock.AsyncMock,
        return_value=(False, 0),
    )
    async def test_server_refresh_tool_no_rebuild_on_failure(
        self, _mock_ext_reinit: mock.AsyncMock
    ) -> None:
        mcp_manager = _make_mock_mcp_manager()
        mcp_manager.reinitialize = mock.AsyncMock(return_value=(False, 0))
        ext_manager = _make_mock_external_manager()
        tool_results: list = []
        rebuild: dict = {}
        tb = {'id': 't1', 'name': mcp.REFRESH_TOOL_NAME, 'input': {}}
        async for _ in endpoints._dispatch_tool_uses(
            [tb],
            tool_results,
            mcp_manager,
            ext_manager,
            _make_auth_context(),
            auth_token=None,
            rebuild=rebuild,
            db=mock.MagicMock(),
        ):
            pass
        self.assertNotIn('tools', rebuild)
        # Whole-call success is the AND of both sources.
        payload = json.loads(tool_results[0]['content'])
        self.assertFalse(payload['success'])
        self.assertTrue(tool_results[0]['is_error'])

    @mock.patch(
        'imbi_assistant.endpoints.external_mcp.reinitialize',
        new_callable=mock.AsyncMock,
        return_value=(True, 1),
    )
    async def test_server_refresh_tool_handles_exception(
        self, _mock_ext_reinit: mock.AsyncMock
    ) -> None:
        mcp_manager = _make_mock_mcp_manager()
        mcp_manager.reinitialize = mock.AsyncMock(
            side_effect=RuntimeError('boom')
        )
        ext_manager = _make_mock_external_manager()
        tool_results: list = []
        rebuild: dict = {}
        tb = {'id': 't1', 'name': mcp.REFRESH_TOOL_NAME, 'input': {}}
        chunks = []
        async for chunk in endpoints._dispatch_tool_uses(
            [tb],
            tool_results,
            mcp_manager,
            ext_manager,
            _make_auth_context(),
            auth_token=None,
            rebuild=rebuild,
            db=mock.MagicMock(),
        ):
            chunks.append(chunk)
        # The stream continues with a tool_result rather than aborting.
        # External MCP refresh still succeeded, so a rebuild still
        # happens; the OpenAPI half is reported as a failure with the
        # exception string preserved.
        self.assertIn('tools', rebuild)
        self.assertEqual(len(tool_results), 1)
        payload = json.loads(tool_results[0]['content'])
        self.assertFalse(payload['success'])
        self.assertEqual(payload['openapi']['error'], 'boom')
        self.assertTrue(payload['external_mcp']['success'])
        self.assertTrue(tool_results[0]['is_error'])
        self.assertTrue(any('event: tool_result' in c for c in chunks))

    @mock.patch(
        'imbi_assistant.endpoints.external_mcp.reinitialize',
        new_callable=mock.AsyncMock,
        side_effect=RuntimeError('graph down'),
    )
    async def test_server_refresh_external_failure_isolated(
        self, _mock_ext_reinit: mock.AsyncMock
    ) -> None:
        """An external-MCP reinit failure must not abort the OpenAPI
        refresh — the LLM should still see the OpenAPI half as healthy
        and the external half as errored with the cause string.
        """
        mcp_manager = _make_mock_mcp_manager()
        mcp_manager.reinitialize = mock.AsyncMock(return_value=(True, 4))
        ext_manager = _make_mock_external_manager()
        tool_results: list = []
        rebuild: dict = {}
        tb = {'id': 't1', 'name': mcp.REFRESH_TOOL_NAME, 'input': {}}
        async for _ in endpoints._dispatch_tool_uses(
            [tb],
            tool_results,
            mcp_manager,
            ext_manager,
            _make_auth_context(),
            auth_token=None,
            rebuild=rebuild,
            db=mock.MagicMock(),
        ):
            pass
        self.assertIn('tools', rebuild)
        payload = json.loads(tool_results[0]['content'])
        self.assertFalse(payload['success'])
        self.assertTrue(payload['openapi']['success'])
        self.assertEqual(payload['external_mcp']['error'], 'graph down')

    async def test_openapi_tool_failure_sets_is_error(self) -> None:
        """When the OpenAPI tool reports a failure, the tool_result
        block must carry ``is_error: true`` and surface the detail —
        otherwise Claude consumes the error JSON as a successful result
        and loops on the same bad input.
        """
        mcp_manager = _make_mock_mcp_manager()
        detail = (
            "Error calling tool 'patch_project': HTTP error 400: "
            "Bad Request - ci_deploy_status: 'Pass' not allowed"
        )
        payload = json.dumps(
            {'error': 'Tool execution failed: patch_project', 'detail': detail}
        )
        mcp_manager.execute_tool = mock.AsyncMock(return_value=(payload, True))
        ext_manager = _make_mock_external_manager()
        ext_manager.has_tool.return_value = False
        tool_results: list = []
        tb = {'id': 't1', 'name': 'patch_project', 'input': {}}
        async for _ in endpoints._dispatch_tool_uses(
            [tb],
            tool_results,
            mcp_manager,
            ext_manager,
            _make_auth_context(),
            auth_token=None,
            rebuild={},
            db=mock.MagicMock(),
        ):
            pass
        self.assertEqual(len(tool_results), 1)
        self.assertIs(tool_results[0]['is_error'], True)
        self.assertIn('ci_deploy_status', tool_results[0]['content'])

    async def test_external_tool_failure_sets_is_error(self) -> None:
        """Same flag-propagation guarantee for external MCP tools."""
        mcp_manager = _make_mock_mcp_manager()
        ext_manager = _make_mock_external_manager()
        ext_manager.has_tool.return_value = True
        ext_manager.execute_tool = mock.AsyncMock(
            return_value=('{"error":"down","detail":"boom"}', True)
        )
        tool_results: list = []
        tb = {'id': 't1', 'name': 'mcp_svc_x', 'input': {}}
        async for _ in endpoints._dispatch_tool_uses(
            [tb],
            tool_results,
            mcp_manager,
            ext_manager,
            _make_auth_context(),
            auth_token=None,
            rebuild={},
            db=mock.MagicMock(),
        ):
            pass
        self.assertEqual(len(tool_results), 1)
        self.assertIs(tool_results[0]['is_error'], True)
        self.assertIn('boom', tool_results[0]['content'])

    async def test_openapi_tool_success_omits_is_error(self) -> None:
        """Successful tool calls must not set ``is_error``."""
        mcp_manager = _make_mock_mcp_manager()
        ext_manager = _make_mock_external_manager()
        ext_manager.has_tool.return_value = False
        tool_results: list = []
        tb = {'id': 't1', 'name': 'list_projects', 'input': {}}
        async for _ in endpoints._dispatch_tool_uses(
            [tb],
            tool_results,
            mcp_manager,
            ext_manager,
            _make_auth_context(),
            auth_token=None,
            rebuild={},
            db=mock.MagicMock(),
        ):
            pass
        self.assertEqual(len(tool_results), 1)
        self.assertNotIn('is_error', tool_results[0])

    async def test_client_tool_routed(self) -> None:
        mcp_manager = _make_mock_mcp_manager()
        ext_manager = _make_mock_external_manager()
        tool_results: list = []
        tb = {
            'id': 't1',
            'name': client_tools.get_tool_names()[0],
            'input': {'x': 1},
        }
        chunks = []
        async for chunk in endpoints._dispatch_tool_uses(
            [tb],
            tool_results,
            mcp_manager,
            ext_manager,
            _make_auth_context(),
            auth_token=None,
            rebuild={},
            db=mock.MagicMock(),
        ):
            chunks.append(chunk)
        self.assertTrue(any('event: client_action' in c for c in chunks))
        self.assertEqual(len(tool_results), 1)


class ToolResultTruncationTestCase(unittest.TestCase):
    """A single oversized tool result must not overflow the context
    window: it is truncated with a recovery notice before it enters the
    conversation (and, crucially, before it is persisted).
    """

    def setUp(self) -> None:
        settings._assistant_settings = None

    def tearDown(self) -> None:
        settings._assistant_settings = None

    def _set_limit(self, limit: int) -> None:
        settings._assistant_settings = settings.Assistant(
            _env_file=None,
            max_tool_result_chars=limit,
        )

    def test_result_under_limit_unchanged(self) -> None:
        self._set_limit(100)
        block = endpoints._tool_result_block('t1', 'small', False)
        self.assertEqual(block['content'], 'small')

    def test_result_over_limit_truncated(self) -> None:
        self._set_limit(50)
        content = 'x' * 500
        block = endpoints._tool_result_block('t1', content, False)
        self.assertTrue(block['content'].startswith('x' * 50))
        self.assertIn('truncated', block['content'])
        self.assertIn('slim=true', block['content'])
        # The kept prefix plus a short notice, not the full payload.
        self.assertLess(len(block['content']), len(content))

    def test_error_flag_preserved_when_truncated(self) -> None:
        self._set_limit(50)
        block = endpoints._tool_result_block('t1', 'y' * 500, True)
        self.assertIs(block['is_error'], True)

    def test_limit_disabled_when_non_positive(self) -> None:
        self._set_limit(0)
        content = 'x' * 10_000
        block = endpoints._tool_result_block('t1', content, False)
        self.assertEqual(block['content'], content)
