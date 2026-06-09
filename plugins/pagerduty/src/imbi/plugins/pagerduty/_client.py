"""Shared PagerDuty REST client for the plugin family.

PagerDuty is cloud-only (a single ``api.pagerduty.com`` host), so unlike
the GitHub plugins there is no host-flavor routing -- every plugin uses
the same base URL and a REST API key credential.

The client converts the two responses the host cares about into the
shared plugin exceptions via an httpx response hook:

* ``401`` -> :class:`PluginAuthenticationFailed` (a bad / revoked REST
  key; surfaces to the operator rather than 500ing the request).
* ``429`` -> :class:`PluginRateLimited` carrying the absolute epoch to
  resume from, derived from ``ratelimit-reset`` (seconds-until-reset) or
  a ``retry-after`` header, so the host's sync fan-out can back off
  instead of hammering the 960 req/min per-key limit.
"""

from __future__ import annotations

import time

import httpx
from imbi_common.plugins.errors import (
    PluginAuthenticationFailed,
    PluginRateLimited,
)

API_BASE = 'https://api.pagerduty.com'
_HTTP_TIMEOUT_SECONDS = 10.0
#: Small cushion added to a rate-limit reset so the resume lands just
#: after the window rolls over rather than on the boundary.
_RATE_LIMIT_PADDING_SECONDS = 1.0


def _retry_at(response: httpx.Response) -> float:
    """Absolute epoch to resume from after a 429, from the headers."""
    for header in ('ratelimit-reset', 'retry-after'):
        raw = response.headers.get(header)
        if raw is None:
            continue
        try:
            seconds = max(0.0, float(raw))
        except ValueError:
            continue
        return time.time() + seconds + _RATE_LIMIT_PADDING_SECONDS
    # No usable header: PagerDuty's window is one minute, so wait that.
    return time.time() + 60.0


async def _raise_on_error(response: httpx.Response) -> None:
    """Map auth / rate-limit responses to shared plugin exceptions."""
    if response.status_code == 401:
        await response.aread()
        raise PluginAuthenticationFailed(
            f'PagerDuty 401 from {response.request.url}: {response.text}'
        )
    if response.status_code == 429:
        await response.aread()
        raise PluginRateLimited(
            _retry_at(response),
            f'PagerDuty rate limit hit at {response.request.url}',
        )


def api_key(credentials: dict[str, str]) -> str:
    """Return the REST API key from ``credentials`` or raise.

    The manifest declares an ``api_key`` credential field; the host
    decrypts the plugin configuration and passes it through here.
    """
    key = credentials.get('api_key')
    if not key:
        raise ValueError(
            'PagerDuty plugin requires a REST API key; expected '
            '``credentials["api_key"]``'
        )
    return key


def client(credentials: dict[str, str]) -> httpx.AsyncClient:
    """Build an :class:`httpx.AsyncClient` for the PagerDuty REST API."""
    return httpx.AsyncClient(
        base_url=API_BASE,
        timeout=_HTTP_TIMEOUT_SECONDS,
        headers={
            'Authorization': f'Token token={api_key(credentials)}',
            'Accept': 'application/vnd.pagerduty+json;version=2',
            'Content-Type': 'application/json',
        },
        event_hooks={'response': [_raise_on_error]},
    )
