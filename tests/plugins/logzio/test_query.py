"""Tests for the ES DSL builder and cursor codec."""

import datetime

import pytest
from imbi_common.plugins.base import LogFilter, LogQuery
from imbi_common.plugins.errors import CursorExpiredError

from imbi_plugin_logzio.query import (
    _seconds_to_fixed_interval,
    build_histogram_body,
    build_query_body,
    compute_fp,
    decode_cursor,
    encode_cursor,
)


def _make_query(**kwargs: object) -> LogQuery:
    defaults: dict[str, object] = {
        'start_time': datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        'end_time': datetime.datetime(2025, 1, 2, tzinfo=datetime.UTC),
        'filters': [],
        'limit': 10,
    }
    defaults.update(kwargs)
    return LogQuery(**defaults)  # type: ignore[arg-type]


def _base_body(**kwargs: object) -> dict[str, object]:
    return build_query_body(
        _make_query(**kwargs),
        base_query=None,
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={},
    )


def test_timestamp_range_present() -> None:
    body = _base_body()
    must = body['query']['bool']['must']  # type: ignore[index]
    range_clause = next(c for c in must if 'range' in c)  # type: ignore[union-attr]
    ts_range = range_clause['range']['@timestamp']  # type: ignore[index]
    assert 'gte' in ts_range
    assert 'lte' in ts_range


def test_size_respects_limit() -> None:
    body = _base_body(limit=5)
    assert body['size'] == 5


def test_size_capped_at_1000() -> None:
    body = _base_body(limit=2000)
    assert body['size'] == 1000


def test_sort_order() -> None:
    body = _base_body()
    sort = body['sort']
    assert sort[0] == {'@timestamp': 'desc'}  # type: ignore[index]


def test_eq_filter() -> None:
    body = build_query_body(
        _make_query(filters=[LogFilter(field='env', op='eq', value='prod')]),
        base_query=None,
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={},
    )
    must = body['query']['bool']['must']  # type: ignore[index]
    assert any(c.get('term', {}).get('env') == 'prod' for c in must)  # type: ignore[union-attr]


def test_ne_filter() -> None:
    body = build_query_body(
        _make_query(filters=[LogFilter(field='env', op='ne', value='dev')]),
        base_query=None,
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={},
    )
    must_not = body['query']['bool'].get('must_not', [])  # type: ignore[index,union-attr]
    assert any(c.get('term', {}).get('env') == 'dev' for c in must_not)  # type: ignore[union-attr]


def test_contains_on_message_uses_match_phrase() -> None:
    body = build_query_body(
        _make_query(
            filters=[LogFilter(field='message', op='contains', value='error')]
        ),
        base_query=None,
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={},
    )
    must = body['query']['bool']['must']  # type: ignore[index]
    assert any(  # type: ignore[union-attr]
        c.get('match_phrase', {}).get('message') == 'error'  # type: ignore[union-attr]
        for c in must  # type: ignore[union-attr]
    )


def test_contains_on_other_field_uses_wildcard() -> None:
    body = build_query_body(
        _make_query(
            filters=[LogFilter(field='host', op='contains', value='web')]
        ),
        base_query=None,
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={},
    )
    must = body['query']['bool']['must']  # type: ignore[index]
    assert any(c.get('wildcard', {}).get('host') == 'web*' for c in must)  # type: ignore[union-attr]


def test_contains_leading_wildcard_raises() -> None:
    with pytest.raises(ValueError, match='leading wildcard'):
        build_query_body(
            _make_query(
                filters=[LogFilter(field='host', op='contains', value='*web')]
            ),
            base_query=None,
            timestamp_field='@timestamp',
            message_field='message',
            ctx_vars={},
        )


def test_contains_leading_question_raises() -> None:
    with pytest.raises(ValueError, match='leading wildcard'):
        build_query_body(
            _make_query(
                filters=[LogFilter(field='host', op='contains', value='?web')]
            ),
            base_query=None,
            timestamp_field='@timestamp',
            message_field='message',
            ctx_vars={},
        )


def test_starts_with_uses_prefix() -> None:
    body = build_query_body(
        _make_query(
            filters=[LogFilter(field='host', op='starts_with', value='web')]
        ),
        base_query=None,
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={},
    )
    must = body['query']['bool']['must']  # type: ignore[index]
    assert any(c.get('prefix', {}).get('host') == 'web' for c in must)  # type: ignore[union-attr]


def test_regex_filter() -> None:
    body = build_query_body(
        _make_query(
            filters=[LogFilter(field='host', op='regex', value='web-[0-9]+')]
        ),
        base_query=None,
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={},
    )
    must = body['query']['bool']['must']  # type: ignore[index]
    assert any(c.get('regexp', {}).get('host') == 'web-[0-9]+' for c in must)  # type: ignore[union-attr]


