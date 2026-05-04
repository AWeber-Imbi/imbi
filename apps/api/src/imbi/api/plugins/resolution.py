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
    query: typing.LiteralString = """
    MATCH (proj:Project {{id: {project_id}}})
    OPTIONAL MATCH (proj)-[pe:USES_PLUGIN]->(p:Plugin)
    WHERE pe.tab = {tab}
    OPTIONAL MATCH (proj)-[:TYPE]->(pt:ProjectType)
      -[pte:USES_PLUGIN]->(p2:Plugin)
    WHERE pte.tab = {tab}
    WITH
      collect(DISTINCT {{id: p.id, slug: p.plugin_slug,
                         options: pe.options, default: pe.default,
                         src: 'project'}})
       AS proj_plugins,
      collect(DISTINCT {{id: p2.id, slug: p2.plugin_slug,
                         options: pte.options, default: pte.default,
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

    # Project overrides project-type; merge by plugin id
    merged: dict[str, dict[str, typing.Any]] = {}
    for p in pt_plugins:
        if p.get('id'):
            merged[p['id']] = p
    for p in proj_plugins:
        if p.get('id'):
            merged[p['id']] = p

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
    options = parse_options(chosen.get('options'))

    try:
        entry = get_plugin(plugin_slug)
    except PluginNotFoundError as exc:
        raise PluginUnavailableError(plugin_slug) from exc

    return ResolvedPlugin(
        plugin_id=plugin_id,
        plugin_slug=plugin_slug,
        entry=entry,
        options=options,
    )
