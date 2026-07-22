"""Tests for the global maintenance endpoints."""

import datetime
from unittest import mock

from fastapi import testclient

from imbi.api import models, scoring
from imbi.api.auth import permissions
from imbi.api.maintenance import OPERATIONS, state
from imbi.common import graph
from tests.api import support


class MaintenanceEndpointTestCase(support.SharedAppTestCase):
    def setUp(self) -> None:
        self.auth_context = permissions.AuthContext(
            user=models.User(
                email='admin@example.com',
                display_name='Admin User',
                is_active=True,
                is_admin=True,
                created_at=datetime.datetime.now(datetime.UTC),
            ),
            session_id='test-session',
            auth_method='jwt',
            permissions={
                'admin:maintenance:read',
                'admin:maintenance:manage',
            },
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.mock_db.execute.return_value = []
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )
        self.mock_valkey = mock.AsyncMock()
        self.test_app.dependency_overrides[scoring._inject_optional_client] = (
            lambda: self.mock_valkey
        )

    def _use_non_admin(self) -> None:
        self.auth_context = permissions.AuthContext(
            user=models.User(
                email='user@example.com',
                display_name='Plain User',
                is_active=True,
                is_admin=False,
                created_at=datetime.datetime.now(datetime.UTC),
            ),
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

    def test_list_operations(self) -> None:
        with mock.patch.object(
            state,
            'read_status',
            mock.AsyncMock(return_value=state.RunStatus()),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get('/maintenance/operations')
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(
            sorted(OPERATIONS), sorted(op['slug'] for op in payload)
        )
        for op in payload:
            self.assertEqual('idle', op['state'])
            self.assertFalse(op['running'])
            self.assertIsNone(op['progress'])
            self.assertTrue(op['label'])
            self.assertTrue(op['description'])

    def test_list_operations_unavailable_without_valkey(self) -> None:
        self.test_app.dependency_overrides[scoring._inject_optional_client] = (
            lambda: None
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.get('/maintenance/operations')
        self.assertEqual(503, response.status_code)

    def test_get_operation_unavailable_without_valkey(self) -> None:
        self.test_app.dependency_overrides[scoring._inject_optional_client] = (
            lambda: None
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.get('/maintenance/operations/rescore')
        self.assertEqual(503, response.status_code)

    def test_list_operations_requires_permission(self) -> None:
        self._use_non_admin()
        with testclient.TestClient(self.test_app) as client:
            response = client.get('/maintenance/operations')
        self.assertEqual(403, response.status_code)

    def test_get_operation_includes_failures(self) -> None:
        status = state.RunStatus(
            state='completed',
            run_id='r1',
            total=3,
            succeeded=2,
            failed=1,
        )
        with (
            mock.patch.object(
                state, 'read_status', mock.AsyncMock(return_value=status)
            ),
            mock.patch.object(
                state,
                'read_failures',
                mock.AsyncMock(return_value={'p1': 'boom'}),
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get('/maintenance/operations/rescore')
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual('completed', payload['state'])
        self.assertEqual({'p1': 'boom'}, payload['failures'])
        self.assertEqual(1, payload['progress']['failed'])

    def test_get_operation_unknown_slug(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.get('/maintenance/operations/nope')
        self.assertEqual(404, response.status_code)

    def test_run_starts_operation(self) -> None:
        started = state.RunStatus(
            state='running', run_id='r1', total=2, remaining=2
        )
        with mock.patch.object(
            state, 'start_run', mock.AsyncMock(return_value=started)
        ) as start:
            with testclient.TestClient(self.test_app) as client:
                response = client.post('/maintenance/operations/rescore/run')
        self.assertEqual(202, response.status_code)
        self.assertEqual({'run_id': 'r1', 'total': 2}, response.json())
        self.assertEqual('admin@example.com', start.await_args.args[3])

    def test_run_conflicts_when_already_running(self) -> None:
        with mock.patch.object(
            state, 'start_run', mock.AsyncMock(return_value=None)
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.post('/maintenance/operations/rescore/run')
        self.assertEqual(409, response.status_code)

    def test_run_unavailable_without_valkey(self) -> None:
        self.test_app.dependency_overrides[scoring._inject_optional_client] = (
            lambda: None
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post('/maintenance/operations/rescore/run')
        self.assertEqual(503, response.status_code)

    def test_run_requires_manage_permission(self) -> None:
        self._use_non_admin()
        with testclient.TestClient(self.test_app) as client:
            response = client.post('/maintenance/operations/rescore/run')
        self.assertEqual(403, response.status_code)

    def test_cancel_running_operation(self) -> None:
        cancelled = state.RunStatus(state='cancelled', run_id='r1', total=2)
        with (
            mock.patch.object(
                state, 'cancel_run', mock.AsyncMock(return_value=True)
            ),
            mock.patch.object(
                state,
                'read_status',
                mock.AsyncMock(return_value=cancelled),
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.post(
                    '/maintenance/operations/rescore/cancel'
                )
        self.assertEqual(200, response.status_code)
        self.assertEqual('cancelled', response.json()['state'])

    def test_cancel_conflicts_when_idle(self) -> None:
        with mock.patch.object(
            state, 'cancel_run', mock.AsyncMock(return_value=False)
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.post(
                    '/maintenance/operations/rescore/cancel'
                )
        self.assertEqual(409, response.status_code)
