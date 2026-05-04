"""End-to-end tests for LogzioPlugin.search() and .schema()."""

import datetime
import json

import httpx
import pytest
import respx
from imbi_common.plugins.base import LogFilter, LogQuery, PluginContext
from imbi_common.plugins.errors import (
    CursorExpiredError,
    PluginCredentialsMissing,
)

from imbi_plugin_logzio.plugin import LogzioPlugin
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
