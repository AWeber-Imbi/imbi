"""End-to-end tests for LogzioPlugin.search(), .histogram(), and .schema()."""

import datetime
import json

import httpx
import pytest
import respx
from imbi_common.plugins.base import (
    LogFilter,
    LogHistogramBucket,
    LogQuery,
    PluginContext,
)
from imbi_common.plugins.errors import (
    CursorExpiredError,
    PluginCredentialsMissing,
)

from imbi_plugin_logzio.plugin import (
    LogzioPlugin,
    _merge_histogram_totals,
    _overlay_histogram_levels,
    _parse_histogram,
)
from imbi_plugin_logzio.query import (
    build_query_body,
    compute_fp,
    encode_cursor,
)

_CREDS = {'api_token': 'test-token'}

_DEFAULT_OPTS: dict[str, object] = {
    'region': 'us',
    'timestamp_field': '@timestamp',
    'message_field': 'message',
    'level_field': 'level',
    'timeout_seconds': 5,
}


def _make_ctx(**opts: object) -> PluginContext:
    assignment_options = {**_DEFAULT_OPTS, **opts}
    return PluginContext(
        project_id='42',
        project_slug='my-project',
        org_slug='my-org',
        environment='production',
        assignment_options=assignment_options,
    )


def _make_query(**kwargs: object) -> LogQuery:
    defaults: dict[str, object] = {
        'start_time': datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        'end_time': datetime.datetime(2025, 1, 2, tzinfo=datetime.UTC),
        'limit': 10,
    }
    defaults.update(kwargs)
    return LogQuery(**defaults)  # type: ignore[arg-type]


def _hits_response(
    hits: list[object],
    total: object = 100,
) -> dict[str, object]:
    return {
        'hits': {
            'total': {'value': total, 'relation': 'eq'},
            'hits': hits,
        }
    }


def _source_hit(
    message: str = 'hello',
    level: str = 'info',
    ts: str = '2025-01-01T12:00:00Z',
    sort: list[object] | None = None,
) -> dict[str, object]:
    hit: dict[str, object] = {
        '_source': {'@timestamp': ts, 'message': message, 'level': level}
    }
    if sort is not None:
        hit['sort'] = sort
    return hit


async def test_search_missing_token_raises() -> None:
    plugin = LogzioPlugin()
    with pytest.raises(PluginCredentialsMissing):
        await plugin.search(_make_ctx(), {}, _make_query())


async def test_search_empty_token_raises() -> None:
    plugin = LogzioPlugin()
    with pytest.raises(PluginCredentialsMissing):
        await plugin.search(_make_ctx(), {'api_token': ''}, _make_query())


@respx.mock
async def test_search_initial_returns_entries() -> None:
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_hits_response([_source_hit()]))
    )
    plugin = LogzioPlugin()
    result = await plugin.search(_make_ctx(), _CREDS, _make_query(limit=1))
    assert len(result.entries) == 1
    assert result.entries[0].message == 'hello'
    assert result.entries[0].level == 'info'


@respx.mock
async def test_search_full_page_sets_next_cursor() -> None:
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(
            200,
            json=_hits_response([_source_hit(sort=[1735732800000, 0])]),
        )
    )
    plugin = LogzioPlugin()
    result = await plugin.search(_make_ctx(), _CREDS, _make_query(limit=1))
    assert result.next_cursor is not None


@respx.mock
async def test_search_partial_page_no_next_cursor() -> None:
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_hits_response([_source_hit()]))
    )
    plugin = LogzioPlugin()
    result = await plugin.search(_make_ctx(), _CREDS, _make_query(limit=10))
    assert result.next_cursor is None


@respx.mock
async def test_search_empty_page_no_next_cursor() -> None:
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_hits_response([]))
    )
    plugin = LogzioPlugin()
    result = await plugin.search(_make_ctx(), _CREDS, _make_query(limit=10))
    assert result.next_cursor is None
    assert result.entries == []


