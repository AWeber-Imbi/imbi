"""CloudWatch Logs Insights query builder + cursor codec.

The cursor binds the next page to the *exact* query that produced it
via a fingerprint over the canonical query string + log group set;
mismatches surface as :class:`CursorExpiredError` so callers replay the
search rather than silently paging across an unrelated query.
"""

from __future__ import annotations

import base64
import collections.abc
import datetime
import hashlib
import json
import re
import typing

from imbi_common.plugins.base import LogFilter
from imbi_common.plugins.errors import CursorExpiredError

_BUILTIN_FIELDS = frozenset(
    {
        '@timestamp',
        '@message',
        '@logStream',
        '@log',
        '@requestId',
        '@duration',
        '@ingestionTime',
        '@ptr',
    }
)

# Maximum results CloudWatch Logs Insights returns from a single query.
INSIGHTS_LIMIT_CEILING = 10000

_REGEX_DELIM = re.compile(r'/')


def _quote_value(value: str) -> str:
    """Quote a string literal for an Insights filter clause."""
    escaped = value.replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


def _quote_regex(value: str) -> str:
    return '/' + _REGEX_DELIM.sub(r'\\/', value) + '/'


def _field_token(field: str) -> str:
    if field.startswith('@'):
        return field
    if field in {f.lstrip('@') for f in _BUILTIN_FIELDS}:
        return f'@{field}'
    # Treat as parsed JSON field; Insights references those by name.
    return field


def filter_clause(filt: LogFilter) -> str:
    """Translate one ``LogFilter`` into an Insights ``filter`` clause."""
    field = _field_token(filt.field)
    match filt.op:
        case 'eq':
            return f'filter {field} = {_quote_value(filt.value)}'
        case 'ne':
            return f'filter {field} != {_quote_value(filt.value)}'
        case 'contains':
            return f'filter {field} like {_quote_value(filt.value)}'
        case 'starts_with':
            escaped = filt.value.replace('\\', '\\\\').replace('/', '\\/')
            return f'filter {field} like /^{escaped}/'
        case 'regex':
            return f'filter {field} like {_quote_regex(filt.value)}'


def build_query(
    *,
    base_filter: str | None,
    filters: collections.abc.Sequence[LogFilter],
    limit: int,
    timestamp_field: str = '@timestamp',
    fields: collections.abc.Sequence[str] = (
        '@timestamp',
        '@message',
        '@logStream',
    ),
) -> str:
    """Assemble a Logs Insights query string."""
    parts: list[str] = ['fields ' + ', '.join(fields)]
    if base_filter:
        parts.append(f'filter {base_filter.strip()}')
    parts.extend(filter_clause(f) for f in filters)
    parts.append(f'sort {timestamp_field} desc')
    capped = max(1, min(int(limit), INSIGHTS_LIMIT_CEILING))
    parts.append(f'limit {capped}')
    return ' | '.join(parts)


def query_fingerprint(
    *,
    query_string: str,
    log_group_names: collections.abc.Sequence[str],
) -> str:
    """Return the 16-character cursor fingerprint for a query."""
    canonical = json.dumps(
        {'q': query_string, 'g': sorted(log_group_names)},
        separators=(',', ':'),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def encode_cursor(
    *,
    last_seen: datetime.datetime,
    fingerprint: str,
) -> str:
    payload = json.dumps(
        {
            'v': 1,
            'ts': last_seen.astimezone(datetime.UTC).isoformat(),
            'fp': fingerprint,
        },
        separators=(',', ':'),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).rstrip(b'=').decode('ascii')


def decode_cursor(cursor: str, *, fingerprint: str) -> datetime.datetime:
    """Decode and validate a cursor against the current query.

    Raises :class:`CursorExpiredError` for malformed cursors, version
    mismatches, or fingerprint changes (i.e. the underlying query was
    modified since the cursor was issued).
    """
    try:
        padding = b'=' * (-len(cursor) % 4)
        decoded = base64.urlsafe_b64decode(cursor.encode('ascii') + padding)
        raw_payload = json.loads(decoded)
    except (ValueError, TypeError) as exc:
        raise CursorExpiredError('Cursor is malformed') from exc
    if not isinstance(raw_payload, dict):
        raise CursorExpiredError('Cursor format is unsupported')
    payload = typing.cast(dict[str, typing.Any], raw_payload)
    if payload.get('v') != 1:
        raise CursorExpiredError('Cursor format is unsupported')
    if payload.get('fp') != fingerprint:
        raise CursorExpiredError('Cursor was issued for a different query')
    ts = payload.get('ts')
    if not isinstance(ts, str):
        raise CursorExpiredError('Cursor is missing a timestamp')
    try:
        return datetime.datetime.fromisoformat(ts)
    except ValueError as exc:
        raise CursorExpiredError('Cursor timestamp is invalid') from exc


__all__ = [
    'INSIGHTS_LIMIT_CEILING',
    'build_query',
    'decode_cursor',
    'encode_cursor',
    'filter_clause',
    'query_fingerprint',
]
