"""Tests for the admin graph query endpoints."""

import datetime
import json
import unittest
from unittest import mock

import psycopg
from fastapi import testclient
from imbi_common import graph

from imbi_api import app, models
from imbi_api.auth import password, permissions


def _build_user(*, is_admin: bool) -> models.User:
    return models.User(
        email=('admin' if is_admin else 'user') + '@example.com',
        display_name='Admin' if is_admin else 'User',
        is_active=True,
        is_admin=is_admin,
        password_hash=password.hash_password('testpassword123'),
        created_at=datetime.datetime.now(datetime.UTC),
    )


class GraphQueryEndpointTestCase(unittest.TestCase):
    """Tests for ``POST /admin/graph/query``."""

    def setUp(self) -> None:
        self.test_app = app.create_app()
        self.auth_context = permissions.AuthContext(
            user=_build_user(is_admin=True),
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
        # Schema endpoint accesses ``db.settings.graph_name`` and
        # ``db.pool``; tests touching the schema endpoint configure
        # these via mocks of their own.
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )
        self.client = testclient.TestClient(self.test_app)

    def _set_non_admin(self) -> None:
        self.auth_context = permissions.AuthContext(
            user=_build_user(is_admin=False),
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

    def test_admin_query_success_with_vertex(self) -> None:
        """Admin POST returns 200 with shaped rows, nodes, and edges."""
        vertex = (
            json.dumps(
                {
                    'id': 844424930131969,
                    'label': 'User',
                    'properties': {'email': 'admin@example.com'},
                }
            )
            + '::vertex'
        )
        self.mock_db.execute.return_value = [{'u': vertex}]

        response = self.client.post(
            '/admin/graph/query',
            json={'query': 'MATCH (u:User) RETURN u LIMIT 1'},
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['columns'], ['u'])
        self.assertEqual(len(data['rows']), 1)
        self.assertEqual(data['rows'][0]['u']['_kind'], 'node')
        self.assertEqual(data['rows'][0]['u']['labels'], ['User'])
        self.assertEqual(
            data['rows'][0]['u']['properties']['email'],
            'admin@example.com',
        )
        self.assertEqual(len(data['nodes']), 1)
        self.assertEqual(data['nodes'][0]['labels'], ['User'])
        self.assertEqual(data['edges'], [])
        self.assertIn('elapsed_ms', data)
        self.assertIsInstance(data['elapsed_ms'], (int, float))

    def test_admin_query_dedupes_nodes_and_edges(self) -> None:
        """Same vertex/edge appearing twice across rows is deduped."""
        vertex_a = (
            json.dumps(
                {
                    'id': 1,
                    'label': 'User',
                    'properties': {'email': 'a@example.com'},
                }
            )
            + '::vertex'
        )
        vertex_b = (
            json.dumps(
                {
                    'id': 2,
                    'label': 'User',
                    'properties': {'email': 'b@example.com'},
                }
            )
            + '::vertex'
        )
        edge = (
            json.dumps(
                {
                    'id': 10,
                    'label': 'KNOWS',
                    'start_id': 1,
                    'end_id': 2,
                    'properties': {},
                }
            )
            + '::edge'
        )
        self.mock_db.execute.return_value = [
            {'a': vertex_a, 'r': edge, 'b': vertex_b},
            {'a': vertex_a, 'r': edge, 'b': vertex_b},
        ]

        response = self.client.post(
            '/admin/graph/query',
            json={
                'query': ('MATCH (a:User)-[r:KNOWS]->(b:User) RETURN a, r, b')
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['columns'], ['a', 'r', 'b'])
        self.assertEqual(len(data['rows']), 2)
        self.assertEqual(len(data['nodes']), 2)
        self.assertEqual(len(data['edges']), 1)
        self.assertEqual(data['edges'][0]['type'], 'KNOWS')
        self.assertEqual(data['edges'][0]['start'], '1')
        self.assertEqual(data['edges'][0]['end'], '2')

    def test_admin_query_scalar_columns(self) -> None:
        """Non-vertex scalar columns are returned as-is."""
        self.mock_db.execute.return_value = [{'cnt': 5}]

        response = self.client.post(
            '/admin/graph/query',
            json={'query': 'MATCH (n) RETURN count(n) AS cnt'},
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['columns'], ['cnt'])
        self.assertEqual(data['rows'], [{'cnt': 5}])
        self.assertEqual(data['nodes'], [])
        self.assertEqual(data['edges'], [])

    def test_non_admin_query_forbidden(self) -> None:
        """Non-admin POST returns 403 without invoking the graph."""
        self._set_non_admin()

        response = self.client.post(
            '/admin/graph/query',
            json={'query': 'MATCH (n) RETURN n'},
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn('Admin', response.json()['detail'])
        self.mock_db.execute.assert_not_awaited()

    def test_empty_query_rejected(self) -> None:
        """Whitespace-only query returns 400 with the empty-query error."""
        response = self.client.post(
            '/admin/graph/query',
            json={'query': '   '},
        )

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertIn('error', body['detail'])
        self.assertIn('empty', body['detail']['error']['message'].lower())
        self.mock_db.execute.assert_not_awaited()

    def test_query_without_return_rejected(self) -> None:
        """A query missing a RETURN clause is rejected with 400."""
        response = self.client.post(
            '/admin/graph/query',
            json={'query': 'MATCH (n)'},
        )

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertIn('RETURN', body['detail']['error']['message'])
        self.mock_db.execute.assert_not_awaited()

    def test_malformed_query_translates_psycopg_error(self) -> None:
        """A psycopg syntax error becomes a 400 with structured detail."""

        class FakeDiag:
            message_primary = 'syntax error at or near "RETUR"'
            sqlstate = '42601'
            statement_position = '14'
            message_hint = None

        # ``psycopg.Error`` defines ``diag`` as a libpq-backed property
        # with no setter. A plain attribute on a stand-in subclass
        # would be shadowed by the descriptor, so we override the
        # class attribute for the lifetime of this test.
        class FakeSyntaxError(psycopg.Error):
            diag = FakeDiag()  # type: ignore[assignment]

        self.mock_db.execute.side_effect = FakeSyntaxError(
            'syntax error at or near "RETUR"',
        )

        response = self.client.post(
            '/admin/graph/query',
            # Passes our RETURN-clause check; the simulated server-side
            # syntax error is what we exercise here.
            json={'query': 'MATCH (n) WHEER true RETURN n'},
        )

        self.assertEqual(response.status_code, 400, response.text)
        body = response.json()
        err = body['detail']['error']
        self.assertEqual(err['code'], '42601', response.text)
        self.assertIn('syntax error', err['message'])
        # statement_position is exposed as ``column``.
        self.assertEqual(err['column'], 14)

    def test_query_with_params_passes_through(self) -> None:
        """The request's ``params`` are forwarded to ``db.execute``."""
        self.mock_db.execute.return_value = []

        response = self.client.post(
            '/admin/graph/query',
            json={
                'query': 'MATCH (u:User {email: {email}}) RETURN u',
                'params': {'email': 'admin@example.com'},
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.mock_db.execute.assert_awaited_once()
        call = self.mock_db.execute.await_args
        assert call is not None
        self.assertEqual(call.args[1], {'email': 'admin@example.com'})


class GraphSchemaEndpointTestCase(unittest.TestCase):
    """Tests for ``GET /admin/graph/schema``."""

    def setUp(self) -> None:
        self.test_app = app.create_app()
        self.auth_context = permissions.AuthContext(
            user=_build_user(is_admin=True),
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db = mock.MagicMock(spec=graph.Graph)
        self.mock_db.settings = mock.MagicMock()
        self.mock_db.settings.graph_name = 'imbi'
        self.mock_db.execute = mock.AsyncMock()

        # Build an async-context-manager chain for db.pool.connection()
        # → conn.cursor() → cursor.fetchall()
        self.mock_cursor = mock.AsyncMock()
        self.mock_cursor.fetchall.return_value = [
            ('User', 'v', 42),
            ('Project', 'v', 17),
            ('KNOWS', 'e', 100),
        ]

        cursor_ctx = mock.MagicMock()
        cursor_ctx.__aenter__ = mock.AsyncMock(return_value=self.mock_cursor)
        cursor_ctx.__aexit__ = mock.AsyncMock(return_value=None)

        mock_conn = mock.MagicMock()
        mock_conn.cursor = mock.MagicMock(return_value=cursor_ctx)

        conn_ctx = mock.MagicMock()
        conn_ctx.__aenter__ = mock.AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = mock.AsyncMock(return_value=None)

        self.mock_db.pool = mock.MagicMock()
        self.mock_db.pool.connection = mock.MagicMock(return_value=conn_ctx)

        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )
        self.client = testclient.TestClient(self.test_app)

    def _set_non_admin(self) -> None:
        self.auth_context = permissions.AuthContext(
            user=_build_user(is_admin=False),
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

    def test_schema_admin_returns_labels(self) -> None:
        """Schema endpoint groups results into nodes/edges/keys."""
        self.mock_db.execute.return_value = [
            {'keys': '["id", "email", "displayName"]'},
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: json.loads(x) if isinstance(x, str) else x,
        ):
            response = self.client.get('/admin/graph/schema')

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        labels = {lc['label']: lc['count'] for lc in data['node_labels']}
        self.assertEqual(labels, {'User': 42, 'Project': 17})
        types = {et['type']: et['count'] for et in data['edge_types']}
        self.assertEqual(types, {'KNOWS': 100})
        self.assertEqual(
            data['property_keys'],
            ['displayName', 'email', 'id'],
        )

    def test_schema_property_key_failure_is_soft(self) -> None:
        """A failure sampling property keys yields an empty list."""

        class FakeOpError(psycopg.Error):
            pass

        self.mock_db.execute.side_effect = FakeOpError('boom')

        response = self.client.get('/admin/graph/schema')

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['property_keys'], [])
        self.assertTrue(data['node_labels'])

    def test_schema_non_admin_forbidden(self) -> None:
        """Non-admin GET returns 403 without touching the graph."""
        self._set_non_admin()

        response = self.client.get('/admin/graph/schema')

        self.assertEqual(response.status_code, 403)
        self.mock_db.pool.connection.assert_not_called()
        self.mock_db.execute.assert_not_awaited()
