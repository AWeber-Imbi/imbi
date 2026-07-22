"""Tests for MCP server admin CRUD endpoints."""

import datetime
import typing
from unittest import mock

import psycopg.errors
from fastapi.testclient import TestClient

from apps.api.tests import support
from imbi.api import models
from imbi.api.auth import permissions
from imbi.api.mcp_test import ConnectionTestResult
from imbi.common import graph


class MCPServerEndpointsTestCase(support.SharedAppTestCase):
    """Test cases for MCP server CRUD endpoints."""

    def setUp(self) -> None:
        """Set up test app with admin authentication."""

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
            permissions=set(),
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

        self.client = TestClient(self.test_app)

    def _server_props(self, **overrides: typing.Any) -> dict[str, typing.Any]:
        """Return a default MCP server vertex property dict."""
        data: dict[str, typing.Any] = {
            'id': 'srv-1',
            'name': 'Example',
            'slug': 'example',
            'url': 'https://mcp.example.com',
            'description': None,
            'icon': None,
            'enabled': True,
            'tool_prefix': None,
            'timeout': 30,
            'verify_ssl': True,
            'ignored_tools': [],
            'auth_type': 'none',
            'static_header': None,
            'static_value_encrypted': None,
            'oauth_token_url': None,
            'oauth_client_id': None,
            'oauth_client_secret_encrypted': None,
            'oauth_scope': None,
            'created_at': '2026-05-27T12:00:00Z',
            'updated_at': '2026-05-27T12:00:00Z',
        }
        data.update(overrides)
        return data

    def _model(self, **overrides: typing.Any) -> models.MCPServer:
        """Return a default MCPServer model instance."""
        return models.MCPServer.model_validate(self._server_props(**overrides))

    # -- Create --------------------------------------------------------

    def test_create_success(self) -> None:
        """A server is created and secrets are encrypted, not echoed."""
        self.mock_db.execute.return_value = [{'n': self._server_props()}]
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.mcp_servers.encrypt_config_value',
                side_effect=lambda v: None if v is None else f'enc:{v}',
            ) as enc,
        ):
            response = self.client.post(
                '/mcp-servers/',
                json={
                    'name': 'Example',
                    'slug': 'example',
                    'url': 'https://mcp.example.com',
                    'auth_type': 'static',
                    'static_header': 'Authorization',
                    'static_value': 'super-secret',
                },
            )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['slug'], 'example')
        self.assertEqual(data['id'], 'srv-1')
        # Plaintext secret was encrypted before persistence.
        enc.assert_any_call('super-secret')
        # The persisted props carried ciphertext, never plaintext.
        persisted = self.mock_db.execute.call_args.args[1]
        self.assertEqual(
            persisted['static_value_encrypted'], 'enc:super-secret'
        )
        self.assertNotIn('static_value', persisted)
        # Response never leaks plaintext or ciphertext.
        self.assertNotIn('static_value', data)
        self.assertNotIn('static_value_encrypted', data)
        self.assertNotIn('oauth_client_secret', data)
        self.assertNotIn('oauth_client_secret_encrypted', data)

    def test_create_validation_error(self) -> None:
        """Missing required fields return 422."""
        response = self.client.post('/mcp-servers/', json={})
        self.assertEqual(response.status_code, 422)

    def test_create_slug_conflict(self) -> None:
        """A duplicate slug returns 409."""
        self.mock_db.execute.side_effect = psycopg.errors.UniqueViolation()
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.mcp_servers.encrypt_config_value',
                side_effect=lambda v: v,
            ),
        ):
            response = self.client.post(
                '/mcp-servers/',
                json={
                    'name': 'Example',
                    'slug': 'example',
                    'url': 'https://mcp.example.com',
                },
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

    def test_create_static_missing_fields_returns_400(self) -> None:
        """auth_type 'static' without header/value is rejected."""
        with mock.patch(
            'imbi.api.endpoints.mcp_servers.encrypt_config_value',
            side_effect=lambda v: None if v is None else f'enc:{v}',
        ):
            response = self.client.post(
                '/mcp-servers/',
                json={
                    'name': 'Example',
                    'slug': 'example',
                    'url': 'https://mcp.example.com',
                    'auth_type': 'static',
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('static', response.json()['detail'])
        self.mock_db.execute.assert_not_called()

    def test_create_oauth_missing_fields_returns_400(self) -> None:
        """auth_type 'oauth_client_credentials' missing fields is rejected."""
        with mock.patch(
            'imbi.api.endpoints.mcp_servers.encrypt_config_value',
            side_effect=lambda v: None if v is None else f'enc:{v}',
        ):
            response = self.client.post(
                '/mcp-servers/',
                json={
                    'name': 'Example',
                    'slug': 'example',
                    'url': 'https://mcp.example.com',
                    'auth_type': 'oauth_client_credentials',
                    'oauth_token_url': 'https://auth.example.com/token',
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('oauth_client_credentials', response.json()['detail'])
        self.mock_db.execute.assert_not_called()

    # -- List / Get ----------------------------------------------------

    def test_list_success(self) -> None:
        """Listing returns secret-presence booleans, never secrets."""
        self.mock_db.match.return_value = [
            self._model(),
            self._model(
                id='srv-2',
                slug='secure',
                name='Secure',
                static_value_encrypted='enc:abc',
                oauth_client_secret_encrypted='enc:def',
            ),
        ]
        response = self.client.get('/mcp-servers/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertFalse(data[0]['has_static_value'])
        self.assertFalse(data[0]['has_oauth_client_secret'])
        self.assertTrue(data[1]['has_static_value'])
        self.assertTrue(data[1]['has_oauth_client_secret'])
        for item in data:
            self.assertNotIn('static_value_encrypted', item)
            self.assertNotIn('oauth_client_secret_encrypted', item)

    def test_get_success(self) -> None:
        """Fetching by id returns the server."""
        self.mock_db.match.return_value = [
            self._model(static_value_encrypted='enc:abc')
        ]
        response = self.client.get('/mcp-servers/srv-1')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['id'], 'srv-1')
        self.assertTrue(data['has_static_value'])
        self.assertNotIn('static_value_encrypted', data)

    def test_get_not_found(self) -> None:
        """Fetching a missing id returns 404."""
        self.mock_db.match.return_value = []
        response = self.client.get('/mcp-servers/missing')
        self.assertEqual(response.status_code, 404)

    # -- Update --------------------------------------------------------

    def test_patch_updates_non_secret_field(self) -> None:
        """A non-secret patch updates the field and persists."""
        self.mock_db.match.return_value = [self._model()]
        self.mock_db.execute.return_value = [
            {'n': self._server_props(name='Renamed')}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/mcp-servers/srv-1', json={'name': 'Renamed'}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'Renamed')

    def test_patch_secret_omitted_keeps_ciphertext(self) -> None:
        """Omitting a secret leaves the stored ciphertext untouched."""
        self.mock_db.match.return_value = [
            self._model(static_value_encrypted='enc:original')
        ]
        self.mock_db.execute.return_value = [
            {'n': self._server_props(static_value_encrypted='enc:original')}
        ]
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi.api.endpoints.mcp_servers.encrypt_config_value',
                side_effect=lambda v: f'enc:{v}',
            ) as enc,
        ):
            response = self.client.patch(
                '/mcp-servers/srv-1', json={'name': 'Renamed'}
            )
        self.assertEqual(response.status_code, 200)
        # Secret was not re-encrypted since it was omitted.
        enc.assert_not_called()
        persisted = self.mock_db.execute.call_args.args[1]
        self.assertEqual(persisted['static_value_encrypted'], 'enc:original')
        self.assertTrue(response.json()['has_static_value'])

    def test_patch_secret_cleared_with_null(self) -> None:
        """An explicit null secret clears the stored ciphertext."""
        self.mock_db.match.return_value = [
            self._model(static_value_encrypted='enc:original')
        ]
        self.mock_db.execute.return_value = [
            {'n': self._server_props(static_value_encrypted=None)}
        ]
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi.api.endpoints.mcp_servers.encrypt_config_value',
                side_effect=lambda v: None if v is None else f'enc:{v}',
            ) as enc,
        ):
            response = self.client.patch(
                '/mcp-servers/srv-1', json={'static_value': None}
            )
        self.assertEqual(response.status_code, 200)
        enc.assert_called_once_with(None)
        persisted = self.mock_db.execute.call_args.args[1]
        self.assertIsNone(persisted['static_value_encrypted'])
        self.assertFalse(response.json()['has_static_value'])

    def test_patch_secret_replaced(self) -> None:
        """A new secret value is re-encrypted and persisted."""
        self.mock_db.match.return_value = [
            self._model(static_value_encrypted='enc:original')
        ]
        self.mock_db.execute.return_value = [
            {'n': self._server_props(static_value_encrypted='enc:new')}
        ]
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi.api.endpoints.mcp_servers.encrypt_config_value',
                side_effect=lambda v: None if v is None else f'enc:{v}',
            ) as enc,
        ):
            response = self.client.patch(
                '/mcp-servers/srv-1', json={'static_value': 'new'}
            )
        self.assertEqual(response.status_code, 200)
        enc.assert_called_once_with('new')
        persisted = self.mock_db.execute.call_args.args[1]
        self.assertEqual(persisted['static_value_encrypted'], 'enc:new')
        self.assertNotIn('static_value', persisted)
        data = response.json()
        self.assertTrue(data['has_static_value'])
        self.assertNotIn('static_value_encrypted', data)

    def test_patch_auth_switch_missing_fields_returns_400(self) -> None:
        """Switching auth_type without its required fields is rejected."""
        self.mock_db.match.return_value = [self._model()]
        with mock.patch(
            'imbi.api.endpoints.mcp_servers.encrypt_config_value',
            side_effect=lambda v: None if v is None else f'enc:{v}',
        ):
            response = self.client.patch(
                '/mcp-servers/srv-1',
                json={'auth_type': 'oauth_client_credentials'},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('oauth_client_credentials', response.json()['detail'])
        self.mock_db.execute.assert_not_called()

    def test_patch_not_found(self) -> None:
        """Patching a missing id returns 404."""
        self.mock_db.match.return_value = []
        response = self.client.patch(
            '/mcp-servers/missing', json={'name': 'X'}
        )
        self.assertEqual(response.status_code, 404)

    def test_patch_slug_conflict(self) -> None:
        """A slug collision on update returns 409."""
        self.mock_db.match.return_value = [self._model()]
        self.mock_db.execute.side_effect = psycopg.errors.UniqueViolation()
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/mcp-servers/srv-1', json={'slug': 'taken'}
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

    # -- Delete --------------------------------------------------------

    def test_delete_success(self) -> None:
        """Deleting an existing server returns 204."""
        self.mock_db.execute.return_value = [{'n': self._server_props()}]
        response = self.client.delete('/mcp-servers/srv-1')
        self.assertEqual(response.status_code, 204)

    def test_delete_not_found(self) -> None:
        """Deleting a missing server returns 404."""
        self.mock_db.execute.return_value = []
        response = self.client.delete('/mcp-servers/missing')
        self.assertEqual(response.status_code, 404)

    # -- Connection test -----------------------------------------------

    def test_test_saved_server_persists_result(self) -> None:
        """Testing a saved server records status/latency/tool count."""
        self.mock_db.match.return_value = [self._model()]
        self.mock_db.execute.return_value = [
            {'n': self._server_props(status='healthy')}
        ]
        result = ConnectionTestResult(
            ok=True,
            status='healthy',
            latency_ms=80,
            tools=['list_repos', 'get_repo'],
            error=None,
        )
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi.api.endpoints.mcp_servers.mcp_test.test_connection',
                new_callable=mock.AsyncMock,
                return_value=result,
            ) as tested,
        ):
            response = self.client.post('/mcp-servers/srv-1/test')
        self.assertEqual(response.status_code, 200)
        tested.assert_awaited_once()
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['status'], 'healthy')
        self.assertEqual(data['latency_ms'], 80)
        self.assertEqual(data['tools'], ['list_repos', 'get_repo'])
        self.assertEqual(data['tools_discovered'], 2)
        # The outcome was persisted onto the node.
        persisted = self.mock_db.execute.call_args.args[1]
        self.assertEqual(persisted['status'], 'healthy')
        self.assertEqual(persisted['tools_discovered'], 2)
        self.assertIsNotNone(persisted['last_tested_at'])

    def test_test_saved_server_failure_marks_unreachable(self) -> None:
        """A failed test persists an unreachable status and the error."""
        self.mock_db.match.return_value = [self._model()]
        self.mock_db.execute.return_value = [
            {'n': self._server_props(status='unreachable')}
        ]
        result = ConnectionTestResult(
            ok=False,
            status='unreachable',
            latency_ms=4001,
            tools=[],
            error='Timed out after 4s',
        )
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi.api.endpoints.mcp_servers.mcp_test.test_connection',
                new_callable=mock.AsyncMock,
                return_value=result,
            ),
        ):
            response = self.client.post('/mcp-servers/srv-1/test')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['ok'])
        self.assertEqual(data['error'], 'Timed out after 4s')
        persisted = self.mock_db.execute.call_args.args[1]
        self.assertEqual(persisted['status'], 'unreachable')
        self.assertEqual(persisted['last_error'], 'Timed out after 4s')

    def test_test_saved_server_not_found(self) -> None:
        """Testing a missing id returns 404."""
        self.mock_db.match.return_value = []
        response = self.client.post('/mcp-servers/missing/test')
        self.assertEqual(response.status_code, 404)

    def test_test_config_does_not_persist(self) -> None:
        """Testing an unsaved config returns a result without writing."""
        result = ConnectionTestResult(
            ok=True,
            status='healthy',
            latency_ms=42,
            tools=['search'],
            error=None,
        )
        with (
            mock.patch(
                'imbi.api.endpoints.mcp_servers.encrypt_config_value',
                side_effect=lambda v: None if v is None else f'enc:{v}',
            ),
            mock.patch(
                'imbi.api.endpoints.mcp_servers.mcp_test.test_connection',
                new_callable=mock.AsyncMock,
                return_value=result,
            ),
        ):
            response = self.client.post(
                '/mcp-servers/test',
                json={'url': 'https://mcp.example.com', 'auth_type': 'none'},
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['tools'], ['search'])
        self.mock_db.execute.assert_not_called()

    def test_test_config_invalid_returns_400(self) -> None:
        """An incomplete config (static, no secret) is rejected."""
        with mock.patch(
            'imbi.api.endpoints.mcp_servers.encrypt_config_value',
            side_effect=lambda v: None if v is None else f'enc:{v}',
        ):
            response = self.client.post(
                '/mcp-servers/test',
                json={
                    'url': 'https://mcp.example.com',
                    'auth_type': 'static',
                },
            )
        self.assertEqual(response.status_code, 400)

    # -- Status report -------------------------------------------------

    def test_report_status_persists(self) -> None:
        """A runtime status report updates status and last_error."""
        self.mock_db.match.return_value = [self._model()]
        self.mock_db.execute.return_value = [
            {'n': self._server_props(status='degraded')}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/mcp-servers/srv-1/status',
                json={'status': 'degraded', 'error': 'tool call failed'},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'degraded')
        persisted = self.mock_db.execute.call_args.args[1]
        self.assertEqual(persisted['status'], 'degraded')
        self.assertEqual(persisted['last_error'], 'tool call failed')
        self.assertIsNotNone(persisted['last_tested_at'])

    def test_report_status_not_found(self) -> None:
        """Reporting status for a missing id returns 404."""
        self.mock_db.match.return_value = []
        response = self.client.post(
            '/mcp-servers/missing/status', json={'status': 'healthy'}
        )
        self.assertEqual(response.status_code, 404)


