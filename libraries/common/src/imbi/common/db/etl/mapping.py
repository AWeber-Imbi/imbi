"""The contract between the ETL runner and one target table.

Each table in ``schemata/tables/public/`` has one mapping module in
:mod:`imbi.common.db.etl.mappings`. The module name is the table name,
and the module has a ``MAPPING`` attribute that satisfies
:class:`Mapping`. The runner finds the modules itself, so a new mapping
does not change a shared file.

``rows()`` reads the graph and yields one :data:`Row` for each target
row, a :class:`Skip` for each source row that an Appendix E rule does
not load, and a :class:`Change` for each row that an Appendix E rule
loads with a change. ``expected()`` is a second, independent query over
the graph: the reconciliation compares its count and its skips with the
target table and with the skips of ``rows()``.
"""

import collections.abc
import dataclasses
import typing

import psycopg

#: One target row: the column name and the value to insert. JSON and
#: JSONB columns take a ``dict`` or a ``list``; the runner adapts them.
Row = dict[str, object]


class EtlError(Exception):
    """The ETL cannot continue. The message says why."""


@dataclasses.dataclass(frozen=True, slots=True)
class Skip:
    """A source row that the ETL does not load.

    ``reason`` is a short, stable name of the rule, for example
    ``'no-organization'``. ``source_id`` is the graph ``id`` property.

    """

    reason: str
    source_id: str


@dataclasses.dataclass(frozen=True, slots=True)
class Change:
    """A source row that the ETL loads with a change.

    ``rule`` is the Appendix E number, for example ``'E35'``. ``detail``
    says what changed. It must not contain personal data, because the
    runner logs it and the reconciliation report contains it.

    """

    rule: str
    source_id: str
    detail: str


@dataclasses.dataclass(frozen=True, slots=True)
class Cardinality:
    """The expected number of rows for each value of ``columns``.

    A join table declares it, for example the number of tags of each
    document. The reconciliation compares it with a ``GROUP BY`` of the
    target table.

    """

    columns: tuple[str, ...]
    counts: collections.abc.Mapping[tuple[str, ...], int]


@dataclasses.dataclass(frozen=True, slots=True)
class Expected:
    """The result of the expected source query of one table."""

    #: The number of rows that must arrive in the target table.
    count: int
    #: The graph ids that the Appendix E rules skip, by reason.
    skipped: collections.abc.Mapping[str, frozenset[str]] = dataclasses.field(
        default_factory=dict[str, frozenset[str]]
    )
    #: Required for a join table (a table whose primary key is made
    #: only of foreign key columns); ``None`` for the other tables.
    cardinality: Cardinality | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class Context:
    """What a mapping can read. The runner and the reconciliation make it.

    ``source`` is in a read-only transaction, so every mapping reads the
    same snapshot of the graph.

    """

    source: psycopg.AsyncConnection[typing.Any]
    #: The AGE graph name, which is also the schema of its label tables.
    graph: str = 'imbi'
    #: The one tenant that the ETL creates (Appendix E, E2).
    tenant_slug: str = 'default'
    tenant_name: str = 'Default'


Event = Row | Skip | Change


@typing.runtime_checkable
class Mapping(typing.Protocol):
    """The mapping of one target table."""

    @property
    def table(self) -> str:  # pragma: no cover
        """The table in the ``public`` schema. It is also the module name."""
        ...

    @property
    def columns(self) -> tuple[str, ...]:  # pragma: no cover
        """The columns that each row sets, in the order of the COPY."""
        ...

    @property
    def source_labels(self) -> tuple[str, ...]:  # pragma: no cover
        """The graph labels that the mapping reads, for the report."""
        ...

    @property
    def source_edges(self) -> tuple[str, ...]:  # pragma: no cover
        """The graph edge types that the mapping reads, for the report."""
        ...

    def rows(
        self, context: Context
    ) -> collections.abc.AsyncIterator[Event]:  # pragma: no cover
        """Yield the rows, skips, and changes of this table."""
        ...

    async def expected(self, context: Context) -> Expected:  # pragma: no cover
        """Return the expected count and skips from the graph."""
        ...
