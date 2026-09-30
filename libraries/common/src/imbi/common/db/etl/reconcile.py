"""Compare the loaded tables with the graph (plan WP1.6, D14).

For each mapped table:

- the target count against the expected count of the mapping;
- the primary key values of the target against the keys of the rows
  that ``rows()`` yields: the missing and the extra keys;
- each NOT NULL column and unique key that ``schemata/`` declares is in
  the target catalog (then PostgreSQL enforces it: ``schema-enforced``);
- the orphans of each foreign key;
- the skips of ``rows()`` by reason against the expected skips, and
  no skipped id in the target;
- for a join table, the row count of each key against the expected
  cardinality;
- for each JSON column, the rows whose value is not an object or an
  array (Appendix E, E30).

Each difference is a mismatch. The report is JSON; ``clean`` is false
when any table has a mismatch. It runs as ``imbi_maintenance``.
"""

import collections.abc
import dataclasses
import datetime
import pathlib
import typing

import psycopg
from psycopg import sql

from imbi.common.db.etl import catalog, mapping, mappings, runner, schemata

#: The table files, relative to the working directory (the repository
#: root, or the directory of the cutover bundle).
SCHEMA_FILES = pathlib.Path('schemata/tables/public')

#: The most keys that the report lists for each difference.
KEY_LIMIT = 100


@dataclasses.dataclass(slots=True)
class TableReport:
    table: str
    source_labels: list[str]
    source_edges: list[str]
    expected_count: int
    target_count: int
    missing_keys: list[str]
    extra_keys: list[str]
    checksum: str
    not_null: dict[str, str]
    unique_keys: dict[str, str]
    orphans: dict[str, int]
    json_not_container: dict[str, int]
    expected_skipped: dict[str, list[str]]
    skipped: dict[str, list[str]]
    skipped_loaded: list[str]
    changed: dict[str, int]
    cardinality: dict[str, int] | None
    mismatches: list[str]

    @property
    def clean(self) -> bool:
        return not self.mismatches


@dataclasses.dataclass(slots=True)
class Report:
    tables: dict[str, TableReport]
    pending: list[str]

    @property
    def clean(self) -> bool:
        return all(table.clean for table in self.tables.values())

    def as_dict(self) -> dict[str, object]:
        return {
            'clean': self.clean,
            'pending': self.pending,
            'tables': {
                name: {'clean': table.clean, **dataclasses.asdict(table)}
                for name, table in self.tables.items()
            },
        }


async def table_checksum(
    conn: psycopg.AsyncConnection[typing.Any], table: str
) -> str:
    """Return an MD5 over the text of every row, in a fixed order.

    The text of a timestamp depends on the ``TimeZone`` setting; compare
    only checksums made with the same setting. ``reconcile()`` uses UTC.

    """
    cursor = await conn.execute(
        sql.SQL(
            'SELECT md5(COALESCE(string_agg(h, {sep} ORDER BY h), {empty}))'
            ' FROM (SELECT md5(t::text) AS h FROM {table} AS t) AS rows'
        ).format(
            sep=sql.Literal(''),
            empty=sql.Literal(''),
            table=sql.Identifier(catalog.SCHEMA, table),
        )
    )
    row = await cursor.fetchone()
    return str(row[0]) if row else ''


async def reconcile(
    source: psycopg.AsyncConnection[typing.Any],
    target: psycopg.AsyncConnection[typing.Any],
    *,
    graph: str = 'imbi',
    tenant_slug: str = 'default',
    tenant_name: str = 'Default',
    missing_timestamp: datetime.datetime | None = None,
    registry: collections.abc.Mapping[str, mapping.Mapping] | None = None,
    pending: collections.abc.Sequence[str] | None = None,
    only: collections.abc.Collection[str] | None = None,
    schema_files: pathlib.Path = SCHEMA_FILES,
) -> Report:
    """Check each mapped table, or only the tables in *only*.

    *schema_files* is ``schemata/tables/public``, the YAML of each table.

    """
    registry = mappings.discover() if registry is None else registry
    pending = tuple(mappings.pending() if pending is None else pending)
    names = sorted(registry if only is None else only)
    unknown = [name for name in names if name not in registry]
    if unknown:
        raise mapping.EtlError('Tables with no mapping: ' + ', '.join(unknown))
    runner.require_idle(target, 'target')
    await runner.begin_snapshot(source)
    context = mapping.Context(
        source=source,
        graph=graph,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
        missing_timestamp=missing_timestamp,
    )
    report = Report(tables={}, pending=list(pending))
    async with target.transaction(), source.transaction():
        await target.execute(
            'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'
        )
        await target.execute("SET LOCAL TimeZone TO 'UTC'")
        tables = await catalog.load(target)
        absent = [name for name in names if name not in tables]
        if absent:
            raise mapping.EtlError(
                'Tables not in the target: ' + ', '.join(absent)
            )
        for name in names:
            report.tables[name] = await _table(
                target,
                tables[name],
                schemata.load(schema_files, name),
                registry[name],
                context,
            )
    return report


