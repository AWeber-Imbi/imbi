"""Tests for operations log endpoints."""

import datetime
import typing
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common import clickhouse as imbi_clickhouse

from imbi_api import app
from imbi_api import models as api_models
from imbi_api.auth import permissions as api_permissions
from imbi_api.endpoints import operations_log

ALL_OPSLOG_PERMS: set[str] = {
    'operations_log:create',
    'operations_log:read',
    'operations_log:update',
    'operations_log:delete',
}


def _sample_row(**overrides: typing.Any) -> dict[str, typing.Any]:
    """Return a dict matching the ClickHouse row shape for an opslog entry."""
    base: dict[str, typing.Any] = {
        'id': 'entry-abc',
        'occurred_at': datetime.datetime(
            2026, 4, 17, 14, 22, 31, 412000, tzinfo=datetime.UTC
        ),
        'recorded_at': datetime.datetime(
            2026, 4, 17, 14, 22, 33, 1000, tzinfo=datetime.UTC
        ),
        'recorded_by': 'alice@example.com',
        'performed_by': 'alice@example.com',
        'completed_at': None,
        'project_id': 'proj-xyz',
        'project_slug': 'imbi-api',
        'environment_slug': 'production',
        'entry_type': 'Deployed',
        'description': 'Rolled out v2.4.0',
        'link': None,
        'notes': None,
        'ticket_slug': None,
        'version': '2.4.0',
        '_row_version': 1,
        'is_deleted': 0,
    }
    base.update(overrides)
    return base


class _OpsLogTestBase(unittest.TestCase):
    """Shared setup for operations-log endpoint tests."""

    permissions_granted: set[str] = ALL_OPSLOG_PERMS

    def setUp(self) -> None:
        self.test_app = app.create_app()
        self.admin = api_models.User(
            email='alice@example.com',
            display_name='Alice',
            password_hash='$argon2id$hash',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = api_permissions.AuthContext(
            user=self.admin,
            session_id='test-session',
            auth_method='jwt',
            permissions=self.permissions_granted,
        )

        async def _current_user() -> api_permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[
            api_permissions.get_current_user
        ] = _current_user

        self.client = testclient.TestClient(self.test_app)
        self.addCleanup(self.client.close)

        # Patch ClickHouse:
        #   * query() is the module-level wrapper used for reads; returns
        #     list[dict].
        #   * insert is the class method Clickhouse.insert called directly
        #     with explicit column names/values (the module-level wrapper
        #     only accepts pydantic models and strips the alias).
        self.insert_patcher = mock.patch.object(
            imbi_clickhouse.client.Clickhouse,
            'insert',
            new_callable=mock.AsyncMock,
        )
        self.query_patcher = mock.patch(
            'imbi_common.clickhouse.query',
            new_callable=mock.AsyncMock,
        )
        self.mock_insert = self.insert_patcher.start()
        self.mock_query = self.query_patcher.start()
        self.addCleanup(self.insert_patcher.stop)
        self.addCleanup(self.query_patcher.stop)

    def _stub_list(
        self,
        rows: list[dict[str, typing.Any]],
        *,
        with_metrics: bool = True,
    ) -> None:
        """Wire `mock_query` for a list-endpoint call.

        The list handler issues 3 ClickHouse queries on the first page
        (list + totals + per-env deploys) and just 1 on paginated pages.
        """
        empty_totals = [
            {
                'event_count': 0,
                'deploys': 0,
                'projects': 0,
                'environments': 0,
                'team_members': 0,
            }
        ]
        self.mock_query.side_effect = (
            [rows, empty_totals, []] if with_metrics else [rows]
        )

    def _revoke_permissions(self) -> None:
        """Swap the auth context to a non-admin user with no permissions.

        Admin users bypass ``require_permission``, so tests that exercise
        403 responses need a regular user. The existing ``_current_user``
        override closes over ``self`` and picks up the new context on
        its next call.
        """
        self.auth_context = api_permissions.AuthContext(
            user=api_models.User(
                email='bob@example.com',
                display_name='Bob',
                password_hash='$argon2id$hash',
                is_active=True,
                is_admin=False,
                is_service_account=False,
                created_at=datetime.datetime.now(datetime.UTC),
            ),
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )


class CursorCodecTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        ts = datetime.datetime(
            2026, 4, 17, 14, 22, 31, 412000, tzinfo=datetime.UTC
        )
        entry_id = 'V1StGXR8_Z5jdHi6B-myT'
        encoded = operations_log._encode_cursor(ts, entry_id)
        self.assertIsInstance(encoded, str)
        decoded = operations_log._decode_cursor(encoded)
        self.assertIsNotNone(decoded)
        assert decoded is not None
        decoded_ts, decoded_id = decoded
        self.assertEqual(decoded_ts, ts)
        self.assertEqual(decoded_id, entry_id)

    def test_decode_malformed_returns_none(self) -> None:
        self.assertIsNone(operations_log._decode_cursor('!!!not-base64!!!'))

    def test_decode_wrong_format_returns_none(self) -> None:
        import base64

        payload = base64.urlsafe_b64encode(b'missing-separator').decode()
        self.assertIsNone(operations_log._decode_cursor(payload))

    def test_decode_empty_string_returns_none(self) -> None:
        self.assertIsNone(operations_log._decode_cursor(''))


class PostOperationLogTests(_OpsLogTestBase):
    def _valid_body(self) -> dict[str, typing.Any]:
        return {
            'project_id': 'proj-xyz',
            'project_slug': 'imbi-api',
            'environment_slug': 'production',
            'entry_type': 'Deployed',
            'description': 'Rolled out v2.4.0',
        }

    def test_create_minimum_body_returns_201(self) -> None:
        response = self.client.post(
            '/operations-log/', json=self._valid_body()
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['entry_type'], 'Deployed')
        self.assertEqual(body['project_slug'], 'imbi-api')
        # Server-stamped fields
        self.assertIsNotNone(body['id'])
        self.assertIsNotNone(body['recorded_at'])
        self.assertEqual(body['recorded_by'], 'alice@example.com')
        self.assertEqual(body['performed_by'], 'alice@example.com')
        # Internal fields excluded
        self.assertNotIn('_row_version', body)
        self.assertNotIn('row_version', body)
        self.assertNotIn('is_deleted', body)
        self.mock_insert.assert_awaited_once()

    def test_create_with_explicit_performed_by(self) -> None:
        body = self._valid_body() | {'performed_by': 'ci-bot'}
        response = self.client.post('/operations-log/', json=body)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['performed_by'], 'ci-bot')

    def test_create_validation_error(self) -> None:
        body = self._valid_body()
        del body['entry_type']
        response = self.client.post('/operations-log/', json=body)
        self.assertEqual(response.status_code, 400)

    def test_create_forbidden_without_permission(self) -> None:
        self._revoke_permissions()
        response = self.client.post(
            '/operations-log/', json=self._valid_body()
        )
        self.assertEqual(response.status_code, 403)
        self.mock_insert.assert_not_awaited()


