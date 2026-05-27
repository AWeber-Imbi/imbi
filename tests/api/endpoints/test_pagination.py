"""Tests for the shared cursor-pagination helpers."""

import datetime
import unittest
from unittest import mock

import fastapi

from imbi_api.endpoints import _pagination


class CursorTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        ts = datetime.datetime(2026, 5, 26, 12, 0, tzinfo=datetime.UTC)
        cursor = _pagination.encode_cursor(ts, 'abc123')
        decoded = _pagination.decode_cursor(cursor)
        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertEqual(decoded, (ts, 'abc123'))

    def test_decode_naive_timestamp_assumed_utc(self) -> None:
        naive = datetime.datetime(2026, 5, 26, 12, 0)  # noqa: DTZ001
        cursor = _pagination.encode_cursor(naive, 'x')
        decoded = _pagination.decode_cursor(cursor)
        assert decoded is not None
        self.assertEqual(decoded[0].tzinfo, datetime.UTC)

    def test_decode_empty_returns_none(self) -> None:
        self.assertIsNone(_pagination.decode_cursor(''))

    def test_decode_invalid_base64_returns_none(self) -> None:
        self.assertIsNone(_pagination.decode_cursor('!!!not-base64!!!'))

    def test_decode_missing_separator_returns_none(self) -> None:
        import base64

        payload = base64.urlsafe_b64encode(b'noseparator').rstrip(b'=')
        self.assertIsNone(_pagination.decode_cursor(payload.decode('ascii')))

    def test_decode_empty_id_returns_none(self) -> None:
        import base64

        payload = base64.urlsafe_b64encode(
            b'2026-05-26T12:00:00+00:00|'
        ).rstrip(b'=')
        self.assertIsNone(_pagination.decode_cursor(payload.decode('ascii')))


class KeysetTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        cursor = _pagination.encode_keyset('Alpha', 'wh_a')
        self.assertEqual(_pagination.decode_keyset(cursor), ('Alpha', 'wh_a'))

    def test_sort_value_with_pipe_survives(self) -> None:
        cursor = _pagination.encode_keyset('a|b|c', 'wh_a')
        self.assertEqual(_pagination.decode_keyset(cursor), ('a|b|c', 'wh_a'))

    def test_decode_empty_returns_none(self) -> None:
        self.assertIsNone(_pagination.decode_keyset(''))

    def test_decode_invalid_base64_returns_none(self) -> None:
        self.assertIsNone(_pagination.decode_keyset('!!!nope!!!'))

    def test_decode_missing_separator_returns_none(self) -> None:
        import base64

        payload = base64.urlsafe_b64encode(b'noseparator').rstrip(b'=')
        self.assertIsNone(_pagination.decode_keyset(payload.decode('ascii')))

    def test_decode_empty_id_returns_none(self) -> None:
        import base64

        payload = base64.urlsafe_b64encode(b'name|').rstrip(b'=')
        self.assertIsNone(_pagination.decode_keyset(payload.decode('ascii')))


class ParseIsoTests(unittest.TestCase):
    def test_naive_treated_as_utc(self) -> None:
        parsed = _pagination.parse_iso('2026-05-26T12:00:00', 'since')
        self.assertEqual(parsed.tzinfo, datetime.UTC)

    def test_invalid_raises_400(self) -> None:
        with self.assertRaises(fastapi.HTTPException) as ctx:
            _pagination.parse_iso('not-a-date', 'since')
        self.assertEqual(ctx.exception.status_code, 400)


class BuildLinkHeaderTests(unittest.TestCase):
    @staticmethod
    def _request(query: str) -> fastapi.Request:
        request = mock.MagicMock(spec=fastapi.Request)
        url = mock.MagicMock()
        url.scheme = 'https'
        url.netloc = 'imbi.example'
        url.path = '/events/'
        request.url = url
        request.query_params.multi_items.return_value = [
            (k, v)
            for k, _, v in (
                part.partition('=') for part in query.split('&') if part
            )
        ]
        return request

    def test_first_only_when_no_next(self) -> None:
        header = _pagination.build_link_header(self._request('limit=50'), None)
        self.assertIn('rel="first"', header)
        self.assertNotIn('rel="next"', header)
        self.assertIn('limit=50', header)

    def test_next_replaces_cursor(self) -> None:
        header = _pagination.build_link_header(
            self._request('limit=50&cursor=old'), 'newcursor'
        )
        self.assertIn('rel="next"', header)
        self.assertIn('cursor=newcursor', header)
        self.assertNotIn('cursor=old', header)


if __name__ == '__main__':
    unittest.main()