async def _table(
    target: psycopg.AsyncConnection[typing.Any],
    table: catalog.Table,
    declared: schemata.Declared,
    item: mapping.Mapping,
    context: mapping.Context,
) -> TableReport:
    expected = await item.expected(context)
    collected = await runner.collect(item, context)
    summary = runner.summarize(table.name, collected)
    ident = sql.Identifier(catalog.SCHEMA, table.name)
    key = table.primary_key
    mismatches: list[str] = []

    target_count = await _scalar(
        target, sql.SQL('SELECT count(*) FROM {}').format(ident)
    )
    if target_count != expected.count:
        mismatches.append(
            f'count: target {target_count}, expected {expected.count}'
        )
    missing_keys, extra_keys = await _keys(
        target, ident, key, item, collected.rows, mismatches
    )
    not_null, unique_keys = declared_states(declared, table)
    orphans = {
        fk.name: await _scalar(target, _orphans_query(ident, fk))
        for fk in table.foreign_keys
    }
    json_not_container = {
        column: await _scalar(
            target,
            sql.SQL(
                'SELECT count(*) FROM {} WHERE {col} IS NOT NULL'
                ' AND jsonb_typeof({col}::jsonb)'
                ' NOT IN ({object}, {array})'
            ).format(
                ident,
                col=sql.Identifier(column),
                object=sql.Literal('object'),
                array=sql.Literal('array'),
            ),
        )
        for column in sorted(table.json_columns)
    }
    expected_skipped = {
        reason: sorted(ids) for reason, ids in expected.skipped.items() if ids
    }
    skipped = {reason: sorted(ids) for reason, ids in summary.skipped.items()}
    skipped_ids = sorted({i for ids in skipped.values() for i in ids})
    skipped_loaded: list[str] = []
    if len(key) == 1 and skipped_ids:
        cursor = await target.execute(
            sql.SQL('SELECT {key} FROM {} WHERE {key} = ANY(%s)').format(
                ident, key=sql.Identifier(key[0])
            ),
            (skipped_ids,),
        )
        skipped_loaded = sorted(str(row[0]) for row in await cursor.fetchall())

    mismatches.extend(
        f'NOT NULL column {c} {state}'
        for c, state in not_null.items()
        if state != schemata.ENFORCED
    )
    mismatches.extend(
        f'{k} {state}'
        for k, state in unique_keys.items()
        if state != schemata.ENFORCED
    )
    mismatches.extend(f'orphans of {k}: {n}' for k, n in orphans.items() if n)
    mismatches.extend(
        f'JSON column {c} not an object or array: {n}'
        for c, n in json_not_container.items()
        if n
    )
    if skipped != expected_skipped:
        mismatches.append('skipped rows differ from the expected skips')
    if skipped_loaded:
        mismatches.append(f'skipped ids in the target: {len(skipped_loaded)}')
    cardinality = await _cardinality(
        target, table, ident, expected, mismatches
    )

    return TableReport(
        table=table.name,
        source_labels=list(item.source_labels),
        source_edges=list(item.source_edges),
        expected_count=expected.count,
        target_count=target_count,
        missing_keys=missing_keys,
        extra_keys=extra_keys,
        checksum=await table_checksum(target, table.name),
        not_null=not_null,
        unique_keys=unique_keys,
        orphans=orphans,
        json_not_container=json_not_container,
        expected_skipped=expected_skipped,
        skipped=skipped,
        skipped_loaded=skipped_loaded,
        changed=summary.changed,
        cardinality=cardinality,
        mismatches=mismatches,
    )


