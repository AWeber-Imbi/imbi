"""Shared host resolution utilities for the GitHub plugin.

Every capability resolves the GitHub host (github.com, a GHEC
``*.ghe.com`` tenant, or a GHES appliance) from the Integration's
``flavor`` + ``host`` option values, surfaced on
``PluginContext.integration_options``.  This module is the single source
of truth for validating those options and mapping the resolved host to
the REST API base.
"""

from __future__ import annotations

import logging
import typing
import urllib.parse

LOGGER = logging.getLogger(__name__)


def normalize_host(raw: typing.Any, label: str) -> str:
    """Validate and normalize an integration ``host`` value.

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


def host_to_api_base(host: str) -> str:
    """Map a resolved GitHub host to its REST API base.

    The single source of truth for GitHub's flavor routing:
    ``github.com`` -> ``api.github.com``, a ``*.ghe.com`` tenant ->
    ``api.<tenant>.ghe.com``, and a GHES appliance -> ``<host>/api/v3``.
    """
    if host == 'github.com':
        return 'https://api.github.com'
    if host.endswith('.ghe.com'):
        return f'https://api.{host}'
    return f'https://{host}/api/v3'


def flavor_host(options: dict[str, typing.Any], label: str) -> str:
    """Validate the Integration's ``flavor`` + ``host`` to a bare host.

    The operator picks an explicit ``flavor`` (``github`` / ``ghec`` /
    ``ghes``); the ``host`` is required for the two enterprise flavors
    and ignored for ``github``. Returns the bare hostname the rest of the
    plugin composes URLs against (``github.com``, the validated
    ``*.ghe.com`` tenant, or the normalized GHES appliance host).
    """
    flavor = str(options.get('flavor') or '').strip()
    if flavor == 'github':
        return 'github.com'
    if flavor == 'ghec':
        return require_ghec_tenant_host(
            normalize_host(options.get('host'), label), label
        )
    if flavor == 'ghes':
        return normalize_host(options.get('host'), label)
    raise ValueError(
        f'{label} got invalid integration flavor {flavor!r}; expected one '
        f'of "github", "ghec", or "ghes"'
    )


def resolve_host(
    integration_options: dict[str, typing.Any], label: str
) -> str | None:
    """Resolve the GitHub host from the Integration options, or ``None``.

    Returns ``None`` (after logging) when the flavor/host is missing or
    unusable so callers on the webhook path can fall through to another
    resolution source rather than failing the delivery. Callers that
    require a host raise on the ``None``.
    """
    try:
        return flavor_host(integration_options, label)
    except ValueError as exc:
        LOGGER.warning('%s: unusable integration flavor/host: %s', label, exc)
        return None