class MCPServerPermissionTestCase(support.SharedAppTestCase):
    """Non-admin permission enforcement for MCP server endpoints."""

    def setUp(self) -> None:
        """Set up the app with a non-admin, unprivileged principal."""

        self.user = models.User(
            email='user@example.com',
            display_name='Plain User',
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
            permissions=set(),
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )
        self.client = TestClient(self.test_app)

    def test_list_denied(self) -> None:
        """Reading without mcp_server:read is forbidden."""
        response = self.client.get('/mcp-servers/')
        self.assertEqual(response.status_code, 403)

    def test_create_denied(self) -> None:
        """Creating without mcp_server:create is forbidden."""
        response = self.client.post(
            '/mcp-servers/',
            json={
                'name': 'Example',
                'slug': 'example',
                'url': 'https://mcp.example.com',
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_delete_denied(self) -> None:
        """Deleting without mcp_server:delete is forbidden."""
        response = self.client.delete('/mcp-servers/srv-1')
        self.assertEqual(response.status_code, 403)

    def test_read_allowed_with_permission(self) -> None:
        """Granting mcp_server:read permits listing."""
        self.auth_context.permissions = {'mcp_server:read'}
        self.mock_db.match.return_value = []
        response = self.client.get('/mcp-servers/')
        self.assertEqual(response.status_code, 200)

    def test_test_config_denied(self) -> None:
        """Testing an unsaved config without mcp_server:create is forbidden."""
        response = self.client.post(
            '/mcp-servers/test',
            json={'url': 'https://mcp.example.com', 'auth_type': 'none'},
        )
        self.assertEqual(response.status_code, 403)

    def test_test_denied(self) -> None:
        """Testing without mcp_server:update is forbidden."""
        response = self.client.post('/mcp-servers/srv-1/test')
        self.assertEqual(response.status_code, 403)

    def test_status_report_denied(self) -> None:
        """Reporting status without mcp_server:update is forbidden."""
        response = self.client.post(
            '/mcp-servers/srv-1/status', json={'status': 'healthy'}
        )
        self.assertEqual(response.status_code, 403)
