"""Shared helpers: integration options, the edge, and its URLs.

The plugin has no Grafana credentials, so the project's relationship
with Grafana is a convention: the ``EXISTS_IN`` edge identifier is the
value that the alert rules carry in one label (``service`` by default),
and the gateway's Identifier Selector reads that label from a delivery.
"""

from __future__ import annotations

import json
import urllib.parse

from imbi.common.plugins.base import (
    PluginContext,
    ServiceConnection,
    ServiceWriteback,
)

#: The alert rule label that names the project when ``label`` is unset.
DEFAULT_LABEL = 'service'


class GrafanaConfigError(Exception):
    """The integration options do not allow the call."""


def base_url(ctx: PluginContext) -> str:
    """The Grafana URL from the ``service_url`` option, or raise."""
    value = str(ctx.integration_options.get('service_url') or '').strip()
    if not value.startswith(('http://', 'https://')):
        raise GrafanaConfigError(
            'The integration option `service_url` must be the Grafana URL.'
        )
    return value.rstrip('/')


def label(ctx: PluginContext) -> str:
    """The alert rule label that holds the project identifier."""
    return str(ctx.integration_options.get('label') or DEFAULT_LABEL)


def connection(ctx: PluginContext) -> ServiceConnection | None:
    """The project's edge to this integration, if any."""
    return next(
        (
            c
            for c in ctx.service_connections
            if c.integration_slug == ctx.integration_slug
        ),
        None,
    )


def default_identifier(ctx: PluginContext) -> str:
    """``{slug}-{id}``: readable, and unique because slugs are not."""
    return f'{ctx.project_slug}-{ctx.project_id}'


def identifier(ctx: PluginContext) -> str:
    """The edge's identifier wins over the default, so a rename keeps
    the labels that Grafana already has working."""
    conn = connection(ctx)
    return conn.identifier if conn else default_identifier(ctx)


def canonical_url(base: str, name: str, value: str) -> str:
    """The Grafana rules API, filtered to the rules with the label.

    ``rule_matcher`` filters the rules; ``matcher`` filters only the
    alert instances of each rule.
    """
    matcher = json.dumps(
        {'name': name, 'value': value, 'isRegex': False, 'isEqual': True},
        separators=(',', ':'),
    )
    return f'{base}/api/prometheus/grafana/api/v1/rules?' + (
        urllib.parse.urlencode({'rule_matcher': matcher})
    )


def dashboard_url(base: str, name: str, value: str) -> str:
    """The alert rules list, searched by the label.

    A filter with whitespace is quoted, as the Grafana search does.
    """
    term = f'{name}={value}'
    if any(c.isspace() for c in term):
        term = f'"{term}"'
    return f'{base}/alerting/list?' + urllib.parse.urlencode(
        {'search': f'label:{term}'}
    )


def link_key(ctx: PluginContext) -> str:
    """The ``Project.links`` key: the integration slug, so a project
    with two Grafana integrations keeps one link for each."""
    return ctx.integration_slug or 'grafana'


def writeback(ctx: PluginContext, value: str) -> ServiceWriteback:
    """Build the ``EXISTS_IN`` edge and the alert rules link."""
    base = base_url(ctx)
    name = label(ctx)
    return ServiceWriteback(
        identifier=value,
        canonical_url=canonical_url(base, name, value),
        dashboard_links={link_key(ctx): dashboard_url(base, name, value)},
    )


def matches(ctx: PluginContext, expected: ServiceWriteback) -> bool:
    """Whether the stored edge and link equal ``expected``."""
    conn = connection(ctx)
    return (
        conn is not None
        and conn.identifier == expected.identifier
        and conn.verified_identifier == conn.identifier
        and conn.canonical_url == expected.canonical_url
        and ctx.project_links.get(link_key(ctx))
        == expected.dashboard_links[link_key(ctx)]
    )
