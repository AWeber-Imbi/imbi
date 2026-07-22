"""Tests for the events log endpoints."""

from __future__ import annotations

import datetime
import typing
import unittest
from unittest import mock

from fastapi import testclient

from imbi.api import models as api_models
from imbi.api.auth import permissions as api_permissions
from imbi.api.endpoints import events
from imbi.common import graph
from tests.api import support


def _row(
    *,
    recorded_at: datetime.datetime | None = None,
    entry_id: str = 'evt-1',
    project_id: str = 'p1',
) -> dict[str, typing.Any]:
    # ``metadata`` and ``payload`` come back from ClickHouse as
    # ``toJSONString``-serialized text (see ``_SELECT_COLUMNS`` in
    # the events endpoint module); the helper handles the JSON
    # parse.
    return {
        'id': entry_id,
        'project_id': project_id,
        'recorded_at': recorded_at
        or datetime.datetime(2026, 4, 1, 12, 0, tzinfo=datetime.UTC),
        'type': 'project-change',
        'integration': 'internal',
        'attributed_to': 'alice@example.com',
        'metadata': '{}',
        'payload': '{"field":"name","old":"A","new":"B"}',
    }


class _EventsTestBase(support.SharedAppTestCase):
    def setUp(self) -> None:
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
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

        self.query_patcher = mock.patch(
            'imbi.common.clickhouse.query',
            new_callable=mock.AsyncMock,
        )
        self.mock_query = self.query_patcher.start()
        self.addCleanup(self.query_patcher.stop)

        self.client = testclient.TestClient(self.test_app)
        self.addCleanup(self.client.close)


class CursorCodecTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        ts = datetime.datetime(2026, 4, 1, 12, 0, tzinfo=datetime.UTC)
        encoded = events.encode_cursor(ts, 'evt-1')
        decoded = events.decode_cursor(encoded)
        self.assertIsNotNone(decoded)
        assert decoded is not None
        decoded_ts, decoded_id = decoded
        self.assertEqual(decoded_ts, ts)
        self.assertEqual(decoded_id, 'evt-1')

    def test_decode_empty_returns_none(self) -> None:
        self.assertIsNone(events.decode_cursor(''))

    def test_decode_invalid_base64_returns_none(self) -> None:
        # Non-utf8 bytes via raw b64
        import base64

        bad = base64.urlsafe_b64encode(b'\xff\xfe\xfd').rstrip(b'=').decode()
        self.assertIsNone(events.decode_cursor(bad))

    def test_decode_missing_separator_returns_none(self) -> None:
        import base64

        payload = (
            base64.urlsafe_b64encode(b'no-separator').rstrip(b'=').decode()
        )
        self.assertIsNone(events.decode_cursor(payload))

    def test_decode_empty_id_returns_none(self) -> None:
        import base64

        payload = (
            base64.urlsafe_b64encode(b'2026-04-01T12:00:00|')
            .rstrip(b'=')
            .decode()
        )
        self.assertIsNone(events.decode_cursor(payload))

    def test_decode_invalid_timestamp_returns_none(self) -> None:
        import base64

        payload = (
            base64.urlsafe_b64encode(b'not-a-timestamp|evt-1')
            .rstrip(b'=')
            .decode()
        )
        self.assertIsNone(events.decode_cursor(payload))

    def test_naive_timestamp_gets_utc(self) -> None:
        import base64

        payload = (
            base64.urlsafe_b64encode(b'2026-04-01T12:00:00|evt-1')
            .rstrip(b'=')
            .decode()
        )
        decoded = events.decode_cursor(payload)
        assert decoded is not None
        ts, _ = decoded
        self.assertEqual(ts.tzinfo, datetime.UTC)


