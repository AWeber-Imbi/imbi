"""Tests for the document editing-presence endpoints."""

import datetime
import unittest
from unittest import mock

import fastapi.testclient

from apps.api.tests import support
from imbi.api import models
from imbi.common import valkey


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

        self.mock_valkey = mock.AsyncMock()
        self.test_app.dependency_overrides[valkey._inject_client] = (
            lambda: self.mock_valkey
        )

        self.client = fastapi.testclient.TestClient(self.test_app)

    # -- GET ---------------------------------------------------------------

    def test_get_editors(self) -> None:
        self.mock_valkey.zrange.return_value = [
            b'zed@example.com',
            b'alice@example.com',
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
        self.mock_valkey.zremrangebyscore.assert_awaited_once()

    def test_get_editors_empty(self) -> None:
        self.mock_valkey.zrange.return_value = []
        response = self.client.get(
            '/organizations/engineering/documents/document-1/editing'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['editors'], [])

    def test_get_editors_valkey_down(self) -> None:
        """Presence degrades to empty rather than failing the request."""
        self.mock_valkey.zremrangebyscore.side_effect = ConnectionError()
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
        self.mock_valkey.zrange.return_value = [b'admin@example.com']
        response = self.client.put(
            '/organizations/engineering/documents/document-1/editing'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['editors'], ['admin@example.com'])
        zadd_call = self.mock_valkey.zadd.await_args
        key, mapping = zadd_call.args
        self.assertEqual(key, 'imbi:document:editing:document-1')
        self.assertEqual(list(mapping), ['admin@example.com'])
        self.mock_valkey.expire.assert_awaited_once()

    def test_heartbeat_valkey_down(self) -> None:
        self.mock_valkey.zadd.side_effect = ConnectionError()
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
            'imbi:document:editing:document-1', 'admin@example.com'
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