def declared_states(
    declared: schemata.Declared, table: catalog.Table
) -> tuple[dict[str, str], dict[str, str]]:
    """Return the state of each declared NOT NULL column and unique key.

    The state is ``schema-enforced`` when the target catalog has it, and
    ``missing from the target`` when it does not. A unique key matches
    on its keys (column names or expressions) and on whether it is
    partial; the names can differ, because ``deploy`` names some keys.

    """
    not_null = {
        column: (
            schemata.ENFORCED if column in table.not_null else schemata.MISSING
        )
        for column in declared.not_null
    }
    found = {
        (tuple(schemata.normalize(k) for k in u.keys), bool(u.predicate))
        for u in table.unique_keys
    }
    unique_keys = {
        u.label: (
            schemata.ENFORCED
            if (tuple(schemata.normalize(k) for k in u.keys), u.partial)
            in found
            else schemata.MISSING
        )
        for u in declared.unique_keys
    }
    return not_null, unique_keys


async def _keys(
    target: psycopg.AsyncConnection[typing.Any],
    ident: sql.Identifier,
    key: tuple[str, ...],
    item: mapping.Mapping,
    rows: list[mapping.Row],
    mismatches: list[str],
) -> tuple[list[str], list[str]]:
    """Compare the primary keys of the target with the keys of *rows*.

    Return the keys that ``rows()`` yields and the target does not have
    (missing), and the keys that the target has and ``rows()`` does not
    yield (extra), each sorted and cut to ``KEY_LIMIT``.

    """
    if not key or not set(key) <= set(item.columns):
        mismatches.append(
            'primary key not in the mapping columns: cannot compare keys'
        )
        return [], []
    yielded = {'/'.join(str(row[c]) for c in key) for row in rows}
    cursor = await target.execute(
        sql.SQL('SELECT {} FROM {}').format(
            sql.SQL(', ').join(
                sql.SQL('{}::text').format(sql.Identifier(c)) for c in key
            ),
            ident,
        )
    )
    loaded = {
        '/'.join(str(value) for value in row)
        for row in await cursor.fetchall()
    }
    missing = sorted(yielded - loaded)
    extra = sorted(loaded - yielded)
    if missing:
        mismatches.append(f'keys missing from the target: {len(missing)}')
    if extra:
        mismatches.append(
            f'keys in the target that rows() does not give: {len(extra)}'
        )
    return missing[:KEY_LIMIT], extra[:KEY_LIMIT]


async def _cardinality(
    target: psycopg.AsyncConnection[typing.Any],
    table: catalog.Table,
    ident: sql.Identifier,
    expected: mapping.Expected,
    mismatches: list[str],
) -> dict[str, int] | None:
    """Compare the rows per key of a join table. Return the differences."""
    if expected.cardinality is None:
        if table.is_join_table:
            mismatches.append('join table with no expected cardinality')
        return None
    columns = expected.cardinality.columns
    cursor = await target.execute(
        sql.SQL('SELECT {cols}, count(*) FROM {} GROUP BY {cols}').format(
            ident,
            cols=sql.SQL(', ').join(sql.Identifier(c) for c in columns),
        )
    )
    actual = {
        tuple(str(value) for value in row[:-1]): int(row[-1])
        for row in await cursor.fetchall()
    }
    wanted = {
        tuple(str(value) for value in k): n
        for k, n in expected.cardinality.counts.items()
        if n
    }
    differences = {
        '/'.join(k): actual.get(k, 0) - wanted.get(k, 0)
        for k in sorted(set(actual) | set(wanted))
        if actual.get(k, 0) != wanted.get(k, 0)
    }
    if differences:
        mismatches.append(
            f'cardinality of ({", ".join(columns)}) differs for'
            f' {len(differences)} keys'
        )
    return differences


def _orphans_query(
    ident: sql.Identifier, fk: catalog.ForeignKey
) -> sql.Composed:
    not_null = sql.SQL(' AND ').join(
        sql.SQL('c.{} IS NOT NULL').format(sql.Identifier(c))
        for c in fk.columns
    )
    matches = sql.SQL(' AND ').join(
        sql.SQL('p.{} = c.{}').format(sql.Identifier(r), sql.Identifier(c))
        for c, r in zip(fk.columns, fk.ref_columns, strict=True)
    )
    return sql.SQL(
        'SELECT count(*) FROM {} AS c WHERE {} AND NOT EXISTS'
        ' (SELECT 1 FROM {} AS p WHERE {})'
    ).format(
        ident,
        not_null,
        sql.Identifier(catalog.SCHEMA, fk.ref_table),
        matches,
    )


async def _scalar(
    conn: psycopg.AsyncConnection[typing.Any], query: sql.Composed
) -> int:
    cursor = await conn.execute(query)
    row = await cursor.fetchone()
    return int(row[0]) if row else 0
