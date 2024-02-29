"""
Some postgres/sql/psycopg helper functions

I would have called this module either psycopg or sql but both
names can be pretty problematic, so I settled on postgres. The
goal is to collect SQL query helpers into this module when they
are applicable to multiple uses.

"""
import typing

import sprockets_postgres
from psycopg2 import sql


async def insert_values(
        conn: sprockets_postgres.PostgresConnector, schema: str,
        table_name: str, column_names: typing.Iterable[str],
        rows: typing.Iterable[typing.Iterable[typing.Any]]) -> None:
    """Insert multiple rows at the same time

    This is similar to the psycopg2 execute_values function and
    I would use it were it included in psycopg 3. Instead, this
    implements the SQL building approach described briefly in
    https://github.com/psycopg/psycopg/issues/576 .

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
    await conn.execute(query.as_string(conn.cursor.raw))