@respx.mock
async def test_search_with_cursor_sends_search_after() -> None:
    route = respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_hits_response([_source_hit()]))
    )
    ctx = _make_ctx()
    query = _make_query(limit=1)

    body = build_query_body(
        query,
        base_query=None,
        timestamp_field='@timestamp',
        message_field='message',
        ctx_vars={
            'project_slug': ctx.project_slug,
            'org_slug': ctx.org_slug,
            'environment': ctx.environment,
            'project_id': ctx.project_id,
        },
    )
    fp = compute_fp(body)
    cursor = encode_cursor([1735732800000, 5], fp)

    plugin = LogzioPlugin()
    await plugin.search(ctx, _CREDS, _make_query(limit=1, cursor=cursor))

    req_body = json.loads(route.calls[0].request.content)  # type: ignore[union-attr]
    assert req_body['search_after'] == [1735732800000, 5]
    assert 'query' in req_body


async def test_search_bad_cursor_token_raises() -> None:
    plugin = LogzioPlugin()
    with pytest.raises(CursorExpiredError):
        await plugin.search(
            _make_ctx(),
            _CREDS,
            _make_query(limit=1, cursor='not-a-valid-cursor!!!'),
        )


@respx.mock
async def test_search_total_dict_format() -> None:
    payload: dict[str, object] = {
        'hits': {'total': {'value': 42, 'relation': 'eq'}, 'hits': []}
    }
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=payload)
    )
    plugin = LogzioPlugin()
    result = await plugin.search(_make_ctx(), _CREDS, _make_query())
    assert result.total == 42


@respx.mock
async def test_search_total_int_format() -> None:
    payload: dict[str, object] = {'hits': {'total': 99, 'hits': []}}
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=payload)
    )
    plugin = LogzioPlugin()
    result = await plugin.search(_make_ctx(), _CREDS, _make_query())
    assert result.total == 99


@respx.mock
async def test_search_timestamp_parsed() -> None:
    hit = {
        '_source': {
            '@timestamp': '2025-01-15T10:30:00+00:00',
            'message': 'ts test',
        }
    }
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_hits_response([hit]))
    )
    plugin = LogzioPlugin()
    result = await plugin.search(_make_ctx(), _CREDS, _make_query())
    assert result.entries[0].timestamp.year == 2025
    assert result.entries[0].timestamp.month == 1
    assert result.entries[0].timestamp.day == 15


@respx.mock
async def test_search_missing_timestamp_defaults_to_utc_now() -> None:
    hit: dict[str, object] = {'_source': {'message': 'no ts'}}
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_hits_response([hit]))
    )
    plugin = LogzioPlugin()
    result = await plugin.search(_make_ctx(), _CREDS, _make_query())
    assert result.entries[0].timestamp.tzinfo is not None


@respx.mock
async def test_search_custom_level_field() -> None:
    hit = {
        '_source': {
            '@timestamp': '2025-01-01T00:00:00Z',
            'message': 'hi',
            'severity': 'WARN',
        }
    }
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_hits_response([hit]))
    )
    plugin = LogzioPlugin()
    ctx = _make_ctx(level_field='severity')
    result = await plugin.search(ctx, _CREDS, _make_query())
    assert result.entries[0].level == 'WARN'


@respx.mock
async def test_search_raw_contains_full_source() -> None:
    source = {
        '@timestamp': '2025-01-01T00:00:00Z',
        'message': 'hi',
        'custom': 'value',
    }
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(
            200, json=_hits_response([{'_source': source}])
        )
    )
    plugin = LogzioPlugin()
    result = await plugin.search(_make_ctx(), _CREDS, _make_query())
    assert result.entries[0].raw['custom'] == 'value'


@respx.mock
async def test_search_with_filter() -> None:
    route = respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_hits_response([]))
    )
    plugin = LogzioPlugin()
    query = _make_query(
        filters=[LogFilter(field='env', op='eq', value='prod')]
    )
    await plugin.search(_make_ctx(), _CREDS, query)

    req_body = json.loads(route.calls[0].request.content)  # type: ignore[union-attr]
    must = req_body['query']['bool']['must']
    assert any(c.get('term', {}).get('env') == 'prod' for c in must)


@respx.mock
async def test_schema_with_log_types() -> None:
    respx.get('https://api.logz.io/v1/account/log-types').mock(
        return_value=httpx.Response(200, json=['syslog', 'nginx'])
    )
    plugin = LogzioPlugin()
    fields = await plugin.schema(_make_ctx(), _CREDS)
    type_field = next(f for f in fields if f['name'] == 'type')
    assert type_field.get('choices') == ['syslog', 'nginx']


