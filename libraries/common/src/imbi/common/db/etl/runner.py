"""Load the relational tables from the graph (plan WP1.5, D20).

One transaction on the target: one ``TRUNCATE`` that names every mapped
and pending table, with no ``CASCADE``, then a ``COPY`` of each mapped
table in foreign key order. No upsert, no delta. An ``INSERT`` does not
fire the ``updated_at`` triggers, so the graph timestamps stay, and a
``TRUNCATE`` does not fire the delete triggers.

The target connection is ``imbi_maintenance`` (BYPASSRLS). The source
connection reads the graph in one read-only snapshot.
"""

import collections.abc
import dataclasses
import datetime
import json
import logging
import typing

import psycopg
from psycopg import sql
from psycopg.types import json as psycopg_json

from imbi.common.db.etl import catalog, mapping, mappings

LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(slots=True)
class TableResult:
    table: str
    rows: int = 0
    skipped: dict[str, list[str]] = dataclasses.field(
        default_factory=dict[str, list[str]]
    )
    changed: dict[str, int] = dataclasses.field(default_factory=dict[str, int])


@dataclasses.dataclass(slots=True)
class RunResult:
    #: The load order, pending tables included.
    order: list[str]
    tables: dict[str, TableResult]
    pending: tuple[str, ...]
    dry_run: bool


@dataclasses.dataclass(slots=True)
class Collected:
    """The events of one mapping, split by kind."""

    rows: list[mapping.Row]
    skips: list[mapping.Skip]
    changes: list[mapping.Change]


def require_idle(conn: psycopg.AsyncConnection[typing.Any], name: str) -> None:
    """Raise unless *conn* is outside a transaction.

    The ETL starts its own transactions. In an open transaction, psycopg
    would make them savepoints, and the load would not commit.

    """
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise mapping.EtlError(f'The {name} connection is in a transaction')


async def begin_snapshot(source: psycopg.AsyncConnection[typing.Any]) -> None:
    """Make the next transaction on *source* one read-only snapshot."""
    require_idle(source, 'source')
    await source.set_autocommit(False)
    await source.set_isolation_level(psycopg.IsolationLevel.REPEATABLE_READ)
    await source.set_read_only(True)


async def collect(
    item: mapping.Mapping, context: mapping.Context
) -> Collected:
    """Run ``item.rows()`` and check each row against ``item.columns``."""
    result = Collected([], [], [])
    expected = set(item.columns)
    async for event in item.rows(context):
        if isinstance(event, mapping.Skip):
            result.skips.append(event)
        elif isinstance(event, mapping.Change):
            result.changes.append(event)
        else:
            if set(event) != expected:
                raise mapping.EtlError(
                    f'{item.table}: row {event.get("id")!r} has the columns'
                    f' {sorted(event)}, not {sorted(expected)}'
                )
            result.rows.append(event)
    return result


async def run(
    source: psycopg.AsyncConnection[typing.Any],
    target: psycopg.AsyncConnection[typing.Any],
    *,
    graph: str = 'imbi',
    tenant_slug: str = 'default',
    tenant_name: str = 'Default',
    missing_timestamp: datetime.datetime | None = None,
    registry: collections.abc.Mapping[str, mapping.Mapping] | None = None,
    pending: collections.abc.Sequence[str] | None = None,
    allow_pending: bool = False,
    dry_run: typing.TextIO | None = None,
) -> RunResult:
    """Truncate and load the mapped tables. Return what was loaded.

    *registry* and *pending* default to the mapping modules and
    ``mappings/_pending.py``. With *dry_run*, the rows, skips, and
    changes go to that stream as JSON lines, and the target is only
    read. The target must have no public table outside the mapped and
    pending tables, so that no table keeps data from an earlier run.

    """
    registry = mappings.discover() if registry is None else registry
    pending = tuple(mappings.pending() if pending is None else pending)
    if pending and not allow_pending:
        raise mapping.EtlError(
            f'{len(pending)} tables have no mapping yet: {", ".join(pending)}'
        )
    require_idle(target, 'target')
    await begin_snapshot(source)
    context = mapping.Context(
        source=source,
        graph=graph,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
        missing_timestamp=missing_timestamp,
    )
    async with target.transaction(), source.transaction():
        if dry_run is not None:
            await target.execute('SET TRANSACTION READ ONLY')
        tables = await catalog.load(target)
        _check_coverage(tables, set(registry), set(pending))
        order = catalog.load_order(tables, [*registry, *pending])
        result = RunResult(
            order=order,
            tables={},
            pending=pending,
            dry_run=dry_run is not None,
        )
        if dry_run is not None:
            for name in order:
                if name in registry:
                    collected = await collect(registry[name], context)
                    result.tables[name] = summarize(name, collected)
                    _write_lines(dry_run, name, collected)
            return result
        await target.execute(
            sql.SQL('TRUNCATE {}').format(
                sql.SQL(', ').join(
                    sql.Identifier(catalog.SCHEMA, name) for name in order
                )
            )
        )
        for name in order:
            if name not in registry:
                continue
            collected = await collect(registry[name], context)
            rows = _parents_first(tables[name], collected.rows)
            await _copy(target, tables[name], registry[name], rows)
            result.tables[name] = summarize(name, collected)
            LOGGER.info(
                '%s: %d rows, %d skipped, %d changed',
                name,
                len(collected.rows),
                len(collected.skips),
                len(collected.changes),
            )
            for change in collected.changes:
                LOGGER.info(
                    '%s: %s %s: %s',
                    name,
                    change.rule,
                    change.source_id,
                    change.detail,
                )
    return result