class GetSingleEntryTests(_OpsLogTestBase):
    def test_get_returns_200(self) -> None:
        self.mock_query.return_value = [_sample_row()]

        response = self.client.get('/operations-log/entry-abc')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['id'], 'entry-abc')
        self.assertEqual(body['entry_type'], 'Deployed')
        self.assertNotIn('_row_version', body)
        self.assertNotIn('is_deleted', body)
        self.mock_query.assert_awaited_once()
        sent_sql = self.mock_query.await_args.args[0]
        self.assertIn('FINAL', sent_sql)
        self.assertIn('is_deleted = 0', sent_sql)

    def test_get_not_found(self) -> None:
        self.mock_query.return_value = []
        response = self.client.get('/operations-log/missing-id')
        self.assertEqual(response.status_code, 404)

    def test_get_forbidden_without_permission(self) -> None:
        self._revoke_permissions()
        response = self.client.get('/operations-log/entry-abc')
        self.assertEqual(response.status_code, 403)
        self.mock_query.assert_not_awaited()


class ListEntriesTests(_OpsLogTestBase):
    def _rows(self, count: int) -> list[dict[str, typing.Any]]:
        base_ts = datetime.datetime(2026, 4, 17, 14, 0, 0, tzinfo=datetime.UTC)
        return [
            _sample_row(
                id=f'entry-{i:03d}',
                occurred_at=base_ts - datetime.timedelta(minutes=i),
            )
            for i in range(count)
        ]

    def test_list_default_limit(self) -> None:
        self._stub_list(self._rows(3))
        response = self.client.get('/operations-log/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body['data']), 3)
        self.assertIsNotNone(body['metrics'])
        link = response.headers['Link']
        self.assertIn('rel="first"', link)
        # Only 3 rows returned, no next page
        self.assertNotIn('rel="next"', link)

    def test_list_has_next_link_when_more_results(self) -> None:
        # Endpoint requests limit+1 rows; we return 3 for limit=2.
        self._stub_list(self._rows(3))
        response = self.client.get('/operations-log/?limit=2')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body['data']), 2)  # extra row popped
        link = response.headers['Link']
        self.assertIn('rel="first"', link)
        self.assertIn('rel="next"', link)
        self.assertIn('cursor=', link)

    def test_list_next_cursor_round_trip(self) -> None:
        import re

        rows = self._rows(3)
        self._stub_list(rows)
        response = self.client.get('/operations-log/?limit=2')
        link = response.headers['Link']
        match = re.search(r'<[^>]*cursor=([^&>]+)[^>]*>;\s*rel="next"', link)
        assert match is not None, link
        cursor = match.group(1)
        decoded = operations_log._decode_cursor(cursor)
        self.assertIsNotNone(decoded)
        assert decoded is not None
        ts, entry_id = decoded
        # Second row in newest-first order is index 1 of the requested 2.
        self.assertEqual(entry_id, rows[1]['id'])
        self.assertEqual(ts, rows[1]['occurred_at'])

    def test_list_invalid_cursor(self) -> None:
        response = self.client.get('/operations-log/?cursor=!!!bad!!!')
        self.assertEqual(response.status_code, 400)

    def test_list_limit_out_of_range(self) -> None:
        response = self.client.get('/operations-log/?limit=0')
        self.assertEqual(response.status_code, 400)
        response = self.client.get('/operations-log/?limit=501')
        self.assertEqual(response.status_code, 400)

    def test_list_project_slug_filter(self) -> None:
        self._stub_list(self._rows(1))
        response = self.client.get('/operations-log/?project_slug=imbi-api')
        self.assertEqual(response.status_code, 200)
        sent_sql, sent_params = self.mock_query.await_args_list[0].args
        self.assertIn('project_slug = {project_slug:String}', sent_sql)
        self.assertEqual(sent_params['project_slug'], 'imbi-api')

    def test_list_since_until(self) -> None:
        self._stub_list([])
        since = '2026-04-01T00:00:00Z'
        until = '2026-05-01T00:00:00Z'
        response = self.client.get(
            f'/operations-log/?since={since}&until={until}'
        )
        self.assertEqual(response.status_code, 200)
        sent_sql, sent_params = self.mock_query.await_args_list[0].args
        self.assertIn('occurred_at >= {since:DateTime64(3)}', sent_sql)
        self.assertIn('occurred_at < {until:DateTime64(3)}', sent_sql)
        self.assertIn('since', sent_params)
        self.assertIn('until', sent_params)

    def test_list_invalid_since(self) -> None:
        response = self.client.get('/operations-log/?since=not-a-date')
        self.assertEqual(response.status_code, 400)

    def test_list_forbidden_without_permission(self) -> None:
        self._revoke_permissions()
        response = self.client.get('/operations-log/')
        self.assertEqual(response.status_code, 403)
        self.mock_query.assert_not_awaited()