@respx.mock
async def test_schema_log_types_error_returns_baseline() -> None:
    respx.get('https://api.logz.io/v1/account/log-types').mock(
        return_value=httpx.Response(500)
    )
    plugin = LogzioPlugin()
    fields = await plugin.schema(_make_ctx(), _CREDS)
    type_field = next(f for f in fields if f['name'] == 'type')
    assert 'choices' not in type_field


async def test_schema_no_token_returns_baseline() -> None:
    plugin = LogzioPlugin()
    fields = await plugin.schema(_make_ctx(), {})
    assert any(f['name'] == '@timestamp' for f in fields)
    assert any(f['name'] == 'message' for f in fields)
    assert any(f['name'] == 'level' for f in fields)


async def test_schema_baseline_field_count() -> None:
    plugin = LogzioPlugin()
    fields = await plugin.schema(_make_ctx(), {})
    assert len(fields) == 8


@respx.mock
async def test_search_with_base_query_option() -> None:
    route = respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_hits_response([]))
    )
    plugin = LogzioPlugin()
    ctx = _make_ctx(base_query='${project_slug}-*')
    await plugin.search(ctx, _CREDS, _make_query())

    req_body = json.loads(route.calls[0].request.content)  # type: ignore[union-attr]
    must = req_body['query']['bool']['must']
    qs = [c for c in must if 'query_string' in c]
    assert any('my-project-*' in c['query_string']['query'] for c in qs)


@respx.mock
async def test_search_naive_timestamp_gets_utc() -> None:
    hit = {
        '_source': {'@timestamp': '2025-01-01T12:00:00', 'message': 'no tz'}
    }
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_hits_response([hit]))
    )
    plugin = LogzioPlugin()
    result = await plugin.search(_make_ctx(), _CREDS, _make_query())
    assert result.entries[0].timestamp.tzinfo is not None


@respx.mock
async def test_search_invalid_timestamp_defaults_to_now() -> None:
    hit = {'_source': {'@timestamp': 'not-a-date', 'message': 'bad ts'}}
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_hits_response([hit]))
    )
    plugin = LogzioPlugin()
    result = await plugin.search(_make_ctx(), _CREDS, _make_query())
    assert result.entries[0].timestamp.tzinfo is not None


@respx.mock
async def test_search_total_missing_returns_none() -> None:
    payload: dict[str, object] = {'hits': {'hits': []}}
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=payload)
    )
    plugin = LogzioPlugin()
    result = await plugin.search(_make_ctx(), _CREDS, _make_query())
    assert result.total is None


# ---------------------------------------------------------------------------
# _parse_histogram unit tests
# ---------------------------------------------------------------------------


def _agg_response(buckets: list[dict[str, object]]) -> dict[str, object]:
    return {'aggregations': {'over_time': {'buckets': buckets}}}


def _bucket(key_ms: int, count: int) -> dict[str, object]:
    return {'key': key_ms, 'doc_count': count}


def test_parse_histogram_empty_response() -> None:
    assert _parse_histogram({}) == []


def test_parse_histogram_missing_aggregations() -> None:
    assert _parse_histogram({'aggregations': 'bad'}) == []


def test_parse_histogram_missing_over_time() -> None:
    assert _parse_histogram({'aggregations': {}}) == []


def test_parse_histogram_empty_buckets() -> None:
    assert _parse_histogram(_agg_response([])) == []


def test_parse_histogram_valid_bucket() -> None:
    key_ms = 1735689600000  # 2025-01-01T00:00:00Z
    result = _parse_histogram(_agg_response([_bucket(key_ms, 42)]))
    assert len(result) == 1
    assert result[0].count == 42
    expected_ts = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    assert result[0].timestamp == expected_ts


def test_parse_histogram_skips_non_dict_buckets() -> None:
    response: dict[str, object] = {
        'aggregations': {
            'over_time': {'buckets': ['bad', _bucket(1735689600000, 1)]}
        }
    }
    result = _parse_histogram(response)
    assert len(result) == 1


