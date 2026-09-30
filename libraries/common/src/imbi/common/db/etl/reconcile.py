"""Compare the loaded tables with the graph (plan WP1.6, D14).

For each mapped table:

- the target count against the expected count of the mapping;
- the distinct primary key values against the count;
- the NULL count of each NOT NULL column;
- the duplicates of each unique key;
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
import typing

import psycopg
from psycopg import sql

from imbi.common.db.etl import catalog, mapping, mappings, runner


@dataclasses.dataclass(slots=True)
class TableReport:
    table: str
    source_labels: list[str]
    source_edges: list[str]
    expected_count: int
    target_count: int
    distinct_keys: int
    checksum: str
    null_counts: dict[str, int]
    duplicates: dict[str, int]
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
    registry: collections.abc.Mapping[str, mapping.Mapping] | None = None,
    pending: collections.abc.Sequence[str] | None = None,
    only: collections.abc.Collection[str] | None = None,
) -> Report:
    """Check each mapped table, or only the tables in *only*."""
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
                target, tables[name], registry[name], context
            )
    return report


async def _table(
    target: psycopg.AsyncConnection[typing.Any],
    table: catalog.Table,
    item: mapping.Mapping,
    context: mapping.Context,
) -> TableReport:
    expected = await item.expected(context)
    collected = await runner.collect(item, context)
    summary = runner.summarize(table.name, collected)
    ident = sql.Identifier(catalog.SCHEMA, table.name)
    key = table.primary_key

    target_count = await _scalar(
        target, sql.SQL('SELECT count(*) FROM {}').format(ident)
    )
    distinct_keys = target_count
    if key:
        distinct_keys = await _scalar(
            target,
            sql.SQL('SELECT count(DISTINCT ({})) FROM {}').format(
                sql.SQL(', ').join(sql.Identifier(c) for c in key), ident
            ),
        )
    null_counts = {
        column: await _scalar(
            target,
            sql.SQL('SELECT count(*) FROM {} WHERE {} IS NULL').format(
                ident, sql.Identifier(column)
            ),
        )
        for column in table.not_null
    }
    duplicates = {
        unique.name: await _scalar(target, _duplicates_query(ident, unique))
        for unique in table.unique_keys
    }
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

    mismatches: list[str] = []
    if target_count != expected.count:
        mismatches.append(
            f'count: target {target_count}, expected {expected.count}'
        )
    if distinct_keys != target_count:
        mismatches.append(
            f'distinct keys: {distinct_keys} for {target_count} rows'
        )
    mismatches.extend(
        f'NULL in NOT NULL column {c}: {n}'
        for c, n in null_counts.items()
        if n
    )
    mismatches.extend(
        f'duplicates of {k}: {n}' for k, n in duplicates.items() if n
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
        distinct_keys=distinct_keys,
        checksum=await table_checksum(target, table.name),
        null_counts=null_counts,
        duplicates=duplicates,
        orphans=orphans,
        json_not_container=json_not_container,
        expected_skipped=expected_skipped,
        skipped=skipped,
        skipped_loaded=skipped_loaded,
        changed=summary.changed,
        cardinality=cardinality,
        mismatches=mismatches,
    )


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


def _duplicates_query(
    ident: sql.Identifier, unique: catalog.UniqueKey
) -> sql.Composed:
    keys = [sql.SQL(k) for k in unique.keys]
    conditions: list[sql.Composable] = []
    if unique.predicate:
        conditions.append(sql.SQL('({})').format(sql.SQL(unique.predicate)))
    if not unique.nulls_not_distinct:
        conditions.extend(sql.SQL('({}) IS NOT NULL').format(k) for k in keys)
    where = (
        sql.SQL(' WHERE ') + sql.SQL(' AND ').join(conditions)
        if conditions
        else sql.SQL('')
    )
    return sql.SQL(
        'SELECT count(*) FROM (SELECT 1 FROM {}{} GROUP BY {}'
        ' HAVING count(*) > 1) AS d'
    ).format(ident, where, sql.SQL(', ').join(keys))


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
