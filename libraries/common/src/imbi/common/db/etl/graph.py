"""Read the AGE graph with plain SQL.

AGE keeps each vertex label in the table ``<graph>."<Label>"`` and each
edge type in ``<graph>."<TYPE>"``. The ETL reads those tables directly,
so it does not need the Cypher client (``imbi.common.graph``). A label
that no code has written yet has no table; it reads as empty.
"""

import collections.abc
import dataclasses
import datetime
import itertools
import json
import typing

import psycopg
from psycopg import sql

from imbi.common.db.etl import ids, mapping

Properties = dict[str, typing.Any]

#: Names of the server-side cursors. A server-side cursor lets a mapping
#: run other queries on the same connection while it reads.
_CURSOR_NAMES = (f'etl_read_{n}' for n in itertools.count())


def vertex_id(label: str, graph_id: str, properties: Properties) -> str:
    """Return the ``id`` of a vertex (Appendix E, E36).

    Some vertices have no ``id`` property, for example the seeded
    ``Organization``. Their id is derived from the label and the graph
    id, so a second run on the same source gives the same id.

    """
    value = properties.get('id')
    if value is None or value == '':
        return ids.derive_id(label, graph_id)
    return str(value)


@dataclasses.dataclass(frozen=True, slots=True)
class Vertex:
    """One vertex: its label, its AGE graph id (as text), its properties."""

    label: str
    graph_id: str
    properties: Properties

    @property
    def id(self) -> str:
        """The ``id`` property, or the derived id (E36)."""
        return vertex_id(self.label, self.graph_id, self.properties)


@dataclasses.dataclass(frozen=True, slots=True)
class EdgeRow:
    """One edge with its two vertices."""

    start: Vertex
    graph_id: str
    properties: Properties
    end: Vertex


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
) -> collections.abc.AsyncIterator[Vertex]:
    """Yield each vertex of *label*.

    The order is the graph id order, so it is the same for each read of
    the same source.

    """
    if not await label_exists(conn, graph, label):
        return
    query = sql.SQL(
        'SELECT id::text, properties::text::jsonb FROM {} ORDER BY id'
    ).format(sql.Identifier(graph, label))
    async with conn.cursor(name=next(_CURSOR_NAMES)) as cursor:
        cursor.itersize = 1000
        await cursor.execute(query)
        async for graph_id, properties in cursor:
            yield Vertex(label, str(graph_id), properties)


async def read_edges(
    conn: psycopg.AsyncConnection[typing.Any],
    graph: str,
    edge_type: str,
    *,
    start_label: str,
    end_label: str,
) -> collections.abc.AsyncIterator[EdgeRow]:
    """Yield each edge of *edge_type* with its two vertices.

    Only the edges from a *start_label* vertex to an *end_label* vertex
    are read, because one edge type connects many label pairs (for
    example ``BELONGS_TO``).

    """
    for name in (edge_type, start_label, end_label):
        if not await label_exists(conn, graph, name):
            return
    query = sql.SQL(
        'SELECT s.id::text, s.properties::text::jsonb,'
        ' e.id::text, e.properties::text::jsonb,'
        ' t.id::text, t.properties::text::jsonb'
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
        async for row in cursor:
            yield EdgeRow(
                start=Vertex(start_label, str(row[0]), row[1]),
                graph_id=str(row[2]),
                properties=row[3],
                end=Vertex(end_label, str(row[4]), row[5]),
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
    async for edge in read_edges(
        conn,
        graph,
        edge_type,
        start_label=start_label,
        end_label=end_label,
    ):
        targets.setdefault(edge.start.id, set()).add(edge.end.id)
    return targets


async def only_organization_id(
    conn: psycopg.AsyncConnection[typing.Any], graph: str
) -> str:
    """Return the ``id`` of the one ``Organization`` vertex.

    Plan O2: a row that has no organization in the graph belongs to the
    one production organization. Appendix E, E1 blocks the ETL when
    there is more than one, so this raises unless there is exactly one.

    """
    found = [org.id async for org in read_label(conn, graph, 'Organization')]
    if len(found) != 1:
        raise mapping.EtlError(
            f'Plan O2 needs one organization; the graph has {len(found)}'
        )
    return found[0]


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


def created_at(
    properties: Properties,
    context: mapping.Context,
    *fallbacks: datetime.datetime | None,
    what: str,
) -> datetime.datetime:
    """Return the ``created_at`` of a row (Appendix E, E40).

    In order: the ``created_at`` property, the ``updated_at`` property,
    the first of *fallbacks* that is not ``None`` (the ``created_at`` of
    the row that this row belongs to), and the ``--missing-timestamp``
    option. *what* names the row in the error when all are missing.

    """
    for value in (
        timestamp(properties.get('created_at')),
        timestamp(properties.get('updated_at')),
        *fallbacks,
    ):
        if value is not None:
            return value
    if context.missing_timestamp is None:
        raise mapping.EtlError(
            f'{what} has no created_at, and no --missing-timestamp'
            ' is given (E40)'
        )
    return context.missing_timestamp


def attributes(
    properties: Properties,
    columns: collections.abc.Set[str],
    booleans: collections.abc.Set[str] = frozenset(),
) -> dict[str, typing.Any]:
    """Return the blueprint attributes of a vertex.

    Each property that is not in *columns* is an attribute. For a key in
    *booleans* (a ``boolean`` field of a blueprint), the strings
    ``'true'`` and ``'false'`` become JSON booleans (D32). Other values
    stay as they are.

    """
    result: dict[str, typing.Any] = {}
    for key, value in sorted(properties.items()):
        if key in columns:
            continue
        if key in booleans and value in ('true', 'false'):
            value = value == 'true'
        result[key] = value
    return result


async def boolean_attributes(
    conn: psycopg.AsyncConnection[typing.Any],
    graph: str,
    blueprint_type: str,
) -> frozenset[str]:
    """Return the ``boolean`` fields of the node blueprints of a type.

    Every blueprint of the type counts, enabled or not: a value that a
    disabled blueprint wrote is still a boolean.

    """
    names: set[str] = set()
    async for blueprint in read_label(conn, graph, 'Blueprint'):
        props = blueprint.properties
        if props.get('kind', 'node') != 'node':
            continue
        if props.get('type') != blueprint_type:
            continue
        schema = json_object(props.get('json_schema'))
        fields = typing.cast(
            dict[str, typing.Any], schema.get('properties') or {}
        )
        for name, field in fields.items():
            if not isinstance(field, dict):
                continue
            kind = typing.cast(dict[str, typing.Any], field).get('type')
            kinds: list[typing.Any] = (
                kind if isinstance(kind, list) else [kind]
            )
            if 'boolean' in kinds:
                names.add(name)
    return frozenset(names)


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
