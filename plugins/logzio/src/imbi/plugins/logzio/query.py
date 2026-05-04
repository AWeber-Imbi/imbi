"""Elasticsearch DSL builder, cursor codec, and fingerprint helpers."""

import base64
import hashlib
import json
from collections.abc import Mapping
from typing import cast

from imbi_common.plugins.base import LogFilter, LogQuery
from imbi_common.plugins.errors import CursorExpiredError
from imbi_common.plugins.templates import expand_template


def build_query_body(
    query: LogQuery,
    *,
    base_query: str | None,
    timestamp_field: str,
    message_field: str,
    ctx_vars: dict[str, str | None],
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

    bool_clause: dict[str, object] = {'must': must}
    if must_not:
        bool_clause['must_not'] = must_not

    return {
        'query': {'bool': bool_clause},
        'sort': [{timestamp_field: 'desc'}, '_doc'],
        'size': min(query.limit, 1000),
        '_source': True,
    }


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
