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


def _headers(api_token: str) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {api_token}',
        'Accept': 'application/json',
        'User-Agent': f'imbi-plugin-sonarqube/{_VERSION}',
    }


async def search_project(
    *,
    base_url: str,
    api_token: str,
    key: str,
    timeout: float = 15.0,
) -> dict[str, typing.Any] | None:
    """Return the SonarQube project component for ``key``, or ``None``.

    Calls ``GET {base_url}/api/projects/search`` filtered by ``projects``
    and returns the component whose ``key`` matches exactly (the
    ``projects`` filter can return prefix-ish matches, so the exact key is
    confirmed client-side).  A well-formed 2xx response with no matching
    component yields ``None`` -- that is the "does not exist" signal the
    doctor acts on, not an error.  Raises :class:`SonarqubeClientError` on
    transport / non-2xx failure (e.g. a rejected token).
    """
    url = base_url.rstrip('/') + '/api/projects/search'
    params = {'projects': key}
    try:
        async with httpx.AsyncClient(timeout=timeout) as http_client:
            response = await http_client.get(
                url, params=params, headers=_headers(api_token)
            )
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
        payload = typing.cast('dict[str, typing.Any]', response.json())
    except ValueError as exc:
        raise SonarqubeClientError(
            'SonarQube returned non-JSON response'
        ) from exc
    components_obj = payload.get('components', [])
    if not isinstance(components_obj, list):
        return None
    for component_obj in typing.cast('list[object]', components_obj):
        if not isinstance(component_obj, dict):
            continue
        component = typing.cast('dict[str, typing.Any]', component_obj)
        if component.get('key') == key:
            return component
    return None


async def create_project(
    *,
    base_url: str,
    api_token: str,
    key: str,
    name: str,
    timeout: float = 15.0,
) -> dict[str, typing.Any]:
    """Create a SonarQube project and return its component payload.

    Calls ``POST {base_url}/api/projects/create`` with the ``project``
    (key) and ``name`` parameters and returns the ``project`` object from
    the response.  Raises :class:`SonarqubeClientError` on transport /
    non-2xx failure (e.g. a duplicate key or insufficient permission).
    """
    url = base_url.rstrip('/') + '/api/projects/create'
    params = {'project': key, 'name': name}
    try:
        async with httpx.AsyncClient(timeout=timeout) as http_client:
            response = await http_client.post(
                url, params=params, headers=_headers(api_token)
            )
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
        payload = typing.cast('dict[str, typing.Any]', response.json())
    except ValueError as exc:
        raise SonarqubeClientError(
            'SonarQube returned non-JSON response'
        ) from exc
    project_obj = payload.get('project')
    if isinstance(project_obj, dict):
        return typing.cast('dict[str, typing.Any]', project_obj)
    return {}