def test_parse_histogram_skips_buckets_missing_key() -> None:
    response: dict[str, object] = {
        'aggregations': {'over_time': {'buckets': [{'doc_count': 5}]}}
    }
    assert _parse_histogram(response) == []


# ---------------------------------------------------------------------------
# _merge_histogram_totals unit tests
# ---------------------------------------------------------------------------

_START = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
_END = datetime.datetime(2025, 1, 2, tzinfo=datetime.UTC)
_KEY_MS = 1735689600000  # 2025-01-01T00:00:00Z in range
_KEY_MS_OUT = 1735862400000  # 2025-01-03T00:00:00Z out of range


def test_merge_histogram_totals_aggregates_duplicate_timestamps() -> None:
    resp = _agg_response([_bucket(_KEY_MS, 10)])
    # Two "total" (label=None) responses for the same timestamp → aggregate.
    labels: list[str | None] = [None, None]
    responses: list[object] = [resp, resp]
    by_ts = _merge_histogram_totals(labels, responses, _START, _END)
    ts = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    assert by_ts[ts].count == 20


def test_merge_histogram_totals_skips_out_of_range() -> None:
    resp = _agg_response([_bucket(_KEY_MS_OUT, 5)])
    labels: list[str | None] = [None]
    responses: list[object] = [resp]
    by_ts = _merge_histogram_totals(labels, responses, _START, _END)
    assert by_ts == {}


def test_merge_histogram_totals_skips_level_labels() -> None:
    resp = _agg_response([_bucket(_KEY_MS, 7)])
    labels: list[str | None] = ['ERROR']
    responses: list[object] = [resp]
    by_ts = _merge_histogram_totals(labels, responses, _START, _END)
    assert by_ts == {}


def test_merge_histogram_totals_logs_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    labels: list[str | None] = [None]
    responses: list[object] = [ValueError('boom')]
    with caplog.at_level(logging.WARNING):
        by_ts = _merge_histogram_totals(labels, responses, _START, _END)
    assert by_ts == {}
    assert 'boom' in caplog.text


def test_merge_histogram_totals_skips_non_dict_response() -> None:
    labels: list[str | None] = [None]
    responses: list[object] = ['not-a-dict']
    by_ts = _merge_histogram_totals(labels, responses, _START, _END)
    assert by_ts == {}


# ---------------------------------------------------------------------------
# _overlay_histogram_levels unit tests
# ---------------------------------------------------------------------------


def _make_by_ts(
    count: int = 100,
) -> dict[datetime.datetime, LogHistogramBucket]:
    ts = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    return {ts: LogHistogramBucket(timestamp=ts, count=count)}


def test_overlay_histogram_levels_sets_level_count() -> None:
    resp = _agg_response([_bucket(_KEY_MS, 5)])
    by_ts = _make_by_ts()
    labels: list[str | None] = [None, 'ERROR']
    responses: list[object] = [_agg_response([_bucket(_KEY_MS, 100)]), resp]
    _overlay_histogram_levels(labels, responses, by_ts)
    ts = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    assert by_ts[ts].levels.get('ERROR') == 5


def test_overlay_histogram_levels_aggregates_across_shards() -> None:
    resp = _agg_response([_bucket(_KEY_MS, 3)])
    by_ts = _make_by_ts()
    labels: list[str | None] = ['ERROR', 'ERROR']
    responses: list[object] = [resp, resp]
    _overlay_histogram_levels(labels, responses, by_ts)
    ts = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    assert by_ts[ts].levels.get('ERROR') == 6


def test_overlay_histogram_levels_skips_missing_timestamp() -> None:
    # Bucket timestamp not present in by_ts → should not raise or create entry.
    resp = _agg_response([_bucket(_KEY_MS_OUT, 9)])
    by_ts = _make_by_ts()
    labels: list[str | None] = ['INFO']
    responses: list[object] = [resp]
    _overlay_histogram_levels(labels, responses, by_ts)
    ts = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    assert 'INFO' not in by_ts[ts].levels


def test_overlay_histogram_levels_logs_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    by_ts = _make_by_ts()
    labels: list[str | None] = ['WARN']
    responses: list[object] = [RuntimeError('shard down')]
    with caplog.at_level(logging.WARNING):
        _overlay_histogram_levels(labels, responses, by_ts)
    assert 'shard down' in caplog.text


