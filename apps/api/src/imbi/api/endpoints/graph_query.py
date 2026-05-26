"""Admin graph query endpoints.

Exposes raw Cypher execution and schema introspection for the admin
"Graph Query" tool (inspired by Neo4j Desktop). Restricted to users
with ``is_admin=True``.
"""

import json
import logging
import re
import time
import typing

import fastapi
import psycopg
import pydantic
from imbi_common import graph
from psycopg import sql

from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

graph_query_router = fastapi.APIRouter(
    prefix='/admin/graph', tags=['Admin: Graph Query']
)


async def require_admin(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
) -> permissions.AuthContext:
    """Dependency: require an authenticated admin user."""
    if not auth.is_admin:
        LOGGER.warning(
            'Graph query denied: principal=%s is not admin',
            auth.principal_name,
        )
        raise fastapi.HTTPException(
            status_code=403,
            detail='Admin privileges required',
        )
    return auth


# ---------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------


class GraphQueryRequest(pydantic.BaseModel):
    """Request body for ``POST /admin/graph/query``."""

    query: str
    params: dict[str, typing.Any] = pydantic.Field(default_factory=dict)


class GraphQueryError(pydantic.BaseModel):
    """Structured error returned on a failed query."""

    message: str
    code: str | None = None
    line: int | None = None
    column: int | None = None
    hint: str | None = None


class GraphNode(pydantic.BaseModel):
    """A vertex extracted from query results."""

    id: str
    labels: list[str]
    properties: dict[str, typing.Any]


class GraphEdge(pydantic.BaseModel):
    """An edge extracted from query results."""

    id: str
    type: str
    start: str
    end: str
    properties: dict[str, typing.Any]


class GraphQueryResponse(pydantic.BaseModel):
    """Response body for a successful query."""

    columns: list[str]
    rows: list[dict[str, typing.Any]]
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    elapsed_ms: float


class LabelCount(pydantic.BaseModel):
    """A node label with its instance count."""

    label: str
    count: int


class EdgeTypeCount(pydantic.BaseModel):
    """An edge type with its instance count."""

    type: str
    count: int


class GraphSchemaResponse(pydantic.BaseModel):
    """Response body for ``GET /admin/graph/schema``."""

    node_labels: list[LabelCount]
    edge_types: list[EdgeTypeCount]
    property_keys: list[str]


# ---------------------------------------------------------------
# AGE result parsing
# ---------------------------------------------------------------

_AGTYPE_SUFFIX_RE = re.compile(r'::(vertex|edge|path|numeric)$')


