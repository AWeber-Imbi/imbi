"""Plugin registry lifecycle — startup audit and unavailable tracking."""

import logging

from imbi_common import graph
from imbi_common.plugins.registry import (
    list_plugins,
    load_plugins,
)

LOGGER = logging.getLogger(__name__)

_unavailable_slugs: list[str] = []


def get_unavailable_slugs() -> list[str]:
    """Return slugs that exist in the graph but not the registry."""
    return list(_unavailable_slugs)


async def startup_load_plugins(db: graph.Graph) -> None:
    """Load plugins and audit for unavailable graph nodes."""
    result = load_plugins()
    LOGGER.info(
        'Plugin registry loaded: %d loaded, %d errors, %d skipped',
        len(result.loaded),
        len(result.errors),
        len(result.skipped),
    )
    for slug, err in result.errors.items():
        LOGGER.error('Plugin load error for %r: %s', slug, err)

    await _audit_unavailable(db)


async def _audit_unavailable(db: graph.Graph) -> None:
    """Find Plugin nodes whose slug is not in the registry."""
    global _unavailable_slugs
    registered = {e.manifest.slug for e in list_plugins()}
    query: str = 'MATCH (p:Plugin) RETURN DISTINCT p.plugin_slug AS slug'
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
    _unavailable_slugs = unavailable
    if unavailable:
        LOGGER.error(
            'Unavailable plugins (in graph but not registry): %s',
            unavailable,
        )
