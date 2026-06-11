"""Resolve external identity *subjects* to Imbi users for attribution.

Both the commit-sync backfill and the deployment resync run inside
imbi-api with a *service* credential (no acting user), yet want to
attribute synced rows to the Imbi user behind an external actor. This
module turns a provider subject (e.g. a GitHub numeric user id) into the
matching Imbi user's email by querying the identity-plugin connections
directly -- no HTTP.
"""

from __future__ import annotations

import logging
import typing
from collections import abc

from imbi_common import graph
from imbi_common.plugins.base import ServicePlugin
from imbi_common.plugins.errors import PluginNotFoundError
from imbi_common.plugins.registry import get_plugin

from imbi_api import models
from imbi_api.identity import repository as identity_repository
from imbi_api.plugins import parse_options

LOGGER = logging.getLogger(__name__)


def identity_plugin_slugs(
    service_plugins: list[ServicePlugin],
) -> list[str]:
    """Return connected plugin slugs registered as identity plugins."""
    slugs: list[str] = []
    for plugin in service_plugins:
        try:
            entry = get_plugin(plugin.slug)
        except PluginNotFoundError:
            continue
        if entry.manifest.plugin_type == 'identity':
            slugs.append(plugin.slug)
    return slugs


def make_user_resolver(
    db: graph.Graph, service_plugins: list[ServicePlugin]
) -> abc.Callable[[str], abc.Awaitable[str | None]] | None:
    """Build a subject -> Imbi-user-email resolver.

    Maps an external identity *subject* (a GitHub numeric user id) to the
    matching Imbi user's email by querying the graph directly. Connected
    plugins are filtered to identity plugins; ``None`` is returned when
    none qualify so the caller skips the lookups entirely. A subject
    resolving to two different users across plugins is treated as
    unresolved (logged), never mis-attributed.
    """
    identity_slugs = identity_plugin_slugs(service_plugins)
    if not identity_slugs:
        return None

    async def _resolve(subject: str) -> str | None:
        emails: set[str] = set()
        for slug in identity_slugs:
            user_id = await identity_repository.find_user_by_subject(
                db, slug, subject
            )
            if user_id is None:
                continue
            users = await db.match(models.User, {'id': user_id})
            if users:
                emails.add(users[0].email)
        if len(emails) > 1:
            LOGGER.error(
                'Identity subject %r resolved to multiple Imbi users via '
                'plugins %r: %r — leaving unattributed',
                subject,
                identity_slugs,
                sorted(emails),
            )
            return None
        return next(iter(emails), None)

    return _resolve


async def load_service_plugins(
    db: graph.Graph, *, project_id: str, plugin_id: str
) -> list[ServicePlugin]:
    """Gather the plugins on the ``ThirdPartyService`` that exposes the
    resolved ``Plugin`` (by ``plugin_id``) and that the project
    ``EXISTS_IN``.

    Used to discover the identity plugins that sit alongside a deployment
    (or commit-sync) plugin on the same service, so their connections can
    resolve an external actor to an Imbi user. Anchoring on the resolved
    plugin's ``id`` (rather than its slug) keeps the lookup pinned to the
    correct service even when two services expose the same deployment
    slug. Returns an empty list when the project has no such service.
    """
    query: typing.LiteralString = """
    MATCH (proj:Project {{id: {project_id}}})
      -[:EXISTS_IN]->(tps:ThirdPartyService)
      -[:HAS_PLUGIN]->(:Plugin {{id: {plugin_id}}})
    MATCH (tps)-[:HAS_PLUGIN]->(sib:Plugin)
    RETURN collect(DISTINCT {{slug: sib.plugin_slug,
                              options: sib.options}}) AS siblings
    LIMIT 1
    """
    records = await db.execute(
        query,
        {'project_id': project_id, 'plugin_id': plugin_id},
        ['siblings'],
    )
    if not records:
        return []
    siblings = typing.cast(
        'list[dict[str, typing.Any]]',
        graph.parse_agtype(records[0].get('siblings')) or [],
    )
    service_plugins: list[ServicePlugin] = []
    for sib in siblings:
        slug = sib.get('slug')
        if not slug:
            continue
        service_plugins.append(
            ServicePlugin(
                slug=str(slug),
                options=parse_options(sib.get('options')),
            )
        )
    return service_plugins