class PatchOperationLogTests(_OpsLogTestBase):
    def _setup_existing(
        self, **overrides: typing.Any
    ) -> dict[str, typing.Any]:
        row = _sample_row(**overrides)
        self.mock_query.return_value = [row]
        return row

    def test_patch_replace_description(self) -> None:
        self._setup_existing()
        response = self.client.patch(
            '/operations-log/entry-abc',
            json=[
                {
                    'op': 'replace',
                    'path': '/description',
                    'value': 'Rolled out v2.4.1',
                }
            ],
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['description'], 'Rolled out v2.4.1')
        self.mock_insert.assert_awaited_once()
        assert self.mock_insert.await_args is not None
        args, _kwargs = self.mock_insert.await_args
        column_names = args[2]
        values = args[1][0]
        columns = dict(zip(column_names, values, strict=True))
        self.assertGreater(columns['_row_version'], 1)
        self.assertEqual(columns['id'], 'entry-abc')

    def test_patch_readonly_id_is_400(self) -> None:
        self._setup_existing()
        response = self.client.patch(
            '/operations-log/entry-abc',
            json=[{'op': 'replace', 'path': '/id', 'value': 'x'}],
        )
        self.assertEqual(response.status_code, 400)

    def test_patch_readonly_occurred_at_is_400(self) -> None:
        self._setup_existing()
        response = self.client.patch(
            '/operations-log/entry-abc',
            json=[
                {
                    'op': 'replace',
                    'path': '/occurred_at',
                    'value': '2020-01-01T00:00:00Z',
                }
            ],
        )
        self.assertEqual(response.status_code, 400)

    def test_patch_readonly_row_version_is_400(self) -> None:
        self._setup_existing()
        response = self.client.patch(
            '/operations-log/entry-abc',
            json=[{'op': 'replace', 'path': '/row_version', 'value': 99}],
        )
        self.assertEqual(response.status_code, 400)

    def test_patch_test_op_failure_is_422(self) -> None:
        self._setup_existing()
        response = self.client.patch(
            '/operations-log/entry-abc',
            json=[
                {
                    'op': 'test',
                    'path': '/description',
                    'value': 'something else',
                }
            ],
        )
        self.assertEqual(response.status_code, 422)

    def test_patch_not_found(self) -> None:
        self.mock_query.return_value = []
        response = self.client.patch(
            '/operations-log/missing',
            json=[
                {
                    'op': 'replace',
                    'path': '/description',
                    'value': 'x',
                }
            ],
        )
        self.assertEqual(response.status_code, 404)

    def test_patch_forbidden_without_permission(self) -> None:
        self._revoke_permissions()
        response = self.client.patch(
            '/operations-log/entry-abc',
            json=[
                {
                    'op': 'replace',
                    'path': '/description',
                    'value': 'x',
                }
            ],
        )
        self.assertEqual(response.status_code, 403)


