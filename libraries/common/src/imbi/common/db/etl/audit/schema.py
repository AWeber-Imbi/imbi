"""The rules of the relational schema that the audit checks.

``tables.py`` holds one ``Table`` for each file in
``schemata/tables/public/`` and one ``Domain`` for each file in
``schemata/domains/public/``. A test compares it with ``schemata/``;
when the schema changes, regenerate it with
``python libraries/common/tests/test_etl_audit_schema.py --write``.
"""

import typing


class Column(typing.NamedTuple):
    name: str
    data_type: str
    nullable: bool
    has_default: bool


class Unique(typing.NamedTuple):
    """A primary key, a unique constraint, or a unique index.

    Each entry of ``columns`` is a column name or an index expression.
    """

    name: str
    columns: tuple[str, ...]
    where: str | None = None
    nulls_not_distinct: bool = False


class ForeignKey(typing.NamedTuple):
    name: str
    columns: tuple[str, ...]
    references: str
    ref_columns: tuple[str, ...]


class Check(typing.NamedTuple):
    name: str
    expression: str


class Table(typing.NamedTuple):
    name: str
    columns: tuple[Column, ...]
    checks: tuple[Check, ...] = ()
    uniques: tuple[Unique, ...] = ()
    foreign_keys: tuple[ForeignKey, ...] = ()

    def column(self, name: str) -> Column | None:
        for column in self.columns:
            if column.name == name:
                return column
        return None


class Domain(typing.NamedTuple):
    """A domain. Each check uses ``VALUE`` for the checked value."""

    name: str
    data_type: str
    checks: tuple[Check, ...]
