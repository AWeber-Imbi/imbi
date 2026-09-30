"""Rules from the schema: NOT NULL, types, domains, CHECK, UNIQUE, FK.

The graph enforces none of these. Each table that has a source query
(``sources.py``) gets one rule for each schema rule that its source
columns can show:

- ``type``: a value that does not convert to the column type.
- ``not_null``: no value for a NOT NULL column.
- ``json_text``: a JSONB value that the graph keeps as JSON text
  (Appendix E, E30). The ETL decodes it.
- ``domain``: a value that the column domain rejects.
- ``check``, ``unique``, ``fk``: the table constraints.

A schema rule that needs a column that the source query does not give
is listed in ``not_covered``, with the reason.
"""

# The queries are constants of this module. They take no input: the
# graph name goes in with sql.Identifier (rules.expand).
# ruff: noqa: S608

import collections.abc
import dataclasses
import re
import typing

from imbi.common.db.etl.audit import rules, schema, tables

#: ``#>> '{}'`` in the placeholder dialect: the scalar as text.
_TEXT = " #>> '{{}}'"

_LITERAL = re.compile(r"'(?:[^']|'')*'")
_WORD = re.compile(r'\b[a-z_][a-z0-9_]*\b')
_VALUE = re.compile(r'\bVALUE\b')
_NUMERIC_TYPES = ('INTEGER', 'BIGINT', 'SMALLINT', 'NUMERIC')

#: The Appendix E rules that a schema rule is part of, found by shape.
_E3_KEY = ('organization_id', 'slug')


@dataclasses.dataclass(frozen=True)
class Source:
    """The rows that the ETL would insert into one table.

    ``query`` returns ``_src`` (text: the graph id of the source row) and
    one ``jsonb`` column for each table column that has a graph source,
    with the raw graph value.

    """

    table: str
    query: str
    acts_on: str = ''
    notes: str = ''


class NotCovered(typing.NamedTuple):
    table: str
    rule: str
    reason: str


def _escape(expression: str) -> str:
    """Double the braces of a schema expression for the placeholders."""
    return expression.replace('{', '{{').replace('}', '}}')


def _quote(name: str) -> str:
    return f'"{name}"'


def references(
    expression: str, columns: collections.abc.Iterable[str]
) -> set[str]:
    """Return the names of *columns* that *expression* uses."""
    words = set(_WORD.findall(_LITERAL.sub("''", expression)))
    return words & set(columns)


def _base_type(column: schema.Column) -> str:
    domain = tables.DOMAINS.get(column.data_type)
    return (domain.data_type if domain else column.data_type).upper()


def _is_null(raw: str) -> str:
    return f"({raw} IS NULL OR jsonb_typeof({raw}) = 'null')"


def _json_text(raw: str) -> str:
    """True when *raw* is a string that holds a JSON object or array."""
    return (
        f"(jsonb_typeof({raw}) = 'string'"
        f" AND pg_input_is_valid({raw}{_TEXT}, 'jsonb')"
        f" AND jsonb_typeof(({raw}{_TEXT})::jsonb) IN ('object', 'array'))"
    )


def _decoded(raw: str) -> str:
    return (
        f'(CASE WHEN {_json_text(raw)} THEN ({raw}{_TEXT})::jsonb'
        f" WHEN jsonb_typeof({raw}) = 'null' THEN NULL ELSE {raw} END)"
    )


def conversion(column: schema.Column) -> tuple[str, str]:
    """Return ``(typed, valid)`` SQL for the raw ``jsonb`` of *column*.

    ``typed`` is the value in the column type, or NULL when there is no
    value or it does not convert. ``valid`` is false only for a value
    that does not convert.

    """
    raw = _quote(column.name)
    base = _base_type(column)
    text = f'({raw}{_TEXT})'
    if base == 'TEXT':
        scalar = f"jsonb_typeof({raw}) IN ('string', 'number', 'boolean')"
        return f'(CASE WHEN {scalar} THEN {text} END)', (
            f'({_is_null(raw)} OR {scalar})'
        )
    if (
        base == 'BOOLEAN'
        or base.startswith(_NUMERIC_TYPES)
        or (base.startswith('TIMESTAMP'))
    ):
        kinds = (
            "('string')"
            if base.startswith('TIMESTAMP')
            else "('string', 'number', 'boolean')"
        )
        valid = (
            f'(jsonb_typeof({raw}) IN {kinds}'
            f" AND pg_input_is_valid({text}, '{column.data_type}'))"
        )
        return (
            f'(CASE WHEN {valid} THEN {text}::{column.data_type} END)',
            f'({_is_null(raw)} OR {valid})',
        )
    if base == 'JSONB':
        return _decoded(raw), 'true'
    if base == 'TEXT[]':
        array = _decoded(raw)
        valid = (
            f"(jsonb_typeof({array}) = 'array' AND NOT EXISTS ("
            f'SELECT 1 FROM jsonb_array_elements({array}) AS element'
            " WHERE jsonb_typeof(element) <> 'string'))"
        )
        return (
            f'(CASE WHEN {valid} THEN ARRAY('
            f'SELECT jsonb_array_elements_text({array})) END)',
            f'({_is_null(raw)} OR {valid})',
        )
    return 'NULL', 'true'


