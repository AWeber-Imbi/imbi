"""Plugin resolution — find the correct plugin for a project+tab."""

import logging
import typing

import fastapi
from imbi_common import graph
from imbi_common.plugins.errors import (
    PluginNotFoundError,
    PluginUnavailableError,
)
from imbi_common.plugins.registry import (
    RegistryEntry,
    get_plugin,
)

from imbi_api.plugins import parse_options

LOGGER = logging.getLogger(__name__)


class ResolvedPlugin(typing.NamedTuple):
    plugin_id: str
    plugin_slug: str
    entry: RegistryEntry
    options: dict[str, typing.Any]
    identity_plugin_id: str | None = None


async def resolve_plugin(
    db: graph.Graph,
    project_id: str,
    tab: str,
    source: str | None,
) -> ResolvedPlugin:
    """Find the plugin assigned to a project for a given tab.

    Merges project-type defaults with project-level overrides.
    If multiple plugins are assigned, ``source`` selects which one
    (by plugin_id); without ``source``, the default is used.

    Raises:
        fastapi.HTTPException 404: No plugin assigned.
        fastapi.HTTPException 400: Multiple plugins but no source given.
        PluginUnavailableError: Plugin node exists but slug not in registry.
    """
    # Cypher map literals must double-escape their braces so the
    # ``SQL.format()``-based template renderer doesn't treat them as
    # replacement fields. ``options`` is read from the edge (``pe`` /
    # ``pte``) so per-assignment overrides reach the plugin handler.
    # ``plugin_identity_plugin_id`` is the default identity plugin set on
    # the Plugin node itself (org-wide). It is used as the lowest-tier
    # fallback when neither the project edge nor the project-type edge
    # names an identity plugin of its own.
    query: typing.LiteralString = """
    MATCH (proj:Project {{id: {project_id}}})
    OPTIONAL MATCH (proj)-[pe:USES_PLUGIN]->(p:Plugin)
    WHERE pe.tab = {tab}
    OPTIONAL MATCH (proj)-[:TYPE]->(pt:ProjectType)
      -[pte:USES_PLUGIN]->(p2:Plugin)
    WHERE pte.tab = {tab}
    WITH
      collect(DISTINCT {{id: p.id, slug: p.plugin_slug,
                         edge_options: pe.options,
                         plugin_options: p.options,
                         identity_plugin_id: pe.identity_plugin_id,
                         plugin_identity_plugin_id: p.identity_plugin_id,
                         default: pe.default,
                         src: 'project'}})
       AS proj_plugins,
      collect(DISTINCT {{id: p2.id, slug: p2.plugin_slug,
                         edge_options: pte.options,
                         plugin_options: p2.options,
                         identity_plugin_id: pte.identity_plugin_id,
                         plugin_identity_plugin_id: p2.identity_plugin_id,
                         default: pte.default,
                         src: 'project_type'}})
       AS pt_plugins
    RETURN proj_plugins, pt_plugins
    """
    records = await db.execute(
        query,
        {'project_id': project_id, 'tab': tab},
        ['proj_plugins', 'pt_plugins'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail='Project not found',
        )

    proj_plugins: list[dict[str, typing.Any]] = (
        graph.parse_agtype(records[0]['proj_plugins']) or []
    )
    pt_plugins: list[dict[str, typing.Any]] = (
        graph.parse_agtype(records[0]['pt_plugins']) or []
    )

    # Project overrides project-type; merge by plugin id.
    # Preserve the project-type entry so its edge options can be used as
    # the baseline when a project-level entry exists for the same plugin.
    pt_by_id: dict[str, dict[str, typing.Any]] = {
        p['id']: p for p in pt_plugins if p.get('id')
    }
    merged: dict[str, dict[str, typing.Any]] = {}
    for p in pt_plugins:
        if p.get('id'):
            merged[p['id']] = p
    for p in proj_plugins:
        pid = p.get('id')
        if not pid:
            continue
        if pid in pt_by_id:
            # Carry the project-type edge options as a middle tier so that
            # a partial project override does not drop project-type settings.
            # Also carry the project-type ``identity_plugin_id`` separately
            # so a project edge that omits it falls back to the type-level
            # binding instead of clearing the identity requirement.
            merged[pid] = {
                **p,
                'pt_edge_options': pt_by_id[pid].get('edge_options'),
                'pt_identity_plugin_id': pt_by_id[pid].get(
                    'identity_plugin_id'
                ),
                'plugin_identity_plugin_id': p.get('plugin_identity_plugin_id')
                or pt_by_id[pid].get('plugin_identity_plugin_id'),
            }
        else:
            merged[pid] = p

    candidates = [p for p in merged.values() if p.get('id')]
    if not candidates:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'No plugin assigned to tab {tab!r} for this project',
        )

    if source:
        chosen = next((p for p in candidates if p['id'] == source), None)
        if chosen is None:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'Plugin {source!r} not assigned to this project',
            )
    elif len(candidates) == 1:
        chosen = candidates[0]
    else:
        # Project-level defaults must win over project-type defaults
        # (project assignments override project-type assignments). The
        # merge dict preserves the project-type entry's insertion order
        # when a project entry overwrites it, so we can't rely on
        # iteration order — explicitly partition by ``src`` instead.
        project_defaults = [
            p
            for p in candidates
            if p.get('src') == 'project' and p.get('default')
        ]
        type_defaults = [
            p
            for p in candidates
            if p.get('src') == 'project_type' and p.get('default')
        ]
        defaults = project_defaults or type_defaults
        if not defaults:
            raise fastapi.HTTPException(
                status_code=400,
                detail=(
                    'Multiple plugins assigned; specify ?source=<plugin_id>'
                ),
            )
        chosen = defaults[0]

    plugin_id: str = chosen['id']
    plugin_slug: str = chosen['slug']
    # Three-tier option merge (lowest → highest precedence):
    #   1. Plugin node defaults (plugin_options on the Plugin node)
    #   2. Project-type edge options (pt_edge_options, preserved above)
    #   3. Project-level edge options (edge_options on the project edge)
    # Admins only need to specify fields that diverge from the tier below.
    plugin_defaults: dict[str, typing.Any] = parse_options(
        chosen.get('plugin_options')
    )
    pt_edge: dict[str, typing.Any] = parse_options(
        chosen.get('pt_edge_options')
    )
    overrides: dict[str, typing.Any] = parse_options(
        chosen.get('edge_options')
    )
    options = {**plugin_defaults, **pt_edge, **overrides}

    try:
        entry = get_plugin(plugin_slug)
    except PluginNotFoundError as exc:
        raise PluginUnavailableError(plugin_slug) from exc

    identity_plugin_id = _select_identity_plugin_id(chosen)

    return ResolvedPlugin(
        plugin_id=plugin_id,
        plugin_slug=plugin_slug,
        entry=entry,
        options=options,
        identity_plugin_id=identity_plugin_id,
    )


def _select_identity_plugin_id(
    chosen: dict[str, typing.Any],
) -> str | None:
    """Pick the identity plugin id with three-tier precedence.

    Order, highest precedence first:

    1. ``identity_plugin_id`` on the chosen edge (project or project-type
       edge).
    2. ``pt_identity_plugin_id`` — the project-type edge's value, carried
       across when a project edge wins but did not name its own identity.
    3. ``plugin_identity_plugin_id`` — the default declared on the Plugin
       node itself, applied org-wide so admins do not have to repeat it
       on every project-type assignment.
    """
    identity_plugin_id = chosen.get('identity_plugin_id')
    if isinstance(identity_plugin_id, str) and not identity_plugin_id:
        identity_plugin_id = None
    if identity_plugin_id is None:
        pt_identity = chosen.get('pt_identity_plugin_id')
        if isinstance(pt_identity, str) and pt_identity:
            identity_plugin_id = pt_identity
    if identity_plugin_id is None:
        plugin_identity = chosen.get('plugin_identity_plugin_id')
        if isinstance(plugin_identity, str) and plugin_identity:
            identity_plugin_id = plugin_identity
    return identity_plugin_id
