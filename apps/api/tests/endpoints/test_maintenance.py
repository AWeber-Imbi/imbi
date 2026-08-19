"""Tests for the global maintenance endpoints."""

import datetime
from unittest import mock

from fastapi import testclient

from apps.api.tests import support
from imbi.api import models, scoring
from imbi.api.auth import permissions
from imbi.api.endpoints import _pagination, maintenance
from imbi.api.maintenance import OPERATIONS, state
from imbi.common import graph


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


def _log_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        'id': 'row1',
        'occurred_at': datetime.datetime(
            2026, 8, 19, 12, 0, tzinfo=datetime.UTC
        ),
        'run_id': 'run1',
        'attempt_id': 'attempt1',
        'item_id': 'p1',
        'slug': 'release-repair',
        'event_type': 'attempt',
        'disposition': 'failed',
        'action': '',
        'project_id': 'p1',
        'project_slug': 'proj',
        'message': 'boom',
        'detail': {'count': 2},
        'duration_ms': 17,
        'started_by': 'admin',
    }
    row.update(overrides)
    return row


class MaintenanceLogEndpointTests(MaintenanceEndpointTestCase):
    """The activity log read endpoint."""

    def _get(
        self, url: str, rows: list[dict[str, object]] | None = None
    ) -> tuple[object, mock.AsyncMock]:
        counts = {
            'succeeded': 3,
            'skipped': 1,
            'failed': 2,
            'deferred': 0,
        }
        query = mock.AsyncMock(
            side_effect=[rows if rows is not None else [], [counts]]
        )
        with mock.patch.object(maintenance.clickhouse, 'query', query):
            with testclient.TestClient(self.test_app) as client:
                return client.get(url), query

    def test_defaults_to_attempt_rows(self) -> None:
        response, query = self._get('/maintenance/log', [_log_row()])
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual(1, len(body['data']))
        entry = body['data'][0]
        self.assertEqual('release-repair', entry['slug'])
        self.assertEqual('failed', entry['disposition'])
        self.assertEqual({'count': 2}, entry['detail'])
        self.assertTrue(entry['occurred_at'].endswith('Z'))
        sql, params = query.await_args_list[0].args
        self.assertIn('event_type = {event_type:String}', sql)
        self.assertEqual('attempt', params['event_type'])

    def test_counts_ignore_the_disposition_filter(self) -> None:
        response, query = self._get(
            '/maintenance/log?disposition=failed', [_log_row()]
        )
        self.assertEqual(2, response.json()['counts']['failed'])
        page_sql, page_params = query.await_args_list[0].args
        self.assertIn('disposition IN', page_sql)
        self.assertEqual(['failed'], page_params['dispositions'])
        count_sql, count_params = query.await_args_list[1].args
        self.assertNotIn('disposition IN', count_sql)
        self.assertIn("event_type = 'attempt'", count_sql)
        self.assertNotIn('dispositions', count_params)

    def test_filters_are_bound_parameters(self) -> None:
        _, query = self._get(
            '/maintenance/log?slug=run-analysis&project_id=p9&run_id=r9'
        )
        _, params = query.await_args_list[0].args
        self.assertEqual('run-analysis', params['slug'])
        self.assertEqual('p9', params['project_id'])
        self.assertEqual('r9', params['run_id'])

    def test_expanding_an_attempt_reads_its_activity(self) -> None:
        _, query = self._get(
            '/maintenance/log?event_type=activity&attempt_id=a1'
        )
        _, params = query.await_args_list[0].args
        self.assertEqual('activity', params['event_type'])
        self.assertEqual('a1', params['attempt_id'])

    def test_a_full_page_offers_a_next_link(self) -> None:
        rows = [_log_row(id=f'row{i}') for i in range(3)]
        query = mock.AsyncMock(side_effect=[rows, []])
        with mock.patch.object(maintenance.clickhouse, 'query', query):
            with testclient.TestClient(self.test_app) as client:
                response = client.get('/maintenance/log?limit=2')
        self.assertEqual(2, len(response.json()['data']))
        self.assertIn('rel="next"', response.headers['Link'])

    def test_a_partial_page_has_no_next_link(self) -> None:
        response, _ = self._get('/maintenance/log?limit=50', [_log_row()])
        self.assertNotIn('rel="next"', response.headers['Link'])

    def test_a_later_page_skips_the_counts(self) -> None:
        cursor = _pagination.encode_cursor(
            datetime.datetime(2026, 8, 19, tzinfo=datetime.UTC), 'row9'
        )
        query = mock.AsyncMock(return_value=[])
        with mock.patch.object(maintenance.clickhouse, 'query', query):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(f'/maintenance/log?cursor={cursor}')
        self.assertIsNone(response.json()['counts'])
        self.assertEqual(1, query.await_count)
        _, params = query.await_args.args
        self.assertEqual('row9', params['cursor_id'])

    def test_a_bad_cursor_is_rejected(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.get('/maintenance/log?cursor=not-a-cursor')
        self.assertEqual(400, response.status_code)

    def test_limit_is_bounded(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.get('/maintenance/log?limit=5000')
        self.assertEqual(400, response.status_code)

    def test_clickhouse_down_is_a_503(self) -> None:
        query = mock.AsyncMock(
            side_effect=maintenance.clickhouse.client.DatabaseError('down')
        )
        with mock.patch.object(maintenance.clickhouse, 'query', query):
            with testclient.TestClient(self.test_app) as client:
                response = client.get('/maintenance/log')
        self.assertEqual(503, response.status_code)

    def test_reading_requires_the_permission(self) -> None:
        self._use_non_admin()
        with testclient.TestClient(self.test_app) as client:
            response = client.get('/maintenance/log')
        self.assertEqual(403, response.status_code)
