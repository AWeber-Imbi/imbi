"""Tests for the admin dashboard status endpoint."""

import datetime
from unittest import mock

import httpx
from fastapi import testclient

from imbi.api import models, settings
from imbi.api.auth import password, permissions
from imbi.api.endpoints import dashboard
from imbi.common import graph
from tests.api import support


def _ok_status_handler(request: httpx.Request) -> httpx.Response:
    """MockTransport handler: every /status answers ok with a version."""
    if request.url.path == '/status':
        return httpx.Response(
            200,
            json={'service': 'svc', 'status': 'ok', 'version': '2.8.0'},
        )
    return httpx.Response(404)


_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _patch_async_client(handler) -> mock._patch:
    """Patch the module's httpx.AsyncClient to use a MockTransport."""
    return mock.patch.object(
        dashboard.httpx,
        'AsyncClient',
        lambda *a, **k: _REAL_ASYNC_CLIENT(
            transport=httpx.MockTransport(handler)
        ),
    )


class DashboardStatusEndpointTestCase(support.SharedAppTestCase):
    """Test cases for GET /admin/dashboard/status."""

    def setUp(self) -> None:
        self.test_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,
            password_hash=password.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.admin_context = permissions.AuthContext(
            user=self.test_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user():
            return self.admin_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.mock_db.execute.return_value = [{'n': 1}]
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)

        # Datastore client patches.
        self.clickhouse_patch = mock.patch.object(
            dashboard.clickhouse,
            'query',
            new=mock.AsyncMock(return_value=[{'size': 2048}]),
        )
        valkey_client = mock.AsyncMock()
        valkey_client.info = mock.AsyncMock(
            return_value={'redis_version': '7', 'used_memory': 1024}
        )
        self.valkey_patch = mock.patch.object(
            dashboard.valkey, 'get_client', return_value=valkey_client
        )
        # Postgres size reads the psycopg pool directly; patch the helper
        # rather than mock the async connection/cursor protocol.
        self.pg_size_patch = mock.patch.object(
            dashboard, '_postgres_size', mock.AsyncMock(return_value=4096)
        )
        # All four sibling services configured.
        self.services_patch = mock.patch.object(
            dashboard.settings,
            'get_internal_services',
            return_value=settings.InternalServices(
                assistant_url='http://assistant:8002',
                gateway_url='http://gateway:8003',
                mcp_url='http://mcp:8001',
                slackbot_url='http://slackbot:8004',
            ),
        )
        self.clickhouse_patch.start()
        self.valkey_patch.start()
        self.services_patch.start()
        self.pg_size_patch.start()
        self.addCleanup(self.clickhouse_patch.stop)
        self.addCleanup(self.valkey_patch.stop)
        self.addCleanup(self.services_patch.stop)
        self.addCleanup(self.pg_size_patch.stop)

    def test_all_healthy(self) -> None:
        """Every datastore ok and every service up."""
        with _patch_async_client(_ok_status_handler):
            response = self.client.get('/admin/dashboard/status')
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertIn('checked_at', body)

        datastores = {d['name']: d for d in body['datastores']}
        self.assertEqual(
            {'PostgreSQL', 'ClickHouse', 'Valkey'}, set(datastores)
        )
        for entry in datastores.values():
            self.assertEqual('ok', entry['status'])
            self.assertIsNotNone(entry['latency_ms'])
        # Size on disk (or resident memory for Valkey) is surfaced.
        self.assertEqual(4096, datastores['PostgreSQL']['size_bytes'])
        self.assertEqual(2048, datastores['ClickHouse']['size_bytes'])
        self.assertEqual(1024, datastores['Valkey']['size_bytes'])

        services = {s['name']: s for s in body['services']}
        self.assertEqual(
            {'API', 'Assistant', 'Gateway', 'MCP', 'Slackbot'}, set(services)
        )
        for entry in services.values():
            self.assertEqual('up', entry['status'])
        # API reports its own version without an HTTP hop.
        self.assertEqual(0.0, services['API']['latency_ms'])
        self.assertEqual('2.8.0', services['Assistant']['version'])

    def test_datastore_error_reported(self) -> None:
        """A failing datastore check returns status=error, not a 500."""
        self.mock_db.execute.side_effect = RuntimeError('pool closed')
        with _patch_async_client(_ok_status_handler):
            response = self.client.get('/admin/dashboard/status')
        self.assertEqual(200, response.status_code)
        datastores = {d['name']: d for d in response.json()['datastores']}
        self.assertEqual('error', datastores['PostgreSQL']['status'])
        self.assertEqual('pool closed', datastores['PostgreSQL']['detail'])
        self.assertEqual('ok', datastores['ClickHouse']['status'])

    def test_service_down_reported(self) -> None:
        """A non-200 from a service marks it down without failing others."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == 'gateway':
                return httpx.Response(503)
            return _ok_status_handler(request)

        with _patch_async_client(handler):
            response = self.client.get('/admin/dashboard/status')
        self.assertEqual(200, response.status_code)
        services = {s['name']: s for s in response.json()['services']}
        self.assertEqual('down', services['Gateway']['status'])
        self.assertEqual('up', services['Assistant']['status'])

    def test_unconfigured_service_marked_down(self) -> None:
        """An empty internal URL marks the service down as not configured."""
        self.services_patch.stop()
        with mock.patch.object(
            dashboard.settings,
            'get_internal_services',
            return_value=settings.InternalServices(
                assistant_url='http://assistant:8002',
            ),
        ):
            with _patch_async_client(_ok_status_handler):
                response = self.client.get('/admin/dashboard/status')
        services = {s['name']: s for s in response.json()['services']}
        self.assertEqual('down', services['Slackbot']['status'])
        self.assertEqual('not configured', services['Slackbot']['detail'])

    def test_requires_permission(self) -> None:
        """A non-admin without admin:dashboard:read is forbidden."""
        self.admin_context.user.is_admin = False
        self.admin_context.permissions = set()
        with _patch_async_client(_ok_status_handler):
            response = self.client.get('/admin/dashboard/status')
        self.assertEqual(403, response.status_code)


class DashboardMetricsEndpointTestCase(support.SharedAppTestCase):
    """Test cases for GET /admin/dashboard/metrics."""

    def setUp(self) -> None:
        self.test_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,
            password_hash=password.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.admin_context = permissions.AuthContext(
            user=self.test_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user():
            return self.admin_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.client = testclient.TestClient(self.test_app)

    def test_metrics_aggregates_and_aligns_daily(self) -> None:
        today = datetime.datetime.now(datetime.UTC).date().isoformat()
        # gather() evaluates args in order: deploys, events, ops, prs. The
        # deploys scan carries both the day series and the env rollup.
        query = mock.AsyncMock(
            side_effect=[
                [
                    {'day': today, 'slug': 'production', 'c': 4},
                    {'day': today, 'slug': 'staging', 'c': 1},
                ],
                [{'day': today, 'c': 5}],
                [{'day': today, 'c': 8}],
                [{'day': today, 'c': 2}],
            ]
        )
        with mock.patch.object(dashboard.clickhouse, 'query', query):
            response = self.client.get('/admin/dashboard/metrics')
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual(5, body['releases']['total'])
        self.assertEqual(5, body['events']['total'])
        self.assertEqual(8, body['ops_log']['total'])
        self.assertEqual(2, body['pull_requests']['total'])
        # Seven daily buckets, today (last) carrying the summed value.
        self.assertEqual(7, len(body['releases']['daily']))
        self.assertEqual(5, body['releases']['daily'][-1])
        self.assertEqual(0, body['releases']['daily'][0])
        # Environments derived from the same scan, sorted by count desc.
        self.assertEqual(
            [
                {'slug': 'production', 'count': 4},
                {'slug': 'staging', 'count': 1},
            ],
            body['releases_by_environment'],
        )

    def test_metrics_empty(self) -> None:
        query = mock.AsyncMock(side_effect=[[], [], [], []])
        with mock.patch.object(dashboard.clickhouse, 'query', query):
            response = self.client.get('/admin/dashboard/metrics')
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual(0, body['events']['total'])
        self.assertEqual([0] * 7, body['ops_log']['daily'])
        self.assertEqual([], body['releases_by_environment'])

    def test_metrics_requires_permission(self) -> None:
        self.admin_context.user.is_admin = False
        self.admin_context.permissions = set()
        response = self.client.get('/admin/dashboard/metrics')
        self.assertEqual(403, response.status_code)
