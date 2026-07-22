"""Generate Cypher queries from Pydantic models.

Each public function returns one or more ``Statement`` named tuples
containing a Cypher template with ``{param}`` placeholders and a
dict of parameter values.  The execution layer (``graph.py``) is
responsible for binding the parameters via ``psycopg.sql``.
"""

import functools
import typing

import pydantic

from imbi.common import models

__all__ = [
    'Statement',
    'create',
    'delete',
    'match',
    'merge',
]


class Statement(typing.NamedTuple):
    """A Cypher query template paired with its parameter values."""

    cypher: str
    params: dict[str, typing.Any]


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _get_edge(
    field_info: pydantic.fields.FieldInfo,
) -> models.Edge | None:
    """Extract ``Edge`` metadata from a Pydantic field, if present."""
    for metadata in field_info.metadata:
        if isinstance(metadata, models.Edge):
            return metadata
    return None


@functools.cache
def _edge_fields(
    model_cls: type[pydantic.BaseModel],
) -> tuple[tuple[str, pydantic.fields.FieldInfo, models.Edge], ...]:
    """Return ``(name, field_info, edge)`` for every relationship field.

    Cached per model class; ``model_fields`` is populated at class
    creation time and never mutates, so the descriptor tuple is
    safe to reuse across calls.

    """
    result: list[tuple[str, pydantic.fields.FieldInfo, models.Edge]] = []
    for name, info in model_cls.model_fields.items():
        edge = _get_edge(info)
        if edge is not None:
            result.append((name, info, edge))
    return tuple(result)


def _is_list_edge(
    field_info: pydantic.fields.FieldInfo,
) -> bool:
    """Return ``True`` when the field annotation is ``list[T]``."""
    return typing.get_origin(field_info.annotation) is list


def _label(
    node_or_type: pydantic.BaseModel | type[pydantic.BaseModel],
) -> str:
    """Return the Cypher node label (the class name)."""
    if isinstance(node_or_type, type):
        return node_or_type.__name__
    return type(node_or_type).__name__


def _node_properties(node: pydantic.BaseModel) -> dict[str, typing.Any]:
    """Return the scalar (non-edge) properties of a node instance.

    Uses ``model_dump(mode='json')`` so that complex types
    (datetime, HttpUrl, etc.) are serialised to JSON-safe values.

    """
    edge_names = {name for name, _, _ in _edge_fields(type(node))}
    data = node.model_dump(mode='json')
    return {k: v for k, v in data.items() if k not in edge_names}


def _props_template(props: dict[str, typing.Any]) -> str:
    """Format *props* as a Cypher property map with placeholders.

    Cypher literal braces are doubled so they survive
    ``sql.SQL.format()``::

        >>> _props_template({'name': 'x', 'slug': 'x'})
        '{{name: {name}, slug: {slug}}}'

    After ``sql.SQL.format()`` the ``{{`` / ``}}`` become ``{`` / ``}``.
    """
    if not props:
        return ''
    pairs = [f'{k}: {{{k}}}' for k in props]
    return '{{' + ', '.join(pairs) + '}}'


def _edge_targets(
    node: models.GraphModel,
) -> list[tuple[str, models.Edge, models.GraphModel]]:
    """Yield ``(tgt_label, edge, target)`` for every edge target."""
    result: list[tuple[str, models.Edge, models.GraphModel]] = []
    for field_name, field_info, edge in _edge_fields(type(node)):
        targets = getattr(node, field_name)
        if _is_list_edge(field_info):
            if not targets:
                continue
        elif targets is None:
            continue
        else:
            targets = [targets]
        for target in targets:
            result.append((_label(target), edge, target))
    return result


def _identity(
    node: models.GraphModel,
) -> tuple[str, str]:
    """Return ``(key_name, key_value)`` for a graph vertex.

    ``Node`` subclasses use ``slug`` (the stable business key);
    plain ``GraphModel`` subclasses use ``id``.

    """
    if isinstance(node, models.Node):
        return ('slug', node.slug)
    return ('id', node.id)


