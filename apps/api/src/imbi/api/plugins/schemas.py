"""Plugin-declared schema audit (imbi-api side).

Complements :func:`imbi_common.plugins.apply_plugin_schemas` (which
creates plugin-declared vlabels in AGE on startup) by surfacing
*orphaned* plugin-declared data — vlabels still present in AGE whose
declaring plugin is no longer in the registry.

The audit result feeds the admin "Unavailable" view in
``GET /admin/plugins`` under an ``unavailable_schemas`` array.
"""

import logging
import pathlib
import tomllib
import typing

import imbi_common.graph
import psycopg
from imbi_common import settings
from imbi_common.plugins.registry import list_plugins

LOGGER = logging.getLogger(__name__)


async def audit_plugin_schemas() -> list[dict[str, typing.Any]]:
    """Return a list of orphaned plugin-declared vlabels.

    Each entry: ``{'vlabel': name}`` for every vlabel present in AGE
    that is neither in core ``schemata.toml`` nor declared by a plugin
    currently in the registry.  An empty list means every plugin-declared
    vlabel currently in AGE has its declaring plugin loaded.
    """
    declared: set[str] = set()
    for entry in list_plugins():
        for vlabel in entry.manifest.vertex_labels:
            declared.add(vlabel.name)

    core_labels = _core_vlabel_names()
    age_labels = await _ag_label_names()

    orphaned = sorted(age_labels - core_labels - declared)
    if orphaned:
        LOGGER.error(
            'Unavailable plugin-declared schemas (in AGE but not '
            'declared by any loaded plugin): %s',
            orphaned,
        )
    return [{'vlabel': name} for name in orphaned]


async def _ag_label_names() -> set[str]:
    """Return the set of vertex-label names currently in AGE."""
    postgres = settings.Postgres()
    try:
        async with await psycopg.AsyncConnection.connect(
            str(postgres.url), autocommit=True
        ) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    'SELECT name FROM ag_catalog.ag_label '
                    "WHERE kind = 'v' AND graph = ("
                    '  SELECT graphid FROM ag_catalog.ag_graph WHERE name = %s'
                    ')',
                    (postgres.graph_name,),
                )
                rows = await cursor.fetchall()
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Failed to enumerate AGE labels for plugin schema audit',
            exc_info=True,
        )
        return set()
    return {row[0] for row in rows}


def _core_vlabel_names() -> set[str]:
    """Return the set of vlabels declared in core ``schemata.toml``."""
    pkg_dir = pathlib.Path(imbi_common.graph.__file__).resolve().parent
    schemata = tomllib.loads((pkg_dir / 'schemata.toml').read_text())
    return set(schemata.get('vlabels', {}).get('name', []))
