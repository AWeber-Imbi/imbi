"""Shared host resolution utilities for the GitHub plugins.

Identity (``plugin.py``) and deployment (``deployment.py``) plugins both
accept a ``host`` option and need to normalise it to a bare hostname
that URLs can be safely composed against.  This module is the single
source of truth for that validation.
"""

from __future__ import annotations

import typing
import urllib.parse


def normalize_host(raw: typing.Any, label: str) -> str:
    """Validate and normalize a manifest ``host`` value.

    Strips whitespace, accepts an optional scheme, and rejects values
    with paths / queries / fragments so callers can compose URLs from
    the result without producing malformed endpoints.
    """
    host = str(raw or '').strip()
    if not host:
        raise ValueError(f'{label} requires the "host" option')
    parsed = urllib.parse.urlsplit(
        host if '://' in host else f'https://{host}'
    )
    if (
        not parsed.hostname
        or parsed.port is not None
        or parsed.path not in ('', '/')
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f'{label} got invalid host value: {host!r}')
    return parsed.hostname


def require_ghec_tenant_host(host: str, label: str) -> str:
    """Refuse anything that isn't a ``*.ghe.com`` tenant host."""
    if (
        not host.endswith('.ghe.com')
        or host == '.ghe.com'
        or host.startswith('api.')
    ):
        raise ValueError(
            f'{label} requires a tenant host like "tenant.ghe.com"; '
            f'got {host!r}'
        )
    return host