def _ctes(table: schema.Table, source: Source, columns: list[str]) -> str:
    typed = ', '.join(
        [
            '_src',
            *(
                part
                for name in columns
                for part in _typed_columns(table, name)
            ),
        ]
    )
    return (
        f'src_{table.name} AS ({source.query}),'
        f' typed_{table.name} AS (SELECT {typed} FROM src_{table.name})'
    )


def _typed_columns(table: schema.Table, name: str) -> list[str]:
    column = table.column(name)
    if column is None:
        return []
    typed, valid = conversion(column)
    raw = _quote(name)
    return [
        f'{typed} AS {raw}',
        f'{valid} AS {_quote(name + "__valid")}',
        f'{_is_null(raw)} AS {_quote(name + "__null")}',
        f'{_json_text(raw)} AS {_quote(name + "__json_text")}',
    ]


def _rule(
    table: schema.Table,
    source: Source,
    rule: str,
    title: str,
    fate: rules.Fate,
    ctes: str,
    where: str,
    covered_by: str | None = None,
) -> rules.Rule:
    return rules.Rule(
        id=f'schema:{table.name}.{rule}',
        title=title,
        fate=fate,
        query=(
            f'WITH {ctes} SELECT _src AS id FROM typed_{table.name}'
            f' WHERE {where}'
        ),
        acts_on=source.acts_on,
        table=table.name,
        covered_by=covered_by,
    )


def build(
    source: Source,
    columns: collections.abc.Sequence[str],
    sources: collections.abc.Mapping[
        str, tuple[Source, collections.abc.Sequence[str]]
    ],
) -> tuple[list[rules.Rule], list[NotCovered]]:
    """Return the schema rules of ``source.table``, and the gaps.

    *columns* are the columns that the source query returns (without
    ``_src``). *sources* gives the source and its columns for each other
    table, for the foreign keys.

    """
    table = tables.TABLES[source.table]
    known = [name for name in columns if table.column(name) is not None]
    ctes = _ctes(table, source, known)
    found: list[rules.Rule] = []
    gaps: list[NotCovered] = [
        NotCovered(table.name, f'{name}', 'not a column of the table')
        for name in columns
        if table.column(name) is None
    ]
    for column in table.columns:
        name = column.name
        if name not in known:
            if not column.nullable and not column.has_default:
                gaps.append(
                    NotCovered(
                        table.name,
                        f'{name}.not_null',
                        'the source query has no value for it',
                    )
                )
            continue
        raw = _quote(name)
        found.append(
            _rule(
                table,
                source,
                f'{name}.type',
                f'{table.name}.{name}: values that are not {column.data_type}',
                'blocking',
                ctes,
                f'NOT {_quote(name + "__valid")}',
            )
        )
        if not column.nullable:
            found.append(
                _rule(
                    table,
                    source,
                    f'{name}.not_null',
                    f'{table.name}.{name} is NOT NULL: rows with no value'
                    + (', the default applies' if column.has_default else ''),
                    'changed' if column.has_default else 'blocking',
                    ctes,
                    _quote(name + '__null'),
                )
            )
        if _base_type(column) in ('JSONB', 'TEXT[]'):
            found.append(
                _rule(
                    table,
                    source,
                    f'{name}.json_text',
                    f'{table.name}.{name}: JSON text that the ETL decodes',
                    'changed',
                    ctes,
                    _quote(name + '__json_text'),
                    covered_by='E30',
                )
            )
        domain = tables.DOMAINS.get(column.data_type)
        if domain is None:
            continue
        for check in domain.checks:
            found.append(
                _rule(
                    table,
                    source,
                    f'{name}.domain',
                    f'{table.name}.{name}: values that the domain'
                    f' {domain.name} rejects',
                    'blocking',
                    ctes,
                    f'{raw} IS NOT NULL AND NOT'
                    f' {_VALUE.sub(raw, _escape(check.expression))}',
                    covered_by=(
                        'E4' if column.data_type == 'public.slug' else None
                    ),
                )
            )
    names = [column.name for column in table.columns]
    for check in table.checks:
        missing = references(check.expression, names) - set(known)
        if missing:
            gaps.append(_gap(table, f'check.{check.name}', missing))
            continue
        found.append(
            _rule(
                table,
                source,
                f'check.{check.name}',
                f'{table.name}: rows that the check {check.name} rejects',
                'blocking',
                ctes,
                f'NOT COALESCE({_escape(check.expression)}, true)',
                covered_by='E4' if check.name == 'slug_valid' else None,
            )
        )
    for unique in table.uniques:
        used = set().union(
            *(references(part, names) for part in unique.columns),
            references(unique.where or '', names),
        )
        missing = used - set(known)
        if missing:
            gaps.append(_gap(table, f'unique.{unique.name}', missing))
            continue
        found.append(_unique(table, source, unique, ctes))
    for key in table.foreign_keys:
        found_key, gap = _foreign_key(table, source, key, known, sources)
        if found_key:
            found.append(found_key)
        if gap:
            gaps.append(gap)
    return found, gaps


