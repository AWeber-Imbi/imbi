"""Tests for the events log endpoints."""

from __future__ import annotations

import datetime
import typing
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common import graph

from imbi_api import app
from imbi_api import models as api_models
from imbi_api.auth import permissions as api_permissions
from imbi_api.endpoints import events


def _row(
    *,
    recorded_at: datetime.datetime | None = None,
    entry_id: str = 'evt-1',
    project_id: str = 'p1',
) -> dict[str, typing.Any]:
    return {
        'id': entry_id,
        'project_id': project_id,
        'recorded_at': recorded_at
        or datetime.datetime(2026, 4, 1, 12, 0, tzinfo=datetime.UTC),
        'type': 'project-change',
        'third_party_service': 'internal',
        'attributed_to': 'alice@example.com',
        'metadata': {},
        'payload': {'field': 'name', 'old': 'A', 'new': 'B'},
    }


class _EventsTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.test_app = app.create_app()
        self.user = api_models.User(
            email='alice@example.com',
            display_name='Alice',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth = api_permissions.AuthContext(
            user=self.user,
            session_id='s',
            auth_method='jwt',
            permissions=set(),
        )

        async def _current_user() -> api_permissions.AuthContext:
            return self.auth

        self.test_app.dependency_overrides[
            api_permissions.get_current_user
        ] = _current_user

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.query_patcher = mock.patch(
            'imbi_common.clickhouse.query',
            new_callable=mock.AsyncMock,
        )
        self.mock_query = self.query_patcher.start()
        self.addCleanup(self.query_patcher.stop)

        self.client = testclient.TestClient(self.test_app)
        self.addCleanup(self.client.close)


class CursorCodecTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        ts = datetime.datetime(2026, 4, 1, 12, 0, tzinfo=datetime.UTC)
        encoded = events._encode_cursor(ts, 'evt-1')
        decoded = events._decode_cursor(encoded)
        self.assertIsNotNone(decoded)
        assert decoded is not None
        decoded_ts, decoded_id = decoded
        self.assertEqual(decoded_ts, ts)
        self.assertEqual(decoded_id, 'evt-1')

    def test_decode_empty_returns_none(self) -> None:
        self.assertIsNone(events._decode_cursor(''))

    def test_decode_invalid_base64_returns_none(self) -> None:
        # Non-utf8 bytes via raw b64
        import base64

        bad = base64.urlsafe_b64encode(b'\xff\xfe\xfd').rstrip(b'=').decode()
        self.assertIsNone(events._decode_cursor(bad))

    def test_decode_missing_separator_returns_none(self) -> None:
        import base64

        payload = (
            base64.urlsafe_b64encode(b'no-separator').rstrip(b'=').decode()
        )
        self.assertIsNone(events._decode_cursor(payload))

    def test_decode_empty_id_returns_none(self) -> None:
        import base64

        payload = (
            base64.urlsafe_b64encode(b'2026-04-01T12:00:00|')
            .rstrip(b'=')
            .decode()
        )
        self.assertIsNone(events._decode_cursor(payload))

    def test_decode_invalid_timestamp_returns_none(self) -> None:
        import base64

        payload = (
            base64.urlsafe_b64encode(b'not-a-timestamp|evt-1')
            .rstrip(b'=')
            .decode()
        )
        self.assertIsNone(events._decode_cursor(payload))

    def test_naive_timestamp_gets_utc(self) -> None:
        import base64

        payload = (
            base64.urlsafe_b64encode(b'2026-04-01T12:00:00|evt-1')
            .rstrip(b'=')
            .decode()
        )
        decoded = events._decode_cursor(payload)
        assert decoded is not None
        ts, _ = decoded
        self.assertEqual(ts.tzinfo, datetime.UTC)


class ParseIsoTests(unittest.TestCase):
    def test_invalid_raises_400(self) -> None:
        import fastapi

        with self.assertRaises(fastapi.HTTPException) as ctx:
            events._parse_iso('garbage', 'since')
        self.assertEqual(ctx.exception.status_code, 400)

    def test_naive_treated_as_utc(self) -> None:
        result = events._parse_iso('2026-04-01T12:00:00', 'since')
        self.assertEqual(result.tzinfo, datetime.UTC)


class RowToResponseTests(unittest.TestCase):
    def test_naive_datetime_made_utc(self) -> None:
        # ClickHouse may return naive datetimes; the helper must
        # stamp them as UTC.
        naive = datetime.datetime(  # noqa: DTZ001
            2026, 4, 1, 12, 0
        )
        out = events._row_to_response({'recorded_at': naive, 'id': 'a'})
        recorded = out['recorded_at']
        assert isinstance(recorded, datetime.datetime)
        self.assertEqual(recorded.tzinfo, datetime.UTC)


class GlobalListTests(_EventsTestBase):
    def test_list_returns_200(self) -> None:
        self.mock_query.return_value = [_row()]
        response = self.client.get('/events/')
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body['data']), 1)
        self.assertEqual(body['data'][0]['id'], 'evt-1')
        self.assertIn('Link', response.headers)
        self.assertIn('rel="first"', response.headers['Link'])

    def test_list_with_filters(self) -> None:
        self.mock_query.return_value = [_row()]
        response = self.client.get(
            '/events/',
            params={
                'project_id': 'p1',
                'type': 'project-change',
                'attributed_to': 'alice@example.com',
            },
        )
        self.assertEqual(response.status_code, 200)
        call = self.mock_query.await_args
        params = call.args[1]
        self.assertEqual(params['project_id'], 'p1')
        self.assertEqual(params['type'], 'project-change')
        self.assertEqual(params['attributed_to'], 'alice@example.com')

    def test_list_with_since_until(self) -> None:
        self.mock_query.return_value = []
        response = self.client.get(
            '/events/',
            params={
                'since': '2026-03-01T00:00:00Z',
                'until': '2026-04-01T00:00:00Z',
            },
        )
        self.assertEqual(response.status_code, 200)
        call = self.mock_query.await_args
        sql = call.args[0]
        self.assertIn('recorded_at >=', sql)
        self.assertIn('recorded_at <', sql)

    def test_list_with_invalid_since_returns_400(self) -> None:
        response = self.client.get('/events/', params={'since': 'garbage'})
        self.assertEqual(response.status_code, 400)

    def test_list_with_invalid_limit_returns_400(self) -> None:
        response = self.client.get('/events/', params={'limit': 0})
        self.assertEqual(response.status_code, 400)

    def test_list_with_too_large_limit_returns_400(self) -> None:
        response = self.client.get('/events/', params={'limit': 10_000})
        self.assertEqual(response.status_code, 400)

    def test_list_emits_next_cursor_when_more_rows(self) -> None:
        rows = [
            _row(
                entry_id=f'evt-{i}',
                recorded_at=datetime.datetime(
                    2026, 4, i + 1, tzinfo=datetime.UTC
                ),
            )
            for i in range(3)
        ]
        self.mock_query.return_value = rows
        response = self.client.get('/events/', params={'limit': 2})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        # Should drop the extra row used for pagination detection
        self.assertEqual(len(body['data']), 2)
        link = response.headers['Link']
        self.assertIn('rel="next"', link)
        self.assertIn('cursor=', link)

    def test_list_with_invalid_cursor_returns_400(self) -> None:
        self.mock_query.return_value = []
        response = self.client.get('/events/', params={'cursor': '!!!'})
        self.assertEqual(response.status_code, 400)

    def test_list_with_valid_cursor_filters_query(self) -> None:
        self.mock_query.return_value = []
        cursor = events._encode_cursor(
            datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC), 'evt-x'
        )
        response = self.client.get('/events/', params={'cursor': cursor})
        self.assertEqual(response.status_code, 200)
        call = self.mock_query.await_args
        sql = call.args[0]
        params = call.args[1]
        self.assertIn('cursor_ts', params)
        self.assertEqual(params['cursor_id'], 'evt-x')
        self.assertIn('(recorded_at, id) <', sql)


class ProjectScopedListTests(_EventsTestBase):
    def test_list_for_project(self) -> None:
        self.mock_query.return_value = [_row()]
        response = self.client.get('/organizations/eng/projects/p1/events/')
        self.assertEqual(response.status_code, 200, response.text)
        call = self.mock_query.await_args
        params = call.args[1]
        # forced filter overrides query filter
        self.assertEqual(params['project_id'], 'p1')

    def test_link_header_omits_cursor_in_first(self) -> None:
        self.mock_query.return_value = []
        response = self.client.get(
            '/organizations/eng/projects/p1/events/',
            params={'type': 'project-change'},
        )
        self.assertEqual(response.status_code, 200)
        link = response.headers['Link']
        self.assertIn('rel="first"', link)
        # The first link must not carry a cursor query param
        first = link.split(',')[0]
        self.assertNotIn('cursor=', first)


if __name__ == '__main__':
    unittest.main()
