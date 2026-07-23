"""Tests for the document editing-presence endpoints."""

import datetime
import unittest
from unittest import mock

import fastapi.testclient

from apps.api.tests import support
from imbi.api import models
from imbi.common import valkey

KEY = 'imbi:document:editing:engineering:document-1'


class DocumentPresenceEndpointsTestCase(support.SharedAppTestCase):
    """Advisory editing markers backed by a Valkey sorted set."""

    def setUp(self) -> None:
        from imbi.api.auth import permissions

        self.admin_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.admin_user,
            session_id='test-session',
            auth_method='jwt',
            permissions={
                'document:read',
                'document:write',
            },
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        # Presence batches its Valkey commands through a pipeline; the
        # command methods queue synchronously, only execute() awaits.
        self.mock_valkey = mock.AsyncMock()
        self.mock_pipe = mock.Mock()
        self.mock_pipe.execute = mock.AsyncMock(return_value=[0, []])
        self.mock_valkey.pipeline = mock.Mock(return_value=self.mock_pipe)
        self.test_app.dependency_overrides[valkey._inject_client] = (
            lambda: self.mock_valkey
        )

        self.client = fastapi.testclient.TestClient(self.test_app)

    # -- GET ---------------------------------------------------------------

    def test_get_editors(self) -> None:
        self.mock_pipe.execute.return_value = [
            2,
            [b'zed@example.com', b'alice@example.com'],
        ]
        response = self.client.get(
            '/organizations/engineering/documents/document-1/editing'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['editors'],
            ['alice@example.com', 'zed@example.com'],
        )
        # Stale entries are pruned before reading.
        self.mock_pipe.zremrangebyscore.assert_called_once()
        self.assertEqual(
            self.mock_pipe.zremrangebyscore.call_args.args[0], KEY
        )

    def test_get_editors_empty(self) -> None:
        response = self.client.get(
            '/organizations/engineering/documents/document-1/editing'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['editors'], [])

    def test_get_editors_valkey_down(self) -> None:
        """Presence degrades to empty rather than failing the request."""
        self.mock_pipe.execute.side_effect = ConnectionError()
        with self.assertLogs(
            'imbi.api.endpoints.document_presence', level='ERROR'
        ):
            response = self.client.get(
                '/organizations/engineering/documents/document-1/editing'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['editors'], [])

    # -- PUT (heartbeat) -----------------------------------------------------

    def test_heartbeat_registers_editor(self) -> None:
        self.mock_pipe.execute.return_value = [
            1,
            True,
            0,
            [b'admin@example.com'],
        ]
        response = self.client.put(
            '/organizations/engineering/documents/document-1/editing'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['editors'], ['admin@example.com'])
        key, mapping = self.mock_pipe.zadd.call_args.args
        self.assertEqual(key, KEY)
        self.assertEqual(list(mapping), ['admin@example.com'])
        self.mock_pipe.expire.assert_called_once()

    def test_heartbeat_valkey_down(self) -> None:
        self.mock_pipe.execute.side_effect = ConnectionError()
        with self.assertLogs(
            'imbi.api.endpoints.document_presence', level='ERROR'
        ):
            response = self.client.put(
                '/organizations/engineering/documents/document-1/editing'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['editors'], [])

    # -- DELETE ---------------------------------------------------------------

    def test_clear_editing(self) -> None:
        response = self.client.delete(
            '/organizations/engineering/documents/document-1/editing'
        )
        self.assertEqual(response.status_code, 204)
        self.mock_valkey.zrem.assert_awaited_once_with(
            KEY, 'admin@example.com'
        )

    def test_clear_editing_valkey_down(self) -> None:
        self.mock_valkey.zrem.side_effect = ConnectionError()
        with self.assertLogs(
            'imbi.api.endpoints.document_presence', level='ERROR'
        ):
            response = self.client.delete(
                '/organizations/engineering/documents/document-1/editing'
            )
        self.assertEqual(response.status_code, 204)


if __name__ == '__main__':
    unittest.main()
