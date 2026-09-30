"""Read the structure of the target tables from the PostgreSQL catalog.

The runner takes the foreign key order from here, and the
reconciliation takes the NOT NULL columns, the unique keys, the foreign
keys, and the JSON columns. The schema of record is ``schemata/``; the
catalog is what ``pglifecycle deploy`` made of it.
"""

import collections.abc
import dataclasses
import graphlib
import typing

import psycopg

from imbi.common.db.etl import mapping

SCHEMA = 'public'


@dataclasses.dataclass(frozen=True, slots=True)
class ForeignKey:
    name: str
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class UniqueKey:
    """A unique index. ``keys`` are SQL: column names or expressions."""

    name: str
    keys: tuple[str, ...]
    predicate: str | None
    nulls_not_distinct: bool
    primary: bool


@dataclasses.dataclass(frozen=True, slots=True)
class Table:
    name: str
    columns: tuple[str, ...]
    not_null: tuple[str, ...]
    json_columns: frozenset[str]
    foreign_keys: tuple[ForeignKey, ...]
    unique_keys: tuple[UniqueKey, ...]

    @property
    def primary_key(self) -> tuple[str, ...]:
        for key in self.unique_keys:
            if key.primary:
                return key.keys
        return ()

    @property
    def self_references(self) -> tuple[ForeignKey, ...]:
        return tuple(
            fk for fk in self.foreign_keys if fk.ref_table == self.name
        )

    @property
    def is_join_table(self) -> bool:
        """``True`` when each primary key column is in a foreign key."""
        referenced = {c for fk in self.foreign_keys for c in fk.columns}
        key = self.primary_key
        return (
            len(self.foreign_keys) >= 2
            and bool(key)
            and set(key) <= referenced
        )


_COLUMNS = """
SELECT c.relname, a.attname, a.attnotnull,
       COALESCE(b.typname, t.typname)
  FROM pg_catalog.pg_attribute AS a
  JOIN pg_catalog.pg_class AS c ON c.oid = a.attrelid
  JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
  JOIN pg_catalog.pg_type AS t ON t.oid = a.atttypid
  LEFT JOIN pg_catalog.pg_type AS b
         ON t.typtype = 'd' AND b.oid = t.typbasetype
 WHERE n.nspname = %s
   AND c.relkind IN ('r', 'p')
   AND a.attnum > 0
   AND NOT a.attisdropped
   AND a.attgenerated = ''
 ORDER BY c.relname, a.attnum
"""

_FOREIGN_KEYS = """
SELECT con.conname, c.relname, f.relname,
       ARRAY(SELECT a.attname
               FROM unnest(con.conkey) WITH ORDINALITY AS k(num, pos)
               JOIN pg_catalog.pg_attribute AS a
                 ON a.attrelid = con.conrelid AND a.attnum = k.num
              ORDER BY k.pos)::text[],
       ARRAY(SELECT a.attname
               FROM unnest(con.confkey) WITH ORDINALITY AS k(num, pos)
               JOIN pg_catalog.pg_attribute AS a
                 ON a.attrelid = con.confrelid AND a.attnum = k.num
              ORDER BY k.pos)::text[]
  FROM pg_catalog.pg_constraint AS con
  JOIN pg_catalog.pg_class AS c ON c.oid = con.conrelid
  JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
  JOIN pg_catalog.pg_class AS f ON f.oid = con.confrelid
 WHERE con.contype = 'f' AND n.nspname = %s
 ORDER BY c.relname, con.conname
"""

_UNIQUE_KEYS = """
SELECT i.relname, c.relname, x.indisprimary, x.indnullsnotdistinct,
       ARRAY(SELECT pg_catalog.pg_get_indexdef(x.indexrelid, k, true)
               FROM generate_series(1, x.indnkeyatts) AS k
              ORDER BY k),
       pg_catalog.pg_get_expr(x.indpred, x.indrelid, true)
  FROM pg_catalog.pg_index AS x
  JOIN pg_catalog.pg_class AS i ON i.oid = x.indexrelid
  JOIN pg_catalog.pg_class AS c ON c.oid = x.indrelid
  JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
 WHERE x.indisunique AND n.nspname = %s
 ORDER BY c.relname, i.relname
"""


async def load(
    conn: psycopg.AsyncConnection[typing.Any], schema: str = SCHEMA
) -> dict[str, Table]:
    """Return every table of *schema*, by name."""
    columns: dict[str, list[str]] = {}
    not_null: dict[str, list[str]] = {}
    json_columns: dict[str, set[str]] = {}
    cursor = await conn.execute(_COLUMNS, (schema,))
    for table, column, is_not_null, base_type in await cursor.fetchall():
        columns.setdefault(table, []).append(column)
        not_null.setdefault(table, [])
        json_columns.setdefault(table, set())
        if is_not_null:
            not_null[table].append(column)
        if base_type in ('json', 'jsonb'):
            json_columns[table].add(column)

    foreign_keys: dict[str, list[ForeignKey]] = {}
    cursor = await conn.execute(_FOREIGN_KEYS, (schema,))
    for name, table, ref_table, cols, ref_cols in await cursor.fetchall():
        foreign_keys.setdefault(table, []).append(
            ForeignKey(name, tuple(cols), ref_table, tuple(ref_cols))
        )

    unique_keys: dict[str, list[UniqueKey]] = {}
    cursor = await conn.execute(_UNIQUE_KEYS, (schema,))
    rows = await cursor.fetchall()
    for name, table, primary, nulls_not_distinct, keys, predicate in rows:
        unique_keys.setdefault(table, []).append(
            UniqueKey(
                name, tuple(keys), predicate, nulls_not_distinct, primary
            )
        )

    return {
        name: Table(
            name=name,
            columns=tuple(cols),
            not_null=tuple(not_null[name]),
            json_columns=frozenset(json_columns[name]),
            foreign_keys=tuple(foreign_keys.get(name, ())),
            unique_keys=tuple(unique_keys.get(name, ())),
        )
        for name, cols in columns.items()
    }


def load_order(
    tables: dict[str, Table], names: collections.abc.Iterable[str]
) -> list[str]:
    """Return *names* in foreign key order: referenced tables first.

    A self-reference does not count; the runner orders the rows of that
    table. A reference to a table outside *names* does not count either:
    that table must already hold the referenced rows. Ties are broken by
    name, so the order is the same on each run.

    """
    selected = set(names)
    sorter: graphlib.TopologicalSorter[str] = graphlib.TopologicalSorter()
    for name in sorted(selected):
        sorter.add(
            name,
            *sorted(
                {
                    fk.ref_table
                    for fk in tables[name].foreign_keys
                    if fk.ref_table in selected and fk.ref_table != name
                }
            ),
        )
    order: list[str] = []
    try:
        sorter.prepare()
    except graphlib.CycleError as error:
        raise mapping.EtlError(
            f'Foreign key cycle between tables: {error.args[1]}'
        ) from error
    while sorter.is_active():
        ready = sorted(sorter.get_ready())
        order.extend(ready)
        sorter.done(*ready)
    return order
