"""Plugin registry lifecycle — startup audit and enable/disable tracking."""

import logging
import typing

from imbi_common import graph
from imbi_common.plugins.registry import (
    list_plugins,
    load_plugins,
)

LOGGER = logging.getLogger(__name__)


async def startup_load_plugins(db: graph.Graph) -> None:
    """Load plugins from entry-points and seed registration state."""
    result = load_plugins()
    LOGGER.info(
        'Plugin registry loaded: %d loaded, %d errors, %d skipped',
        len(result.loaded),
        len(result.errors),
        len(result.skipped),
    )
    for slug, err in result.errors.items():
        LOGGER.error('Plugin load error for %r: %s', slug, err)

    await _seed_registrations(db)
    await _audit_unavailable(db)


async def _audit_unavailable(db: graph.Graph) -> None:
    """Log any Plugin nodes whose slug is not in the registry."""
    registered = {e.manifest.slug for e in list_plugins()}
    query: typing.LiteralString = (
        'MATCH (p:Plugin) RETURN DISTINCT p.plugin_slug AS slug'
    )
    try:
        records = await db.execute(query, {}, ['slug'])
    except Exception:  # noqa: BLE001
        LOGGER.warning('Failed to audit unavailable plugins', exc_info=True)
        return
    graph_slugs = {
        graph.parse_agtype(r['slug'])
        for r in records
        if r.get('slug') is not None
    }
    unavailable = sorted(graph_slugs - registered)
    if unavailable:
        LOGGER.error(
            'Unavailable plugins (in graph but not registry): %s',
            unavailable,
        )


async def _seed_registrations(db: graph.Graph) -> None:
    """MERGE a PluginRegistration node per loaded plugin slug.

    Default ``enabled=false`` — admin must explicitly enable a freshly
    discovered plugin before it can be assigned anywhere.
    """
    # AGE has no ON CREATE SET; coalesce preserves an admin-flipped
    # ``enabled`` across restarts and defaults new registrations to
    # disabled.
    query: typing.LiteralString = """
    MERGE (r:PluginRegistration {{slug: {slug}}})
    SET r.enabled = coalesce(r.enabled, {default})
    """
    for entry in list_plugins():
        try:
            await db.execute(
                query,
                {'slug': entry.manifest.slug, 'default': False},
                [],
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                'Failed to seed PluginRegistration for %r',
                entry.manifest.slug,
                exc_info=True,
            )


async def is_plugin_enabled(db: graph.Graph, slug: str) -> bool:
    """Return whether the registration node for ``slug`` is enabled."""
    query: typing.LiteralString = """
    MATCH (r:PluginRegistration {{slug: {slug}}})
    RETURN r.enabled AS enabled
    LIMIT 1
    """
    records = await db.execute(query, {'slug': slug}, ['enabled'])
    if not records:
        return False
    raw = records[0].get('enabled')
    if raw is None:
        return False
    return bool(graph.parse_agtype(raw))


async def get_enabled_map(db: graph.Graph) -> dict[str, bool]:
    """Return ``{slug: enabled}`` for all known registrations."""
    query: typing.LiteralString = (
        'MATCH (r:PluginRegistration) RETURN r.slug AS slug, '
        'r.enabled AS enabled'
    )
    records = await db.execute(query, {}, ['slug', 'enabled'])
    out: dict[str, bool] = {}
    for r in records:
        slug = graph.parse_agtype(r['slug']) if r.get('slug') else None
        if not slug:
            continue
        enabled = (
            bool(graph.parse_agtype(r['enabled']))
            if r.get('enabled') is not None
            else False
        )
        out[slug] = enabled
    return out


async def set_plugin_enabled(
    db: graph.Graph, slug: str, enabled: bool
) -> None:
    """Set the enabled flag on a PluginRegistration."""
    query: typing.LiteralString = """
    MERGE (r:PluginRegistration {{slug: {slug}}})
    SET r.enabled = {enabled}
    """
    await db.execute(query, {'slug': slug, 'enabled': enabled}, [])


def get_unavailable_slugs() -> list[str]:
    """Return catalog slugs not present in the installed plugin registry."""
    from imbi_api.plugins.catalog import list_catalog_entries

    return [
        slug
        for entry in list_catalog_entries()
        if entry['status'] == 'not_installed'
        for slug in entry['slugs']
    ]
