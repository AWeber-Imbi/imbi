"""Read parameter values from the database.

The recorder runs against the AGE-era database, so most sources are
Cypher queries. Values are strings, because they go into URLs.
"""

import re
import typing

import psycopg
from psycopg import sql

if typing.TYPE_CHECKING:
    from scripts.replay import models

_VARIABLE = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)')
_COLUMN = re.compile(r'^[a-z_][a-z0-9_]*$')

Row = dict[str, str]


def _quote_cypher(value: str) -> str:
    escaped = value.replace('\\', '\\\\').replace("'", "\\'")
    return f"'{escaped}'"


def substitute(query: str, variables: dict[str, str], *, cypher: bool) -> str:
    """Replace ``$name`` with the quoted value of a global variable."""

    def replace(found: re.Match[str]) -> str:
        name = found.group(1)
        if name not in variables:
            raise KeyError(f'the query uses ${name}, which has no value')
        if cypher:
            return _quote_cypher(variables[name])
        return "'" + variables[name].replace("'", "''") + "'"

    return _VARIABLE.sub(replace, query)


def _text(value: typing.Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


class Database:
    """A read-only connection to the recorded database."""

    def __init__(self, dsn: str, graph: str) -> None:
        # ``read_only`` on the connection has no effect in autocommit
        # mode, so the session setting makes every statement read only.
        self._connection = psycopg.connect(
            dsn,
            autocommit=True,
            options='-c default_transaction_read_only=on',
        )
        self._graph = graph
        self._connection.execute(
            'SET search_path = ag_catalog, "$user", public'
        )

    def close(self) -> None:
        self._connection.close()

    def fetch(
        self,
        source: models.Source,
        variables: dict[str, str],
        limit: int,
    ) -> list[Row]:
        """Return up to ``limit`` rows. A row with a NULL is dropped."""
        if source.rows is not None:
            return [dict(row) for row in source.rows[:limit]]
        if source.cypher is not None:
            return self._cypher(source, variables, limit)
        if source.sql is None:  # pragma: no cover - the model prevents it
            raise ValueError('source has no query')
        query = substitute(source.sql, variables, cypher=False)
        statement = sql.SQL(
            'SELECT * FROM ({query}) AS q LIMIT {limit}'
        ).format(
            query=sql.SQL(query),  # pyright: ignore[reportArgumentType]
            limit=sql.Literal(limit),
        )
        with self._connection.cursor() as cursor:
            cursor.execute(statement)
            names = [column.name for column in cursor.description or []]
            rows: list[Row] = []
            for record in cursor.fetchall():
                values = [_text(value) for value in record]
                if all(value is not None for value in values):
                    rows.append(
                        dict(
                            zip(
                                names,
                                typing.cast('list[str]', values),
                                strict=True,
                            )
                        )
                    )
            return rows

    def _cypher(
        self,
        source: models.Source,
        variables: dict[str, str],
        limit: int,
    ) -> list[Row]:
        for column in source.columns:
            if not _COLUMN.match(column):
                raise ValueError(f'bad column name {column!r}')
        query = substitute(source.cypher or '', variables, cypher=True)
        if '$$' in query:
            raise ValueError('a cypher source cannot contain "$$"')
        columns = sql.SQL(', ').join(
            sql.SQL('{} agtype').format(sql.Identifier(column))
            for column in source.columns
        )
        texts = sql.SQL(', ').join(
            sql.SQL('{}::text').format(sql.Identifier(column))
            for column in source.columns
        )
        statement = sql.SQL(
            'SELECT {texts} FROM ag_catalog.cypher({graph}, $$ {query} $$)'
            ' AS ({columns}) LIMIT {limit}'
        ).format(
            texts=texts,
            graph=sql.Literal(self._graph),
            query=sql.SQL(query),  # pyright: ignore[reportArgumentType]
            columns=columns,
            limit=sql.Literal(limit),
        )
        with self._connection.cursor() as cursor:
            cursor.execute(statement)
            rows: list[Row] = []
            for record in cursor.fetchall():
                # ``agtype::text`` gives a string scalar without its
                # quotes, and a number or a boolean as its literal.
                values = list(record)
                if all(value is not None for value in values):
                    rows.append(
                        dict(
                            zip(
                                source.columns,
                                typing.cast('list[str]', values),
                                strict=True,
                            )
                        )
                    )
            return rows
