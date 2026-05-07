"""Generic plugin-edge helpers.

Anchor routers pass their own ``MATCH`` fragment so the helpers stay
generic across anchor types.
"""

import json
import logging
import typing

import fastapi
import pydantic
from imbi_common import graph
from imbi_common.plugins.base import PluginEdgeLabel
from imbi_common.plugins.registry import list_plugins

LOGGER = logging.getLogger(__name__)


class EdgePutBody(pydantic.BaseModel):
    """Request body for the PUT-edge endpoint.

    ``target_id`` is the node id of the target (the value stored in
    ``n.id``, not the AGE internal id).  ``properties`` is validated
    against the manifest's declared property schema; unknown keys are
    rejected.
    """

    target_label: str
    target_id: str
    properties: dict[str, typing.Any] = pydantic.Field(default_factory=dict)


class EdgeResponse(pydantic.BaseModel):
    """A single materialized edge."""

    rel_type: str
    target_label: str
    target: dict[str, typing.Any]
    properties: dict[str, typing.Any] = pydantic.Field(default_factory=dict)


_ALLOWED_PROP_TYPES: dict[str, type] = {
    'str': str,
    'int': int,
    'bool': bool,
}


def _coerce_property(
    name: str, expected: str, value: typing.Any
) -> typing.Any:
    """Coerce a value against a manifest-declared type string.

    The manifest's edge ``properties`` is ``dict[str, str]`` where
    each value is a Python-style type expression.  We support the
    common subset:

    * ``str``, ``int``, ``bool`` — scalar
    * ``list[str]`` — flat string list
    * ``dict[str, str]`` — flat string→string map

    Anything outside this set is logged and accepted as-is so plugins
    can experiment without breaking the host.
    """
    if expected in _ALLOWED_PROP_TYPES:
        cls = _ALLOWED_PROP_TYPES[expected]
        if not isinstance(value, cls):
            raise ValueError(
                f'Edge property {name!r} must be {expected}, got '
                f'{type(value).__name__}'
            )
        return value
    if expected == 'list[str]':
        if not isinstance(value, list) or not all(
            isinstance(v, str)
            for v in value  # pyright: ignore[reportUnknownVariableType]
        ):
            raise ValueError(f'Edge property {name!r} must be list[str]')
        return value  # pyright: ignore[reportUnknownVariableType]
    if expected == 'dict[str, str]':
        if not isinstance(value, dict) or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in value.items()  # pyright: ignore[reportUnknownVariableType,reportUnknownMemberType]
        ):
            raise ValueError(f'Edge property {name!r} must be dict[str, str]')
        return value  # pyright: ignore[reportUnknownVariableType]
    LOGGER.warning(
        'Unknown edge-property type %r for %r — accepting as-is',
        expected,
        name,
    )
    return value


def _validate_properties(
    edge: PluginEdgeLabel, props: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    """Validate user-supplied edge properties against the manifest."""
    declared = edge.properties or {}
    extra = set(props) - set(declared)
    if extra:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Edge {edge.name!r} does not declare properties: '
                f'{sorted(extra)}'
            ),
        )
    out: dict[str, typing.Any] = {}
    for name, expected in declared.items():
        if name in props:
            try:
                out[name] = _coerce_property(name, expected, props[name])
            except ValueError as exc:
                raise fastapi.HTTPException(
                    status_code=400, detail=str(exc)
                ) from exc
    return out


def resolve_edge_for(anchor_label: str, rel_type: str) -> PluginEdgeLabel:
    """Return the manifest's ``PluginEdgeLabel`` for the given anchor.

    Raises:
        404 if no enabled-or-installed plugin declares ``rel_type`` for
        an anchor whose label is in ``from_labels``.

    """
    for entry in list_plugins():
        for edge in entry.manifest.edge_labels:
            if edge.name == rel_type and anchor_label in edge.from_labels:
                return edge
    raise fastapi.HTTPException(
        status_code=404,
        detail=(f'No plugin declares edge {rel_type!r} from {anchor_label!r}'),
    )


def _parse_edge_props(raw: typing.Any) -> dict[str, typing.Any]:
    """Return a ``{}`` dict for an agtype edge value or its properties."""
    if raw is None:
        return {}
    parsed: typing.Any = graph.parse_agtype(raw)
    # Edges come back either as the full edge envelope (with a
    # ``properties`` sub-dict) or as a bare property dict — accept both.
    if isinstance(parsed, dict) and 'properties' in parsed:
        parsed = parsed['properties']  # pyright: ignore[reportUnknownVariableType]
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return {}
    if not isinstance(parsed, dict):
        return {}
    out: dict[str, typing.Any] = {**parsed}
    # AGE round-trips dict/list values as JSON strings.
    for key, value in list(out.items()):
        if isinstance(value, str) and value and value[0] in '{[':
            try:
                out[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return out


def _row_to_edge(
    row: dict[str, typing.Any],
    rel_type: str,
    edge: PluginEdgeLabel,
) -> EdgeResponse | None:
    if row.get('t') is None:
        return None
    target: typing.Any = graph.parse_agtype(row['t'])
    labels_raw: typing.Any = graph.parse_agtype(row['target_labels'])
    labels: list[str] = (
        [str(lbl) for lbl in labels_raw]  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
        if isinstance(labels_raw, list)
        else []
    )
    target_label = next(
        (lbl for lbl in labels if lbl in edge.to_labels),
        edge.to_labels[0],
    )
    target_dict: dict[str, typing.Any] = (
        {str(k): v for k, v in target.items()}  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType,reportUnknownMemberType]
        if isinstance(target, dict)
        else {}
    )
    return EdgeResponse(
        rel_type=rel_type,
        target_label=target_label,
        target=target_dict,
        properties=_parse_edge_props(row.get('r')),
    )


