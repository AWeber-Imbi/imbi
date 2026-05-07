"""Org-scoped listing of identity plugin instances.

Used by the admin UI to populate the "Identity Plugin" dropdown on
plugin assignment rows (third-party-service / project-type / project
levels) — only plugin instances whose registry entry is
``plugin_type='identity'`` are eligible.
"""

from __future__ import annotations

import typing

import fastapi
import pydantic
from imbi_common import graph
from imbi_common.plugins.errors import PluginNotFoundError
from imbi_common.plugins.registry import get_plugin

from imbi_api.auth import permissions

identity_plugins_router = fastapi.APIRouter(tags=['Identity Plugins'])


class IdentityPluginRef(pydantic.BaseModel):
    plugin_id: str
    plugin_slug: str
    label: str


@identity_plugins_router.get('/')
async def list_identity_plugins(
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('third_party_service:read'),
        ),
    ],
) -> list[IdentityPluginRef]:
    """List all identity plugin instances visible in this org.

    Walks ``ThirdPartyService -[:HAS_PLUGIN]-> Plugin`` for the org
    and filters to entries whose registry record is
    ``plugin_type='identity'`` (the registry is in-process, so the
    filter is cheap).
    """
    _ = auth
    query: typing.LiteralString = """
    MATCH (s:ThirdPartyService)
          -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
    MATCH (s)-[:HAS_PLUGIN]->(p:Plugin)
    RETURN p.id AS id, p.plugin_slug AS slug, p.label AS label
    ORDER BY p.label
    """
    records = await db.execute(
        query, {'org_slug': org_slug}, ['id', 'slug', 'label']
    )
    out: list[IdentityPluginRef] = []
    for row in records:
        plugin_id = graph.parse_agtype(row['id'])
        slug = graph.parse_agtype(row['slug'])
        label = graph.parse_agtype(row.get('label'))
        if not plugin_id or not slug:
            continue
        try:
            entry = get_plugin(str(slug))
        except PluginNotFoundError:
            continue
        if entry.manifest.plugin_type != 'identity':
            continue
        out.append(
            IdentityPluginRef(
                plugin_id=str(plugin_id),
                plugin_slug=str(slug),
                label=str(label) if label else str(slug),
            )
        )
    return out
