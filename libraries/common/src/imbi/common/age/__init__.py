"""Apache AGE graph database integration layer.

Drop-in replacement for the ``imbi_common.neo4j`` module.  Provides
the same public API — ``initialize``, ``aclose``, ``session``,
``query``, ``run``, ``fetch_node``, ``fetch_nodes``, ``upsert``,
``create_node``, ``create_relationship``, ``refresh_relationship``,
``retrieve_relationship_edges``, ``delete_node`` — but executes
openCypher queries through the AGE PostgreSQL extension via psycopg v3.
"""

import contextlib
import datetime
import json
import logging
import re
import typing
import uuid

import psycopg
import pydantic
import pydantic_core

from . import client, constants, relationships
from . import exceptions as exceptions

LOGGER = logging.getLogger(__name__)

GRAPH = constants.GRAPH_NAME

# -- Type variables --------------------------------------------------------

ModelType = typing.TypeVar('ModelType', bound=pydantic.BaseModel)
SourceNode = typing.TypeVar('SourceNode', bound=pydantic.BaseModel)
TargetNode = typing.TypeVar('TargetNode', bound=pydantic.BaseModel)
RelationshipProperties = typing.TypeVar(
    'RelationshipProperties', bound=pydantic.BaseModel
)
EdgeType = typing.TypeVar('EdgeType')


# -- Lifecycle -------------------------------------------------------------


async def aclose() -> None:
    """Close the AGE connection pool."""
    await client.AGE.get_instance().aclose()


async def initialize() -> None:
    """Initialize AGE: create extension, graph, indexes."""
    await client.AGE.get_instance().initialize()


@contextlib.asynccontextmanager
async def session() -> typing.AsyncGenerator[
    psycopg.AsyncConnection[typing.Any], None
]:
    """Return an async connection with AGE loaded."""
    instance = client.AGE.get_instance()
    async with instance.connection() as conn:
        yield conn


# -- agtype helpers --------------------------------------------------------

_AGTYPE_SUFFIX_RE = re.compile(r'::(vertex|edge|path|numeric)$')