async def list_anchor_edges(
    *,
    db: graph.Graph,
    anchor_label: str,
    anchor_match: str,
    anchor_params: dict[str, typing.Any],
    rel_type: str,
) -> list[EdgeResponse]:
    """Return every edge of ``rel_type`` from a given anchor."""
    edge = resolve_edge_for(anchor_label, rel_type)

    target_label_expr = '|'.join(edge.to_labels)
    query = (
        f'{anchor_match} '
        f'OPTIONAL MATCH (a)-[r:{rel_type}]->(t:{target_label_expr}) '
        f'RETURN r, t, labels(t) AS target_labels'
    )
    rows = await db.execute(query, anchor_params, ['r', 't', 'target_labels'])
    out: list[EdgeResponse] = []
    for row in rows:
        parsed = _row_to_edge(row, rel_type, edge)
        if parsed is not None:
            out.append(parsed)
    return out


async def list_org_environment_edges(
    *,
    db: graph.Graph,
    rel_type: str,
    org_slug: str,
) -> dict[str, list[EdgeResponse]]:
    """Return ``{env_slug: [edges]}`` for every environment in ``org_slug``.

    Resolves the edge from the plugin manifest (anchor=``Environment``)
    and walks all environments under the organization in a single query,
    so a card mounting N environment rows costs one HTTP round-trip
    instead of N.

    Environments without an outgoing edge of ``rel_type`` are present in
    the result with an empty list — callers can render an empty row
    without an extra "exists?" check.
    """
    edge = resolve_edge_for('Environment', rel_type)
    target_label_expr = '|'.join(edge.to_labels)
    query = (
        'MATCH (a:Environment)-[:BELONGS_TO]->'
        '(:Organization {{slug: {org_slug}}}) '
        f'OPTIONAL MATCH (a)-[r:{rel_type}]->(t:{target_label_expr}) '
        'RETURN a.slug AS anchor_slug, r, t, labels(t) AS target_labels'
    )
    rows = await db.execute(
        query,
        {'org_slug': org_slug},
        ['anchor_slug', 'r', 't', 'target_labels'],
    )
    out: dict[str, list[EdgeResponse]] = {}
    for row in rows:
        anchor_raw = row.get('anchor_slug')
        if anchor_raw is None:
            continue
        anchor_slug = graph.parse_agtype(anchor_raw)
        if not isinstance(anchor_slug, str):
            continue
        bucket = out.setdefault(anchor_slug, [])
        parsed = _row_to_edge(row, rel_type, edge)
        if parsed is not None:
            bucket.append(parsed)
    return out


async def put_anchor_edge(
    *,
    db: graph.Graph,
    anchor_label: str,
    anchor_match: str,
    anchor_params: dict[str, typing.Any],
    rel_type: str,
    body: EdgePutBody,
) -> EdgeResponse:
    """Replace the single edge of ``rel_type`` from this anchor.

    For multi-edge relationships, a future ``?append=true`` mode will be
    added.  Today the semantics are: delete any existing edge with the
    same ``rel_type``, then create a fresh one.
    """
    edge = resolve_edge_for(anchor_label, rel_type)
    if body.target_label not in edge.to_labels:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Edge {rel_type!r} does not allow target label '
                f'{body.target_label!r} (allowed: {edge.to_labels})'
            ),
        )
    coerced_props = _validate_properties(edge, body.properties)

    check_query = (
        f'{anchor_match} '
        f'MATCH (t:{body.target_label} {{{{id: {{target_id}}}}}}) '
        f'RETURN a.id AS anchor_id, t.id AS target_id LIMIT 1'
    )
    check_rows = await db.execute(
        check_query,
        {**anchor_params, 'target_id': body.target_id},
        ['anchor_id', 'target_id'],
    )
    if not check_rows:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Anchor or target {body.target_id!r} ({body.target_label}) '
                f'not found'
            ),
        )

    if coerced_props:
        prop_pairs = ', '.join(
            f'{key}: {{prop_{key}}}' for key in coerced_props
        )
        prop_clause = '{{' + prop_pairs + '}}'
    else:
        prop_clause = ''

    upsert_query = (
        f'{anchor_match} '
        f'MATCH (t:{body.target_label} {{{{id: {{target_id}}}}}}) '
        f'OPTIONAL MATCH (a)-[old:{rel_type}]->() '
        f'DELETE old '
        f'WITH a, t '
        f'CREATE (a)-[r:{rel_type} {prop_clause}]->(t) '
        f'RETURN r'
    )
    params: dict[str, typing.Any] = {
        **anchor_params,
        'target_id': body.target_id,
    }
    for key, value in coerced_props.items():
        params[f'prop_{key}'] = value
    await db.execute(upsert_query, params, ['r'])

    return EdgeResponse(
        rel_type=rel_type,
        target_label=body.target_label,
        target={'id': body.target_id},
        properties=coerced_props,
    )


async def delete_anchor_edge(
    *,
    db: graph.Graph,
    anchor_label: str,
    anchor_match: str,
    anchor_params: dict[str, typing.Any],
    rel_type: str,
) -> None:
    """Remove every edge of ``rel_type`` from this anchor. Idempotent."""
    resolve_edge_for(anchor_label, rel_type)
    query = f'{anchor_match} OPTIONAL MATCH (a)-[r:{rel_type}]->() DELETE r'
    await db.execute(query, anchor_params, [])


__all__ = [
    'EdgePutBody',
    'EdgeResponse',
    'delete_anchor_edge',
    'list_anchor_edges',
    'list_org_environment_edges',
    'put_anchor_edge',
    'resolve_edge_for',
]
