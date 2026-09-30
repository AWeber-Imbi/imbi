"""Run the audit rules in one read-only transaction.

All rules read one snapshot (REPEATABLE READ), so the counts agree with
each other. A rule that fails with a database error is reported with
the error, and the audit then exits 1: an unknown count cannot show
that a blocking rule is clean.
"""

import collections.abc
import dataclasses
import datetime
import typing

import psycopg
from psycopg import sql

from imbi.common.db.etl.audit import checks, rules
from imbi.common.db.etl.audit import tables as schema_tables

ID_LIMIT = 100


@dataclasses.dataclass
class Result:
    rule: rules.Rule
    count: int | None = None
    ids: list[str] = dataclasses.field(default_factory=list)
    error: str | None = None
    note: str | None = None

    @property
    def failed(self) -> bool:
        """True when the rule blocks the ETL or has no count."""
        if self.error is not None:
            return True
        return self.rule.fate == 'blocking' and bool(self.count)

    def as_dict(self) -> dict[str, typing.Any]:
        return {
            'id': self.rule.id,
            'title': self.rule.title,
            'fate': self.rule.fate,
            'acts_on': self.rule.acts_on,
            'decision': self.rule.decision,
            'table': self.rule.table,
            'covered_by': self.rule.covered_by,
            'count': self.count,
            'ids': self.ids,
            'error': self.error,
            'note': self.note,
        }


@dataclasses.dataclass
class Report:
    graph: str
    started_at: datetime.datetime
    results: list[Result] = dataclasses.field(default_factory=list)
    not_covered: list[checks.NotCovered] = dataclasses.field(
        default_factory=list
    )

    @property
    def failed(self) -> bool:
        return any(result.failed for result in self.results)

    def as_dict(self) -> dict[str, typing.Any]:
        blocking = [
            result
            for result in self.results
            if result.rule.fate == 'blocking' and result.count
        ]
        return {
            'graph': self.graph,
            'started_at': self.started_at.isoformat(),
            'exit_code': 1 if self.failed else 0,
            'blocking_rules_with_rows': len(blocking),
            'errors': sum(1 for r in self.results if r.error is not None),
            'rules': [result.as_dict() for result in self.results],
            'not_covered': [gap._asdict() for gap in self.not_covered],
        }


Connection = psycopg.AsyncConnection[typing.Any]


async def graph_tables(conn: Connection, graph: str) -> set[str]:
    """Return the names of the label and edge tables of *graph*."""
    cursor = await conn.execute(
        'SELECT c.relname FROM pg_catalog.pg_class AS c'
        ' JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace'
        " WHERE n.nspname = %s AND c.relkind IN ('r', 'p')",
        (graph,),
    )
    return {name for (name,) in await cursor.fetchall()}


async def _relation_exists(conn: Connection, name: str) -> bool:
    cursor = await conn.execute('SELECT to_regclass(%s) IS NOT NULL', (name,))
    row = await cursor.fetchone()
    return bool(row and row[0])


async def source_columns(
    conn: Connection, graph: str, tables: set[str], source: checks.Source
) -> list[str]:
    """Return the output columns of a source query, without ``_src``."""
    query = sql.SQL('SELECT * FROM ({}) AS probe LIMIT 0').format(
        rules.expand(source.query, graph, tables)
    )
    async with conn.transaction():
        cursor = await conn.execute(query)
    return [
        column.name
        for column in cursor.description or ()
        if column.name != '_src'
    ]


async def _count(
    conn: Connection,
    graph: str,
    tables: set[str],
    rule: rules.Rule,
    id_limit: int,
) -> Result:
    for name in rule.requires:
        if not await _relation_exists(conn, name):
            return Result(rule, 0, note=f'{name} does not exist')
    query = sql.SQL(
        'SELECT count(*), (array_agg(DISTINCT rule_rows.id::text)'
        ' FILTER (WHERE rule_rows.id IS NOT NULL))[1:{}]'
        ' FROM ({}) AS rule_rows'
    ).format(sql.Literal(id_limit), rules.expand(rule.query, graph, tables))
    try:
        async with conn.transaction():
            cursor = await conn.execute(query)
            row = await cursor.fetchone()
    except psycopg.Error as error:
        return Result(rule, error=str(error).strip())
    count, ids = row if row else (0, None)
    return Result(rule, int(count), sorted(ids or []))


def _apply_covered(
    found: list[rules.Rule],
    appendix_rules: collections.abc.Sequence[rules.Rule],
    covered: collections.abc.Mapping[str, str],
) -> list[rules.Rule]:
    """Give each covered schema rule the fate of its Appendix E rule."""
    fates = {rule.id: rule.fate for rule in appendix_rules}
    return [
        dataclasses.replace(
            rule, covered_by=covered[rule.id], fate=fates[covered[rule.id]]
        )
        if rule.id in covered
        else rule
        for rule in found
    ]


async def run(
    conn: Connection,
    appendix_rules: collections.abc.Sequence[rules.Rule],
    sources: collections.abc.Sequence[checks.Source],
    *,
    graph: str = 'imbi',
    only: collections.abc.Collection[str] | None = None,
    id_limit: int = ID_LIMIT,
    not_covered: collections.abc.Mapping[str, str] | None = None,
    covered: collections.abc.Mapping[str, str] | None = None,
) -> Report:
    """Run every rule on *conn* and return the report.

    *conn* must not be in a transaction. The audit sets it read only.
    *only* limits the run to the rules whose id starts with one of its
    entries (``E5``, ``schema:users``).

    """
    report = Report(graph, datetime.datetime.now(datetime.UTC))
    await conn.set_autocommit(False)
    await conn.set_read_only(True)
    await conn.set_isolation_level(psycopg.IsolationLevel.REPEATABLE_READ)
    async with conn.transaction():
        tables = await graph_tables(conn, graph)
        found = list(appendix_rules)
        probed: dict[str, tuple[checks.Source, list[str]]] = {}
        for source in sources:
            try:
                columns = await source_columns(conn, graph, tables, source)
            except psycopg.Error as error:
                report.results.append(
                    Result(
                        rules.Rule(
                            id=f'schema:{source.table}.source',
                            title=f'{source.table}: the source query runs',
                            fate='blocking',
                            query=source.query,
                            table=source.table,
                        ),
                        error=str(error).strip(),
                    )
                )
                continue
            probed[source.table] = (source, columns)
        for source, columns in probed.values():
            table_rules, gaps = checks.build(source, columns, probed)
            found.extend(table_rules)
            report.not_covered.extend(gaps)
        report.not_covered.extend(
            checks.NotCovered(
                name,
                '*',
                (not_covered or {}).get(name, 'no source query'),
            )
            for name in schema_tables.TABLES
            if name not in probed
        )
        found = _apply_covered(found, appendix_rules, covered or {})
        for rule in found:
            if only and not any(rule.id.startswith(o) for o in only):
                continue
            report.results.append(
                await _count(conn, graph, tables, rule, id_limit)
            )
    return report
