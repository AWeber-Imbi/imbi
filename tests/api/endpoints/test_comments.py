"""Tests for document comment thread + comment endpoints."""

import datetime
import typing
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from imbi_common import graph

from imbi_api import models
from tests import support

_BASE = '/organizations/engineering/projects/proj-abc/documents/doc-1/comments'


class CommentEndpointsTestCase(support.SharedAppTestCase):
    """Test cases for comment threads and comments CRUD."""

    def setUp(self) -> None:
        from imbi_api.auth import permissions

        self.user = models.User(
            email='alice@example.com',
            display_name='Alice',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.user,
            session_id='test-session',
            auth_method='jwt',
            permissions={
                'document:read',
                'comment:create',
                'comment:write',
                'comment:delete',
            },
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

        self.client = TestClient(self.test_app)

    def _set_permissions(self, perms: set[str]) -> None:
        from imbi_api.auth import permissions

        self.auth_context = permissions.AuthContext(
            user=self.user,
            session_id='test-session',
            auth_method='jwt',
            permissions=perms,
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

    def _document(self, **overrides: typing.Any) -> dict:
        data: dict[str, typing.Any] = {'id': 'doc-1', 'slug': 'runbook'}
        data.update(overrides)
        return data

    def _thread(self, **overrides: typing.Any) -> dict:
        data: dict[str, typing.Any] = {
            'id': 'thread-1',
            'kind': 'page',
            'resolved': False,
            'resolved_by': None,
            'resolved_at': None,
            'anchor_quote': '',
            'anchor_prefix': '',
            'anchor_suffix': '',
            'anchor_start': 0,
            'created_by': 'alice@example.com',
            'created_at': '2026-03-17T12:00:00Z',
            'updated_at': None,
        }
        data.update(overrides)
        return data

    def _comment(self, **overrides: typing.Any) -> dict:
        data: dict[str, typing.Any] = {
            'id': 'comment-1',
            'thread_id': 'thread-1',
            'author': 'alice@example.com',
            'body': 'First!',
            'mentions': [],
            'acknowledged_by': [],
            'edited': False,
            'created_at': '2026-03-17T12:00:00Z',
            'updated_at': None,
        }
        data.update(overrides)
        return data

    def _thread_row(
        self,
        thread: dict | None = None,
        comments: list[dict] | None = None,
    ) -> dict:
        return {
            't': thread or self._thread(),
            'd': self._document(),
            'comments': comments
            if comments is not None
            else [self._comment()],
        }

    # -- List ----------------------------------------------------------

    def test_list_threads(self) -> None:
        # 1: _verify_document, 2: list query
        self.mock_db.execute.side_effect = [
            [{'id': 'doc-1'}],
            [
                self._thread_row(
                    comments=[
                        self._comment(
                            id='c1', created_at='2026-03-17T12:00:00Z'
                        ),
                        self._comment(
                            id='c2',
                            body='reply',
                            created_at='2026-03-17T12:05:00Z',
                        ),
                    ]
                ),
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(_BASE)
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(len(data), 1)
        # Root is first; comments preserved in oldest-first order.
        self.assertEqual([c['id'] for c in data[0]['comments']], ['c1', 'c2'])
        self.assertIsNone(data[0]['anchor'])

    def test_list_document_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(_BASE)
        self.assertEqual(response.status_code, 404)

    # -- Create thread -------------------------------------------------

    def test_create_thread_and_root(self) -> None:
        # 1: verify_document, 2: create, 3: _fetch_thread
        self.mock_db.execute.side_effect = [
            [{'id': 'doc-1'}],
            [{'id': 'thread-1'}],
            [self._thread_row()],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(_BASE, json={'body': 'First!'})
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['document_id'], 'doc-1')
        self.assertEqual(body['kind'], 'page')
        self.assertFalse(body['resolved'])
        self.assertEqual(len(body['comments']), 1)
        self.assertEqual(body['comments'][0]['body'], 'First!')
        # Root comment authored by principal.
        create_call = self.mock_db.execute.await_args_list[1]
        self.assertEqual(create_call.args[1]['author'], 'alice@example.com')
        self.assertEqual(create_call.args[1]['anchor_quote'], '')
        self.assertEqual(create_call.args[1]['anchor_start'], 0)

    def test_create_thread_emits_event(self) -> None:
        # Creating a comment writes a 'document-comment' row to the
        # ClickHouse events table so it surfaces in the activity feeds.
        self.mock_db.execute.side_effect = [
            [{'id': 'doc-1'}],
            [{'id': 'thread-1'}],
            [self._thread_row()],
        ]
        ch = mock.AsyncMock()
        with (
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi_api.endpoints.comments.ch_client.Clickhouse'
                '.get_instance',
                return_value=ch,
            ),
        ):
            response = self.client.post(_BASE, json={'body': 'First!'})
        self.assertEqual(response.status_code, 201)
        ch.insert.assert_awaited_once()
        table, rows, columns = ch.insert.await_args.args
        self.assertEqual(table, 'events')
        record = dict(zip(columns, rows[0], strict=True))
        self.assertEqual(record['type'], 'document-comment')
        self.assertEqual(record['project_id'], 'proj-abc')
        self.assertEqual(record['attributed_to'], 'alice@example.com')
        self.assertEqual(record['payload']['action'], 'created')
        self.assertEqual(record['payload']['document_id'], 'doc-1')

    def test_create_thread_clickhouse_failure_is_best_effort(self) -> None:
        # A failed ClickHouse insert must not fail the comment request.
        self.mock_db.execute.side_effect = [
            [{'id': 'doc-1'}],
            [{'id': 'thread-1'}],
            [self._thread_row()],
        ]
        ch = mock.AsyncMock()
        ch.insert.side_effect = Exception('boom')
        with (
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi_api.endpoints.comments.ch_client.Clickhouse'
                '.get_instance',
                return_value=ch,
            ),
        ):
            response = self.client.post(_BASE, json={'body': 'First!'})
        self.assertEqual(response.status_code, 201)
        ch.insert.assert_awaited_once()

    def test_create_reply_emits_event(self) -> None:
        # Replying writes a 'document-comment' row with action 'replied'
        # and an empty kind.
        self.mock_db.execute.return_value = [
            {'c': self._comment(id='c2', body='reply')}
        ]
        ch = mock.AsyncMock()
        with (
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi_api.endpoints.comments.ch_client.Clickhouse'
                '.get_instance',
                return_value=ch,
            ),
        ):
            response = self.client.post(
                f'{_BASE}/thread-1/comments', json={'body': 'reply'}
            )
        self.assertEqual(response.status_code, 201)
        ch.insert.assert_awaited_once()
        columns, rows = (
            ch.insert.await_args.args[2],
            ch.insert.await_args.args[1],
        )
        record = dict(zip(columns, rows[0], strict=True))
        self.assertEqual(record['type'], 'document-comment')
        self.assertEqual(record['payload']['action'], 'replied')
        self.assertEqual(record['payload']['kind'], '')
        self.assertEqual(record['payload']['thread_id'], 'thread-1')

    def test_create_reply_clickhouse_failure_is_best_effort(self) -> None:
        # A failed ClickHouse insert must not fail the reply request.
        self.mock_db.execute.return_value = [
            {'c': self._comment(id='c2', body='reply')}
        ]
        ch = mock.AsyncMock()
        ch.insert.side_effect = Exception('boom')
        with (
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi_api.endpoints.comments.ch_client.Clickhouse'
                '.get_instance',
                return_value=ch,
            ),
        ):
            response = self.client.post(
                f'{_BASE}/thread-1/comments', json={'body': 'reply'}
            )
        self.assertEqual(response.status_code, 201)
        ch.insert.assert_awaited_once()

    def test_create_thread_persists_mentions(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'id': 'doc-1'}],
            [{'id': 'thread-1'}],
            [
                self._thread_row(
                    comments=[self._comment(mentions=['a@x.com', 'b@x.com'])]
                )
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                _BASE,
                json={
                    'body': 'First!',
                    'mentions': ['a@x.com', 'b@x.com'],
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json()['comments'][0]['mentions'],
            ['a@x.com', 'b@x.com'],
        )
        create_call = self.mock_db.execute.await_args_list[1]
        self.assertEqual(
            create_call.args[1]['mentions'], ['a@x.com', 'b@x.com']
        )

    def test_create_thread_defaults_mentions_empty(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'id': 'doc-1'}],
            [{'id': 'thread-1'}],
            [self._thread_row()],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(_BASE, json={'body': 'First!'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['comments'][0]['mentions'], [])
        create_call = self.mock_db.execute.await_args_list[1]
        self.assertEqual(create_call.args[1]['mentions'], [])

    def test_create_thread_document_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(_BASE, json={'body': 'x'})
        self.assertEqual(response.status_code, 404)

    def test_create_thread_empty_body_rejected(self) -> None:
        response = self.client.post(_BASE, json={'body': ''})
        self.assertEqual(response.status_code, 422)

    # -- Create inline thread ------------------------------------------

    def test_create_inline_thread_with_anchor(self) -> None:
        inline_thread = self._thread(
            kind='inline',
            anchor_quote='the disputed phrase',
            anchor_prefix='before ',
            anchor_suffix=' after',
            anchor_start=42,
        )
        # 1: verify_document, 2: create, 3: _fetch_thread
        self.mock_db.execute.side_effect = [
            [{'id': 'doc-1'}],
            [{'id': 'thread-1'}],
            [self._thread_row(thread=inline_thread)],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                _BASE,
                json={
                    'kind': 'inline',
                    'body': 'Inline!',
                    'anchor': {
                        'quote': 'the disputed phrase',
                        'prefix': 'before ',
                        'suffix': ' after',
                        'start': 42,
                    },
                },
            )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['kind'], 'inline')
        self.assertEqual(body['anchor']['quote'], 'the disputed phrase')
        self.assertEqual(body['anchor']['prefix'], 'before ')
        self.assertEqual(body['anchor']['suffix'], ' after')
        self.assertEqual(body['anchor']['start'], 42)
        # Persisted params carry the anchor scalars.
        create_call = self.mock_db.execute.await_args_list[1]
        self.assertEqual(create_call.args[1]['kind'], 'inline')
        self.assertEqual(
            create_call.args[1]['anchor_quote'], 'the disputed phrase'
        )
        self.assertEqual(create_call.args[1]['anchor_prefix'], 'before ')
        self.assertEqual(create_call.args[1]['anchor_suffix'], ' after')
        self.assertEqual(create_call.args[1]['anchor_start'], 42)

    def test_create_page_thread_has_no_anchor(self) -> None:
        # Regression: page threads round-trip anchor=None.
        self.mock_db.execute.side_effect = [
            [{'id': 'doc-1'}],
            [{'id': 'thread-1'}],
            [self._thread_row()],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(_BASE, json={'body': 'First!'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['kind'], 'page')
        self.assertIsNone(response.json()['anchor'])

    def test_create_inline_thread_missing_anchor_rejected(self) -> None:
        response = self.client.post(
            _BASE, json={'kind': 'inline', 'body': 'x'}
        )
        self.assertEqual(response.status_code, 422)

    def test_create_inline_thread_blank_quote_rejected(self) -> None:
        response = self.client.post(
            _BASE,
            json={
                'kind': 'inline',
                'body': 'x',
                'anchor': {
                    'quote': '   ',
                    'prefix': '',
                    'suffix': '',
                    'start': 0,
                },
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_create_page_thread_ignores_anchor(self) -> None:
        # A page thread with an anchor in the body persists empty scalars
        # and round-trips anchor=None.
        self.mock_db.execute.side_effect = [
            [{'id': 'doc-1'}],
            [{'id': 'thread-1'}],
            [self._thread_row()],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                _BASE,
                json={
                    'kind': 'page',
                    'body': 'First!',
                    'anchor': {
                        'quote': 'ignored',
                        'prefix': '',
                        'suffix': '',
                        'start': 7,
                    },
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()['anchor'])
        create_call = self.mock_db.execute.await_args_list[1]
        self.assertEqual(create_call.args[1]['kind'], 'page')
        self.assertEqual(create_call.args[1]['anchor_quote'], '')
        self.assertEqual(create_call.args[1]['anchor_start'], 0)

    # -- Reply ---------------------------------------------------------

    def test_create_reply(self) -> None:
        self.mock_db.execute.return_value = [
            {
                'c': self._comment(
                    id='c2', body='reply', author='alice@example.com'
                )
            }
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                f'{_BASE}/thread-1/comments', json={'body': 'reply'}
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['body'], 'reply')
        self.assertEqual(response.json()['id'], 'c2')

    def test_create_reply_persists_mentions(self) -> None:
        self.mock_db.execute.return_value = [
            {
                'c': self._comment(
                    id='c2',
                    body='reply',
                    mentions=['c@x.com'],
                )
            }
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                f'{_BASE}/thread-1/comments',
                json={'body': 'reply', 'mentions': ['c@x.com']},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['mentions'], ['c@x.com'])
        create_call = self.mock_db.execute.await_args_list[0]
        self.assertEqual(create_call.args[1]['mentions'], ['c@x.com'])

    def test_create_reply_defaults_mentions_empty(self) -> None:
        self.mock_db.execute.return_value = [
            {'c': self._comment(id='c2', body='reply')}
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                f'{_BASE}/thread-1/comments', json={'body': 'reply'}
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['mentions'], [])
        create_call = self.mock_db.execute.await_args_list[0]
        self.assertEqual(create_call.args[1]['mentions'], [])

    def test_create_reply_thread_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                f'{_BASE}/ghost/comments', json={'body': 'reply'}
            )
        self.assertEqual(response.status_code, 404)

    # -- Resolve / reopen ----------------------------------------------

    def test_resolve_thread(self) -> None:
        # 1: _fetch_thread (existing), 2: SET, 3: _fetch_thread (final)
        self.mock_db.execute.side_effect = [
            [self._thread_row()],
            [{'id': 'thread-1'}],
            [
                self._thread_row(
                    thread=self._thread(
                        resolved=True,
                        resolved_by='alice@example.com',
                        resolved_at='2026-03-18T09:00:00Z',
                    )
                )
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                f'{_BASE}/thread-1',
                json=[{'op': 'replace', 'path': '/resolved', 'value': True}],
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['resolved'])
        self.assertEqual(response.json()['resolved_by'], 'alice@example.com')
        set_call = self.mock_db.execute.await_args_list[1]
        self.assertTrue(set_call.args[1]['resolved'])
        self.assertEqual(set_call.args[1]['resolved_by'], 'alice@example.com')
        self.assertIsNotNone(set_call.args[1]['resolved_at'])

    def test_reopen_thread_clears_resolution(self) -> None:
        resolved = self._thread(
            resolved=True,
            resolved_by='alice@example.com',
            resolved_at='2026-03-18T09:00:00Z',
        )
        self.mock_db.execute.side_effect = [
            [self._thread_row(thread=resolved)],
            [{'id': 'thread-1'}],
            [self._thread_row()],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                f'{_BASE}/thread-1',
                json=[{'op': 'replace', 'path': '/resolved', 'value': False}],
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['resolved'])
        set_call = self.mock_db.execute.await_args_list[1]
        self.assertFalse(set_call.args[1]['resolved'])
        self.assertIsNone(set_call.args[1]['resolved_by'])
        self.assertIsNone(set_call.args[1]['resolved_at'])

    def test_patch_thread_readonly_path_rejected(self) -> None:
        self.mock_db.execute.return_value = [self._thread_row()]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                f'{_BASE}/thread-1',
                json=[
                    {
                        'op': 'replace',
                        'path': '/resolved_by',
                        'value': 'attacker',
                    }
                ],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_thread_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.patch(
            f'{_BASE}/ghost',
            json=[{'op': 'replace', 'path': '/resolved', 'value': True}],
        )
        self.assertEqual(response.status_code, 404)

    def test_patch_thread_non_bool_rejected(self) -> None:
        self.mock_db.execute.return_value = [self._thread_row()]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                f'{_BASE}/thread-1',
                json=[{'op': 'replace', 'path': '/resolved', 'value': 'yes'}],
            )
        self.assertEqual(response.status_code, 400)

    # -- Edit comment body ---------------------------------------------

    def test_edit_comment_body(self) -> None:
        # 1: _fetch_comment, 2: SET
        self.mock_db.execute.side_effect = [
            [{'c': self._comment()}],
            [{'c': self._comment(body='edited', edited=True)}],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                f'{_BASE}/thread-1/comments/comment-1',
                json=[{'op': 'replace', 'path': '/body', 'value': 'edited'}],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['body'], 'edited')
        self.assertTrue(response.json()['edited'])
        set_call = self.mock_db.execute.await_args_list[1]
        self.assertEqual(set_call.args[1]['body'], 'edited')
        self.assertTrue(set_call.args[1]['edited'])

    def test_edit_comment_replaces_mentions(self) -> None:
        # 1: _fetch_comment, 2: SET
        self.mock_db.execute.side_effect = [
            [{'c': self._comment(mentions=['old@x.com'])}],
            [{'c': self._comment(mentions=['new@x.com'], edited=True)}],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                f'{_BASE}/thread-1/comments/comment-1',
                json=[
                    {
                        'op': 'replace',
                        'path': '/mentions',
                        'value': ['new@x.com'],
                    }
                ],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['mentions'], ['new@x.com'])
        self.assertTrue(response.json()['edited'])
        set_call = self.mock_db.execute.await_args_list[1]
        self.assertEqual(set_call.args[1]['mentions'], ['new@x.com'])
        self.assertTrue(set_call.args[1]['edited'])

    def test_edit_comment_mentions_non_author_forbidden(self) -> None:
        self.mock_db.execute.return_value = [
            {'c': self._comment(author='bob@example.com')}
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                f'{_BASE}/thread-1/comments/comment-1',
                json=[
                    {
                        'op': 'replace',
                        'path': '/mentions',
                        'value': ['new@x.com'],
                    }
                ],
            )
        self.assertEqual(response.status_code, 403)

    def test_edit_comment_body_keeps_mentions(self) -> None:
        # Regression: editing only /body preserves existing mentions.
        self.mock_db.execute.side_effect = [
            [{'c': self._comment(mentions=['keep@x.com'])}],
            [
                {
                    'c': self._comment(
                        body='edited',
                        mentions=['keep@x.com'],
                        edited=True,
                    )
                }
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                f'{_BASE}/thread-1/comments/comment-1',
                json=[{'op': 'replace', 'path': '/body', 'value': 'edited'}],
            )
        self.assertEqual(response.status_code, 200)
        set_call = self.mock_db.execute.await_args_list[1]
        self.assertEqual(set_call.args[1]['mentions'], ['keep@x.com'])

    def test_edit_comment_non_author_forbidden(self) -> None:
        self.mock_db.execute.return_value = [
            {'c': self._comment(author='bob@example.com')}
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                f'{_BASE}/thread-1/comments/comment-1',
                json=[{'op': 'replace', 'path': '/body', 'value': 'edited'}],
            )
        self.assertEqual(response.status_code, 403)

    def test_edit_comment_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.patch(
            f'{_BASE}/thread-1/comments/ghost',
            json=[{'op': 'replace', 'path': '/body', 'value': 'x'}],
        )
        self.assertEqual(response.status_code, 404)

    def test_edit_comment_empty_body_rejected(self) -> None:
        self.mock_db.execute.return_value = [{'c': self._comment()}]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                f'{_BASE}/thread-1/comments/comment-1',
                json=[{'op': 'replace', 'path': '/body', 'value': ''}],
            )
        self.assertEqual(response.status_code, 400)

    def test_edit_comment_readonly_path_rejected(self) -> None:
        self.mock_db.execute.return_value = [{'c': self._comment()}]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                f'{_BASE}/thread-1/comments/comment-1',
                json=[
                    {'op': 'replace', 'path': '/author', 'value': 'attacker'}
                ],
            )
        self.assertEqual(response.status_code, 400)

    # -- Acknowledge toggle --------------------------------------------

    def test_acknowledge_adds_principal(self) -> None:
        # 1: _fetch_comment, 2: SET
        self.mock_db.execute.side_effect = [
            [{'c': self._comment(acknowledged_by=[])}],
            [{'c': self._comment(acknowledged_by=['alice@example.com'])}],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                f'{_BASE}/thread-1/comments/comment-1/acknowledge'
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn('alice@example.com', response.json()['acknowledged_by'])
        set_call = self.mock_db.execute.await_args_list[1]
        self.assertEqual(
            set_call.args[1]['acknowledged_by'], ['alice@example.com']
        )

    def test_acknowledge_removes_principal(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'c': self._comment(acknowledged_by=['alice@example.com'])}],
            [{'c': self._comment(acknowledged_by=[])}],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                f'{_BASE}/thread-1/comments/comment-1/acknowledge'
            )
        self.assertEqual(response.status_code, 200)
        set_call = self.mock_db.execute.await_args_list[1]
        self.assertEqual(set_call.args[1]['acknowledged_by'], [])

    def test_acknowledge_comment_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.post(
            f'{_BASE}/thread-1/comments/ghost/acknowledge'
        )
        self.assertEqual(response.status_code, 404)

    # -- Delete --------------------------------------------------------

    def test_delete_reply_keeps_thread(self) -> None:
        # 1: _fetch_comment, 2: _fetch_thread (root + reply), 3: DELETE
        thread_with_two = self._thread_row(
            comments=[
                self._comment(
                    id='comment-1', created_at='2026-03-17T12:00:00Z'
                ),
                self._comment(
                    id='comment-2', created_at='2026-03-17T12:05:00Z'
                ),
            ]
        )
        self.mock_db.execute.side_effect = [
            [{'c': self._comment(id='comment-2')}],
            [thread_with_two],
            [{'deleted': 1}],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.delete(
                f'{_BASE}/thread-1/comments/comment-2'
            )
        self.assertEqual(response.status_code, 204)
        # The DELETE query must only delete the comment (not the thread).
        delete_query = self.mock_db.execute.await_args_list[2].args[0]
        self.assertNotIn('DETACH DELETE c, t', delete_query)

    def test_delete_root_only_comment_removes_thread(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'c': self._comment(id='comment-1')}],
            [self._thread_row(comments=[self._comment(id='comment-1')])],
            [{'deleted': 1}],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.delete(
                f'{_BASE}/thread-1/comments/comment-1'
            )
        self.assertEqual(response.status_code, 204)
        delete_query = self.mock_db.execute.await_args_list[2].args[0]
        self.assertIn('DETACH DELETE c, t', delete_query)

    def test_delete_root_with_replies_keeps_thread(self) -> None:
        thread_with_two = self._thread_row(
            comments=[
                self._comment(
                    id='comment-1', created_at='2026-03-17T12:00:00Z'
                ),
                self._comment(
                    id='comment-2', created_at='2026-03-17T12:05:00Z'
                ),
            ]
        )
        self.mock_db.execute.side_effect = [
            [{'c': self._comment(id='comment-1')}],
            [thread_with_two],
            [{'deleted': 1}],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.delete(
                f'{_BASE}/thread-1/comments/comment-1'
            )
        self.assertEqual(response.status_code, 204)
        delete_query = self.mock_db.execute.await_args_list[2].args[0]
        self.assertNotIn('DETACH DELETE c, t', delete_query)

    def test_delete_non_author_forbidden(self) -> None:
        self.mock_db.execute.return_value = [
            {'c': self._comment(author='bob@example.com')}
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.delete(
                f'{_BASE}/thread-1/comments/comment-1'
            )
        self.assertEqual(response.status_code, 403)

    def test_delete_comment_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.delete(f'{_BASE}/thread-1/comments/ghost')
        self.assertEqual(response.status_code, 404)

    # -- Permission failures -------------------------------------------

    def test_create_thread_requires_comment_create(self) -> None:
        self._set_permissions({'document:read'})
        response = self.client.post(_BASE, json={'body': 'x'})
        self.assertEqual(response.status_code, 403)

    def test_reply_requires_comment_create(self) -> None:
        self._set_permissions({'document:read'})
        response = self.client.post(
            f'{_BASE}/thread-1/comments', json={'body': 'x'}
        )
        self.assertEqual(response.status_code, 403)

    def test_patch_thread_requires_comment_write(self) -> None:
        self._set_permissions({'document:read'})
        response = self.client.patch(
            f'{_BASE}/thread-1',
            json=[{'op': 'replace', 'path': '/resolved', 'value': True}],
        )
        self.assertEqual(response.status_code, 403)

    def test_acknowledge_requires_comment_write(self) -> None:
        self._set_permissions({'document:read'})
        response = self.client.post(
            f'{_BASE}/thread-1/comments/comment-1/acknowledge'
        )
        self.assertEqual(response.status_code, 403)

    def test_delete_requires_comment_delete(self) -> None:
        self._set_permissions({'document:read', 'comment:write'})
        response = self.client.delete(f'{_BASE}/thread-1/comments/comment-1')
        self.assertEqual(response.status_code, 403)

    def test_list_requires_document_read(self) -> None:
        self._set_permissions({'comment:create'})
        response = self.client.get(_BASE)
        self.assertEqual(response.status_code, 403)


class ThreadRowParsingTestCase(unittest.TestCase):
    """Parse a thread row from the **raw agtype strings** AGE returns.

    The endpoint tests mock ``graph.execute`` and hand back pre-parsed
    dicts, so they never exercise ``graph.parse_agtype``. This case feeds
    ``_parse_thread_row`` the wire form -- vertex strings for ``t``/``d``
    and a JSON array of map projections for ``comments`` -- which is what
    ``_COMMENTS_TAIL`` actually emits. It guards the regression where the
    tail collected raw vertices: ``parse_agtype`` could not decode the
    resulting ``::vertex``-suffixed list-string, fell back to the raw
    string, and the comment list came back empty.
    """

    def test_comments_round_trip_from_agtype(self) -> None:
        from imbi_api.endpoints import comments

        thread_vertex = (
            '{"id": 0, "label": "CommentThread", "properties": '
            '{"id": "thread-1", "kind": "page", "resolved": false, '
            '"resolved_by": null, "resolved_at": null, '
            '"anchor_quote": "", "anchor_prefix": "", '
            '"anchor_suffix": "", "anchor_start": 0, '
            '"created_by": "alice@example.com", '
            '"created_at": "2026-03-17T12:00:00Z", '
            '"updated_at": null}}::vertex'
        )
        document_vertex = (
            '{"id": 1, "label": "Document", "properties": '
            '{"id": "doc-1", "slug": "runbook"}}::vertex'
        )
        # Map projections serialize as plain JSON maps (no ::vertex).
        comments_column = (
            '[{"id": "c1", "thread_id": "thread-1", '
            '"author": "alice@example.com", "body": "First!", '
            '"mentions": [], "acknowledged_by": [], "edited": false, '
            '"created_at": "2026-03-17T12:00:00Z", "updated_at": null}]'
        )

        row = comments._parse_thread_row(
            {
                't': thread_vertex,
                'd': document_vertex,
                'comments': comments_column,
            }
        )

        self.assertEqual(row['id'], 'thread-1')
        self.assertEqual(row['document_id'], 'doc-1')
        self.assertEqual(len(row['comments']), 1)
        self.assertEqual(row['comments'][0]['id'], 'c1')
        self.assertEqual(row['comments'][0]['body'], 'First!')


if __name__ == '__main__':
    unittest.main()
