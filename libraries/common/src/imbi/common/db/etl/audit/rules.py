"""Audit rules and the SQL dialect that they use.

A rule is one read-only SELECT over the AGE graph tables that returns one
text column, ``id``, for each row that breaks the rule: the graph ``id``
property of the node, or ``<start id>/<end id>`` for an edge.

The SELECT names graph tables with placeholders, so that it does not
depend on the graph schema name and still runs when a label has no
table yet (AGE creates a label table at the first write):

- ``{Project}``, a label, is
  ``(SELECT gid, p FROM <graph>."Project")``: ``gid`` is the graph id as
  ``bigint`` and ``p`` is the property map as ``jsonb``. A vertex with
  no ``id`` property gets ``gid:<graph id>`` in ``p`` (E36).
- ``{OWNED_BY}``, an edge type (upper case), is
  ``(SELECT gid, s, t, p FROM <graph>."OWNED_BY")``: ``s`` and ``t`` are
  the graph ids of the start and the end vertex.

A label or edge type with no table is an empty relation. Braces in SQL
literals are doubled (``'{{}}'``).
"""

import collections.abc
import dataclasses
import string
import typing

from psycopg import sql

Fate = typing.Literal['blocking', 'skipped', 'changed']

#: A vertex with no ``id`` property gets ``gid:<graph id>`` as its id,
#: in place of the id that the ETL derives from the graph id (E36). So
#: the rows that refer to it still join, and E36 counts it.
DERIVED_ID_PREFIX = 'gid:'


@dataclasses.dataclass(frozen=True)
class Rule:
    """One audit query and the fate of the rows that it finds.

    ``fate`` comes from plan Appendix E. ``blocking`` stops the ETL
    until the count is zero or a decision covers it; ``skipped`` rows are
    not loaded; ``changed`` rows are loaded with a change.

    """

    id: str
    title: str
    fate: Fate
    query: str
    acts_on: str = ''
    decision: str | None = None
    table: str | None = None
    covered_by: str | None = None
    requires: tuple[str, ...] = ()


def placeholders(template: str) -> set[str]:
    """Return the label and edge type names that *template* uses."""
    return {
        name
        for _text, name, _spec, _conversion in string.Formatter().parse(
            template
        )
        if name
    }


def is_edge_type(name: str) -> bool:
    return name.isupper()


def _relation(graph: str, name: str, exists: bool) -> sql.Composable:
    if is_edge_type(name):
        if not exists:
            return sql.SQL(
                '(SELECT NULL::bigint AS gid, NULL::bigint AS s,'
                ' NULL::bigint AS t, NULL::jsonb AS p WHERE false)'
            )
        return sql.SQL(
            '(SELECT id::text::bigint AS gid,'
            ' start_id::text::bigint AS s, end_id::text::bigint AS t,'
            ' properties::text::jsonb AS p FROM {})'
        ).format(sql.Identifier(graph, name))
    if not exists:
        return sql.SQL(
            '(SELECT NULL::bigint AS gid, NULL::jsonb AS p WHERE false)'
        )
    return sql.SQL(
        "(SELECT gid, CASE WHEN nullif(p->'id', 'null') IS NULL"
        " THEN p || jsonb_build_object('id', {} || gid::text) ELSE p END"
        ' AS p FROM (SELECT id::text::bigint AS gid,'
        ' properties::text::jsonb AS p FROM {}) AS raw)'
    ).format(sql.Literal(DERIVED_ID_PREFIX), sql.Identifier(graph, name))


def expand(
    template: str, graph: str, tables: collections.abc.Container[str]
) -> sql.Composed:
    """Replace the placeholders of *template* with graph relations.

    *tables* holds the names of the label and edge tables that exist in
    the graph schema.

    """
    return sql.SQL(template).format(
        **{
            name: _relation(graph, name, name in tables)
            for name in placeholders(template)
        }
    )
