"""Logz.io HTTP client: region resolution, auth, error mapping."""

import logging
from typing import cast

import httpx
from imbi_common.plugins.errors import (
    PluginCredentialsMissing,
    PluginTimeoutError,
    PluginUnavailableError,
)

LOGGER = logging.getLogger(__name__)

REGION_HOSTS: dict[str, str] = {
    'us': 'https://api.logz.io',
    'eu': 'https://api-eu.logz.io',
    'uk': 'https://api-uk.logz.io',
    'au': 'https://api-au.logz.io',
    'ca': 'https://api-ca.logz.io',
}

_DEFAULT_REGION = 'us'


def base_url(region: str) -> str:
    return REGION_HOSTS.get(region, REGION_HOSTS[_DEFAULT_REGION])


def _build_headers(api_token: str, version: str) -> dict[str, str]:
    return {
        'X-API-TOKEN': api_token,
        'Content-Type': 'application/json',
        'Accept-Encoding': 'deflate, gzip',
        'User-Agent': f'imbi-plugin-logzio/{version}',
    }


def _log_error(response: httpx.Response) -> None:
    request = response.request
    request_body = ''
    if request.content:
        try:
            request_body = request.content.decode('utf-8', errors='replace')
        except (AttributeError, UnicodeDecodeError):
            request_body = repr(request.content)
    LOGGER.error(
        'Logz.io %s %s returned %d: request_body=%s response_body=%s',
        request.method,
        request.url,
        response.status_code,
        request_body,
        response.text,
    )


def _check_response(response: httpx.Response) -> None:
    status = response.status_code
    if status in (401, 403):
        _log_error(response)
        raise PluginCredentialsMissing('Invalid or missing Logz.io API token')
    if status == 429 or status >= 500:
        _log_error(response)
        raise PluginUnavailableError(f'Logz.io returned status {status}')
    if 400 <= status < 500:
        _log_error(response)
        raise PluginUnavailableError(
            f'Logz.io returned status {status}: {response.text}'
        )


async def post_search(
    *,
    api_token: str,
    region: str,
    body: dict[str, object],
    timeout: float,
    version: str,
    day_offset: int = 0,
) -> dict[str, object]:
    url = f'{base_url(region)}/v1/search'
    if day_offset > 0:
        url = f'{url}?dayOffset={day_offset}'
    headers = _build_headers(api_token, version)
    LOGGER.debug('Logz.io POST %s body=%s', url, body)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, json=body, headers=headers, timeout=timeout
            )
    except httpx.TimeoutException as exc:
        raise PluginTimeoutError('Logz.io request timed out') from exc
    except httpx.RequestError as exc:
        raise PluginUnavailableError(f'Logz.io request failed: {exc}') from exc
    _check_response(response)
    try:
        result: dict[str, object] = response.json()
    except ValueError as exc:
        raise PluginUnavailableError(
            'Logz.io returned non-JSON response'
        ) from exc
    return result


async def get_log_types(
    *,
    api_token: str,
    region: str,
    timeout: float,
    version: str,
) -> list[str] | None:
    url = f'{base_url(region)}/v1/account/log-types'
    headers = _build_headers(api_token, version)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=timeout)
        if response.status_code != 200:
            return None
        data: object = response.json()
        if isinstance(data, list):
            return [str(t) for t in cast('list[object]', data) if t]
        if isinstance(data, dict):
            data_dict = cast('dict[str, object]', data)
            items: object = (
                data_dict.get('logTypes') or data_dict.get('log_types') or []
            )
            if isinstance(items, list):
                return [str(t) for t in cast('list[object]', items) if t]
        return None
    except (httpx.HTTPError, ValueError, KeyError, OSError):
        return None
