"""
Some postgres/sql/psycopg helper functions

I would have called this module either psycopg or sql but both
names can be pretty problematic, so I settled on postgres. The
goal is to collect SQL query helpers into this module when they
are applicable to multiple uses.

"""
from __future__ import annotations

import typing
import uuid

import sprockets_postgres
from psycopg2 import sql

_omitted = str(uuid.uuid4())


async def insert_values(
        conn: sprockets_postgres.PostgresConnector, schema: str,
        table_name: str, column_names: typing.Iterable[str],
        rows: typing.Iterable[typing.Iterable[typing.Any]]) -> None:
    """Insert multiple rows at the same time

    This is similar to the psycopg2 execute_values function and
    I would use it were it included in psycopg 3. Instead, this
    implements the SQL building approach described briefly in
    https://github.com/psycopg/psycopg/issues/576 .

    .. code-block::

       INSERT INTO {schema}.{table_name} ({column_names})
            VALUES (*rows[0]), (*rows[1]), ...

    """
    if not rows:
        return

    # please avert your eyes ... I apologize
    query = sql.SQL('INSERT INTO {table} ({columns}) VALUES {values}').format(
        table=sql.Identifier(schema, table_name),
        columns=sql.SQL(',').join(sql.Identifier(n) for n in column_names),
        values=sql.SQL(',').join(
            sql.SQL('({})').format(
                sql.SQL(',').join(sql.Literal(v) for v in row))
            for row in rows))
    await conn.execute(query.as_string(conn.cursor.raw),
                       metric_name=f'insert-{table_name}')


async def update_entity(
    conn: sprockets_postgres.PostgresConnector,
    schema: str,
    table_name: str,
    original: dict[str, typing.Any],
    updated: dict[str, typing.Any],
    columns: typing.Iterable[str],
    *,
    id_column: str = 'id',
    id_value: typing.Any = _omitted,
) -> None:
    """Update an entity from `original` into `updated`

    This function dynamically generates the SQL UPDATE statement
    constraining the changes to those in `columns`. The row is
    assumed to be identified by a column named ``id``. The value
    is taken from ``original['id']``.

    .. code-block::

       UPDATE {schema}.{table_name}
          SET col1 = updated[col1],
              ...
        WHERE id = original[id]

    """
    modified_columns = [c for c in columns if original[c] != updated[c]]
    if not modified_columns:
        return None

    id_value = original[id_column] if id_value is _omitted else id_value
    query = sql.SQL(
        'UPDATE {table} SET {values} WHERE {id_column} = {id_value}').format(
            table=sql.Identifier(schema, table_name),
            values=sql.SQL(',').join(
                sql.SQL('{} = {}').format(sql.Identifier(column),
                                          sql.Literal(updated[column]))
                for column in modified_columns),
            id_column=sql.Identifier(id_column),
            id_value=sql.Literal(id_value),
        )
    await conn.execute(query.as_string(conn.cursor.raw),
                       metric_name=f'update-{table_name}')