class ProjectScopedListTests(_OpsLogTestBase):
    def test_project_scoped_forces_project_id(self) -> None:
        row = _sample_row(project_id='proj-xyz')
        self._stub_list([row])
        # Client-supplied ?project_id= is ignored; path wins.
        response = self.client.get(
            '/organizations/engineering/projects/proj-xyz/operations-log/'
            '?project_id=hacker-attempt'
        )
        self.assertEqual(response.status_code, 200)
        _sql, params = self.mock_query.await_args_list[0].args
        self.assertEqual(params['project_id'], 'proj-xyz')

    def test_project_scoped_has_link_headers(self) -> None:
        self._stub_list([_sample_row()])
        response = self.client.get(
            '/organizations/engineering/projects/proj-xyz/operations-log/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('rel="first"', response.headers['Link'])

    def test_project_scoped_forbidden_without_permission(self) -> None:
        self._revoke_permissions()
        response = self.client.get(
            '/organizations/engineering/projects/proj-xyz/operations-log/'
        )
        self.assertEqual(response.status_code, 403)


class DeleteOperationLogTests(_OpsLogTestBase):
    def test_delete_204(self) -> None:
        self.mock_query.return_value = [_sample_row()]
        response = self.client.delete('/operations-log/entry-abc')
        self.assertEqual(response.status_code, 204)
        self.mock_insert.assert_awaited_once()
        assert self.mock_insert.await_args is not None
        args, _kwargs = self.mock_insert.await_args
        column_names = args[2]
        values = args[1][0]
        row = dict(zip(column_names, values, strict=True))
        self.assertEqual(row['id'], 'entry-abc')
        self.assertEqual(row['is_deleted'], 1)
        self.assertGreater(row['_row_version'], 1)

    def test_delete_idempotent_after_tombstone(self) -> None:
        # First delete: row exists.
        self.mock_query.return_value = [_sample_row()]
        first = self.client.delete('/operations-log/entry-abc')
        self.assertEqual(first.status_code, 204)

        # Second delete: tombstoned rows are invisible due to is_deleted = 0.
        self.mock_query.return_value = []
        second = self.client.delete('/operations-log/entry-abc')
        self.assertEqual(second.status_code, 404)

    def test_delete_not_found(self) -> None:
        self.mock_query.return_value = []
        response = self.client.delete('/operations-log/missing')
        self.assertEqual(response.status_code, 404)

    def test_delete_forbidden_without_permission(self) -> None:
        self._revoke_permissions()
        response = self.client.delete('/operations-log/entry-abc')
        self.assertEqual(response.status_code, 403)
