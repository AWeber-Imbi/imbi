"""Resolve a project's PagerDuty service.

A project is bound to a PagerDuty service two ways:

* the ``pagerduty-service`` project link (the service's html_url, written
  back by the lifecycle plugin on create), and
* the lifecycle plugin names the PagerDuty service after the project
  slug, so a service can be re-found by name when the link is missing
  (e.g. on a project rename, where ``previous_project_slug`` is tried
  too).

These helpers centralize that resolution so the lifecycle and incidents
plugins agree on how to locate a service.
"""

from __future__ import annotations

import typing
import urllib.parse

import httpx
from imbi_common.plugins.base import PluginContext

SERVICE_LINK_KEY = 'pagerduty-service'


def service_id_from_link(links: dict[str, str]) -> str | None:
    """Parse the PagerDuty service id from the stored service link.

    PagerDuty service URLs end in the id (e.g.
    ``https://acme.pagerduty.com/service-directory/PIJ90N7``), so the id
    is the last non-empty path segment. Returns ``None`` when the link is
    absent or unparseable.
    """
    url = links.get(SERVICE_LINK_KEY)
    if not url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    segments = [segment for segment in parsed.path.split('/') if segment]
    return segments[-1] if segments else None


async def find_service_by_name(
    client: httpx.AsyncClient, name: str
) -> dict[str, typing.Any] | None:
    """Return the PagerDuty service whose name equals ``name``, or None.

    ``GET /services?query=`` is a substring search, so the exact-name
    match is applied client-side to avoid adopting a near-miss.
    """
    response = await client.get('/services', params={'query': name})
    response.raise_for_status()
    payload: dict[str, typing.Any] = response.json()
    services: list[dict[str, typing.Any]] = payload.get('services') or []
    for service in services:
        if service.get('name') == name:
            return service
    return None


async def resolve_service_id(
    client: httpx.AsyncClient, ctx: PluginContext
) -> str | None:
    """Resolve the project's PagerDuty service id.

    Prefers the stored ``pagerduty-service`` link; falls back to an
    exact-name lookup on the current slug and then the pre-rename slug.
    Returns ``None`` when the project has no resolvable service (the
    incidents tab renders empty; the lifecycle plugin treats it as
    "create").
    """
    linked = service_id_from_link(ctx.project_links)
    if linked:
        return linked
    candidates = [ctx.project_slug, ctx.previous_project_slug]
    seen: set[str] = set()
    for slug in candidates:
        if not slug or slug in seen:
            continue
        seen.add(slug)
        service = await find_service_by_name(client, slug)
        if service is not None:
            ident = service.get('id')
            if ident:
                return str(ident)
    return None