def _edge_statements(
    node: models.GraphModel,
    verb: str = 'CREATE',
) -> list[Statement]:
    """Generate edge statements for every relationship on *node*.

    *verb* controls whether ``CREATE`` or ``MERGE`` is used for the
    relationship itself (``MATCH`` is always used for the endpoints).

    Each endpoint is matched by its canonical identity key — ``slug``
    for ``Node`` subclasses, ``id`` for plain ``GraphModel``.

    """
    statements: list[Statement] = []
    src_label = _label(node)
    src_key, src_val = _identity(node)
    for tgt_label, edge, target in _edge_targets(node):
        tgt_key, tgt_val = _identity(target)
        if edge.direction == 'OUTGOING':
            arrow = f'(a)-[r:{edge.rel_type}]->(b)'
        else:
            arrow = f'(a)<-[r:{edge.rel_type}]-(b)'
        cypher = (
            f'MATCH (a:{src_label} {{{{{src_key}: {{src}}}}}}), '
            f'(b:{tgt_label} {{{{{tgt_key}: {{tgt}}}}}})'
            f' {verb} {arrow} RETURN r'
        )
        statements.append(
            Statement(
                cypher=cypher,
                params={
                    'src': src_val,
                    'tgt': tgt_val,
                },
            )
        )
    return statements


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def create(node: models.GraphModel) -> list[Statement]:
    """Generate ``CREATE`` statements for *node* and its edges.

    Returns a list where the first entry creates the node and
    subsequent entries create each relationship.

    """
    props = _node_properties(node)
    cypher = f'CREATE (n:{_label(node)} {_props_template(props)}) RETURN n'
    statements = [Statement(cypher=cypher, params=props)]
    statements.extend(_edge_statements(node))
    return statements


def delete(node: models.GraphModel) -> Statement:
    """Generate a ``DETACH DELETE`` statement for *node*."""
    key, val = _identity(node)
    return Statement(
        cypher=(
            f'MATCH (n:{_label(node)} {{{{{key}: {{key}}}}}}) '
            f'DETACH DELETE n RETURN n'
        ),
        params={'key': val},
    )


def match(
    node_type: type[pydantic.BaseModel],
    params: dict[str, typing.Any] | None = None,
    order_by: str | None = None,
) -> Statement:
    """Generate a ``MATCH`` statement for *node_type*.

    When *params* is provided the matched nodes are filtered by
    those properties; otherwise all nodes of the label are returned.

    *order_by*, when given, appends ``ORDER BY n.<field>``.

    """
    params = dict(params) if params else {}
    label = _label(node_type)
    edge_names = {n for n, _, _ in _edge_fields(node_type)}
    scalar = set(node_type.model_fields) - edge_names
    if params:
        bad = [k for k in params if k not in scalar]
        if bad:
            raise ValueError(f'Unknown field(s) for {label}: {", ".join(bad)}')
        cypher = f'MATCH (n:{label} {_props_template(params)}) RETURN n'
    else:
        cypher = f'MATCH (n:{label}) RETURN n'
    if order_by:
        if order_by not in scalar:
            raise ValueError(f'Unknown order_by field for {label}: {order_by}')
        cypher += f' ORDER BY n.{order_by}'
    return Statement(cypher=cypher, params=params)


def merge(
    node: models.GraphModel,
    match_on: list[str] | None = None,
) -> list[Statement]:
    """Generate ``MERGE`` statements for *node* and its edges.

    *match_on* lists the property names used to identify the node
    for the ``MERGE`` clause.  Defaults to ``['slug']`` for
    ``Node`` subclasses (stable business key) and ``['id']`` for
    plain ``GraphModel`` subclasses.  All other non-None scalar
    properties appear in the ``SET`` clause.

    ``id`` and ``created_at`` use ``COALESCE`` so they are written
    on first creation but preserved on subsequent merges (Apache
    AGE does not support ``ON CREATE SET`` / ``ON MATCH SET``).

    Properties whose value is ``None`` are omitted so that existing
    graph values are preserved rather than being deleted.

    """
    if match_on is None:
        match_on = [_identity(node)[0]]
    if not match_on:
        raise ValueError('match_on must contain at least one key')
    props = _node_properties(node)

    bad = [k for k in match_on if k not in props]
    if bad:
        raise ValueError(
            f'Unknown merge key(s) for {_label(node)}: {", ".join(bad)}'
        )
    match_props = {k: props[k] for k in match_on}
    set_props = {
        k: v for k, v in props.items() if k not in match_on and v is not None
    }

    cypher = f'MERGE (n:{_label(node)} {_props_template(match_props)})'

    # Build SET assignments.  ``id`` and ``created_at`` use
    # COALESCE so the first MERGE persists them but subsequent
    # merges preserve the original values (Apache AGE lacks
    # ``ON CREATE SET`` / ``ON MATCH SET``).
    once_only = {'id', 'created_at'}
    assignments: list[str] = []
    for k in set_props:
        if k in once_only:
            assignments.append(
                f'n.{k} = coalesce(n.{k}, {{{k}}})',
            )
        else:
            assignments.append(f'n.{k} = {{{k}}}')
    if assignments:
        cypher += ' SET ' + ', '.join(assignments)
    cypher += ' RETURN n'

    statements = [Statement(cypher=cypher, params=props)]
    statements.extend(_edge_statements(node, verb='MERGE'))
    return statements
