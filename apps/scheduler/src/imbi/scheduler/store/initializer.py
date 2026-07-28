"""Create the scheduler's Postgres schema from ``schemata.toml``.

Follows :mod:`imbi.common.graph.initializer`: read a declarative TOML file,
compose identifiers with :mod:`psycopg.sql`, and issue only ``IF NOT EXISTS``
DDL so a re-run is a no-op. There is no migration framework in this repo, so
column changes are additive and applied here.
"""

import logging
import pathlib
import tomllib
import typing

import psycopg
from psycopg import sql

from imbi.common import settings as common_settings
from imbi.scheduler import settings

LOGGER = logging.getLogger(__name__)

SCHEMATA_PATH = pathlib.Path(__file__).parent / 'schemata.toml'


def load_schemata() -> dict[str, typing.Any]:
    """Return the parsed schema definition."""
    return tomllib.loads(SCHEMATA_PATH.read_text())


async def initialize() -> None:
    """Create the scheduler schema, tables, and indexes."""
    postgres = common_settings.Postgres()
    schema = settings.Scheduler().schema_name
    schemata = load_schemata()
    async with (
        await psycopg.AsyncConnection.connect(
            str(postgres.url), autocommit=True
        ) as conn,
        conn.cursor() as cursor,
    ):
        await _create_schema(cursor, schema)
        for table in schemata.get('tables', []):
            await _create_table(cursor, schema, table)
            await _create_indexes(cursor, schema, table)
    LOGGER.info('Scheduler schema %r initialized', schema)


async def _create_schema(
    cursor: psycopg.AsyncCursor[typing.Any], schema: str
) -> None:
    await cursor.execute(
        sql.SQL('CREATE SCHEMA IF NOT EXISTS {schema}').format(
            schema=sql.Identifier(schema)
        )
    )


async def _create_table(
    cursor: psycopg.AsyncCursor[typing.Any],
    schema: str,
    table: dict[str, typing.Any],
) -> None:
    col_defs = sql.SQL(', ').join(
        sql.SQL('{name} {type}').format(
            name=sql.Identifier(name), type=sql.SQL(col_type)
        )
        for name, col_type in table['columns'].items()
    )
    pk_def = sql.SQL('PRIMARY KEY ({cols})').format(
        cols=sql.SQL(', ').join(
            sql.Identifier(col) for col in table['primary_key']['columns']
        )
    )
    await cursor.execute(
        sql.SQL(
            'CREATE TABLE IF NOT EXISTS {table} ({col_defs}, {pk_def})'
        ).format(
            table=sql.Identifier(schema, table['name']),
            col_defs=col_defs,
            pk_def=pk_def,
        )
    )
    await _add_missing_columns(cursor, schema, table)


async def _add_missing_columns(
    cursor: psycopg.AsyncCursor[typing.Any],
    schema: str,
    table: dict[str, typing.Any],
) -> None:
    """Add columns declared since the table was created.

    ``CREATE TABLE IF NOT EXISTS`` silently ignores new columns on an
    existing table, which would leave a deployed schema behind this file.
    """
    for name, col_type in table['columns'].items():
        await cursor.execute(
            sql.SQL(
                'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {type}'
            ).format(
                table=sql.Identifier(schema, table['name']),
                name=sql.Identifier(name),
                type=sql.SQL(col_type),
            )
        )


async def _create_indexes(
    cursor: psycopg.AsyncCursor[typing.Any],
    schema: str,
    table: dict[str, typing.Any],
) -> None:
    for index in table.get('indexes', []):
        unique = sql.SQL('UNIQUE ') if index.get('unique') else sql.SQL('')
        await cursor.execute(
            sql.SQL(
                'CREATE {unique}INDEX IF NOT EXISTS {name} ON {table} ({cols})'
            ).format(
                unique=unique,
                name=sql.Identifier(index['name']),
                table=sql.Identifier(schema, table['name']),
                cols=sql.SQL(', ').join(
                    sql.Identifier(col) for col in index['columns']
                ),
            )
        )
