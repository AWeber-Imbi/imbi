"""Plugin resolution — find the plugin for a project + plugin_type."""

import logging
import typing

import fastapi
from imbi_common import graph
from imbi_common.plugins.base import ServicePlugin
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


async def resolve_service_plugins(
    db: graph.Graph, project_id: str
) -> list[ServicePlugin]:
    """Return the sibling plugins on the project's connected services.

    Walks ``(:Project)-[:EXISTS_IN]->(:ThirdPartyService)-[:HAS_PLUGIN]
    ->(:Plugin)`` and surfaces each plugin as a ``ServicePlugin`` (slug +
    non-secret ``options``), mirroring how ``imbi-gateway`` populates
    ``PluginContext.service_plugins`` for the webhook path. Behavioral
    plugins read these to resolve shared config -- e.g. the GitHub host
    from the ``github-connection`` sibling. Credentials are deliberately
    excluded; secrets are resolved separately by the host.
    """
    query: typing.LiteralString = """
    MATCH (proj:Project {{id: {project_id}}})-[:EXISTS_IN]->
      (:ThirdPartyService)-[:HAS_PLUGIN]->(p:Plugin)
    RETURN collect(DISTINCT {{slug: p.plugin_slug, options: p.options}})
      AS plugins
    """
    records = await db.execute(query, {'project_id': project_id}, ['plugins'])
    if not records or records[0].get('plugins') is None:
        return []
    rows: list[dict[str, typing.Any]] = (
        graph.parse_agtype(records[0]['plugins']) or []
    )
    return [
        ServicePlugin(
            slug=str(row['slug']),
            options=parse_options(row.get('options')),
        )
        for row in rows
        if row.get('slug')
    ]


def _registry_plugin_type(slug: str) -> str | None:
    try:
        return get_plugin(slug).manifest.plugin_type
    except PluginNotFoundError:
        return None


def _tps_identity_plugin_ids(
    tps_raw: list[dict[str, typing.Any]],
) -> dict[str, str]:
    """Map each third-party service slug to its identity plugin id.

    Plugin nodes don't carry ``plugin_type``, so the type is resolved
    from the registry. When a service has more than one identity plugin
    the one flagged ``used_as_login`` wins.
    """
    out: dict[str, str] = {}
    for p in tps_raw:
        slug = p.get('tps_slug')
        pid = p.get('id')
        if not slug or not pid or not p.get('slug'):
            continue
        if _registry_plugin_type(p['slug']) != 'identity':
            continue
        if slug not in out or p.get('used_as_login'):
            out[slug] = pid
    return out


class ResolvedPlugin(typing.NamedTuple):
    plugin_id: str
    plugin_slug: str
    entry: RegistryEntry
    options: dict[str, typing.Any]
    identity_plugin_id: str | None = None
    # Per-env payload dict keyed by env slug; values are merged into
    # GitHub Deployment ``payload`` (workflow inputs) at trigger time.
    # Lives on the USES_PLUGIN edge so plugin-specific behaviour stays
    # with the plugin assignment.  Two-tier merge (project edge wins per
    # env slug over project-type edge).  ``None`` is treated as "no
    # per-env payloads" by call sites; the default is None rather than
    # {} so the NamedTuple does not carry a shared mutable default.
    env_payloads: dict[str, dict[str, typing.Any]] | None = None
    # Slug of the ThirdPartyService this plugin instance is attached to
    # via ``(:ThirdPartyService)-[:HAS_PLUGIN]->(:Plugin)``, or ``None``
    # when the plugin is not bound to a service.  The host injects it
    # into ``PluginContext.third_party_service_slug`` so the plugin knows
    # which service its ``service_writeback`` / ``EXISTS_IN`` edge
    # targets.
    third_party_service_slug: str | None = None


def _merge_env_payloads(
    pt_raw: typing.Any,
    project_raw: typing.Any,
) -> dict[str, dict[str, typing.Any]]:
    """Two-tier merge of ``env_payloads`` from project-type + project edges.

    Each tier is a ``{env_slug: {...payload}}`` dict (stored JSON-encoded
    on the AGE edge).  For each env slug present in either tier we
    shallow-merge the two payload dicts, with the project-edge value
    winning per key, matching the precedence the rest of the resolver
    uses for ``options``.
    """
    pt = parse_options(pt_raw)
    project = parse_options(project_raw)
    merged: dict[str, dict[str, typing.Any]] = {}
    for slug, payload in pt.items():
        if isinstance(payload, dict):
            merged[slug] = dict(payload)  # pyright: ignore[reportUnknownArgumentType]
    for slug, payload in project.items():
        if not isinstance(payload, dict):
            continue
        existing = merged.get(slug, {})
        merged[slug] = {**existing, **payload}  # pyright: ignore[reportUnknownArgumentType]
    return merged


