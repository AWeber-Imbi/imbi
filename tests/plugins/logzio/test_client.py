"""Tests for the Logz.io HTTP client wrapper."""

import httpx
import pytest
import respx
from imbi_common.plugins.errors import (
    PluginCredentialsMissing,
    PluginTimeoutError,
    PluginUnavailableError,
)

from imbi_plugin_logzio.client import (
    REGION_HOSTS,
    base_url,
    get_log_types,
    post_search,
)


def _empty_hits_payload() -> dict[str, object]:
    return {'hits': {'total': {'value': 0, 'relation': 'eq'}, 'hits': []}}


def test_region_us() -> None:
    assert base_url('us') == 'https://api.logz.io'


def test_region_eu() -> None:
    assert base_url('eu') == 'https://api-eu.logz.io'


def test_region_uk() -> None:
    assert base_url('uk') == 'https://api-uk.logz.io'


def test_region_au() -> None:
    assert base_url('au') == 'https://api-au.logz.io'


def test_region_ca() -> None:
    assert base_url('ca') == 'https://api-ca.logz.io'


def test_unknown_region_defaults_to_us() -> None:
    assert base_url('xx') == REGION_HOSTS['us']


@respx.mock
async def test_post_search_success() -> None:
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_empty_hits_payload())
    )
    result = await post_search(
        api_token='tok', region='us', body={}, timeout=5.0, version='test'
    )
    assert 'hits' in result


@respx.mock
async def test_post_search_sends_auth_header() -> None:
    route = respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_empty_hits_payload())
    )
    await post_search(
        api_token='my-token',
        region='us',
        body={},
        timeout=5.0,
        version='1.2.3',
    )
    req = route.calls[0].request  # type: ignore[union-attr]
    assert req.headers['X-API-TOKEN'] == 'my-token'  # type: ignore[index]
    assert req.headers['User-Agent'] == 'imbi-plugin-logzio/1.2.3'  # type: ignore[index]
    assert 'gzip' in req.headers['Accept-Encoding']  # type: ignore[operator]


@respx.mock
async def test_post_search_strips_token_whitespace() -> None:
    # A pasted token with surrounding whitespace must not produce an
    # illegal HTTP header value (h11 rejects it).
    route = respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_empty_hits_payload())
    )
    await post_search(
        api_token='  my-token\n',
        region='us',
        body={},
        timeout=5.0,
        version='1.2.3',
    )
    req = route.calls[0].request  # type: ignore[union-attr]
    assert req.headers['X-API-TOKEN'] == 'my-token'  # type: ignore[index]


@respx.mock
async def test_post_search_eu_region() -> None:
    route = respx.post('https://api-eu.logz.io/v1/search').mock(
        return_value=httpx.Response(200, json=_empty_hits_payload())
    )
    await post_search(
        api_token='tok', region='eu', body={}, timeout=5.0, version='test'
    )
    assert route.called


@respx.mock
async def test_post_search_401_raises_credentials_missing() -> None:
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(401)
    )
    with pytest.raises(PluginCredentialsMissing):
        await post_search(
            api_token='bad', region='us', body={}, timeout=5.0, version='test'
        )


@respx.mock
async def test_post_search_403_raises_credentials_missing() -> None:
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(403)
    )
    with pytest.raises(PluginCredentialsMissing):
        await post_search(
            api_token='bad', region='us', body={}, timeout=5.0, version='test'
        )


@respx.mock
async def test_post_search_429_raises_unavailable() -> None:
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(429)
    )
    with pytest.raises(PluginUnavailableError):
        await post_search(
            api_token='tok', region='us', body={}, timeout=5.0, version='test'
        )


@respx.mock
async def test_post_search_500_raises_unavailable() -> None:
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(500)
    )
    with pytest.raises(PluginUnavailableError):
        await post_search(
            api_token='tok', region='us', body={}, timeout=5.0, version='test'
        )


@respx.mock
async def test_post_search_timeout_raises_plugin_timeout() -> None:
    respx.post('https://api.logz.io/v1/search').mock(
        side_effect=httpx.TimeoutException('timed out')
    )
    with pytest.raises(PluginTimeoutError):
        await post_search(
            api_token='tok', region='us', body={}, timeout=1.0, version='test'
        )


@respx.mock
async def test_post_search_request_error_raises_unavailable() -> None:
    respx.post('https://api.logz.io/v1/search').mock(
        side_effect=httpx.ConnectError('connection refused')
    )
    with pytest.raises(PluginUnavailableError):
        await post_search(
            api_token='tok', region='us', body={}, timeout=5.0, version='test'
        )


@respx.mock
async def test_post_search_invalid_json_raises_unavailable() -> None:
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(200, content=b'not-json')
    )
    with pytest.raises(PluginUnavailableError):
        await post_search(
            api_token='tok', region='us', body={}, timeout=5.0, version='test'
        )


@respx.mock
async def test_get_log_types_list_response() -> None:
    respx.get('https://api.logz.io/v1/account/log-types').mock(
        return_value=httpx.Response(200, json=['syslog', 'nginx', 'apache'])
    )
    result = await get_log_types(
        api_token='tok', region='us', timeout=5.0, version='test'
    )
    assert result == ['syslog', 'nginx', 'apache']


@respx.mock
async def test_get_log_types_dict_response() -> None:
    respx.get('https://api.logz.io/v1/account/log-types').mock(
        return_value=httpx.Response(
            200, json={'logTypes': ['syslog', 'nginx']}
        )
    )
    result = await get_log_types(
        api_token='tok', region='us', timeout=5.0, version='test'
    )
    assert result == ['syslog', 'nginx']


@respx.mock
async def test_get_log_types_non_200_returns_none() -> None:
    respx.get('https://api.logz.io/v1/account/log-types').mock(
        return_value=httpx.Response(403)
    )
    result = await get_log_types(
        api_token='tok', region='us', timeout=5.0, version='test'
    )
    assert result is None


@respx.mock
async def test_get_log_types_network_error_returns_none() -> None:
    respx.get('https://api.logz.io/v1/account/log-types').mock(
        side_effect=httpx.NetworkError('unreachable')
    )
    result = await get_log_types(
        api_token='tok', region='us', timeout=5.0, version='test'
    )
    assert result is None


@respx.mock
async def test_get_log_types_timeout_returns_none() -> None:
    respx.get('https://api.logz.io/v1/account/log-types').mock(
        side_effect=httpx.TimeoutException('timed out')
    )
    result = await get_log_types(
        api_token='tok', region='us', timeout=1.0, version='test'
    )
    assert result is None


@respx.mock
async def test_get_log_types_unexpected_json_type_returns_none() -> None:
    respx.get('https://api.logz.io/v1/account/log-types').mock(
        return_value=httpx.Response(200, json='unexpected-string')
    )
    result = await get_log_types(
        api_token='tok', region='us', timeout=5.0, version='test'
    )
    assert result is None


@respx.mock
async def test_post_search_4xx_raises_unavailable() -> None:
    respx.post('https://api.logz.io/v1/search').mock(
        return_value=httpx.Response(400, json={'error': 'bad request'})
    )
    with pytest.raises(PluginUnavailableError) as exc_info:
        await post_search(
            api_token='tok', region='us', body={}, timeout=5.0, version='test'
        )
    assert 'bad request' in str(exc_info.value)
