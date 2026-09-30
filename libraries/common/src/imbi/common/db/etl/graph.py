"""Read the AGE graph with plain SQL.

AGE keeps each vertex label in the table ``<graph>."<Label>"`` and each
edge type in ``<graph>."<TYPE>"``. The ETL reads those tables directly,
so it does not need the Cypher client (``imbi.common.graph``). A label
that no code has written yet has no table; it reads as empty.
"""

import collections.abc
import datetime
import itertools
import json
import typing

import psycopg
from psycopg import sql

from imbi.common.db.etl import mapping

Properties = dict[str, typing.Any]

#: Names of the server-side cursors. A server-side cursor lets a mapping
#: run other queries on the same connection while it reads.
_CURSOR_NAMES = (f'etl_read_{n}' for n in itertools.count())


async def label_exists(
    conn: psycopg.AsyncConnection[typing.Any], graph: str, label: str
) -> bool:
    """Return ``True`` when the table of *label* exists."""
    cursor = await conn.execute(
        'SELECT to_regclass(%s) IS NOT NULL',
        (sql.Identifier(graph, label).as_string(conn),),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def read_label(
    conn: psycopg.AsyncConnection[typing.Any], graph: str, label: str
) -> collections.abc.AsyncIterator[Properties]:
    """Yield the properties of each vertex of *label*.

    The order is the graph id order, so it is the same for each read of
    the same source.

    """
    if not await label_exists(conn, graph, label):
        return
    query = sql.SQL(
        'SELECT properties::text::jsonb FROM {} ORDER BY id'
    ).format(sql.Identifier(graph, label))
    async with conn.cursor(name=next(_CURSOR_NAMES)) as cursor:
        cursor.itersize = 1000
        await cursor.execute(query)
        async for (properties,) in cursor:
            yield typing.cast(Properties, properties)


async def read_edges(
    conn: psycopg.AsyncConnection[typing.Any],
    graph: str,
    edge_type: str,
    *,
    start_label: str,
    end_label: str,
) -> collections.abc.AsyncIterator[tuple[Properties, Properties, Properties]]:
    """Yield ``(start, edge, end)`` properties for each edge.

    Only the edges from a *start_label* vertex to an *end_label* vertex
    are read, because one edge type connects many label pairs (for
    example ``BELONGS_TO``).

    """
    for name in (edge_type, start_label, end_label):
        if not await label_exists(conn, graph, name):
            return
    query = sql.SQL(
        'SELECT s.properties::text::jsonb,'
        ' e.properties::text::jsonb,'
        ' t.properties::text::jsonb'
        ' FROM {edge} AS e'
        ' JOIN {start} AS s ON s.id {eq} e.start_id'
        ' JOIN {end} AS t ON t.id {eq} e.end_id'
        ' ORDER BY e.id'
    ).format(
        edge=sql.Identifier(graph, edge_type),
        start=sql.Identifier(graph, start_label),
        end=sql.Identifier(graph, end_label),
        eq=await id_equals(conn, graph, edge_type),
    )
    async with conn.cursor(name=next(_CURSOR_NAMES)) as cursor:
        cursor.itersize = 1000
        await cursor.execute(query)
        async for start, edge, end in cursor:
            yield (
                typing.cast(Properties, start),
                typing.cast(Properties, edge),
                typing.cast(Properties, end),
            )


async def id_equals(
    conn: psycopg.AsyncConnection[typing.Any], graph: str, table: str
) -> sql.Composable:
    """Return the ``=`` operator for the graph ids of *table*.

    AGE ids are ``ag_catalog.graphid``, and its ``=`` is in
    ``ag_catalog``, which is not on the search path. A fake graph uses
    ``bigint``. Use it in each SQL join on a graph id.

    """
    cursor = await conn.execute(
        'SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_attribute'
        ' WHERE attrelid = to_regclass(%s) AND attname = %s'
        " AND atttypid = to_regtype('ag_catalog.graphid'))",
        (sql.Identifier(graph, table).as_string(conn), 'id'),
    )
    row = await cursor.fetchone()
    if row and row[0]:
        return sql.SQL('OPERATOR(ag_catalog.=)')
    return sql.SQL('=')


async def edge_targets(
    conn: psycopg.AsyncConnection[typing.Any],
    graph: str,
    edge_type: str,
    *,
    start_label: str,
    end_label: str,
) -> dict[str, set[str]]:
    """Return the ``id`` of each end vertex, by the start vertex ``id``."""
    targets: dict[str, set[str]] = {}
    async for start, _edge, end in read_edges(
        conn,
        graph,
        edge_type,
        start_label=start_label,
        end_label=end_label,
    ):
        targets.setdefault(str(start['id']), set()).add(str(end['id']))
    return targets


def timestamp(value: object) -> datetime.datetime | None:
    """Parse a graph timestamp (an ISO 8601 string).

    A timestamp with no zone is UTC, because the application writes
    ``datetime.now(datetime.UTC)``. ``None`` and ``''`` give ``None``.

    """
    if value is None or value == '':
        return None
    if not isinstance(value, str):
        raise mapping.EtlError(f'Timestamp {value!r} is not a string')
    parsed = datetime.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed


def json_array(value: object) -> list[typing.Any]:
    """Return a graph list property as a list (Appendix E, E30).

    Some writers store a list as JSON text, so a string is decoded.
    ``None`` and ``''`` give an empty list.

    """
    decoded = _decode(value)
    if decoded is None:
        return []
    if not isinstance(decoded, list):
        raise mapping.EtlError(f'Value {value!r} is not a list')
    result: list[typing.Any] = decoded
    return result


def json_object(value: object) -> dict[str, typing.Any]:
    """Return a graph map property as a dict (Appendix E, E30).

    Some writers store a map as JSON text, so a string is decoded.
    ``None`` and ``''`` give an empty dict.

    """
    decoded = _decode(value)
    if decoded is None:
        return {}
    if not isinstance(decoded, dict):
        raise mapping.EtlError(f'Value {value!r} is not a map')
    return typing.cast(dict[str, typing.Any], decoded)


def _decode(value: object) -> object:
    if value is None or value == '':
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value
