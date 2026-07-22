"""Plugin-declared graph schema lifecycle.

Identity (and any future plugin type that needs operator-managed
reference data) can extend the AGE graph with their own vertex labels
and edges via :class:`PluginVertexLabel` / :class:`PluginEdgeLabel`.

Two responsibilities live here:

1. :func:`validate_no_collisions` — refuse any plugin manifest declaring
   a vlabel name already in core ``schemata.toml`` or repeated across
   manifests.
2. :func:`apply_plugin_schemas` — create plugin-declared vlabels and
   their indexes in AGE, mirroring :mod:`imbi_common.graph.initializer`
   primitives but sourced from the registry instead of a static file.

Edge labels are created on first write per AGE convention; declarations
are recorded for validation and admin UI only.
"""

import logging
import pathlib
import tomllib
import typing

import psycopg
from psycopg import sql

from imbi_common import settings
from imbi_common.plugins.base import (
    PluginEdgeLabel,
    PluginManifest,
    PluginVertexLabel,
)
from imbi_common.plugins.errors import PluginSchemaCollisionError

LOGGER = logging.getLogger(__name__)


def _load_core_vlabel_names(
    schemata_toml_path: pathlib.Path | None = None,
) -> set[str]:
    """Read core ``schemata.toml`` and return the declared vlabel set."""
    path = schemata_toml_path or (
        pathlib.Path(__file__).resolve().parent.parent
        / 'graph'
        / 'schemata.toml'
    )
    schemata = tomllib.loads(path.read_text())
    return set(schemata.get('vlabels', {}).get('name', []))


def validate_no_collisions(
    manifests: list[PluginManifest],
    schemata_toml_path: pathlib.Path | None = None,
) -> None:
    """Refuse vlabel/elabel name collisions across plugins / core.

    Logs at ERROR and raises :class:`PluginSchemaCollisionError` on the
    first collision detected.
    """
    core_names = _load_core_vlabel_names(schemata_toml_path)
    seen_vlabels: dict[str, tuple[str, PluginVertexLabel]] = {}
    seen_edges: dict[str, tuple[str, PluginEdgeLabel]] = {}

    for manifest in manifests:
        for vlabel in manifest.vertex_labels:
            if vlabel.name in core_names:
                LOGGER.error(
                    'Plugin %r declares vlabel %r which collides with '
                    'core schemata',
                    manifest.slug,
                    vlabel.name,
                )
                raise PluginSchemaCollisionError(
                    f'Plugin {manifest.slug!r} declares vlabel '
                    f'{vlabel.name!r} which collides with core schemata'
                )
            existing = seen_vlabels.get(vlabel.name)
            if existing is not None:
                owner_slug, owner_vlabel = existing
                if owner_vlabel != vlabel:
                    LOGGER.error(
                        'Plugin %r declares vlabel %r with a shape that '
                        'differs from plugin %r',
                        manifest.slug,
                        vlabel.name,
                        owner_slug,
                    )
                    raise PluginSchemaCollisionError(
                        f'Plugin {manifest.slug!r} declares vlabel '
                        f'{vlabel.name!r} with a shape that differs '
                        f'from plugin {owner_slug!r}'
                    )
                continue
            seen_vlabels[vlabel.name] = (manifest.slug, vlabel)

        for elabel in manifest.edge_labels:
            existing_edge = seen_edges.get(elabel.name)
            if existing_edge is not None:
                owner_slug, owner_edge = existing_edge
                if owner_edge != elabel:
                    LOGGER.error(
                        'Plugin %r declares edge label %r with a shape '
                        'that differs from plugin %r',
                        manifest.slug,
                        elabel.name,
                        owner_slug,
                    )
                    raise PluginSchemaCollisionError(
                        f'Plugin {manifest.slug!r} declares edge label '
                        f'{elabel.name!r} with a shape that differs '
                        f'from plugin {owner_slug!r}'
                    )
                continue
            seen_edges[elabel.name] = (manifest.slug, elabel)


async def apply_plugin_schemas(
    manifests: list[PluginManifest],
) -> None:
    """Apply each plugin's declared vlabels + indexes to AGE.

    Mirrors :func:`imbi_common.graph.initializer.initialize` primitives.
    Idempotent — safe to invoke on every startup.
    """
    if not manifests:
        return

    validate_no_collisions(manifests)

    postgres = settings.Postgres()

    async with await psycopg.AsyncConnection.connect(
        str(postgres.url),
        autocommit=True,
    ) as conn:
        await conn.execute(
            'SET search_path = ag_catalog, "$user", public',
        )
        async with conn.cursor() as cursor:
            for manifest in manifests:
                for vlabel in manifest.vertex_labels:
                    await _ensure_vlabel(
                        cursor, postgres.graph_name, vlabel.name
                    )
                    for index in vlabel.indexes:
                        await _ensure_vlabel_index(
                            cursor,
                            postgres.graph_name,
                            vlabel.name,
                            index.fields,
                            index.unique,
                        )


async def _ensure_vlabel(
    cursor: psycopg.AsyncCursor[typing.Any],
    graph_name: str,
    vlabel: str,
) -> None:
    exists = await cursor.execute(
        sql.SQL(
            'SELECT 1'
            '  FROM ag_catalog.ag_label'
            ' WHERE name = {vlabel}'
            '   AND graph = ('
            '        SELECT graphid'
            '          FROM ag_catalog.ag_graph'
            '         WHERE name = {graph})',
        ).format(
            vlabel=sql.Literal(vlabel),
            graph=sql.Literal(graph_name),
        ),
    )
    if await exists.fetchone():
        return
    LOGGER.info('Creating plugin-declared vlabel %s.%s', graph_name, vlabel)
    await cursor.execute(
        sql.SQL(
            'SELECT ag_catalog.create_vlabel({graph}, {vlabel})',
        ).format(
            graph=sql.Literal(graph_name),
            vlabel=sql.Literal(vlabel),
        ),
    )


async def _ensure_vlabel_index(
    cursor: psycopg.AsyncCursor[typing.Any],
    graph_name: str,
    vlabel: str,
    attributes: list[str],
    unique: bool,
) -> None:
    name_parts = [vlabel.lower()]
    name_parts.extend(a.lower() for a in attributes)
    if unique:
        name_parts.append('unique')
    name_parts.append('idx')
    idx_name = '_'.join(name_parts)

    cols = sql.SQL(', ').join(
        sql.SQL(
            'ag_catalog.agtype_access_operator(properties, \'"{}"\'::agtype)',
        ).format(sql.SQL(attr))
        for attr in attributes
    )
    unique_clause = sql.SQL('UNIQUE ') if unique else sql.SQL('')

    await cursor.execute(
        sql.SQL(
            'CREATE {unique}INDEX IF NOT EXISTS'
            ' {idx_name} ON {schema}.{table} ({cols})',
        ).format(
            unique=unique_clause,
            idx_name=sql.Identifier(idx_name),
            schema=sql.Identifier(graph_name),
            table=sql.Identifier(vlabel),
            cols=cols,
        ),
    )