def _check_coverage(
    tables: collections.abc.Mapping[str, catalog.Table],
    mapped: set[str],
    pending: set[str],
) -> None:
    both = mapped & pending
    if both:
        raise mapping.EtlError(
            f'Tables both mapped and pending: {", ".join(sorted(both))}'
        )
    absent = (mapped | pending) - set(tables)
    if absent:
        raise mapping.EtlError(
            'Tables not in the target: ' + ', '.join(sorted(absent))
        )
    uncovered = set(tables) - mapped - pending
    if uncovered:
        raise mapping.EtlError(
            'Target tables with no mapping: ' + ', '.join(sorted(uncovered))
        )


def summarize(name: str, collected: Collected) -> TableResult:
    result = TableResult(name, rows=len(collected.rows))
    for skip in collected.skips:
        result.skipped.setdefault(skip.reason, []).append(skip.source_id)
    for change in collected.changes:
        result.changed[change.rule] = result.changed.get(change.rule, 0) + 1
    return result


def _parents_first(
    table: catalog.Table, rows: list[mapping.Row]
) -> list[mapping.Row]:
    """Order the rows of a self-referencing table, parents first.

    The only self-reference in the schema is ``roles.parent_role_id``. A
    row whose parent is not in *rows* has no dependency here; its
    foreign key then fails at the insert.

    """
    references = table.self_references
    if not references:
        return rows
    keys = {
        (fk.ref_columns, tuple(row.get(c) for c in fk.ref_columns)): index
        for index, row in enumerate(rows)
        for fk in references
    }
    parents: dict[int, set[int]] = {index: set() for index in range(len(rows))}
    for index, row in enumerate(rows):
        for fk in references:
            values = tuple(row.get(c) for c in fk.columns)
            if any(value is None for value in values):
                continue
            parent = keys.get((fk.ref_columns, values))
            if parent is not None and parent != index:
                parents[index].add(parent)
    ordered: list[mapping.Row] = []
    done: set[int] = set()
    while len(done) < len(rows):
        ready = [
            index
            for index in range(len(rows))
            if index not in done and parents[index] <= done
        ]
        if not ready:
            raise mapping.EtlError(f'{table.name}: the rows refer in a cycle')
        for index in ready:
            ordered.append(rows[index])
            done.add(index)
    return ordered


async def _copy(
    target: psycopg.AsyncConnection[typing.Any],
    table: catalog.Table,
    item: mapping.Mapping,
    rows: list[mapping.Row],
) -> None:
    unknown = set(item.columns) - set(table.columns)
    if unknown:
        raise mapping.EtlError(
            f'{table.name}: no such columns: {", ".join(sorted(unknown))}'
        )
    statement = sql.SQL('COPY {} ({}) FROM STDIN').format(
        sql.Identifier(catalog.SCHEMA, table.name),
        sql.SQL(', ').join(sql.Identifier(c) for c in item.columns),
    )
    async with target.cursor() as cursor, cursor.copy(statement) as copy:
        for row in rows:
            await copy.write_row(
                [_adapt(row[c], c in table.json_columns) for c in item.columns]
            )


def _adapt(value: object, is_json: bool) -> object:
    if is_json and value is not None:
        return psycopg_json.Jsonb(value)
    return value


def _write_lines(
    stream: typing.TextIO, table: str, collected: Collected
) -> None:
    for row in collected.rows:
        _write(stream, {'kind': 'row', 'table': table, 'row': row})
    for skip in collected.skips:
        _write(
            stream,
            {
                'kind': 'skip',
                'table': table,
                'reason': skip.reason,
                'source_id': skip.source_id,
            },
        )
    for change in collected.changes:
        _write(
            stream,
            {
                'kind': 'change',
                'table': table,
                'rule': change.rule,
                'source_id': change.source_id,
                'detail': change.detail,
            },
        )


def _write(stream: typing.TextIO, line: dict[str, object]) -> None:
    stream.write(json.dumps(line, default=_json_default, sort_keys=True))
    stream.write('\n')


def _json_default(value: object) -> object:
    if isinstance(value, datetime.datetime | datetime.date):
        return value.isoformat()
    raise TypeError(f'Cannot write {type(value).__name__} as JSON')