def _parse_agtype(value: typing.Any) -> typing.Any:
    """Parse a single agtype value into a Python object.

    AGE returns results as ``agtype`` which psycopg delivers as
    strings.  Vertices look like ``{...}::vertex``, edges like
    ``{...}::edge``, and scalars are bare JSON.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    # Strip ::vertex, ::edge, etc.
    cleaned = _AGTYPE_SUFFIX_RE.sub('', value)
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return value
    # If it's a vertex dict, extract properties
    if isinstance(parsed, dict) and 'properties' in parsed:
        props = parsed['properties']
        # Preserve the AGE vertex id and label for internal use
        if 'id' in parsed and 'label' in parsed:
            props.setdefault('_age_id', parsed['id'])
            props.setdefault('_age_label', parsed['label'])
        return props
    return parsed


def _parse_row(
    row: tuple[typing.Any, ...],
    columns: list[str],
) -> dict[str, typing.Any]:
    """Convert a result row into a dict with parsed agtype values."""
    return {
        col: _parse_agtype(val) for col, val in zip(columns, row, strict=True)
    }


def convert_neo4j_types(data: typing.Any) -> typing.Any:
    """Compatibility shim — identity for AGE data.

    Kept so callers that still reference ``convert_neo4j_types``
    (e.g. ``WebhookResponse.from_neo4j_record``) continue to work.
    AGE data is already native Python after :func:`_parse_agtype`.
    """
    if isinstance(data, dict):
        return {key: convert_neo4j_types(value) for key, value in data.items()}
    if isinstance(data, list):
        return [convert_neo4j_types(item) for item in data]
    return data


# -- Parameter binding -----------------------------------------------------


def _escape_cypher_value(value: typing.Any) -> str:
    """Convert a Python value to a Cypher literal string.

    This is used to inline parameters into the Cypher query text
    because AGE's ``cypher()`` function does not support ``$param``
    placeholders the way the Neo4j driver does.
    """
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        escaped = (
            value.replace('\\', '\\\\')
            .replace("'", "\\'")
            .replace('\n', '\\n')
            .replace('\r', '\\r')
            .replace('\t', '\\t')
        )
        return f"'{escaped}'"
    if isinstance(value, datetime.datetime):
        return f"'{value.isoformat()}'"
    if isinstance(value, datetime.date):
        return f"'{value.isoformat()}'"
    if isinstance(value, list):
        items = ', '.join(_escape_cypher_value(item) for item in value)
        return f'[{items}]'
    if isinstance(value, dict):
        pairs = ', '.join(
            f'{k}: {_escape_cypher_value(v)}' for k, v in value.items()
        )
        return f'{{{pairs}}}'
    if isinstance(value, pydantic.AnyUrl):
        return _escape_cypher_value(str(value))
    # Fall back to string representation
    return _escape_cypher_value(str(value))


def _bind_params(cypher: str, parameters: dict[str, typing.Any]) -> str:
    """Replace ``$param`` placeholders with escaped literal values.

    Handles ``$param`` in property maps ``{key: $key}`` and in
    ``SET`` clauses.  Only replaces ``$name`` when *name* is a key
    in *parameters* to avoid mangling unrelated dollar signs.
    """
    if not parameters:
        return cypher

    def _replacer(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in parameters:
            return _escape_cypher_value(parameters[name])
        return match.group(0)  # leave unrecognised placeholders alone

    # Match $word_chars but not $$
    return re.sub(r'\$([A-Za-z_]\w*)', _replacer, cypher)


# -- RETURN clause parsing -------------------------------------------------


def _mask_braces(text: str) -> str:
    """Replace brace-enclosed content with spaces for keyword search."""
    depth = 0
    masked = []
    for ch in text.upper():
        if ch == '{':
            depth += 1
            masked.append(' ')
        elif ch == '}':
            depth = max(depth - 1, 0)
            masked.append(' ')
        else:
            masked.append(ch if depth == 0 else ' ')
    return ''.join(masked)


def _strip_trailing_clauses(text: str) -> str:
    """Remove ORDER BY / LIMIT / SKIP outside of brace nesting."""
    for kw in ('ORDER BY', 'LIMIT', 'SKIP'):
        depth = 0
        upper = text.upper()
        for i, ch in enumerate(text):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth = max(depth - 1, 0)
            elif depth == 0 and upper[i:].startswith(kw):
                return text[:i]
    return text


def _split_top_level(text: str, sep: str = ',') -> list[str]:
    """Split *text* on *sep* respecting (), {}, [] nesting."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in text:
        if ch in ('(', '{', '['):
            depth += 1
            current.append(ch)
        elif ch in (')', '}', ']'):
            depth = max(depth - 1, 0)
            current.append(ch)
        elif ch == sep and depth == 0:
            parts.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append(''.join(current).strip())
    return parts


def _column_name(part: str, index: int) -> str:
    """Extract the column alias from a single RETURN expression."""
    part = part.strip()
    if not part:
        return f'_c{index}'
    as_match = re.search(r'\bAS\s+(\w+)\s*$', part, re.IGNORECASE)
    if as_match:
        return as_match.group(1)
    tokens = re.findall(r'\w+', part)
    return tokens[-1] if tokens else f'_c{index}'


def _extract_return_columns(cypher: str) -> list[str]:
    """Parse the RETURN clause to determine result column names."""
    masked = _mask_braces(cypher)
    idx = masked.rfind('RETURN ')
    if idx == -1:
        return ['result']
    after_return = _strip_trailing_clauses(cypher[idx + 7 :])
    parts = _split_top_level(after_return)
    columns = [_column_name(p, i) for i, p in enumerate(parts)]
    return columns or ['result']


def _build_age_sql(cypher: str, columns: list[str]) -> psycopg.sql.SQL:
    """Wrap a Cypher query in AGE's ``cypher()`` SQL function."""
    col_defs = ', '.join(f'{col} agtype' for col in columns)
    # Use a unique dollar-quote tag per query to prevent injection
    # via property values containing the tag string.
    tag = f'$_age_{uuid.uuid4().hex}$'
    sql_text = (
        f"SELECT * FROM cypher('{GRAPH}', {tag} "  # noqa: S608
        f'{cypher} '
        f'{tag}) as ({col_defs})'
    )
    return psycopg.sql.SQL(sql_text)


# -- Prepare node data -----------------------------------------------------