def test_regex_leading_dotstar_raises() -> None:
    with pytest.raises(ValueError, match='leading wildcard'):
        build_query_body(
            _make_query(
                filters=[LogFilter(field='host', op='regex', value='.*web')]
            ),
            base_query=None,
            timestamp_field='@timestamp',
            message_field='message',
            ctx_vars={},
        )


def test_regex_leading_star_raises() -> None:
    with pytest.raises(ValueError):
        build_query_body(
            _make_query(
                filters=[LogFilter(field='host', op='regex', value='*web')]
            ),
            base_query=None,
            timestamp_field='@timestamp',
            message_field='message',
            ctx_vars={},
        )


def test_base_query_expands_template() -> None:
    body = build_query_body(
        _make_query(),
        base_query='${project_slug}-logs',
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={
            'project_slug': 'my-project',
            'org_slug': None,
            'environment': None,
            'project_id': None,
        },
    )
    must = body['query']['bool']['must']  # type: ignore[index]
    qs_clauses = [c for c in must if 'query_string' in c]  # type: ignore[union-attr]
    assert any(  # type: ignore[union-attr]
        c['query_string']['query'] == 'my-project-logs'  # type: ignore[index]
        for c in qs_clauses  # type: ignore[union-attr]
    )


def test_base_query_unknown_var_raises() -> None:
    with pytest.raises(ValueError):
        build_query_body(
            _make_query(),
            base_query='${unknown_var}',
            timestamp_field='@timestamp',
            message_field='message',
            ctx_vars={},
        )


def test_multiple_ne_filters_collected() -> None:
    body = build_query_body(
        _make_query(
            filters=[
                LogFilter(field='env', op='ne', value='dev'),
                LogFilter(field='env', op='ne', value='staging'),
            ]
        ),
        base_query=None,
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={},
    )
    must_not = body['query']['bool'].get('must_not', [])  # type: ignore[index,union-attr]
    assert len(must_not) == 2  # type: ignore[arg-type]


def test_cursor_round_trip() -> None:
    search_after: list[object] = [1735732800000, 5]
    fp = 'deadbeef12345678'
    token = encode_cursor(search_after, fp)
    assert decode_cursor(token, fp) == search_after


def test_cursor_no_padding_in_token() -> None:
    token = encode_cursor([1, 2], 'fp12345678901234')
    assert '=' not in token


def test_cursor_fp_mismatch_raises() -> None:
    token = encode_cursor([1, 2], 'fp1234567890abcd')
    with pytest.raises(CursorExpiredError):
        decode_cursor(token, 'different_fp1234')


def test_cursor_invalid_base64_raises() -> None:
    with pytest.raises(CursorExpiredError):
        decode_cursor('not!!!valid', 'fp')


def test_cursor_wrong_version_raises() -> None:
    import base64
    import json

    payload = json.dumps(
        {'v': 99, 'sa': [1], 'fp': 'fp'}, separators=(',', ':')
    ).encode()
    token = base64.urlsafe_b64encode(payload).decode().rstrip('=')
    with pytest.raises(CursorExpiredError):
        decode_cursor(token, 'fp')


def test_cursor_non_dict_json_raises() -> None:
    import base64
    import json

    payload = json.dumps([1, 2, 3], separators=(',', ':')).encode()
    token = base64.urlsafe_b64encode(payload).decode().rstrip('=')
    with pytest.raises(CursorExpiredError):
        decode_cursor(token, 'fp')


def test_cursor_missing_search_after_raises() -> None:
    import base64
    import json

    payload = json.dumps(
        {'v': 1, 'fp': 'fp12345678901234'}, separators=(',', ':')
    ).encode()
    token = base64.urlsafe_b64encode(payload).decode().rstrip('=')
    with pytest.raises(CursorExpiredError):
        decode_cursor(token, 'fp12345678901234')


def test_compute_fp_is_16_chars() -> None:
    fp = compute_fp({'query': {}, 'size': 10})
    assert len(fp) == 16


def test_compute_fp_is_deterministic() -> None:
    body: dict[str, object] = {
        'query': {'bool': {}},
        'size': 100,
        'sort': [{'@timestamp': 'desc'}],
    }
    assert compute_fp(body) == compute_fp(body)


def test_compute_fp_differs_for_different_bodies() -> None:
    assert compute_fp({'size': 10}) != compute_fp({'size': 20})


# ---------------------------------------------------------------------------
# _seconds_to_fixed_interval tests
# ---------------------------------------------------------------------------


def test_seconds_to_fixed_interval_seconds() -> None:
    assert _seconds_to_fixed_interval(30) == '30s'