class ParseIsoTests(unittest.TestCase):
    def test_invalid_raises_400(self) -> None:
        import fastapi

        with self.assertRaises(fastapi.HTTPException) as ctx:
            events.parse_iso('garbage', 'since')
        self.assertEqual(ctx.exception.status_code, 400)

    def test_naive_treated_as_utc(self) -> None:
        result = events.parse_iso('2026-04-01T12:00:00', 'since')
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

    def test_metadata_parsed_from_json_text(self) -> None:
        """``toJSONString`` returns JSON text; the helper parses it
        back to a Python dict for serialization."""
        out = events._row_to_response(
            {
                'id': 'a',
                'metadata': '{"webhook_id":"w-1","handlers":[]}',
                'payload': '{"ref":"main"}',
            }
        )
        self.assertEqual('w-1', out['metadata']['webhook_id'])
        self.assertEqual([], out['metadata']['handlers'])
        self.assertEqual('main', out['payload']['ref'])

    def test_bytes_metadata_decoded_then_parsed(self) -> None:
        """If clickhouse-connect hands back the JSON text as bytes
        (e.g. with a Latin-1 byte inside a string value), decode
        with replacement before parsing."""
        out = events._row_to_response(
            {'id': 'a', 'metadata': b'{"foo":"AB\x80C"}'}
        )
        self.assertEqual('AB�C', out['metadata']['foo'])

    def test_malformed_json_in_metadata_does_not_500(self) -> None:
        out = events._row_to_response(
            {'id': 'a', 'metadata': 'not actually json'}
        )
        self.assertEqual('not actually json', out['metadata']['__raw__'])
        self.assertIn('invalid JSON', out['metadata']['__error__'])


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

    def test_list_tolerates_non_utf8_bytes_in_payload(self) -> None:
        # ClickHouse returns raw bytes for JSON string values that aren't
        # valid UTF-8 (e.g. a cp1252 smart quote, 0x91). The endpoint must
        # decode leniently instead of 500ing on a single bad row.
        row = _row()
        row['payload'] = {'title': b'fix \x91thing\x92'}
        self.mock_query.return_value = [row]
        response = self.client.get('/events/')
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['data'][0]['payload']['title'], 'fix �thing�')

    def test_list_with_filters(self) -> None:
        self.mock_query.return_value = [_row()]
        response = self.client.get(
            '/events/',
            params={
                'project_id': 'p1',
                'type': 'project-change',
                'attributed_to': 'alice@example.com',
                'integration': 'github-enterprise-cloud',
            },
        )
        self.assertEqual(response.status_code, 200)
        call = self.mock_query.await_args
        params = call.args[1]
        self.assertEqual(params['project_id'], 'p1')
        self.assertEqual(params['type'], 'project-change')
        self.assertEqual(params['attributed_to'], 'alice@example.com')
        self.assertEqual(params['integration'], 'github-enterprise-cloud')
        sql = call.args[0]
        self.assertIn('integration =', sql)

    def test_list_filters_by_event_type_through_metadata(self) -> None:
        """``event_type`` filters on ``metadata.event_type`` so the
        webhook-history view can narrow within ``type=webhook``."""
        self.mock_query.return_value = [_row()]
        response = self.client.get(
            '/events/',
            params={'type': 'webhook', 'event_type': 'pull_request'},
        )
        self.assertEqual(response.status_code, 200)
        call = self.mock_query.await_args
        sql = call.args[0]
        params = call.args[1]
        self.assertEqual(params['type'], 'webhook')
        self.assertEqual(params['event_type'], 'pull_request')
        self.assertIn('metadata.event_type', sql)

    def test_list_reads_from_events_table(self) -> None:
        self.mock_query.return_value = []
        response = self.client.get('/events/')
        self.assertEqual(response.status_code, 200)
        sql = self.mock_query.await_args.args[0]
        self.assertIn('FROM events WHERE', sql)

    def test_list_reads_payload_only_for_the_selected_page(self) -> None:
        # The events table is sorted by ``(project_id, id)``, so ordering
        # by ``recorded_at`` can't short-circuit the LIMIT. Reading the
        # heavy ``payload`` JSON for every matching row before discarding
        # all but the page exhausted ClickHouse memory. The query must
        # pick the page keys from the light ``(recorded_at, id)`` columns
        # in a subquery, then read the JSON only for those rows.
        self.mock_query.return_value = []
        response = self.client.get('/events/')
        self.assertEqual(response.status_code, 200)
        sql = self.mock_query.await_args.args[0]
        # Outer query reads the heavy JSON columns exactly once...
        self.assertEqual(sql.count('toJSONString(payload)'), 1)
        self.assertEqual(sql.count('toJSONString(metadata)'), 1)
        # ...and only for the page selected by the light-column subquery.
        self.assertIn('(recorded_at, id) IN (', sql)
        self.assertIn('SELECT recorded_at, id FROM events WHERE', sql)
        inner = sql.split('(recorded_at, id) IN (', 1)[1]
        inner_page = inner.split('LIMIT', 1)[0]
        self.assertNotIn('payload', inner_page)
        self.assertNotIn('metadata', inner_page)
        self.assertIn('LIMIT {row_limit:UInt32}', inner)

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

    def test_non_admin_without_event_permission_denied(self) -> None:
        """Non-admin users without admin:events:read get 403."""
        non_admin = api_models.User(
            email='basic@example.com',
            display_name='Basic',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth = api_permissions.AuthContext(
            user=non_admin,
            session_id='s',
            auth_method='jwt',
            permissions={'project:read'},
        )
        response = self.client.get('/events/')
        self.assertEqual(response.status_code, 403)

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
        cursor = events.encode_cursor(
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


class GetEventByIdTests(_EventsTestBase):
    """Tests for the GET /events/{event_id} deep-link endpoint."""

    def test_returns_event_when_found(self) -> None:
        self.mock_query.return_value = [_row(entry_id='evt-deep-link')]
        response = self.client.get('/events/evt-deep-link')
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['id'], 'evt-deep-link')

    def test_reads_from_events_table(self) -> None:
        self.mock_query.return_value = [_row(entry_id='evt-1')]
        response = self.client.get('/events/evt-1')
        self.assertEqual(response.status_code, 200)
        sql = self.mock_query.await_args.args[0]
        self.assertIn('FROM events ', sql)
        params = self.mock_query.await_args.args[1]
        self.assertEqual(params['event_id'], 'evt-1')

    def test_returns_404_when_not_found(self) -> None:
        self.mock_query.return_value = []
        response = self.client.get('/events/nope')
        self.assertEqual(response.status_code, 404)

    def test_tolerates_non_utf8_bytes_in_payload(self) -> None:
        # The by-id lookup must share the list feed's lenient decode
        # policy: a non-UTF-8 byte in a payload string can't 500 it.
        row = _row(entry_id='evt-1')
        row['payload'] = {'title': b'fix \x91thing\x92'}
        self.mock_query.return_value = [row]
        response = self.client.get('/events/evt-1')
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['payload']['title'], 'fix �thing�')

    def test_non_admin_denied(self) -> None:
        non_admin = api_models.User(
            email='basic@example.com',
            display_name='Basic',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth = api_permissions.AuthContext(
            user=non_admin,
            session_id='s',
            auth_method='jwt',
            permissions={'project:read'},
        )
        response = self.client.get('/events/evt-1')
        self.assertEqual(response.status_code, 403)


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