def _prepare_node_data(
    model_cls: type[pydantic.BaseModel],
    node_data: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Handle relationship fields not stored as node properties."""
    prepared_data = node_data.copy()
    # Remove internal AGE metadata
    prepared_data.pop('_age_id', None)
    prepared_data.pop('_age_label', None)

    for field_name, field_info in model_cls.model_fields.items():
        if field_name in prepared_data:
            continue
        is_relationship = any(
            isinstance(md, relationships.Relationship)
            for md in field_info.metadata
        )
        if is_relationship:
            if field_info.default is not pydantic_core.PydanticUndefined:
                prepared_data[field_name] = field_info.default
            elif field_info.default_factory is not None and callable(
                field_info.default_factory
            ):
                prepared_data[field_name] = field_info.default_factory()  # type: ignore[call-arg]
            else:
                prepared_data[field_name] = None
    return prepared_data


# -- Low-level query execution ---------------------------------------------


class _AGEResult:
    """Wrapper around AGE query results providing a Neo4j-like interface.

    Supports ``await result.data()`` and ``await result.single()``
    so that existing code using ``async with age.run(...) as result``
    works without modification.
    """

    def __init__(
        self,
        rows: list[tuple[typing.Any, ...]],
        columns: list[str],
    ) -> None:
        self._rows = rows
        self._columns = columns
        self._parsed: list[dict[str, typing.Any]] | None = None

    def _ensure_parsed(self) -> list[dict[str, typing.Any]]:
        if self._parsed is None:
            self._parsed = [
                _parse_row(row, self._columns) for row in self._rows
            ]
        return self._parsed

    async def data(self) -> list[dict[str, typing.Any]]:
        """Return all rows as a list of dicts with parsed agtype."""
        return self._ensure_parsed()

    async def single(self) -> dict[str, typing.Any] | None:
        """Return the first row or None."""
        parsed = self._ensure_parsed()
        return parsed[0] if parsed else None

    async def consume(self) -> None:
        """Consume remaining results (no-op for AGE).

        Provided for Neo4j API compatibility -- callers that
        used ``await result.consume()`` continue to work.
        """

    def __getitem__(self, key: str) -> typing.Any:
        """Allow dict-style access on the first row."""
        parsed = self._ensure_parsed()
        if parsed:
            return parsed[0][key]
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return key in self._columns


@contextlib.asynccontextmanager
async def run(
    cypher: str, **parameters: typing.Any
) -> typing.AsyncGenerator[_AGEResult, None]:
    """Run a Cypher query via AGE.

    Yields an :class:`_AGEResult` with ``.data()`` and ``.single()``
    methods for Neo4j API compatibility.

    Raises :class:`exceptions.ConstraintError` when a unique constraint
    is violated (wraps ``psycopg.errors.UniqueViolation``).
    """
    bound = _bind_params(re.sub(r'\s+', ' ', cypher), parameters)
    columns = _extract_return_columns(bound)
    sql = _build_age_sql(bound, columns)
    async with session() as conn:
        try:
            cursor = await conn.execute(sql)
        except psycopg.errors.UniqueViolation as err:
            raise exceptions.ConstraintError(str(err)) from err
        rows = await cursor.fetchall()
        yield _AGEResult(rows, columns)


async def query(
    cypher: str,
    **parameters: typing.Any,
) -> list[dict[str, typing.Any]]:
    """Run a Cypher query and return results as a list of dicts."""
    async with run(cypher, **parameters) as result:
        return await result.data()


# -- Cypher property helpers -----------------------------------------------


def _cypher_property_params(value: dict[str, typing.Any]) -> str:
    """Build ``key: $key, ...`` Cypher fragment from a dict."""
    return ', '.join(f'{key}: ${key}' for key in (value or {}).keys())


def _build_match_dict(properties: dict[str, typing.Any]) -> str:
    """Build ``key: value, ...`` fragment with escaped literal values."""
    return ', '.join(
        f'{k}: {_escape_cypher_value(v)}' for k, v in properties.items()
    )


# Public alias
cypher_property_params = _cypher_property_params


# -- High-level CRUD -------------------------------------------------------


def _build_fetch_query(
    model: type[pydantic.BaseModel] | str,
    parameters: dict[str, typing.Any] | None = None,
    order_by: str | list[str] | None = None,
) -> str:
    """Build a MATCH query to fetch nodes."""
    name = model.__name__ if isinstance(model, type) else model
    q = f'MATCH (node:{name}'
    if parameters:
        q += f' {{{_cypher_property_params(parameters)}}}'
    q += ') RETURN node'
    if order_by:
        if isinstance(order_by, list):
            order_by = ', '.join(f'node.{key}' for key in order_by)
        elif isinstance(order_by, str):
            order_by = f'node.{order_by}'
        q += f' ORDER BY {order_by}'
    return q


async def fetch_node(
    model: type[ModelType],
    parameters: dict[str, typing.Any],
) -> ModelType | None:
    """Fetch a single node by matching properties."""
    q = _build_fetch_query(model, parameters)
    LOGGER.debug('Running Query: %s', q)
    records = await query(q, **parameters)
    if records:
        node_data = records[0].get('node', records[0])
        prepared = _prepare_node_data(model, node_data)
        return model.model_validate(prepared)
    return None


async def fetch_nodes(
    model: type[ModelType],
    parameters: dict[str, typing.Any] | None = None,
    order_by: str | list[str] | None = None,
) -> typing.AsyncGenerator[ModelType, None]:
    """Fetch nodes, optionally filtered and ordered."""
    q = _build_fetch_query(model, parameters, order_by)
    LOGGER.debug('Running Query: %s', q)
    records = await query(q, **(parameters or {}))
    for record in records:
        node_data = record.get('node', record)
        prepared = _prepare_node_data(model, node_data)
        yield model.model_validate(prepared)


async def create_node(model: ModelType) -> ModelType:
    """Create a node from a Pydantic model instance."""
    now = datetime.datetime.now(datetime.UTC)
    if hasattr(model, 'created_at') and model.created_at is None:
        model.created_at = now
    if hasattr(model, 'updated_at') and model.updated_at is None:
        model.updated_at = now

    label = type(model).__name__
    properties = _model_properties(model)
    prop_pairs = _build_match_dict(properties)
    cypher = f'CREATE (node:{label} {{{prop_pairs}}}) RETURN node'
    records = await query(cypher)
    if not records:
        raise RuntimeError(f'CREATE query returned no results for {label}')
    node_data = records[0].get('node', records[0])
    prepared = _prepare_node_data(type(model), node_data)
    return type(model).model_validate(prepared)


async def create_relationship(
    from_node: SourceNode,
    to_node: TargetNode,
    rel_props: RelationshipProperties | None = None,
    *,
    rel_type: str | None = None,
) -> dict[str, typing.Any]:
    """Create a relationship between two nodes."""
    if rel_props is not None:
        config = getattr(rel_props, 'cypherantic_config', None)
        if config is not None:
            rel_type = config.rel_type
        elif rel_type is None:
            raise ValueError(
                'rel_props must have cypherantic_config or '
                'rel_type must be provided'
            )
    elif rel_type is None:
        raise ValueError('Either rel_props or rel_type must be provided')

    from_label = type(from_node).__name__
    to_label = type(to_node).__name__
    from_key = _unique_key_props(from_node)
    to_key = _unique_key_props(to_node)

    from_match = _build_match_dict(from_key)
    to_match = _build_match_dict(to_key)

    rel_prop_str = ''
    if rel_props is not None:
        props = {
            k: v
            for k, v in rel_props.model_dump().items()
            if not k.startswith('cypherantic_')
        }
        if props:
            pairs = ', '.join(
                f'{k}: {_escape_cypher_value(v)}' for k, v in props.items()
            )
            rel_prop_str = f' {{{pairs}}}'

    cypher = (
        f'MATCH (a:{from_label} {{{from_match}}}), '
        f'(b:{to_label} {{{to_match}}}) '
        f'CREATE (a)-[r:{rel_type}{rel_prop_str}]->(b) '
        f'RETURN r'
    )
    records = await query(cypher)
    if records:
        result: dict[str, typing.Any] = records[0].get('r', {})
        return result
    return {}


async def refresh_relationship(model: SourceNode, rel_property: str) -> None:
    """Lazy-load a relationship property on a model instance."""
    field_info = type(model).model_fields.get(rel_property)
    if field_info is None:
        raise ValueError(f'No field {rel_property!r} on {type(model)}')

    rel_meta = None
    for md in field_info.metadata:
        if isinstance(md, relationships.Relationship):
            rel_meta = md
            break
    if rel_meta is None:
        raise ValueError(f'Field {rel_property!r} has no Relationship meta')

    label = type(model).__name__
    match_pairs = _build_match_dict(_unique_key_props(model))

    if rel_meta.direction == 'OUTGOING':
        arrow = f'(a:{label} {{{match_pairs}}})-[r:{rel_meta.rel_type}]->(b)'
    elif rel_meta.direction == 'INCOMING':
        arrow = f'(a:{label} {{{match_pairs}}})<-[r:{rel_meta.rel_type}]-(b)'
    else:
        arrow = f'(a:{label} {{{match_pairs}}})-[r:{rel_meta.rel_type}]-(b)'

    cypher = f'MATCH {arrow} RETURN b'
    # Determine target type from field annotation
    records = await query(cypher)
    # For list fields, collect all; for single, take first
    annotation = field_info.annotation
    origin = typing.get_origin(annotation)
    if origin is list or (
        isinstance(annotation, type) and issubclass(annotation, list)
    ):
        setattr(model, rel_property, [r.get('b', r) for r in records])
    elif records:
        setattr(model, rel_property, records[0].get('b', records[0]))


async def retrieve_relationship_edges(
    model: SourceNode,
    rel_name: str,
    direction: typing.Literal['INCOMING', 'OUTGOING', 'UNDIRECTED'],
    edge_cls: type[EdgeType],
) -> list[EdgeType]:
    """Fetch related nodes with relationship properties."""
    label = type(model).__name__
    match_pairs = _build_match_dict(_unique_key_props(model))

    if direction == 'OUTGOING':
        pattern = f'(a:{label} {{{match_pairs}}})-[r:{rel_name}]->(b)'
    elif direction == 'INCOMING':
        pattern = f'(a:{label} {{{match_pairs}}})<-[r:{rel_name}]-(b)'
    else:
        pattern = f'(a:{label} {{{match_pairs}}})-[r:{rel_name}]-(b)'

    cypher = f'MATCH {pattern} RETURN b, r'
    records = await query(cypher)

    edges: list[EdgeType] = []
    # edge_cls is expected to be a NamedTuple with (node, properties)
    annotations = getattr(edge_cls, '__annotations__', {})
    node_type = annotations.get('node', None)
    props_type = annotations.get('properties', None)
    for record in records:
        node_data = record.get('b', {})
        rel_data = record.get('r', {})
        node = (
            node_type.model_validate(node_data)
            if node_type and hasattr(node_type, 'model_validate')
            else node_data
        )
        props = (
            props_type.model_validate(rel_data)
            if props_type and hasattr(props_type, 'model_validate')
            else rel_data
        )
        edges.append(edge_cls(node=node, properties=props))  # type: ignore[call-arg]
    return edges


async def upsert(
    node: pydantic.BaseModel,
    constraint: dict[str, typing.Any],
    auto_increment: list[str] | None = None,
    immutable_fields: list[str] | None = None,
) -> str:
    """Upsert a node, returning the AGE vertex id.

    Uses Cypher ``MERGE`` with ``ON CREATE SET`` / ``ON MATCH SET``.
    """
    now = datetime.datetime.now(datetime.UTC)
    if hasattr(node, 'updated_at'):
        node.updated_at = now
    if hasattr(node, 'created_at') and node.created_at is None:
        node.created_at = now

    auto_increment_fields = set(auto_increment or [])
    immutable = set(immutable_fields or [])

    model_cls = type(node)
    field_to_alias = {
        name: info.alias or name
        for name, info in model_cls.model_fields.items()
    }
    alias_to_field = {v: k for k, v in field_to_alias.items()}
    auto_increment_aliases = {
        field_to_alias.get(f, f) for f in auto_increment_fields
    }
    immutable_aliases = {field_to_alias.get(f, f) for f in immutable}

    properties = node.model_dump(by_alias=True)
    # Remove relationship fields
    rel_fields = _relationship_field_names(model_cls)
    for rf in rel_fields:
        alias = field_to_alias.get(rf, rf)
        properties.pop(alias, None)

    label = node.__class__.__name__

    # Build SET assignments with inlined values
    assignment = []
    for key, val in properties.items():
        if key in auto_increment_aliases:
            assignment.append(f'node.{key} = coalesce(node.{key}, 0) + 1')
        else:
            assignment.append(f'node.{key} = {_escape_cypher_value(val)}')

    created_at_alias = field_to_alias.get('created_at', 'created_at')
    create_only_aliases = {created_at_alias} | immutable_aliases
    on_create_assignment = list(assignment)
    on_match_assignment = [
        expr
        for key, expr in zip(properties.keys(), assignment, strict=True)
        if key not in create_only_aliases
    ]

    where_props = _build_match_dict(constraint)

    returned_aliases = auto_increment_aliases | immutable_aliases
    return_fields = 'id(node) AS nodeId'
    if returned_aliases:
        return_fields += ', ' + ', '.join(
            f'node.{key} AS {key}' for key in sorted(returned_aliases)
        )

    match_clause = (
        f'  ON MATCH SET {", ".join(on_match_assignment)}'
        if on_match_assignment
        else ''
    )
    cypher = (
        f'MERGE (node:{label} {{{where_props}}})'
        f' ON CREATE SET {", ".join(on_create_assignment)}'
        f'{match_clause}'
        f' RETURN {return_fields}'
    ).strip()
    LOGGER.debug('Upsert query: %s', cypher)

    records = await query(cypher)
    if not records:
        raise ValueError('Upsert query returned no results')
    record = records[0]
    for alias in sorted(returned_aliases):
        if alias in record:
            field_name = alias_to_field.get(alias, alias)
            setattr(node, field_name, record[alias])
    return str(record['nodeId'])


async def delete_node(
    model: type[pydantic.BaseModel],
    parameters: dict[str, typing.Any],
) -> bool:
    """Delete a node matching the given parameters."""
    label = model.__name__
    where_clauses = [f'node.{key} = ${key}' for key in parameters]
    where_clause = ' AND '.join(where_clauses)

    cypher = (
        f' MATCH (node:{label})'
        f' WHERE {where_clause}'
        f' DETACH DELETE node'
        f' RETURN count(node) as deleted'
    )
    LOGGER.debug('Delete query: %s', cypher)
    records = await query(cypher, **parameters)
    return bool(records and records[0].get('deleted', 0) > 0)


# -- Internal helpers ------------------------------------------------------


def _model_properties(
    model: pydantic.BaseModel,
) -> dict[str, typing.Any]:
    """Extract non-relationship properties from a model instance."""
    rel_fields = _relationship_field_names(type(model))
    props = model.model_dump(by_alias=True)
    return {k: v for k, v in props.items() if k not in rel_fields}


def _relationship_field_names(
    model_cls: type[pydantic.BaseModel],
) -> set[str]:
    """Return field names (and aliases) that are relationships."""
    names: set[str] = set()
    for field_name, field_info in model_cls.model_fields.items():
        is_rel = any(
            isinstance(md, relationships.Relationship)
            for md in field_info.metadata
        )
        if is_rel:
            names.add(field_name)
            if field_info.alias:
                names.add(field_info.alias)
    return names


def _unique_key_props(
    model: pydantic.BaseModel,
) -> dict[str, typing.Any]:
    """Extract properties used for unique matching (fields with unique=True
    metadata or common unique identifiers)."""
    props: dict[str, typing.Any] = {}
    model_cls = type(model)
    for field_name, field_info in model_cls.model_fields.items():
        # Check for unique=True in JSON schema extra
        json_extra = field_info.json_schema_extra
        if isinstance(json_extra, dict) and json_extra.get('unique'):
            props[field_name] = getattr(model, field_name)
            continue
        # Check common unique fields
        if field_name in (
            'email',
            'slug',
            'id',
            'key_id',
            'client_id',
            'session_id',
            'jti',
            'username',
        ):
            val = getattr(model, field_name, None)
            if val is not None:
                props[field_name] = val
    if not props:
        raise ValueError(
            f'No unique key fields found on {model_cls.__name__}. '
            f'Add json_schema_extra={{"unique": True}} to a Field, '
            f'or use a standard name (slug, id, email, etc.).'
        )
    return props
