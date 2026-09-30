"""A fake target schema and static mappings for the runner tests."""

import collections.abc
import typing

import psycopg

from imbi.common.db.etl import mapping
from libraries.common.tests.db.etl import support

SCHEMA = """
CREATE TABLE parent (
    id text PRIMARY KEY,
    name text NOT NULL,
    data jsonb,
    labels text[] NOT NULL DEFAULT '{}'
);
CREATE TABLE child (
    id text PRIMARY KEY,
    parent_id text NOT NULL REFERENCES parent,
    created_at timestamptz
);
CREATE TABLE node (
    id text PRIMARY KEY,
    parent_id text REFERENCES node
);
"""


class Static:
    """A mapping that yields fixed events."""

    source_labels = ('Fake',)
    source_edges = ()

    def __init__(
        self,
        table: str,
        columns: tuple[str, ...],
        events: collections.abc.Sequence[mapping.Event],
        expected: mapping.Expected | None = None,
    ) -> None:
        self.table = table
        self.columns = columns
        self.events = events
        self._expected = expected

    async def rows(
        self, context: mapping.Context
    ) -> collections.abc.AsyncIterator[mapping.Event]:
        for event in self.events:
            yield event

    async def expected(self, context: mapping.Context) -> mapping.Expected:
        if self._expected is not None:
            return self._expected
        count = sum(1 for e in self.events if isinstance(e, dict))
        return mapping.Expected(count=count)


def parent(row_id: str, **values: object) -> mapping.Row:
    return {
        'id': row_id,
        'name': values.get('name', row_id),
        'data': values.get('data'),
        'labels': values.get('labels', []),
    }


def registry(
    parents: collections.abc.Sequence[mapping.Event] = (),
    children: collections.abc.Sequence[mapping.Event] = (),
    nodes: collections.abc.Sequence[mapping.Event] = (),
) -> dict[str, mapping.Mapping]:
    """Return the three mappings, children first, to test the order."""
    return {
        'child': Static('child', ('id', 'parent_id', 'created_at'), children),
        'node': Static('node', ('id', 'parent_id'), nodes),
        'parent': Static('parent', ('id', 'name', 'data', 'labels'), parents),
    }


async def target(
    case: typing.Any,
) -> tuple[
    psycopg.AsyncConnection[typing.Any], psycopg.AsyncConnection[typing.Any]
]:
    """Reset the fake target database. Return (source, target) connections.

    The mappings are static, so the source is a second connection to
    the same database.

    """
    name = await support.scratch_database()
    target_conn = await psycopg.AsyncConnection.connect(support.url(name))
    case.addAsyncCleanup(target_conn.close)
    await support.reset(target_conn, 'other', 'g')
    await target_conn.execute(SCHEMA)
    await target_conn.commit()
    source_conn = await psycopg.AsyncConnection.connect(support.url(name))
    case.addAsyncCleanup(source_conn.close)
    return source_conn, target_conn


async def rows(
    conn: psycopg.AsyncConnection[typing.Any], query: str
) -> list[tuple[typing.Any, ...]]:
    cursor = await conn.execute(query)
    result = await cursor.fetchall()
    await conn.commit()
    return result