def _parse_value(raw: typing.Any) -> typing.Any:
    """Parse an AGE agtype value preserving vertex/edge structure.

    Unlike ``graph.parse_agtype`` (which unwraps to a vertex's
    properties dict), this returns a tagged structure for vertices
    and edges so the frontend can render them coherently.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw

    match = _AGTYPE_SUFFIX_RE.search(raw)
    suffix = match.group(1) if match else None
    cleaned = _AGTYPE_SUFFIX_RE.sub('', raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError, TypeError:
        return raw

    return _shape_value(parsed, suffix)


def _shape_value(parsed: typing.Any, suffix: str | None) -> typing.Any:
    """Apply a vertex/edge shape based on the agtype suffix."""
    if suffix == 'vertex' and isinstance(parsed, dict):
        as_dict = typing.cast(dict[str, typing.Any], parsed)
        return {
            '_kind': 'node',
            'id': str(as_dict.get('id')),
            'labels': [as_dict['label']] if 'label' in as_dict else [],
            'properties': as_dict.get('properties', {}),
        }
    if suffix == 'edge' and isinstance(parsed, dict):
        as_dict = typing.cast(dict[str, typing.Any], parsed)
        return {
            '_kind': 'edge',
            'id': str(as_dict.get('id')),
            'type': as_dict.get('label', ''),
            'start': str(as_dict.get('start_id')),
            'end': str(as_dict.get('end_id')),
            'properties': as_dict.get('properties', {}),
        }
    if suffix == 'path' and isinstance(parsed, list):
        as_list = typing.cast(  # type: ignore[redundant-cast]
            list[typing.Any], parsed
        )
        return {
            '_kind': 'path',
            'elements': [
                _shape_value(
                    elem,
                    'edge' if i % 2 == 1 else 'vertex',
                )
                if isinstance(elem, dict)
                else elem
                for i, elem in enumerate(as_list)
            ],
        }
    return parsed


def _collect_graph_elements(
    value: typing.Any,
    nodes: dict[str, GraphNode],
    edges: dict[str, GraphEdge],
) -> None:
    """Recursively scan ``value`` and collect deduped nodes / edges."""
    if isinstance(value, dict):
        as_dict = typing.cast(dict[str, typing.Any], value)
        kind = as_dict.get('_kind')
        if kind == 'node':
            node_id = str(as_dict['id'])
            if node_id not in nodes:
                nodes[node_id] = GraphNode(
                    id=node_id,
                    labels=list(as_dict.get('labels') or []),
                    properties=dict(as_dict.get('properties') or {}),
                )
            return
        if kind == 'edge':
            edge_id = str(as_dict['id'])
            if edge_id not in edges:
                edges[edge_id] = GraphEdge(
                    id=edge_id,
                    type=str(as_dict.get('type') or ''),
                    start=str(as_dict['start']),
                    end=str(as_dict['end']),
                    properties=dict(as_dict.get('properties') or {}),
                )
            return
        if kind == 'path':
            elements = typing.cast(
                list[typing.Any], as_dict.get('elements') or []
            )
            for elem in elements:
                _collect_graph_elements(elem, nodes, edges)
            return
        for v in as_dict.values():
            _collect_graph_elements(v, nodes, edges)
    elif isinstance(value, list):
        as_list = typing.cast(  # type: ignore[redundant-cast]
            list[typing.Any], value
        )
        for item in as_list:
            _collect_graph_elements(item, nodes, edges)


# ---------------------------------------------------------------
# Query column inference
# ---------------------------------------------------------------

_RETURN_RE = re.compile(r'\breturn\b', re.IGNORECASE)


def _split_top_level_commas(text: str) -> list[str]:
    """Split ``text`` on commas that are not nested in (), [], {}."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    in_str: str | None = None
    for ch in text:
        if in_str:
            buf.append(ch)
            if ch == in_str:
                in_str = None
            continue
        if ch in ('"', "'", '`'):
            in_str = ch
            buf.append(ch)
            continue
        if ch in '([{':
            depth += 1
            buf.append(ch)
            continue
        if ch in ')]}':
            depth -= 1
            buf.append(ch)
            continue
        if ch == ',' and depth == 0:
            parts.append(''.join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    tail = ''.join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _strip_return_modifiers(text: str) -> str:
    """Drop trailing ORDER BY / SKIP / LIMIT clauses from a RETURN body."""
    lowered = text.lower()
    best = len(text)
    for keyword in (' order by ', ' skip ', ' limit '):
        idx = lowered.find(keyword)
        if idx != -1 and idx < best:
            best = idx
    return text[:best]


def _column_alias(expr: str, fallback_index: int) -> str:
    """Extract an alias from ``expr`` or build a fallback name."""
    # Look for ` AS alias` at the end (case-insensitive).
    m = re.search(r'\s+AS\s+([A-Za-z_][A-Za-z0-9_]*)\s*$', expr, re.IGNORECASE)
    if m:
        return m.group(1)
    # Bare identifier (e.g. ``RETURN n``).
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', expr.strip()):
        return expr.strip()
    return f'col{fallback_index}'


def _extract_columns(query: str) -> list[str]:
    """Best-effort column-name extraction from a Cypher RETURN clause."""
    matches = list(_RETURN_RE.finditer(query))
    if not matches:
        raise ValueError('Query is missing a RETURN clause')
    # Take the last RETURN — Cypher allows multiple WITH/RETURN, but the
    # query's final projection wins.
    last = matches[-1]
    body = query[last.end() :]
    body = _strip_return_modifiers(body)
    body = body.rstrip(';').strip()
    if not body:
        raise ValueError('RETURN clause is empty')
    if body.upper().startswith('DISTINCT '):
        body = body[len('DISTINCT ') :].lstrip()
    parts = _split_top_level_commas(body)
    if not parts:
        raise ValueError('RETURN clause is empty')
    return [_column_alias(expr, i) for i, expr in enumerate(parts)]


# ---------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------


def _diagnostic_int(value: str | None) -> int | None:
    """Convert a psycopg ``Diagnostic`` numeric field to ``int``."""
    if value is None:
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def _build_error_response(
    message: str,
    code: str | None = None,
    line: int | None = None,
    column: int | None = None,
    hint: str | None = None,
) -> dict[str, dict[str, typing.Any]]:
    return {
        'error': GraphQueryError(
            message=message,
            code=code,
            line=line,
            column=column,
            hint=hint,
        ).model_dump(),
    }


def _error_from_psycopg(exc: psycopg.Error) -> dict[str, typing.Any]:
    """Translate a psycopg exception into the public error envelope."""
    diag = getattr(exc, 'diag', None)
    message = ''
    code: str | None = None
    line: int | None = None
    column: int | None = None
    hint: str | None = None
    if diag is not None:
        message = (getattr(diag, 'message_primary', None) or '').strip()
        code = getattr(diag, 'sqlstate', None)
        line = _diagnostic_int(
            getattr(diag, 'statement_position', None),
        )
        # psycopg exposes the position as a 1-based character offset
        # into the full statement. We don't have the SQL text the
        # server saw (it's AGE-wrapped), so surface it as ``column``
        # for client-side hinting and leave ``line`` unset.
        if line is not None:
            column = line
            line = None
        hint = getattr(diag, 'message_hint', None)
    if not message:
        message = str(exc).strip() or exc.__class__.__name__
    return _build_error_response(message, code, line, column, hint)


# ---------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------


@graph_query_router.post('/query', response_model=GraphQueryResponse)
async def run_graph_query(
    body: GraphQueryRequest,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(require_admin)
    ],
) -> GraphQueryResponse:
    """Execute an ad-hoc Cypher query against the graph."""
    query = body.query.strip()
    if not query:
        raise fastapi.HTTPException(
            status_code=400,
            detail=_build_error_response('Query must not be empty'),
        )

    try:
        columns = _extract_columns(query)
    except ValueError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=_build_error_response(str(exc)),
        ) from exc

    LOGGER.info(
        'Graph query: principal=%s columns=%s',
        auth.principal_name,
        columns,
    )

    start = time.monotonic()
    try:
        raw_rows = await db.execute(
            query, body.params, columns=columns, raw=True
        )
    except psycopg.Error as exc:
        LOGGER.info(
            'Graph query failed: principal=%s error=%s',
            auth.principal_name,
            exc,
        )
        raise fastapi.HTTPException(
            status_code=400,
            detail=_error_from_psycopg(exc),
        ) from exc
    except (ValueError, KeyError, IndexError) as exc:
        # sql.SQL.format may raise on bad placeholder references in
        # the user's query (e.g. unmatched ``{param}``).
        raise fastapi.HTTPException(
            status_code=400,
            detail=_build_error_response(str(exc) or exc.__class__.__name__),
        ) from exc
    elapsed_ms = (time.monotonic() - start) * 1000.0

    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}
    shaped_rows: list[dict[str, typing.Any]] = []
    for row in raw_rows:
        shaped: dict[str, typing.Any] = {}
        for col in columns:
            value = _parse_value(row.get(col))
            shaped[col] = value
            _collect_graph_elements(value, nodes, edges)
        shaped_rows.append(shaped)

    return GraphQueryResponse(
        columns=columns,
        rows=shaped_rows,
        nodes=list(nodes.values()),
        edges=list(edges.values()),
        elapsed_ms=round(elapsed_ms, 3),
    )


