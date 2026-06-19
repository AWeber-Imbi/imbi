"""Shared host resolution utilities for the GitHub plugins.

Identity (``plugin.py``) and deployment (``deployment.py``) plugins both
accept a ``host`` option and need to normalise it to a bare hostname
that URLs can be safely composed against.  This module is the single
source of truth for that validation.
"""

from __future__ import annotations

import collections.abc
import typing
import urllib.parse

#: Slug of the GitHub connection plugin. A single connection plugin is
#: attached to each GitHub ``ThirdPartyService`` and carries the
#: ``flavor`` + ``host`` options (and the shared App/PAT credentials)
#: that every sibling GitHub plugin reads. Behavioral plugins resolve
#: their host from this sibling rather than from a per-flavor variant of
#: their own class.
GITHUB_CONNECTION_SLUG = 'github-connection'


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


def host_to_api_base(host: str) -> str:
    """Map a resolved GitHub host to its REST API base.

    The single source of truth for GitHub's flavor routing:
    ``github.com`` -> ``api.github.com``, a ``*.ghe.com`` tenant ->
    ``api.<tenant>.ghe.com``, and a GHES appliance -> ``<host>/api/v3``.
    Shared by every behavioral plugin once it has resolved its host from
    the connection plugin via :func:`resolve_connection_host`.
    """
    if host == 'github.com':
        return 'https://api.github.com'
    if host.endswith('.ghe.com'):
        return f'https://api.{host}'
    return f'https://{host}/api/v3'


class _ConnectionLike(typing.Protocol):
    """Structural view of an :class:`imbi_common.plugins.ServicePlugin`."""

    slug: str
    options: dict[str, typing.Any]


def flavor_host(options: dict[str, typing.Any], label: str) -> str:
    """Validate the connection plugin's ``flavor`` + ``host`` to a host.

    The operator picks an explicit ``flavor`` (``github.com`` / ``ghec``
    / ``ghes``); the ``host`` is required for the two enterprise flavors
    and ignored for ``github.com``. Returns the bare hostname the rest of
    the plugin composes URLs against (``github.com``, the validated
    ``*.ghe.com`` tenant, or the normalized GHES appliance host).
    """
    flavor = str(options.get('flavor') or '').strip()
    if flavor == 'github.com':
        return 'github.com'
    if flavor == 'ghec':
        return require_ghec_tenant_host(
            normalize_host(options.get('host'), label), label
        )
    if flavor == 'ghes':
        return normalize_host(options.get('host'), label)
    raise ValueError(
        f'{label} got invalid connection flavor {flavor!r}; expected one '
        f'of "github.com", "ghec", or "ghes"'
    )


def find_connection(
    service_plugins: collections.abc.Iterable[_ConnectionLike],
) -> _ConnectionLike | None:
    """Return the ``github-connection`` sibling, or ``None`` if absent.

    Locates the connection plugin without validating its options, so
    callers that want to fall back when no connection plugin is attached
    (the webhook path) can distinguish "absent" from "misconfigured".
    """
    for plugin in service_plugins:
        if plugin.slug == GITHUB_CONNECTION_SLUG:
            return plugin
    return None


def resolve_connection_host(
    service_plugins: collections.abc.Iterable[_ConnectionLike], label: str
) -> str:
    """Return the GitHub host from the connection plugin sibling.

    Scans ``service_plugins`` for the single ``github-connection`` entry
    and resolves its ``flavor`` + ``host`` to a bare hostname. Raises
    ``ValueError`` (operator-facing) when no connection plugin is
    attached to the service or its flavor/host is unusable.
    """
    plugin = find_connection(service_plugins)
    if plugin is None:
        raise ValueError(
            f'{label}: no {GITHUB_CONNECTION_SLUG} plugin is attached to '
            f'the service; cannot resolve the GitHub host'
        )
    return flavor_host(plugin.options, label)
