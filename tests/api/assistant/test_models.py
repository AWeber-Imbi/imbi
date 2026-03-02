"""Tests for assistant models module."""

import datetime
import unittest

import pydantic

from imbi_api.assistant import models


class ConversationModelTestCase(unittest.TestCase):
    """Test cases for Conversation model."""

    def test_create_conversation(self) -> None:
        """Test creating a Conversation model."""
        now = datetime.datetime.now(datetime.UTC)
        conv = models.Conversation(
            user_email='test@example.com',
            created_at=now,
            updated_at=now,
            model='claude-sonnet-4-20250514',
        )
        self.assertEqual(conv.user_email, 'test@example.com')
        self.assertIsNotNone(conv.id)
        self.assertIsNone(conv.title)
        self.assertFalse(conv.is_archived)

    def test_conversation_with_title(self) -> None:
        """Test Conversation with title."""
        now = datetime.datetime.now(datetime.UTC)
        conv = models.Conversation(
            user_email='test@example.com',
            title='Test Conversation',
            created_at=now,
            updated_at=now,
            model='claude-sonnet-4-20250514',
        )
        self.assertEqual(conv.title, 'Test Conversation')

    def test_conversation_ignores_extra_fields(self) -> None:
        """Test that extra fields are ignored."""
        now = datetime.datetime.now(datetime.UTC)
        conv = models.Conversation(
            user_email='test@example.com',
            created_at=now,
            updated_at=now,
            model='claude-sonnet-4-20250514',
            unknown_field='ignored',
        )
        self.assertFalse(hasattr(conv, 'unknown_field'))


class MessageModelTestCase(unittest.TestCase):
    """Test cases for Message model."""

    def test_create_message(self) -> None:
        """Test creating a Message model."""
        now = datetime.datetime.now(datetime.UTC)
        msg = models.Message(
            conversation_id='conv-123',
            role='user',
            content='Hello',
            created_at=now,
            sequence=0,
        )
        self.assertEqual(msg.role, 'user')
        self.assertEqual(msg.content, 'Hello')
        self.assertEqual(msg.sequence, 0)
        self.assertIsNone(msg.tool_use)
        self.assertIsNone(msg.tool_results)
        self.assertIsNone(msg.token_usage)

    def test_message_with_tool_data(self) -> None:
        """Test Message with tool use data."""
        now = datetime.datetime.now(datetime.UTC)
        msg = models.Message(
            conversation_id='conv-123',
            role='assistant',
            content='Let me look that up.',
            tool_use=[{'id': 'tool-1', 'name': 'list_projects'}],
            tool_results=[{'tool_use_id': 'tool-1', 'content': 'ok'}],
            token_usage={'input_tokens': 100, 'output_tokens': 50},
            created_at=now,
            sequence=1,
        )
        self.assertIsNotNone(msg.tool_use)
        self.assertIsNotNone(msg.tool_results)
        self.assertEqual(
            msg.token_usage,
            {
                'input_tokens': 100,
                'output_tokens': 50,
            },
        )

    def test_message_invalid_role(self) -> None:
        """Test Message rejects invalid role."""
        now = datetime.datetime.now(datetime.UTC)
        with self.assertRaises(pydantic.ValidationError):
            models.Message(
                conversation_id='conv-123',
                role='invalid_role',
                content='Hello',
                created_at=now,
                sequence=0,
            )


class RequestModelTestCase(unittest.TestCase):
    """Test cases for request models."""

    def test_create_conversation_request_defaults(self) -> None:
        """Test CreateConversationRequest with defaults."""
        req = models.CreateConversationRequest()
        self.assertIsNone(req.model)

    def test_create_conversation_request_with_model(self) -> None:
        """Test CreateConversationRequest with custom model."""
        req = models.CreateConversationRequest(
            model='claude-opus-4-20250514',
        )
        self.assertEqual(req.model, 'claude-opus-4-20250514')

    def test_send_message_request(self) -> None:
        """Test SendMessageRequest validation."""
        req = models.SendMessageRequest(content='Hello assistant')
        self.assertEqual(req.content, 'Hello assistant')

    def test_send_message_request_empty_content(self) -> None:
        """Test SendMessageRequest rejects empty content."""
        with self.assertRaises(pydantic.ValidationError):
            models.SendMessageRequest(content='')

    def test_send_message_request_content_too_long(self) -> None:
        """Test SendMessageRequest rejects content over max length."""
        with self.assertRaises(pydantic.ValidationError):
            models.SendMessageRequest(content='x' * 32769)

    def test_update_conversation_request(self) -> None:
        """Test UpdateConversationRequest."""
        req = models.UpdateConversationRequest(
            title='New Title',
            is_archived=True,
        )
        self.assertEqual(req.title, 'New Title')
        self.assertTrue(req.is_archived)


class ResponseModelTestCase(unittest.TestCase):
    """Test cases for response models."""

    def test_conversation_response(self) -> None:
        """Test ConversationResponse model."""
        resp = models.ConversationResponse(
            id='conv-123',
            user_email='test@example.com',
            title='Test',
            created_at='2026-01-01T00:00:00',
            updated_at='2026-01-01T00:00:00',
            model='claude-sonnet-4-20250514',
            is_archived=False,
        )
        self.assertEqual(resp.id, 'conv-123')

    def test_conversation_with_messages_response(self) -> None:
        """Test ConversationWithMessagesResponse model."""
        msg = models.MessageResponse(
            id='msg-1',
            conversation_id='conv-123',
            role='user',
            content='Hello',
            created_at='2026-01-01T00:00:00',
            sequence=0,
        )
        resp = models.ConversationWithMessagesResponse(
            id='conv-123',
            user_email='test@example.com',
            title=None,
            created_at='2026-01-01T00:00:00',
            updated_at='2026-01-01T00:00:00',
            model='claude-sonnet-4-20250514',
            is_archived=False,
            messages=[msg],
        )
        self.assertEqual(len(resp.messages), 1)


class ConverterTestCase(unittest.TestCase):
    """Test cases for model converters."""

    def test_conversation_to_response(self) -> None:
        """Test conversation_to_response converter."""
        now = datetime.datetime.now(datetime.UTC)
        conv = models.Conversation(
            id='conv-123',
            user_email='test@example.com',
            title='Test',
            created_at=now,
            updated_at=now,
            model='claude-sonnet-4-20250514',
        )
        resp = models.conversation_to_response(conv)
        self.assertEqual(resp.id, 'conv-123')
        self.assertEqual(resp.created_at, now.isoformat())

    def test_message_to_response(self) -> None:
        """Test message_to_response converter."""
        now = datetime.datetime.now(datetime.UTC)
        msg = models.Message(
            id='msg-1',
            conversation_id='conv-123',
            role='user',
            content='Hello',
            created_at=now,
            sequence=0,
        )
        resp = models.message_to_response(msg)
        self.assertEqual(resp.id, 'msg-1')
        self.assertEqual(resp.created_at, now.isoformat())
        self.assertEqual(resp.role, 'user')