# ---------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------


async def _load_label_counts(
    db: graph.Graph,
) -> tuple[list[LabelCount], list[EdgeTypeCount]]:
    """Enumerate vertex/edge labels and count rows in each.

    AGE creates one row in ``ag_catalog.ag_label`` per label
    (``kind = 'v'`` for vertices, ``'e'`` for edges) plus the
    bookkeeping ``_ag_label_vertex`` / ``_ag_label_edge`` rows which
    are filtered out. Each label is stored in its own table under the
    graph's schema, so the count is a plain ``count(*)`` per table.

    Counts are exact rather than estimated. ``pg_class.reltuples``
    would be cheaper but reports ``-1`` for any table not yet
    ``ANALYZE``d (PostgreSQL 14+), which surfaced as ``0`` for every
    lightly-written label (User, Team, Organization, ...). The graph
    is small enough that exact counts stay cheap.
    """
    labels_query = sql.SQL(
        """
        SELECT l.name AS name, l.kind AS kind
          FROM ag_catalog.ag_label l
          JOIN ag_catalog.ag_graph g ON l.graph = g.graphid
         WHERE g.name = {graph}
           AND l.name NOT LIKE '\\_ag\\_label\\_%' ESCAPE '\\'
         ORDER BY l.name
        """,
    ).format(graph=sql.Literal(db.settings.graph_name))

    node_labels: list[LabelCount] = []
    edge_types: list[EdgeTypeCount] = []
    async with db.pool.connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(labels_query)
            labels = await cursor.fetchall()
            for name, kind in labels:
                count_query = sql.SQL('SELECT count(*) FROM {table}').format(
                    table=sql.Identifier(db.settings.graph_name, name),
                )
                await cursor.execute(count_query)
                row = await cursor.fetchone()
                count = int(row[0]) if row else 0
                if kind == 'v':
                    node_labels.append(LabelCount(label=name, count=count))
                elif kind == 'e':
                    edge_types.append(EdgeTypeCount(type=name, count=count))
    return node_labels, edge_types


