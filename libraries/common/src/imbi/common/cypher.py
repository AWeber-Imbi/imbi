"""Generate Cypher queries from Pydantic models.

Each public function returns one or more ``Statement`` named tuples
containing a Cypher template with ``{param}`` placeholders and a
dict of parameter values.  The execution layer (``graph.py``) is
responsible for binding the parameters via ``psycopg.sql``.
"""

import typing

import pydantic

from imbi_common import models

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


def _edge_fields(
    model_cls: type[pydantic.BaseModel],
) -> list[tuple[str, pydantic.fields.FieldInfo, models.Edge]]:
    """Return ``(name, field_info, edge)`` for every relationship field."""
    result: list[tuple[str, pydantic.fields.FieldInfo, models.Edge]] = []
    for name, info in model_cls.model_fields.items():
        edge = _get_edge(info)
        if edge is not None:
            result.append((name, info, edge))
    return result


def _is_list_edge(
    field_info: pydantic.fields.FieldInfo,
) -> bool:
    """Return ``True`` when the field annotation is ``list[T]``."""
    annotation = field_info.annotation
    origin = typing.get_origin(annotation)
    if origin is list:
        return True
    if origin is typing.Annotated:
        args = typing.get_args(annotation)
        if args:
            return typing.get_origin(args[0]) is list
    return False


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
    node: models.Node,
) -> list[tuple[str, models.Edge, models.Node]]:
    """Yield ``(tgt_label, edge, target)`` for every edge target."""
    result: list[tuple[str, models.Edge, models.Node]] = []
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


def _edge_statements(
    node: models.Node,
    verb: str = 'CREATE',
) -> list[Statement]:
    """Generate edge statements for every relationship on *node*.

    *verb* controls whether ``CREATE`` or ``MERGE`` is used for the
    relationship itself (``MATCH`` is always used for the endpoints).

    """
    statements: list[Statement] = []
    src_label = _label(node)
    for tgt_label, edge, target in _edge_targets(node):
        if edge.direction == 'OUTGOING':
            arrow = f'(a)-[r:{edge.rel_type}]->(b)'
        else:
            arrow = f'(a)<-[r:{edge.rel_type}]-(b)'
        cypher = (
            f'MATCH (a:{src_label} {{{{slug: {{src_slug}}}}}}), '
            f'(b:{tgt_label} {{{{slug: {{tgt_slug}}}}}}) '
            f'{verb} {arrow} RETURN r'
        )
        statements.append(
            Statement(
                cypher=cypher,
                params={
                    'src_slug': node.slug,
                    'tgt_slug': target.slug,
                },
            )
        )
    return statements


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def create(node: models.Node) -> list[Statement]:
    """Generate ``CREATE`` statements for *node* and its edges.

    Returns a list where the first entry creates the node and
    subsequent entries create each relationship.

    """
    props = _node_properties(node)
    cypher = f'CREATE (n:{_label(node)} {_props_template(props)}) RETURN n'
    statements = [Statement(cypher=cypher, params=props)]
    statements.extend(_edge_statements(node))
    return statements


def delete(node: models.Node) -> Statement:
    """Generate a ``DETACH DELETE`` statement for *node*."""
    return Statement(
        cypher=(
            f'MATCH (n:{_label(node)} {{{{slug: {{slug}}}}}}) '
            f'DETACH DELETE n RETURN n'
        ),
        params={'slug': node.slug},
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
    node: pydantic.BaseModel,
    match_on: list[str] | None = None,
) -> list[Statement]:
    """Generate ``MERGE`` statements for *node* and its edges.

    *match_on* lists the property names used to identify the node
    for the ``MERGE`` clause (defaults to ``['slug']``).  All other
    non-None scalar properties appear in the ``SET`` clause
    (Apache AGE does not support ``ON CREATE SET`` / ``ON MATCH SET``).

    Properties whose value is ``None`` are omitted so that existing
    graph values are preserved rather than being deleted.

    """
    match_on = match_on or ['slug']
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
    if set_props:
        # Exclude created_at from SET — it is set when the
        # node is first created and should not be overwritten
        # on subsequent merges.  Apache AGE does not support
        # ON CREATE SET / ON MATCH SET, so we simply omit it.
        update_keys = [k for k in set_props if k != 'created_at']
        if update_keys:
            assignments = ', '.join(f'n.{k} = {{{k}}}' for k in update_keys)
            cypher += f' SET {assignments}'
    cypher += ' RETURN n'

    statements = [Statement(cypher=cypher, params=props)]
    if isinstance(node, models.Node):
        statements.extend(_edge_statements(node, verb='MERGE'))
    return statements
