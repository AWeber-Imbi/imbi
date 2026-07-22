"""Initialize the graph database based on schemata.toml."""

import logging
import pathlib
import tomllib
import typing

import psycopg
from psycopg import sql

from imbi_common import settings

LOGGER = logging.getLogger(__name__)


async def initialize() -> None:
    """Initialize the graph database based on schemata.toml."""
    postgres = settings.Postgres()

    path = pathlib.Path(__file__).parent / 'schemata.toml'
    schemata = tomllib.loads(path.read_text())

    async with await psycopg.AsyncConnection.connect(
        str(postgres.url),
        autocommit=True,
    ) as conn:
        await conn.execute(
            'SET search_path = ag_catalog, "$user", public',
        )
        async with conn.cursor() as cursor:
            await _create_extensions(cursor, schemata)
            await _create_graph(cursor, postgres.graph_name)
            await _create_vlabels(
                cursor,
                postgres.graph_name,
                schemata,
            )
            await _create_vlabel_indexes(
                cursor,
                postgres.graph_name,
                schemata,
            )
            await _create_embeddings_table(
                cursor,
                schemata,
            )
            await _create_functions(cursor, schemata)


async def _create_extensions(
    cursor: psycopg.AsyncCursor[typing.Any],
    schemata: dict[str, typing.Any],
) -> None:
    for ext in schemata.get('extensions', []):
        await cursor.execute(
            sql.SQL(
                'CREATE EXTENSION IF NOT EXISTS {ext}',
            ).format(ext=sql.Identifier(ext['name'])),
        )


async def _create_graph(
    cursor: psycopg.AsyncCursor[typing.Any],
    graph_name: str,
) -> None:
    result = await cursor.execute(
        sql.SQL(
            'SELECT 1 FROM ag_catalog.ag_graph WHERE name = {name}',
        ).format(name=sql.Literal(graph_name)),
    )
    if await result.fetchone():
        return
    LOGGER.info('Creating graph %s', graph_name)
    await cursor.execute(
        sql.SQL(
            'SELECT ag_catalog.create_graph({name})',
        ).format(name=sql.Literal(graph_name)),
    )


async def _create_vlabels(
    cursor: psycopg.AsyncCursor[typing.Any],
    graph_name: str,
    schemata: dict[str, typing.Any],
) -> None:
    for vlabel in schemata.get('vlabels', {}).get('name', []):
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
            continue
        LOGGER.info(
            'Creating vlabel %s.%s',
            graph_name,
            vlabel,
        )
        await cursor.execute(
            sql.SQL(
                'SELECT ag_catalog.create_vlabel({graph}, {vlabel})',
            ).format(
                graph=sql.Literal(graph_name),
                vlabel=sql.Literal(vlabel),
            ),
        )


async def _create_vlabel_indexes(
    cursor: psycopg.AsyncCursor[typing.Any],
    graph_name: str,
    schemata: dict[str, typing.Any],
) -> None:
    for idx in schemata.get('vlabel_indexes', []):
        vlabel = idx['vlabel']
        attrs = idx['attributes']
        unique = idx.get('unique', False)

        name_parts = [vlabel.lower()]
        name_parts.extend(a.lower() for a in attrs)
        if unique:
            name_parts.append('unique')
        name_parts.append('idx')
        idx_name = '_'.join(name_parts)

        cols = sql.SQL(', ').join(
            sql.SQL(
                'ag_catalog.agtype_access_operator('
                'properties, \'"{}"\'::agtype)',
            ).format(sql.SQL(attr))
            for attr in attrs
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


async def _create_embeddings_table(
    cursor: psycopg.AsyncCursor[typing.Any],
    schemata: dict[str, typing.Any],
) -> None:
    embed_conf = schemata.get('embeddings')
    if not embed_conf:
        return

    table = sql.SQL(embed_conf['table'])
    columns = embed_conf['columns']
    pk_cols = embed_conf['primary_key']['columns']

    col_defs = sql.SQL(', ').join(
        sql.SQL('{name} {type}').format(
            name=sql.Identifier(name),
            type=sql.SQL(col_type),
        )
        for name, col_type in columns.items()
    )

    pk_def = sql.SQL(
        'PRIMARY KEY ({cols})',
    ).format(
        cols=sql.SQL(', ').join(sql.Identifier(c) for c in pk_cols),
    )

    await cursor.execute(
        sql.SQL(
            'CREATE TABLE IF NOT EXISTS {table} ({col_defs}, {pk_def})',
        ).format(
            table=table,
            col_defs=col_defs,
            pk_def=pk_def,
        ),
    )

    # Standard B-tree indexes
    for idx in embed_conf.get('indexes', []):
        idx_cols = sql.SQL(', ').join(
            sql.Identifier(c) for c in idx['columns']
        )
        await cursor.execute(
            sql.SQL(
                'CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})',
            ).format(
                name=sql.Identifier(idx['name']),
                table=table,
                cols=idx_cols,
            ),
        )

    # HNSW vector index — dimensions and model_name from settings
    hnsw = embed_conf.get('hnsw_index')
    if hnsw:
        embed_settings = settings.Embeddings()
        model_name = embed_settings.default_model
        model_conf = embed_settings.models.get(model_name)
        if not model_conf:
            LOGGER.warning(
                'Skipping HNSW index %s: model %r not configured',
                hnsw['name'],
                model_name,
            )
        else:
            await cursor.execute(
                sql.SQL(
                    'CREATE INDEX IF NOT EXISTS {name}'
                    ' ON {table}'
                    ' USING hnsw'
                    ' ((embedding::vector({dims}))'
                    ' {ops})'
                    ' WHERE model_name = {model}',
                ).format(
                    name=sql.Identifier(hnsw['name']),
                    table=table,
                    dims=sql.Literal(model_conf.dimensions),
                    ops=sql.SQL(hnsw['ops']),
                    model=sql.Literal(model_name),
                ),
            )


async def _create_functions(
    cursor: psycopg.AsyncCursor[typing.Any],
    schemata: dict[str, typing.Any],
) -> None:
    for func in schemata.get('functions', []):
        await cursor.execute(
            sql.SQL(
                'CREATE OR REPLACE FUNCTION {name}({args})'
                ' RETURNS {returns}'
                ' AS $${body}$$'
                ' LANGUAGE {lang}',
            ).format(
                name=sql.SQL(func['name']),
                args=sql.SQL(func['args']),
                returns=sql.SQL(func['returns']),
                body=sql.SQL(func['body']),
                lang=sql.SQL(func['language']),
            ),
        )
