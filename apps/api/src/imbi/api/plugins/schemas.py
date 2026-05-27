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
    model_labels = _model_vlabel_names()
    age_labels = await _ag_label_names()

    orphaned = sorted(age_labels - core_labels - model_labels - declared)
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
    # ``_ag_label_vertex`` / ``_ag_label_edge`` are AGE's built-in
    # inheritance-parent labels, present in every graph by construction;
    # they are never plugin- or model-declared, so exclude them.
    return {row[0] for row in rows if not row[0].startswith('_ag_label_')}


def _core_vlabel_names() -> set[str]:
    """Return the set of vlabels declared in core ``schemata.toml``."""
    pkg_dir = pathlib.Path(imbi_common.graph.__file__).resolve().parent
    schemata = tomllib.loads((pkg_dir / 'schemata.toml').read_text())
    return set(schemata.get('vlabels', {}).get('name', []))


def _model_vlabel_names() -> set[str]:
    """Return vlabels backed by a registered ``GraphModel`` subclass.

    AGE vertex labels are the model class name (the graph client always
    derives the label as ``type(node).__name__``), so any ``GraphModel``
    subclass defined in the shared or API-local model modules is a
    legitimate, non-plugin vlabel that may be created lazily on first
    write (e.g. ``Document``, ``Tag``, ``LocalAuthConfig``) and must not
    be reported as orphaned.
    """
    from imbi_common import models as common_models

    from imbi_api.domain import models as domain_models

    base = common_models.GraphModel
    names: set[str] = set()
    for module in (common_models, domain_models):
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, base)
                and obj is not base
            ):
                names.add(obj.__name__)
    return names
