"""Elasticsearch DSL builder, cursor codec, and fingerprint helpers."""

import base64
import hashlib
import json
from collections.abc import Mapping
from typing import cast

from imbi_common.plugins.base import LogFilter, LogQuery
from imbi_common.plugins.errors import CursorExpiredError
from imbi_common.plugins.templates import expand_template


def _build_bool_clause(
    query: LogQuery,
    *,
    base_query: str | None,
    timestamp_field: str,
    message_field: str,
    ctx_vars: dict[str, str | None],
    environment_field: str | None = None,
    environment_value: str | None = None,
    level_field: str | None = None,
) -> dict[str, object]:
    must: list[dict[str, object]] = [
        {
            'range': {
                timestamp_field: {
                    'gte': query.start_time.isoformat(),
                    'lte': query.end_time.isoformat(),
                }
            }
        }
    ]
    must_not: list[dict[str, object]] = []

    if environment_field and environment_value:
        must.append({'term': {environment_field: environment_value}})

    if level_field and query.levels:
        must.append({'terms': {level_field: list(query.levels)}})

    if base_query:
        expanded = expand_template(base_query, ctx_vars)
        must.append(
            {
                'query_string': {
                    'query': expanded,
                    'allow_leading_wildcard': False,
                }
            }
        )

    for f in query.filters:
        _translate_filter(f, must, must_not, message_field)

    clause: dict[str, object] = {'must': must}
    if must_not:
        clause['must_not'] = must_not
    return clause


def build_query_body(
    query: LogQuery,
    *,
    base_query: str | None,
    timestamp_field: str,
    message_field: str,
    ctx_vars: dict[str, str | None],
    environment_field: str | None = None,
    environment_value: str | None = None,
    level_field: str | None = None,
) -> dict[str, object]:
    bool_clause = _build_bool_clause(
        query,
        base_query=base_query,
        timestamp_field=timestamp_field,
        message_field=message_field,
        ctx_vars=ctx_vars,
        environment_field=environment_field,
        environment_value=environment_value,
        level_field=level_field,
    )
    return {
        'query': {'bool': bool_clause},
        'sort': [{timestamp_field: 'desc'}, '_doc'],
        'size': min(query.limit, 1000),
        '_source': True,
    }


def build_histogram_body(
    query: LogQuery,
    *,
    base_query: str | None,
    timestamp_field: str,
    message_field: str,
    ctx_vars: dict[str, str | None],
    bucket_count: int = 60,
    level_filter: str | None = None,
    level_field: str = 'level',
    environment_field: str | None = None,
    environment_value: str | None = None,
) -> dict[str, object]:
    """Build an ES body that returns a date_histogram aggregation.

    ``size: 0`` suppresses hit results so only aggregation data is
    returned, keeping the response small regardless of event volume.

    When ``level_filter`` is provided a term filter is added so only
    events matching that level are counted, enabling per-level breakdown
    without nested bucket aggregations (which Logz.io forbids).
    """
    bool_clause = _build_bool_clause(
        query,
        base_query=base_query,
        timestamp_field=timestamp_field,
        message_field=message_field,
        ctx_vars=ctx_vars,
        environment_field=environment_field,
        environment_value=environment_value,
    )
    if level_filter is not None:
        must = list(cast('list[dict[str, object]]', bool_clause['must']))
        must.append({'term': {level_field: level_filter}})
        bool_clause = dict(bool_clause)
        bool_clause['must'] = must
    total_seconds = max(
        1,
        int((query.end_time - query.start_time).total_seconds()),
    )
    interval_seconds = max(1, -(-total_seconds // bucket_count))
    interval_str = _seconds_to_fixed_interval(interval_seconds)
    return {
        'size': 0,
        'query': {'bool': bool_clause},
        'aggs': {
            'over_time': {
                'date_histogram': {
                    'field': timestamp_field,
                    'fixed_interval': interval_str,
                },
            }
        },
    }


def _seconds_to_fixed_interval(seconds: int) -> str:
    """Convert a duration to an ES fixed_interval string.

    Uses ceiling division so the returned interval is always *at least* as
    long as requested, ensuring the actual bucket count never exceeds the
    caller's target (floor division undershoots and produces extra buckets).
    """
    if seconds < 60:
        return f'{max(1, seconds)}s'
    minutes = -(-seconds // 60)  # ceiling division
    if minutes < 60:
        return f'{minutes}m'
    hours = -(-minutes // 60)  # ceiling division
    if hours < 24:
        return f'{hours}h'
    days = -(-hours // 24)  # ceiling division
    return f'{days}d'


def _translate_filter(
    f: LogFilter,
    must: list[dict[str, object]],
    must_not: list[dict[str, object]],
    message_field: str,
) -> None:
    if f.op == 'eq':
        must.append({'term': {f.field: f.value}})
    elif f.op == 'ne':
        must_not.append({'term': {f.field: f.value}})
    elif f.op == 'contains':
        if f.field == message_field:
            must.append({'match_phrase': {f.field: f.value}})
        else:
            if f.value.startswith(('*', '?')):
                raise ValueError(
                    f'contains filter on field {f.field!r} would require '
                    f'a leading wildcard, which is not supported by Logz.io'
                )
            must.append({'wildcard': {f.field: f'{f.value}*'}})
    elif f.op == 'starts_with':
        must.append({'prefix': {f.field: f.value}})
    elif f.op == 'regex':
        if f.value.startswith(('.*', '*', '?')):
            raise ValueError(
                f'regex filter on field {f.field!r} starts with a leading '
                f'wildcard pattern, which is not supported by Logz.io'
            )
        must.append({'regexp': {f.field: f.value}})
    else:
        raise ValueError(
            f'unsupported filter operator {f.op!r} on field {f.field!r}'
        )


def compute_fp(body: Mapping[str, object]) -> str:
    canonical = json.dumps(
        body, sort_keys=True, separators=(',', ':')
    ).encode()
    return hashlib.sha256(canonical).hexdigest()[:16]


def encode_cursor(search_after: list[object], fp: str) -> str:
    payload = json.dumps(
        {'v': 1, 'sa': search_after, 'fp': fp}, separators=(',', ':')
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip('=')


def decode_cursor(token: str, expected_fp: str) -> list[object]:
    pad = '=' * (-len(token) % 4)
    try:
        parsed: object = json.loads(base64.urlsafe_b64decode(token + pad))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CursorExpiredError('Invalid cursor token') from exc
    if not isinstance(parsed, dict):
        raise CursorExpiredError('Invalid cursor token structure')
    data = cast('dict[str, object]', parsed)
    if data.get('v') != 1 or data.get('fp') != expected_fp:
        raise CursorExpiredError(
            'Cursor fingerprint mismatch or version unsupported'
        )
    sa = data.get('sa')
    if not isinstance(sa, list):
        raise CursorExpiredError('Invalid cursor search_after')
    return cast('list[object]', sa)
