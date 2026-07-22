"""Tests for assistant age_ops module."""

import datetime
import json
import re
import unittest
from unittest import mock

from imbi.assistant import age_ops, models


def mock_db(
    data: list | None = None,
) -> mock.AsyncMock:
    """Create a mock graph.Graph with db.execute."""
    db = mock.AsyncMock()
    db.execute.return_value = data if data is not None else []
    return db


class CreateConversationTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    async def test_create_conversation(self) -> None:
        db = mock_db()
        conv = await age_ops.create_conversation(
            db,
            user_email='test@example.com',
            model='claude-sonnet-4-20250514',
        )
        self.assertIsInstance(conv, models.Conversation)
        self.assertEqual(conv.user_email, 'test@example.com')
        self.assertEqual(conv.model, 'claude-sonnet-4-20250514')
        self.assertIsNotNone(conv.id)
        self.assertFalse(conv.is_archived)
        self.assertEqual(db.execute.await_count, 2)


class GetConversationTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    async def test_conversation_found(self) -> None:
        now = datetime.datetime.now(datetime.UTC)
        db = mock_db([{'c': {'raw': 'data'}}])
        with mock.patch(
            'imbi.common.graph.parse_agtype',
        ) as mc:
            mc.return_value = {
                'id': 'conv-123',
                'user_email': 'test@example.com',
                'title': 'Test',
                'created_at': now,
                'updated_at': now,
                'model': 'claude-sonnet-4-20250514',
                'is_archived': False,
            }
            conv = await age_ops.get_conversation(
                db, 'conv-123', 'test@example.com'
            )
            self.assertIsNotNone(conv)
            self.assertEqual(conv.id, 'conv-123')

    async def test_conversation_not_found(self) -> None:
        db = mock_db()
        conv = await age_ops.get_conversation(
            db, 'missing', 'test@example.com'
        )
        self.assertIsNone(conv)


class GetEnabledMCPServersTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    async def test_returns_empty(self) -> None:
        db = mock_db()
        servers = await age_ops.get_enabled_mcp_servers(db)
        self.assertEqual(servers, [])

    async def test_parses_servers(self) -> None:
        db = mock_db([{'s': {'raw': 'data'}}])
        with mock.patch('imbi.common.graph.parse_agtype') as mc:
            mc.return_value = {
                'name': 'Example',
                'slug': 'example',
                'url': 'https://mcp.example.com/mcp',
                'enabled': True,
            }
            servers = await age_ops.get_enabled_mcp_servers(db)
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0].slug, 'example')
        self.assertEqual(str(servers[0].url), 'https://mcp.example.com/mcp')

    async def test_skips_invalid_rows(self) -> None:
        db = mock_db([{'s': {'raw': 'bad'}}, {'s': {'raw': 'good'}}])
        valid = {
            'name': 'Example',
            'slug': 'example',
            'url': 'https://mcp.example.com/mcp',
            'enabled': True,
        }
        with mock.patch('imbi.common.graph.parse_agtype') as mc:
            # First row is missing required fields and fails validation;
            # the loader must skip it and still return the valid one.
            mc.side_effect = [{'enabled': True}, valid]
            servers = await age_ops.get_enabled_mcp_servers(db)
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0].slug, 'example')


class ListConversationsTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    async def test_list_empty(self) -> None:
        db = mock_db()
        convs = await age_ops.list_conversations(db, 'test@example.com')
        self.assertEqual(convs, [])

    async def test_list_with_conversations(self) -> None:
        now = datetime.datetime.now(datetime.UTC)
        db = mock_db(
            [
                {'c': {'raw': 'data1'}},
                {'c': {'raw': 'data2'}},
            ]
        )
        with mock.patch(
            'imbi.common.graph.parse_agtype',
        ) as mc:
            mc.side_effect = [
                {
                    'id': 'conv-1',
                    'user_email': 'test@example.com',
                    'title': 'First',
                    'created_at': now,
                    'updated_at': now,
                    'model': 'claude-sonnet-4-20250514',
                    'is_archived': False,
                },
                {
                    'id': 'conv-2',
                    'user_email': 'test@example.com',
                    'title': 'Second',
                    'created_at': now,
                    'updated_at': now,
                    'model': 'claude-sonnet-4-20250514',
                    'is_archived': False,
                },
            ]
            convs = await age_ops.list_conversations(db, 'test@example.com')
            self.assertEqual(len(convs), 2)

    async def test_include_archived(self) -> None:
        db = mock_db()
        await age_ops.list_conversations(
            db,
            'test@example.com',
            include_archived=True,
        )
        call_args = db.execute.call_args
        query = call_args[0][0]
        self.assertIsNone(
            re.search(
                r'is_archived\s*:\s*false',
                query,
                re.IGNORECASE,
            ),
        )


class AddMessageTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    async def test_add_user_message(self) -> None:
        db = mock_db([{'sequence': 0}])
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            return_value=0,
        ):
            msg = await age_ops.add_message(
                db,
                conversation_id='conv-123',
                role='user',
                content='Hello',
            )
        self.assertIsInstance(msg, models.Message)
        self.assertEqual(msg.role, 'user')
        self.assertEqual(msg.content, 'Hello')
        self.assertEqual(msg.sequence, 0)

    async def test_add_assistant_message_with_tools(
        self,
    ) -> None:
        tool_use = [{'id': 't1', 'name': 'list_projects'}]
        tool_results = [{'tool_use_id': 't1', 'content': 'ok'}]
        token_usage = {
            'input_tokens': 100,
            'output_tokens': 50,
        }
        db = mock_db([{'sequence': 1}])
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            return_value=1,
        ):
            msg = await age_ops.add_message(
                db,
                conversation_id='conv-123',
                role='assistant',
                content='Here are the projects.',
                tool_use=tool_use,
                tool_results=tool_results,
                token_usage=token_usage,
            )
        self.assertEqual(msg.role, 'assistant')
        self.assertEqual(msg.tool_use, tool_use)
        self.assertEqual(msg.token_usage, token_usage)
        call_kwargs = db.execute.call_args[0][1]
        self.assertEqual(
            call_kwargs['tool_use'],
            json.dumps(tool_use),
        )
        self.assertEqual(
            call_kwargs['tool_results'],
            json.dumps(tool_results),
        )
        self.assertEqual(
            call_kwargs['token_usage'],
            json.dumps(token_usage),
        )

    async def test_add_message_missing_conversation(
        self,
    ) -> None:
        db = mock_db()
        with self.assertRaises(ValueError) as ctx:
            await age_ops.add_message(
                db,
                conversation_id='conv-123',
                role='user',
                content='Hello',
            )
        self.assertIn('not found', str(ctx.exception))


class GetMessagesTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    async def test_get_empty_messages(self) -> None:
        db = mock_db()
        msgs = await age_ops.get_messages(db, 'conv-123')
        self.assertEqual(msgs, [])

    async def test_get_messages_with_json_fields(
        self,
    ) -> None:
        now = datetime.datetime.now(datetime.UTC)
        db = mock_db([{'m': {'raw': 'data'}}])
        with mock.patch(
            'imbi.common.graph.parse_agtype',
        ) as mc:
            mc.return_value = {
                'id': 'msg-1',
                'conversation_id': 'conv-123',
                'role': 'assistant',
                'content': 'Result',
                'tool_use': json.dumps([{'id': 't1'}]),
                'tool_results': json.dumps([{'content': 'ok'}]),
                'token_usage': json.dumps(
                    {
                        'input_tokens': 10,
                        'output_tokens': 20,
                    }
                ),
                'created_at': now,
                'sequence': 0,
            }
            msgs = await age_ops.get_messages(db, 'conv-123')
            self.assertEqual(len(msgs), 1)
            msg = msgs[0]
            self.assertIsInstance(msg.tool_use, list)
            self.assertIsInstance(msg.token_usage, dict)


class CountMessagesTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    async def test_count_messages(self) -> None:
        db = mock_db([{'cnt': 5}])
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            return_value=5,
        ):
            count = await age_ops.count_messages(db, 'conv-123')
        self.assertEqual(count, 5)

    async def test_count_messages_empty(self) -> None:
        db = mock_db()
        count = await age_ops.count_messages(db, 'conv-123')
        self.assertEqual(count, 0)


class UpdateConversationTitleTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    async def test_update_title_success(self) -> None:
        db = mock_db([{'id': 'conv-123'}])
        result = await age_ops.update_conversation_title(
            db,
            'conv-123',
            'test@example.com',
            'New Title',
        )
        self.assertTrue(result)

    async def test_update_title_not_found(self) -> None:
        db = mock_db()
        result = await age_ops.update_conversation_title(
            db,
            'missing',
            'test@example.com',
            'New Title',
        )
        self.assertFalse(result)


class ArchiveConversationTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    async def test_archive_success(self) -> None:
        db = mock_db([{'id': 'conv-123'}])
        result = await age_ops.archive_conversation(
            db, 'conv-123', 'test@example.com'
        )
        self.assertTrue(result)

    async def test_archive_not_found(self) -> None:
        db = mock_db()
        result = await age_ops.archive_conversation(
            db, 'missing', 'test@example.com'
        )
        self.assertFalse(result)


class DeleteConversationTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    async def test_delete_success(self) -> None:
        db = mock.AsyncMock()
        # First call (check): found
        # Second call (delete): ok
        db.execute.side_effect = [
            [{'id': 'conv-123'}],
            [{'ok': 1}],
        ]
        result = await age_ops.delete_conversation(
            db, 'conv-123', 'test@example.com'
        )
        self.assertTrue(result)
        self.assertEqual(db.execute.await_count, 2)

    async def test_delete_not_found(self) -> None:
        db = mock_db()  # check returns empty
        result = await age_ops.delete_conversation(
            db, 'missing', 'test@example.com'
        )
        self.assertFalse(result)
        db.execute.assert_awaited_once()