async def _sample_property_keys(
    db: graph.Graph, sample_size: int = 200
) -> list[str]:
    """Return the union of property keys across a sample of vertices."""
    query: typing.LiteralString = (
        'MATCH (n) WITH n LIMIT {limit}'
        ' UNWIND keys(n) AS k'
        ' RETURN collect(DISTINCT k) AS keys'
    )
    try:
        records = await db.execute(
            query,
            {'limit': sample_size},
            columns=['keys'],
        )
    except psycopg.Error:
        LOGGER.warning(
            'Failed to sample property keys for schema endpoint',
            exc_info=True,
        )
        return []
    if not records:
        return []
    raw: typing.Any = graph.parse_agtype(records[0].get('keys'))
    if not isinstance(raw, list):
        return []
    as_list = typing.cast(  # type: ignore[redundant-cast]
        list[typing.Any], raw
    )
    return sorted({k for k in as_list if isinstance(k, str)})


@graph_query_router.get('/schema', response_model=GraphSchemaResponse)
async def get_graph_schema(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(require_admin)
    ],
) -> GraphSchemaResponse:
    """Return labels, edge types, and sampled property keys."""
    LOGGER.info('Graph schema requested: principal=%s', auth.principal_name)
    node_labels, edge_types = await _load_label_counts(db)
    property_keys = await _sample_property_keys(db)
    return GraphSchemaResponse(
        node_labels=node_labels,
        edge_types=edge_types,
        property_keys=property_keys,
    )
