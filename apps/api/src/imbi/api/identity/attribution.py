"""Resolve external identity *subjects* to Imbi users for attribution.

Both the commit-sync backfill and the deployment resync run inside
imbi-api with a *service* credential (no acting user), yet want to
attribute synced rows to the Imbi user behind an external actor. This
module turns a provider subject (e.g. a GitHub numeric user id) into the
matching Imbi user's email by querying the identity connections
directly -- no HTTP.

Plugin Architecture v3: identity is a capability on an ``Integration``,
not a standalone plugin type. A project's identity-capable Integrations
are discovered by walking its ``EXISTS_IN`` edges rather than by asking
the caller to enumerate the "sibling" plugins on a
``ThirdPartyService``.
"""

from __future__ import annotations

import logging
import typing
from collections import abc

from imbi_common import graph
from imbi_common.plugins import PluginNotFoundError, get_plugin

from imbi_api import models
from imbi_api.identity import repository as identity_repository

LOGGER = logging.getLogger(__name__)

_PROJECT_INTEGRATIONS: typing.LiteralString = """
MATCH (proj:Project {{id: {project_id}}})-[:EXISTS_IN]->(i:Integration)
RETURN collect(DISTINCT {{id: i.id, plugin: i.plugin}}) AS integrations
"""


async def identity_integration_ids_for_project(
    db: graph.Graph, project_id: str
) -> list[str]:
    """Return ids of Integrations the project ``EXISTS_IN`` whose plugin
    declares an ``identity`` capability.

    Used to discover the identity Integrations that sit alongside a
    deployment (or commit-sync) Integration for the same project, so
    their connections can resolve an external actor to an Imbi user.
    Returns an empty list when the project exists in no such
    Integration.
    """
    records = await db.execute(
        _PROJECT_INTEGRATIONS, {'project_id': project_id}, ['integrations']
    )
    if not records:
        return []
    rows = typing.cast(
        'list[dict[str, typing.Any]]',
        graph.parse_agtype(records[0].get('integrations')) or [],
    )
    integration_ids: list[str] = []
    for row in rows:
        integration_id = row.get('id')
        plugin_slug = row.get('plugin')
        if not integration_id or not plugin_slug:
            continue
        try:
            entry = get_plugin(str(plugin_slug))
        except PluginNotFoundError:
            continue
        if entry.manifest.get_capability('identity') is not None:
            integration_ids.append(str(integration_id))
    return integration_ids


def make_user_resolver(
    db: graph.Graph, integration_ids: list[str]
) -> abc.Callable[[str], abc.Awaitable[str | None]] | None:
    """Build a subject -> Imbi-user-email resolver.

    Maps an external identity *subject* (a GitHub numeric user id) to the
    matching Imbi user's email by querying the graph directly.
    ``integration_ids`` should already be filtered to identity-capable
    Integrations (see :func:`identity_integration_ids_for_project`);
    ``None`` is returned when none qualify so the caller skips the
    lookups entirely. A subject resolving to two different users across
    Integrations is treated as unresolved (logged), never
    mis-attributed.
    """
    if not integration_ids:
        return None

    async def _resolve(subject: str) -> str | None:
        emails: set[str] = set()
        for integration_id in integration_ids:
            user_id = await identity_repository.find_user_by_subject(
                db, integration_id, subject
            )
            if user_id is None:
                continue
            users = await db.match(models.User, {'id': user_id})
            if users:
                emails.add(users[0].email)
        if len(emails) > 1:
            LOGGER.error(
                'Identity subject %r resolved to multiple Imbi users via '
                'integrations %r: %r — leaving unattributed',
                subject,
                integration_ids,
                sorted(emails),
            )
            return None
        return next(iter(emails), None)

    return _resolve