def test_seconds_to_fixed_interval_one_second_minimum() -> None:
    assert _seconds_to_fixed_interval(0) == '1s'


def test_seconds_to_fixed_interval_minutes() -> None:
    # 90 s → ceil(90/60) = 2 m
    assert _seconds_to_fixed_interval(90) == '2m'


def test_seconds_to_fixed_interval_exact_minute() -> None:
    assert _seconds_to_fixed_interval(60) == '1m'


def test_seconds_to_fixed_interval_hours() -> None:
    # 3601 s → ceil(3601/60)=61 m → ceil(61/60)=2 h
    assert _seconds_to_fixed_interval(3601) == '2h'


def test_seconds_to_fixed_interval_exact_hour() -> None:
    assert _seconds_to_fixed_interval(3600) == '1h'


def test_seconds_to_fixed_interval_days() -> None:
    # 25*3600 s → ceil(90000/60)=1500 m → ceil(1500/60)=25 h → ceil(25/24)=2 d
    assert _seconds_to_fixed_interval(25 * 3600) == '2d'


def test_seconds_to_fixed_interval_exact_day() -> None:
    assert _seconds_to_fixed_interval(24 * 3600) == '1d'


# ---------------------------------------------------------------------------
# build_histogram_body tests
# ---------------------------------------------------------------------------


def _make_hist_query(**kwargs: object) -> LogQuery:
    defaults: dict[str, object] = {
        'start_time': datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        'end_time': datetime.datetime(2025, 1, 2, tzinfo=datetime.UTC),
        'filters': [],
        'limit': 10,
    }
    defaults.update(kwargs)
    return LogQuery(**defaults)  # type: ignore[arg-type]


def test_histogram_body_has_size_zero() -> None:
    body = build_histogram_body(
        _make_hist_query(),
        base_query=None,
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={},
    )
    assert body['size'] == 0


def test_histogram_body_has_date_histogram_agg() -> None:
    body = build_histogram_body(
        _make_hist_query(),
        base_query=None,
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={},
        bucket_count=60,
    )
    aggs = body['aggs']  # type: ignore[index]
    assert 'over_time' in aggs  # type: ignore[operator]
    assert 'date_histogram' in aggs['over_time']  # type: ignore[index]


def test_histogram_body_field_matches_timestamp_field() -> None:
    body = build_histogram_body(
        _make_hist_query(),
        base_query=None,
        timestamp_field='my_ts',
        message_field='message',
        ctx_vars={},
    )
    dh = body['aggs']['over_time']['date_histogram']  # type: ignore[index]
    assert dh['field'] == 'my_ts'  # type: ignore[index]


def test_histogram_body_ceiling_interval_never_exceeds_bucket_count() -> None:
    # 24h range, 60 buckets → ceil(86400/60)=1440s → ceil(1440/60)=24m.
    query = _make_hist_query(
        start_time=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        end_time=datetime.datetime(2025, 1, 2, tzinfo=datetime.UTC),
    )
    body = build_histogram_body(
        query,
        base_query=None,
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={},
        bucket_count=60,
    )
    dh = body['aggs']['over_time']['date_histogram']  # type: ignore[index]
    assert dh['fixed_interval'] == '24m'  # type: ignore[index]


def test_histogram_body_with_level_filter() -> None:
    body = build_histogram_body(
        _make_hist_query(),
        base_query=None,
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={},
        level_filter='ERROR',
        level_field='level',
    )
    must = body['query']['bool']['must']  # type: ignore[index]
    assert any(c.get('term', {}).get('level') == 'ERROR' for c in must)  # type: ignore[union-attr]


def test_histogram_body_without_level_filter_no_level_term() -> None:
    body = build_histogram_body(
        _make_hist_query(),
        base_query=None,
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={},
    )
    must = body['query']['bool']['must']  # type: ignore[index]
    assert not any('level' in c.get('term', {}) for c in must)  # type: ignore[union-attr]


def test_histogram_body_with_environment_field() -> None:
    body = build_histogram_body(
        _make_hist_query(),
        base_query=None,
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={},
        environment_field='env',
        environment_value='production',
    )
    must = body['query']['bool']['must']  # type: ignore[index]
    assert any(c.get('term', {}).get('env') == 'production' for c in must)  # type: ignore[union-attr]


def test_histogram_body_regex_leading_wildcard_raises() -> None:
    with pytest.raises(ValueError, match='leading wildcard'):
        build_histogram_body(
            _make_hist_query(
                filters=[LogFilter(field='host', op='regex', value='.*bad')]
            ),
            base_query=None,
            timestamp_field='@timestamp',
            message_field='message',
            ctx_vars={},
        )