def test_overlay_histogram_levels_skips_non_dict_response() -> None:
    by_ts = _make_by_ts()
    labels: list[str | None] = ['DEBUG']
    responses: list[object] = ['not-a-dict']
    _overlay_histogram_levels(labels, responses, by_ts)
    ts = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
    assert 'DEBUG' not in by_ts[ts].levels


# ---------------------------------------------------------------------------
# histogram() integration tests
# ---------------------------------------------------------------------------


def _histogram_response(
    key_ms: int = _KEY_MS, count: int = 10
) -> dict[str, object]:
    return _agg_response([_bucket(key_ms, count)])


@respx.mock
async def test_histogram_missing_token_raises() -> None:
    plugin = LogzioPlugin()
    with pytest.raises(PluginCredentialsMissing):
        await plugin.histogram(_make_ctx(), {}, _make_query())


@respx.mock
async def test_histogram_returns_sorted_buckets() -> None:
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_histogram_response())
    )
    plugin = LogzioPlugin()
    # Use a past date so that end_offset and start_offset are positive.
    query = _make_query(
        start_time=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        end_time=datetime.datetime(2025, 1, 2, tzinfo=datetime.UTC),
    )
    buckets = await plugin.histogram(
        _make_ctx(), _CREDS, query, bucket_count=10
    )
    assert isinstance(buckets, list)
    # Buckets should be in ascending timestamp order.
    timestamps = [b.timestamp for b in buckets]
    assert timestamps == sorted(timestamps)


@respx.mock
async def test_histogram_filters_out_of_range_buckets() -> None:
    # Return a bucket whose timestamp is outside the query range.
    out_of_range_ms = int(
        datetime.datetime(2020, 6, 1, tzinfo=datetime.UTC).timestamp() * 1000
    )
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(
            200, json=_histogram_response(out_of_range_ms)
        )
    )
    plugin = LogzioPlugin()
    query = _make_query(
        start_time=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        end_time=datetime.datetime(2025, 1, 2, tzinfo=datetime.UTC),
    )
    buckets = await plugin.histogram(_make_ctx(), _CREDS, query)
    assert buckets == []


@respx.mock
async def test_histogram_tolerates_failed_shards() -> None:
    # First call succeeds, subsequent calls fail.
    call_count = 0

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json=_histogram_response())
        return httpx.Response(500)

    respx.post('https://api.logz.io/v1/search').mock(side_effect=side_effect)
    plugin = LogzioPlugin()
    query = _make_query(
        start_time=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        end_time=datetime.datetime(2025, 1, 2, tzinfo=datetime.UTC),
    )
    # Should not raise even if some shards fail.
    buckets = await plugin.histogram(_make_ctx(), _CREDS, query)
    assert isinstance(buckets, list)


@respx.mock
async def test_histogram_environment_field_option() -> None:
    route = respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_histogram_response())
    )
    plugin = LogzioPlugin()
    ctx = _make_ctx(environment_field='env')
    query = _make_query(
        start_time=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        end_time=datetime.datetime(2025, 1, 2, tzinfo=datetime.UTC),
    )
    await plugin.histogram(ctx, _CREDS, query)
    req_body = json.loads(route.calls[0].request.content)  # type: ignore[union-attr]
    must = req_body['query']['bool']['must']
    assert any(c.get('term', {}).get('env') == 'production' for c in must)


@respx.mock
async def test_histogram_dayoffset_url_for_old_range() -> None:
    """Verify that older ranges generate dayOffset query params."""
    captured_urls: list[str] = []

    def capture(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        return httpx.Response(200, json=_histogram_response())

    respx.post('https://api.logz.io/v1/search').mock(side_effect=capture)
    plugin = LogzioPlugin()
    # A very old range → multiple dayOffset windows.
    query = _make_query(
        start_time=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        end_time=datetime.datetime(2025, 1, 5, tzinfo=datetime.UTC),
    )
    await plugin.histogram(_make_ctx(), _CREDS, query)
    # At least one request should carry a dayOffset param.
    assert any('dayOffset' in url for url in captured_urls)
