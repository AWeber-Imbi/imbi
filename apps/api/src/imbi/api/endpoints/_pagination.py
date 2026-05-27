"""Shared cursor-pagination helpers for list endpoints.

Several read endpoints (events, documents, operations log, user
activity) page over a ``(timestamp, id)`` keyset and expose a
``Link`` header. They each carried byte-for-byte copies of the same
cursor encode/decode, ISO parsing, and Link-header builders; this
module is the single home for that logic.
"""

from __future__ import annotations

import base64
import datetime
import urllib.parse

import fastapi


def encode_cursor(timestamp: datetime.datetime, entry_id: str) -> str:
    """Encode a ``(timestamp, id)`` keyset cursor as urlsafe base64."""
    payload = f'{timestamp.isoformat()}|{entry_id}'.encode()
    return base64.urlsafe_b64encode(payload).rstrip(b'=').decode('ascii')


def decode_cursor(
    cursor: str,
) -> tuple[datetime.datetime, str] | None:
    """Decode a cursor string; return None for any malformed input.

    The timestamp is normalized to UTC (naive values are assumed UTC).
    """
    if not cursor:
        return None
    padding = '=' * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding).decode('utf-8')
    except ValueError, UnicodeDecodeError:
        return None
    if '|' not in raw:
        return None
    ts_str, _, entry_id = raw.partition('|')
    if not entry_id:
        return None
    try:
        ts = datetime.datetime.fromisoformat(ts_str)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.UTC)
    return ts.astimezone(datetime.UTC), entry_id


def parse_iso(value: str, field_name: str) -> datetime.datetime:
    """Parse an ISO-8601 query-param value, raising HTTP 400 on failure.

    Naive timestamps are assumed UTC; the result is normalized to UTC.
    """
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as err:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Invalid ISO timestamp for {field_name!r}',
        ) from err
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def build_link_header(
    request: fastapi.Request,
    next_cursor: str | None,
) -> str:
    """Build an RFC 8288 ``Link`` header with ``first`` and ``next``.

    All existing query params are preserved except ``cursor``, which is
    replaced on the ``next`` link.
    """
    url = request.url
    base_params = {
        k: v for k, v in request.query_params.multi_items() if k != 'cursor'
    }

    def _url_with(params: dict[str, str]) -> str:
        scheme_host_path = f'{url.scheme}://{url.netloc}{url.path}'
        if not params:
            return scheme_host_path
        return f'{scheme_host_path}?{urllib.parse.urlencode(params)}'

    links = [f'<{_url_with(base_params)}>; rel="first"']
    if next_cursor is not None:
        next_params = dict(base_params)
        next_params['cursor'] = next_cursor
        links.append(f'<{_url_with(next_params)}>; rel="next"')
    return ', '.join(links)


__all__ = [
    'build_link_header',
    'decode_cursor',
    'encode_cursor',
    'parse_iso',
]