def _gap(table: schema.Table, rule: str, missing: set[str]) -> NotCovered:
    return NotCovered(
        table.name,
        rule,
        'the source query has no value for ' + ', '.join(sorted(missing)),
    )


def _unique(
    table: schema.Table,
    source: Source,
    unique: schema.Unique,
    ctes: str,
) -> rules.Rule:
    key = ', '.join(_escape(part) for part in unique.columns)
    conditions = [f'({_escape(unique.where)})'] if unique.where else []
    if not unique.nulls_not_distinct:
        conditions.extend(
            f'({_escape(part)}) IS NOT NULL' for part in unique.columns
        )
    where = ' AND '.join(conditions) or 'true'
    return rules.Rule(
        id=f'schema:{table.name}.unique.{unique.name}',
        title=f'{table.name}: rows that share a {unique.name} key ({key})',
        fate='blocking',
        query=(
            f'WITH {ctes} SELECT _src AS id FROM (SELECT _src, count(*)'
            f' OVER (PARTITION BY {key}) AS copies FROM typed_{table.name}'
            f' WHERE {where}) AS keyed WHERE copies > 1'
        ),
        acts_on=source.acts_on,
        table=table.name,
        covered_by='E3' if unique.columns == _E3_KEY else None,
    )


def _foreign_key(
    table: schema.Table,
    source: Source,
    key: schema.ForeignKey,
    known: list[str],
    sources: collections.abc.Mapping[
        str, tuple[Source, collections.abc.Sequence[str]]
    ],
) -> tuple[rules.Rule | None, NotCovered | None]:
    rule = f'fk.{key.name}'
    missing = set(key.columns) - set(known)
    if missing:
        return None, _gap(table, rule, missing)
    if key.references not in sources:
        return None, NotCovered(
            table.name, rule, f'{key.references} has no source query'
        )
    target, target_columns = sources[key.references]
    target_table = tables.TABLES[key.references]
    target_missing = set(key.ref_columns) - set(target_columns)
    if target_missing:
        return None, NotCovered(
            table.name,
            rule,
            f'the {key.references} source query has no value for '
            + ', '.join(sorted(target_missing)),
        )
    ctes = _ctes(table, source, known)
    if target_table.name != table.name:
        ctes += ', ' + _ctes(
            target_table,
            target,
            [
                name
                for name in target_columns
                if target_table.column(name) is not None
            ],
        )
    present = ' AND '.join(f'child.{name} IS NOT NULL' for name in key.columns)
    match = ' AND '.join(
        f'parent.{ref} = child.{name}'
        for name, ref in zip(key.columns, key.ref_columns, strict=True)
    )
    return (
        rules.Rule(
            id=f'schema:{table.name}.{rule}',
            title=(
                f'{table.name}: rows whose {", ".join(key.columns)} names'
                f' no {key.references} row'
            ),
            fate='blocking',
            query=(
                f'WITH {ctes} SELECT child._src AS id FROM'
                f' typed_{table.name} AS child WHERE {present} AND NOT'
                f' EXISTS (SELECT 1 FROM typed_{key.references} AS parent'
                f' WHERE {match})'
            ),
            acts_on=source.acts_on,
            table=table.name,
        ),
        None,
    )
