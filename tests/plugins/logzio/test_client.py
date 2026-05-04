"""Tests for the Logz.io HTTP client wrapper."""

import json

import httpx
import pytest
import respx
from imbi_common.plugins.errors import (
    CursorExpiredError,
    PluginCredentialsMissing,
    PluginTimeoutError,
    PluginUnavailableError,
)

from imbi_plugin_logzio.client import (
    REGION_HOSTS,
    base_url,
    get_log_types,
    post_scroll,
)


def _empty_hits_payload(scroll_id: str = 'sid') -> dict[str, object]:
    inner = {'hits': {'total': 0, 'hits': []}}
    return {'scrollId': scroll_id, 'hits': json.dumps(inner)}


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
async def test_post_scroll_success() -> None:
    respx.post('https://api.logz.io/v1/scroll').mock(
        return_value=httpx.Response(200, json=_empty_hits_payload('new-sid'))
    )
    result = await post_scroll(
        api_token='tok', region='us', body={}, timeout=5.0, version='test'
    )
    assert result['scrollId'] == 'new-sid'


@respx.mock
async def test_post_scroll_sends_auth_header() -> None:
    route = respx.post('https://api.logz.io/v1/scroll').mock(
        return_value=httpx.Response(200, json=_empty_hits_payload())
    )
    await post_scroll(
        api_token='my-token',
        region='us',
        body={},
        timeout=5.0,
        version='1.2.3',
    )
    req = route.calls[0].request
    assert req.headers['X-API-TOKEN'] == 'my-token'
    assert req.headers['User-Agent'] == 'imbi-plugin-logzio/1.2.3'
    assert 'gzip' in req.headers['Accept-Encoding']


@respx.mock
async def test_post_scroll_eu_region() -> None:
    route = respx.post('https://api-eu.logz.io/v1/scroll').mock(
        return_value=httpx.Response(200, json=_empty_hits_payload())
    )
    await post_scroll(
        api_token='tok', region='eu', body={}, timeout=5.0, version='test'
    )
    assert route.called


@respx.mock
async def test_post_scroll_401_raises_credentials_missing() -> None:
    respx.post('https://api.logz.io/v1/scroll').mock(
        return_value=httpx.Response(401)
    )
    with pytest.raises(PluginCredentialsMissing):
        await post_scroll(
            api_token='bad', region='us', body={}, timeout=5.0, version='test'
        )


@respx.mock
async def test_post_scroll_403_raises_credentials_missing() -> None:
    respx.post('https://api.logz.io/v1/scroll').mock(
        return_value=httpx.Response(403)
    )
    with pytest.raises(PluginCredentialsMissing):
        await post_scroll(
            api_token='bad', region='us', body={}, timeout=5.0, version='test'
        )


@respx.mock
async def test_post_scroll_429_raises_unavailable() -> None:
    respx.post('https://api.logz.io/v1/scroll').mock(
        return_value=httpx.Response(429)
    )
    with pytest.raises(PluginUnavailableError):
        await post_scroll(
            api_token='tok', region='us', body={}, timeout=5.0, version='test'
        )


@respx.mock
async def test_post_scroll_500_raises_unavailable() -> None:
    respx.post('https://api.logz.io/v1/scroll').mock(
        return_value=httpx.Response(500)
    )
    with pytest.raises(PluginUnavailableError):
        await post_scroll(
            api_token='tok', region='us', body={}, timeout=5.0, version='test'
        )


@respx.mock
async def test_post_scroll_scroll_expired_in_body_raises_cursor_expired() -> (
    None
):
    respx.post('https://api.logz.io/v1/scroll').mock(
        return_value=httpx.Response(404, text='scroll context has expired')
    )
    with pytest.raises(CursorExpiredError):
        await post_scroll(
            api_token='tok',
            region='us',
            body={'scroll_id': 'old'},
            timeout=5.0,
            version='test',
        )


@respx.mock
async def test_post_scroll_timeout_raises_plugin_timeout() -> None:
    respx.post('https://api.logz.io/v1/scroll').mock(
        side_effect=httpx.TimeoutException('timed out')
    )
    with pytest.raises(PluginTimeoutError):
        await post_scroll(
            api_token='tok', region='us', body={}, timeout=1.0, version='test'
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
async def test_post_scroll_4xx_non_scroll_reraises() -> None:
    respx.post('https://api.logz.io/v1/scroll').mock(
        return_value=httpx.Response(400, json={'error': 'bad request'})
    )
    with pytest.raises(httpx.HTTPStatusError):
        await post_scroll(
            api_token='tok', region='us', body={}, timeout=5.0, version='test'
        )