async def resolve_plugin(
    db: graph.Graph,
    project_id: str,
    plugin_type: str,
    source: str | None,
) -> ResolvedPlugin:
    """Find the plugin assigned to a project for a given plugin type.

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
    WHERE coalesce(pe.plugin_type, pe.tab) = {plugin_type}
    OPTIONAL MATCH (proj)-[:TYPE]->(pt:ProjectType)
      -[pte:USES_PLUGIN]->(p2:Plugin)
    WHERE coalesce(pte.plugin_type, pte.tab) = {plugin_type}
    WITH
      collect(DISTINCT {{id: p.id, slug: p.plugin_slug,
                         edge_options: pe.options,
                         edge_env_payloads: pe.env_payloads,
                         plugin_options: p.options,
                         identity_plugin_id: pe.identity_plugin_id,
                         plugin_identity_plugin_id: p.identity_plugin_id,
                         default: pe.default,
                         src: 'project'}})
       AS proj_plugins,
      collect(DISTINCT {{id: p2.id, slug: p2.plugin_slug,
                         edge_options: pte.options,
                         edge_env_payloads: pte.env_payloads,
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
        {'project_id': project_id, 'plugin_type': plugin_type},
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
                'pt_edge_env_payloads': pt_by_id[pid].get('edge_env_payloads'),
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
            detail=(
                f'No plugin assigned for plugin_type {plugin_type!r}'
                f' for this project'
            ),
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

    # Treat a disabled PluginRegistration the same as a missing-from-
    # registry plugin so admin-driven disable is honored at the resolve
    # layer, not just by ``dispatch_lifecycle`` downstream. Importing
    # lazily avoids a circular ``resolution -> lifecycle -> resolution``
    # at module load.
    from imbi_api.plugins.lifecycle import is_plugin_enabled

    if not await is_plugin_enabled(db, plugin_slug):
        raise PluginUnavailableError(plugin_slug)

    identity_plugin_id = _select_identity_plugin_id(chosen)
    env_payloads = _merge_env_payloads(
        chosen.get('pt_edge_env_payloads'),
        chosen.get('edge_env_payloads'),
    )

    return ResolvedPlugin(
        plugin_id=plugin_id,
        plugin_slug=plugin_slug,
        entry=entry,
        options=options,
        identity_plugin_id=identity_plugin_id,
        env_payloads=env_payloads,
    )


async def resolve_all_plugins(
    db: graph.Graph,
    project_id: str,
    plugin_type: str,
) -> list[ResolvedPlugin]:
    """Return every plugin assigned to ``project_id`` for ``plugin_type``.

    Sibling to :func:`resolve_plugin` for fan-out call sites (e.g.
    lifecycle hooks) that must invoke *every* assigned plugin rather
    than a single default.  Applies the same project-over-project-type
    merge by plugin id and the same three-tier options precedence
    (plugin defaults < project-type edge < project edge), and resolves
    ``identity_plugin_id`` using :func:`_select_identity_plugin_id`.

    Returns an empty list when no plugins are assigned — callers that
    expect at least one are responsible for raising.

    Plugins whose slug is not in the registry are dropped silently
    (logged at WARNING).  Rationale: a single missing/disabled plugin
    must not block lifecycle dispatch for the others.
    """
    query: typing.LiteralString = """
    MATCH (proj:Project {{id: {project_id}}})
    OPTIONAL MATCH (proj)-[pe:USES_PLUGIN]->(p:Plugin)
    WHERE coalesce(pe.plugin_type, pe.tab) = {plugin_type}
    OPTIONAL MATCH (tps1:ThirdPartyService)-[:HAS_PLUGIN]->(p)
    OPTIONAL MATCH (proj)-[:TYPE]->(pt:ProjectType)
      -[pte:USES_PLUGIN]->(p2:Plugin)
    WHERE coalesce(pte.plugin_type, pte.tab) = {plugin_type}
    OPTIONAL MATCH (tps2:ThirdPartyService)-[:HAS_PLUGIN]->(p2)
    WITH
      collect(DISTINCT {{id: p.id, slug: p.plugin_slug,
                         edge_options: pe.options,
                         edge_env_payloads: pe.env_payloads,
                         plugin_options: p.options,
                         identity_plugin_id: pe.identity_plugin_id,
                         plugin_identity_plugin_id: p.identity_plugin_id,
                         tps_slug: tps1.slug,
                         default: pe.default,
                         src: 'project'}})
       AS proj_plugins,
      collect(DISTINCT {{id: p2.id, slug: p2.plugin_slug,
                         edge_options: pte.options,
                         edge_env_payloads: pte.env_payloads,
                         plugin_options: p2.options,
                         identity_plugin_id: pte.identity_plugin_id,
                         plugin_identity_plugin_id: p2.identity_plugin_id,
                         tps_slug: tps2.slug,
                         default: pte.default,
                         src: 'project_type'}})
       AS pt_plugins
    RETURN proj_plugins, pt_plugins
    """
    records = await db.execute(
        query,
        {'project_id': project_id, 'plugin_type': plugin_type},
        ['proj_plugins', 'pt_plugins'],
    )
    if not records:
        return []

    proj_plugins: list[dict[str, typing.Any]] = (
        graph.parse_agtype(records[0]['proj_plugins']) or []
    )
    pt_plugins: list[dict[str, typing.Any]] = (
        graph.parse_agtype(records[0]['pt_plugins']) or []
    )

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
            merged[pid] = {
                **p,
                'pt_edge_options': pt_by_id[pid].get('edge_options'),
                'pt_edge_env_payloads': pt_by_id[pid].get('edge_env_payloads'),
                'pt_identity_plugin_id': pt_by_id[pid].get(
                    'identity_plugin_id'
                ),
                'plugin_identity_plugin_id': p.get('plugin_identity_plugin_id')
                or pt_by_id[pid].get('plugin_identity_plugin_id'),
            }
        else:
            merged[pid] = p

    # Single query for admin-managed enabled flags so the fan-out below
    # doesn't issue N round-trips. Imported lazily to avoid the
    # ``resolution -> lifecycle -> resolution`` cycle at module load.
    from imbi_api.plugins.lifecycle import get_enabled_map

    enabled_map = await get_enabled_map(db)

    resolved: list[ResolvedPlugin] = []
    for chosen in merged.values():
        plugin_id = chosen.get('id')
        plugin_slug = chosen.get('slug')
        if not plugin_id or not plugin_slug:
            continue
        if not enabled_map.get(plugin_slug, False):
            LOGGER.info(
                'Skipping disabled plugin %r (id=%s) during fan-out',
                plugin_slug,
                plugin_id,
            )
            continue
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
        except PluginNotFoundError:
            LOGGER.warning(
                'Skipping unregistered plugin %r (id=%s) during fan-out',
                plugin_slug,
                plugin_id,
            )
            continue
        tps_slug = chosen.get('tps_slug')
        resolved.append(
            ResolvedPlugin(
                plugin_id=plugin_id,
                plugin_slug=plugin_slug,
                entry=entry,
                options=options,
                identity_plugin_id=_select_identity_plugin_id(chosen),
                env_payloads=_merge_env_payloads(
                    chosen.get('pt_edge_env_payloads'),
                    chosen.get('edge_env_payloads'),
                ),
                third_party_service_slug=(
                    tps_slug
                    if isinstance(tps_slug, str) and tps_slug
                    else None
                ),
            )
        )
    return resolved


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


async def resolve_analysis_plugins(
    db: graph.Graph,
    project_id: str,
) -> list[ResolvedPlugin]:
    """Return every analysis plugin applicable to ``project_id``.

    The union covers three discovery paths:

    1. ``(:Project)-[:USES_PLUGIN {plugin_type:'analysis'}]->(:Plugin)`` —
       project override.
    2. ``(:Project)-[:TYPE]->(:ProjectType)
       -[:USES_PLUGIN {plugin_type:'analysis'}]->(:Plugin)`` — project-type
       default. Project override wins per
       plugin id, mirroring :func:`resolve_all_plugins`.
    3. ``(:Project)-[:EXISTS_IN]->(:ThirdPartyService)-[:HAS_PLUGIN]
       ->(:Plugin)`` filtered to ``plugin_type='analysis'``. The
       third-party-service path attaches an analysis plugin to every
       project that connects to that TPS, without requiring an
       operator-managed ``USES_PLUGIN`` edge.

    Deduped by ``plugin_id``: a plugin reachable via multiple paths is
    returned once with options resolved from the highest-precedence
    edge (project edge > project-type edge; TPS-only entries carry no
    edge options). Plugins whose registry entry is missing or whose
    :class:`PluginRegistration` is disabled are silently dropped (a
    single misconfigured plugin must not block the rest of the
    fan-out, matching :func:`resolve_all_plugins`).
    """
    query: typing.LiteralString = """
    MATCH (proj:Project {{id: {project_id}}})
    OPTIONAL MATCH (proj)-[pe:USES_PLUGIN]->(p:Plugin)
    WHERE coalesce(pe.plugin_type, pe.tab) = 'analysis'
    OPTIONAL MATCH (proj)-[:TYPE]->(pt:ProjectType)
      -[pte:USES_PLUGIN]->(p2:Plugin)
    WHERE coalesce(pte.plugin_type, pte.tab) = 'analysis'
    OPTIONAL MATCH (proj)-[:EXISTS_IN]->(tps:ThirdPartyService)
      -[:HAS_PLUGIN]->(p3:Plugin)
    WITH
      collect(DISTINCT {{id: p.id, slug: p.plugin_slug,
                         edge_options: pe.options,
                         plugin_options: p.options,
                         default: pe.default,
                         identity_plugin_id: pe.identity_plugin_id,
                         plugin_identity_plugin_id: p.identity_plugin_id,
                         src: 'project'}})
       AS proj_plugins,
      collect(DISTINCT {{id: p2.id, slug: p2.plugin_slug,
                         edge_options: pte.options,
                         plugin_options: p2.options,
                         default: pte.default,
                         identity_plugin_id: pte.identity_plugin_id,
                         plugin_identity_plugin_id: p2.identity_plugin_id,
                         src: 'project_type'}})
       AS pt_plugins,
      collect(DISTINCT {{id: p3.id, slug: p3.plugin_slug,
                         plugin_options: p3.options,
                         tps_slug: tps.slug,
                         used_as_login: p3.used_as_login,
                         src: 'third_party_service'}})
       AS tps_plugins
    RETURN proj_plugins, pt_plugins, tps_plugins
    """
    records = await db.execute(
        query,
        {'project_id': project_id},
        ['proj_plugins', 'pt_plugins', 'tps_plugins'],
    )
    # ``MATCH (proj:Project)`` anchors the whole pipeline: if the
    # project doesn't exist, the OPTIONAL MATCHes still run but
    # collect() aggregates over zero rows and the RETURN line yields
    # no records at all. A project that exists but has no analysis
    # plugins returns exactly one record with three empty
    # collections — that's the falls-through-to-merge case. Mirror
    # ``resolve_plugin`` and raise 404 when the project itself is
    # missing so callers can distinguish "no findings" from "the
    # project_id is bogus".
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
    tps_raw: list[dict[str, typing.Any]] = (
        graph.parse_agtype(records[0]['tps_plugins']) or []
    )
    tps_plugins: list[dict[str, typing.Any]] = [
        p
        for p in tps_raw
        if p.get('id')
        and p.get('slug')
        and _registry_plugin_type(p['slug']) == 'analysis'
    ]
    # Map each third-party service to the identity plugin attached to it,
    # so a doctor (analysis) plugin discovered via that service can run as
    # the acting user instead of a static token.
    tps_identity_plugin_id = _tps_identity_plugin_ids(tps_raw)

    pt_by_id: dict[str, dict[str, typing.Any]] = {
        p['id']: p for p in pt_plugins if p.get('id')
    }
    merged: dict[str, dict[str, typing.Any]] = {}
    # Seed with TPS entries first; project-type and project edges win.
    for p in tps_plugins:
        if p.get('id'):
            merged[p['id']] = p
    for p in pt_plugins:
        if p.get('id'):
            merged[p['id']] = p
    for p in proj_plugins:
        pid = p.get('id')
        if not pid:
            continue
        if pid in pt_by_id:
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

    from imbi_api.plugins.lifecycle import get_enabled_map

    enabled_map = await get_enabled_map(db)

    resolved: list[ResolvedPlugin] = []
    for chosen in merged.values():
        plugin_id = chosen.get('id')
        plugin_slug = chosen.get('slug')
        if not plugin_id or not plugin_slug:
            continue
        if not enabled_map.get(plugin_slug, False):
            LOGGER.info(
                'Skipping disabled plugin %r (id=%s) during analysis fan-out',
                plugin_slug,
                plugin_id,
            )
            continue
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
        except PluginNotFoundError:
            LOGGER.warning(
                'Skipping unregistered plugin %r (id=%s) during analysis '
                'fan-out',
                plugin_slug,
                plugin_id,
            )
            continue
        tps_slug = chosen.get('tps_slug')
        tps_slug_str = (
            tps_slug if isinstance(tps_slug, str) and tps_slug else None
        )
        resolved.append(
            ResolvedPlugin(
                plugin_id=plugin_id,
                plugin_slug=plugin_slug,
                entry=entry,
                options=options,
                identity_plugin_id=(
                    _select_identity_plugin_id(chosen)
                    or (
                        tps_identity_plugin_id.get(tps_slug_str)
                        if tps_slug_str
                        else None
                    )
                ),
                third_party_service_slug=tps_slug_str,
            )
        )
    return resolved
