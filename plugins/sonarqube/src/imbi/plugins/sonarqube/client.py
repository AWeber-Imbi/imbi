"""SonarQube HTTP client used by the webhook action."""

import importlib.metadata
import logging
import typing
from collections import abc

import httpx

LOGGER = logging.getLogger(__name__)

_VERSION = importlib.metadata.version('imbi-plugin-sonarqube')


class SonarqubeClientError(Exception):
    """Raised on non-2xx responses or transport errors."""


async def fetch_component_measures(
    *,
    base_url: str,
    api_token: str,
    component: str,
    metric_keys: abc.Sequence[str],
    timeout: float = 15.0,
) -> dict[str, typing.Any]:
    """Fetch SonarQube component measures.

    Calls ``GET {base_url}/api/measures/component`` with the
    ``component`` and ``metricKeys`` query parameters and a Bearer
    authorization header.  Returns the parsed JSON response on success
    or raises :class:`SonarqubeClientError` on transport / non-2xx
    failure.
    """
    url = base_url.rstrip('/') + '/api/measures/component'
    params = {
        'component': component,
        'metricKeys': ','.join(metric_keys),
    }
    headers = {
        'Authorization': f'Bearer {api_token}',
        'Accept': 'application/json',
        'User-Agent': f'imbi-plugin-sonarqube/{_VERSION}',
    }
    LOGGER.debug('SonarQube GET %s params=%s', url, params)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params=params, headers=headers)
    except httpx.RequestError as exc:
        raise SonarqubeClientError(f'SonarQube request failed: {exc}') from exc
    if response.is_error:
        LOGGER.warning(
            'SonarQube %s %s returned %d: %s',
            response.request.method,
            response.request.url,
            response.status_code,
            response.text,
        )
        raise SonarqubeClientError(
            f'SonarQube returned status {response.status_code}'
        )
    try:
        return typing.cast('dict[str, typing.Any]', response.json())
    except ValueError as exc:
        raise SonarqubeClientError(
            'SonarQube returned non-JSON response'
        ) from exc
