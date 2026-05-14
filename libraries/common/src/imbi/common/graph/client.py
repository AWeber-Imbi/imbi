"""
Apache AGE Database Interface

"""

import dataclasses
import functools
import json
import logging
import re
import typing

import psycopg
import psycopg_pool
import pydantic
from pgvector.psycopg import register_vector_async
from psycopg import rows, sql

from imbi_common import models, settings
from imbi_common.graph import cypher

LOGGER = logging.getLogger(__name__)

_AGTYPE_SUFFIX = re.compile(
    r'::(vertex|edge|path|numeric)$',
)

ModelT = typing.TypeVar('ModelT', bound=pydantic.BaseModel)
GraphModelT = typing.TypeVar(
    'GraphModelT',
    bound=models.GraphModel,
)


def _dollar_quote_tag(body: str) -> str:
    """Return a dollar-quote delimiter not present in *body*.

    PostgreSQL dollar quoting uses ``$tag$...$tag$``.  If the
    Cypher payload contains ``$$`` a static delimiter would let
    a crafted value escape the quoted string.  This picks the
    shortest safe tag.

    """
    tag = '$$'
    if tag not in body:
        return tag
    n = 0
    while True:
        tag = f'$q{n}$'
        if tag not in body:
            return tag
        n += 1


@functools.cache
def _embeddable_descriptors(
    node_type: type[pydantic.BaseModel],
) -> tuple[tuple[str, models.Embeddable], ...]:
    """Return ``(name, spec)`` tuples for embeddable fields.

    Cached per model class; model class field metadata is
    immutable after class creation.

    """
    result: list[tuple[str, models.Embeddable]] = []
    for name, info in node_type.model_fields.items():
        for md in info.metadata:
            if isinstance(md, models.Embeddable):
                result.append((name, md))
                break
    return tuple(result)


def _embeddable_fields(
    node: models.Node,
) -> list[tuple[str, str | None, models.Embeddable]]:
    """Return ``(name, value, spec)`` for embeddable fields.

    Fields whose current value is ``None`` are included with
    a ``None`` value so callers can clean up stale embeddings.

    """
    result: list[tuple[str, str | None, models.Embeddable]] = []
    for name, spec in _embeddable_descriptors(type(node)):
        value = getattr(node, name)
        result.append(
            (
                name,
                str(value) if value is not None else None,
                spec,
            ),
        )
    return result


@functools.cache
def _edge_field_names(
    node_type: type[pydantic.BaseModel],
) -> frozenset[str]:
    """Return the set of edge field names for *node_type*.

    Cached per model class.  Used by ``_strip_edge_fields``
    to skip the per-call metadata walk.

    """
    names: list[str] = []
    for name, info in node_type.model_fields.items():
        for md in info.metadata:
            if isinstance(md, models.Edge):
                names.append(name)
                break
    return frozenset(names)


def _strip_edge_fields(
    node_type: type[pydantic.BaseModel],
    props: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Remove edge field keys from *props*.

    AGE vertices only contain scalar properties; edge fields
    are separate graph relationships.  Removing them lets
    ``model_construct`` supply the field default (e.g. ``[]``
    or ``None``) without type-validation conflicts.

    """
    for name in _edge_field_names(node_type):
        props.pop(name, None)
    return props


def parse_agtype(value: typing.Any) -> typing.Any:
    """Parse a single agtype value into a Python dict.

    AGE returns vertices as ``{...}::vertex`` strings.  This
    strips the suffix, parses the JSON, and extracts the
    ``properties`` dict when present.

    """
    if value is None or not isinstance(value, str):
        return value
    cleaned = _AGTYPE_SUFFIX.sub('', value)
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return value
    if isinstance(parsed, dict) and 'properties' in parsed:
        return parsed['properties']
    return parsed


@dataclasses.dataclass(frozen=True, slots=True)
class SearchResult:
    """A vector search result with distance score."""

    node_label: str
    node_id: str
    attribute: str
    chunk_text: str
    distance: float


class Graph:
    """Wrapper around the PostgreSQL connection pool.

    Supports both Apache AGE Cypher queries and pgvector
    similarity search against the ``embeddings`` table.

    """

    def __init__(self) -> None:
        self.opened = False
        self.settings = settings.Postgres()
        self.pool = psycopg_pool.AsyncConnectionPool(
            conninfo=str(self.settings.url),
            min_size=self.settings.min_pool_size,
            max_size=self.settings.max_pool_size,
            configure=self._configure_connection,
            open=False,
        )

    @staticmethod
    async def _configure_connection(
        conn: psycopg.AsyncConnection[typing.Any],
    ) -> None:
        """Set up each pool connection.

        AGE is loaded via ``shared_preload_libraries`` in
        ``postgresql.conf``, so ``LOAD 'age'`` is not needed.
        Only the search path must include ``ag_catalog``.
        pgvector types are registered for transparent
        ``vector`` column handling.

        """
        await conn.set_autocommit(True)
        await conn.execute(
            'SET search_path = ag_catalog, "$user", public',
        )
        await register_vector_async(conn)

    async def open(self) -> None:
        """Open the connection pool."""
        await self.pool.open()
        self.opened = True

    async def close(self) -> None:
        """Close the connection pool and release models."""
        from imbi_common.graph import embeddings

        await self.pool.close()
        embeddings.close()
        self.opened = False

    # ----------------------------------------------------------
    # Graph CRUD
    # ----------------------------------------------------------

    async def create(
        self,
        node: GraphModelT,
    ) -> GraphModelT:
        """Create a node and its relationships in the graph."""
        await self._execute_batch(cypher.create(node))
        if isinstance(node, models.Node):
            await self._auto_embed(node)
        return node

    async def delete(self, node: models.GraphModel) -> None:
        """Delete a node, its relationships, and embeddings.

        The Cypher delete runs via AGE (requires autocommit),
        then embeddings are cleaned up on the same connection.

        """
        if not self.opened:
            raise RuntimeError('Graph pool is not open')
        stmt = cypher.delete(node)
        async with self.pool.connection() as conn:
            await self._execute_on(
                conn,
                stmt.cypher,
                stmt.params,
            )
            if isinstance(node, models.Node):
                await self._delete_embeddings_where(
                    conn,
                    node_label=type(node).__name__,
                    node_id=node.id,
                )

    @staticmethod
    def _row_to_model(
        node_type: type[ModelT],
        props: dict[str, typing.Any],
    ) -> ModelT:
        """Deserialize a vertex property dict into a model.

        Strips edge-field keys (stored as separate graph
        relationships, never on vertex data) then tries
        ``model_validate`` so field validators run.  On
        ``ValidationError`` (e.g. extra AGE metadata a
        validator rejects) falls back to ``model_construct``.

        """
        _strip_edge_fields(node_type, props)
        try:
            return node_type.model_validate(props)
        except pydantic.ValidationError:
            return node_type.model_construct(**props)

    async def match(
        self,
        node_type: type[ModelT],
        params: dict[str, typing.Any] | None = None,
        order_by: str | None = None,
    ) -> list[ModelT]:
        """Match nodes and return model instances.

        Deserialization prefers ``model_validate`` (so field
        validators run) and falls back to ``model_construct``
        when validation fails.

        """
        stmt = cypher.match(node_type, params, order_by)
        raw_rows = await self.execute(
            stmt.cypher,
            stmt.params,
        )
        results: list[ModelT] = []
        for row in raw_rows:
            for value in row.values():
                props = parse_agtype(value)
                if isinstance(props, dict):
                    results.append(
                        self._row_to_model(node_type, props),
                    )
        return results

    async def merge(
        self,
        node: GraphModelT,
        match_on: list[str] | None = None,
    ) -> GraphModelT:
        """Upsert a node and its relationships in the graph."""
        await self._execute_batch(
            cypher.merge(node, match_on),
        )
        if isinstance(node, models.Node):
            await self._auto_embed(node)
        return node

    # ----------------------------------------------------------
    # Vector search
    # ----------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        model_name: str = 'text',
        node_label: str | None = None,
        attribute: str | None = None,
        limit: int = 10,
        distance_threshold: float | None = None,
    ) -> list[SearchResult]:
        """Search for nodes by semantic similarity.

        Embeds *query* using the specified model, then
        performs a cosine similarity search against the
        ``embeddings`` table.  Results are ordered by
        distance (ascending = most similar).

        """
        if not self.opened:
            raise RuntimeError('Graph pool is not open')
        from imbi_common.graph import embeddings

        vector = await embeddings.aembed_one(
            query,
            model_name,
        )
        vec = sql.Placeholder('vec')
        dims = embeddings.get_dimensions(model_name)
        distance = sql.SQL(
            '(embedding::vector({dims})) <=> ({vec}::vector({dims}))',
        ).format(
            dims=sql.Literal(dims),
            vec=vec,
        )
        params: dict[str, typing.Any] = {
            'vec': vector,
            'model': model_name,
            'limit': limit,
        }
        query_sql = sql.SQL(
            'SELECT node_label, node_id, attribute,'
            '       chunk_text,'
            '       {distance} AS distance'
            '  FROM public.embeddings'
            ' WHERE model_name = {model}'
        ).format(
            distance=distance,
            model=sql.Placeholder('model'),
        )
        if node_label is not None:
            params['label'] = node_label
            query_sql += sql.SQL(
                ' AND node_label = {label}',
            ).format(label=sql.Placeholder('label'))
        if attribute is not None:
            params['attribute'] = attribute
            query_sql += sql.SQL(
                ' AND attribute = {attribute}',
            ).format(attribute=sql.Placeholder('attribute'))
        if distance_threshold is not None:
            params['threshold'] = distance_threshold
            query_sql += sql.SQL(
                ' AND {distance} <= {threshold}',
            ).format(
                distance=distance,
                threshold=sql.Placeholder('threshold'),
            )
        query_sql += sql.SQL(
            ' ORDER BY {distance} LIMIT {limit}',
        ).format(
            distance=distance,
            limit=sql.Placeholder('limit'),
        )
        async with self.pool.connection() as conn:
            async with conn.cursor(
                row_factory=rows.dict_row,
            ) as cur:
                await cur.execute(query_sql, params)
                result_rows = await cur.fetchall()
        return [
            SearchResult(
                node_label=r['node_label'],
                node_id=r['node_id'],
                attribute=r['attribute'],
                chunk_text=r['chunk_text'],
                distance=r['distance'],
            )
            for r in result_rows
        ]

    async def search_nodes(
        self,
        node_type: type[ModelT],
        query: str,
        *,
        model_name: str = 'text',
        limit: int = 10,
    ) -> list[ModelT]:
        """Search and return full node instances.

        Combines vector search with graph node retrieval.
        Results are deduplicated by ``id`` (multiple chunks
        from the same node may match).

        """
        # Over-fetch embedding rows so deduplication still
        # yields enough distinct nodes for the requested limit.
        chunk_multiplier = 5
        results = await self.search(
            query,
            model_name=model_name,
            node_label=node_type.__name__,
            limit=limit * chunk_multiplier,
        )
        node_ids = list(
            dict.fromkeys(r.node_id for r in results),
        )[:limit]
        if not node_ids:
            return []
        label = node_type.__name__
        id_list = ', '.join(f'{{{f"id{i}"}}}' for i in range(len(node_ids)))
        cypher_q = f'MATCH (n:{label}) WHERE n.id IN [{id_list}] RETURN n'
        params: dict[str, typing.Any] = {
            f'id{i}': nid for i, nid in enumerate(node_ids)
        }
        raw_rows = await self.execute(cypher_q, params)
        # Re-order to match the ranking from search()
        by_id: dict[str, ModelT] = {}
        for row in raw_rows:
            for value in row.values():
                props = parse_agtype(value)
                if isinstance(props, dict):
                    nid = props.get('id')
                    node = self._row_to_model(node_type, props)
                    if nid is not None:
                        by_id[nid] = node
        return [by_id[nid] for nid in node_ids if nid in by_id]

    # ----------------------------------------------------------
    # Auto-embedding
    # ----------------------------------------------------------

    async def _auto_embed(self, node: models.Node) -> None:
        """Generate and store embeddings for embeddable fields.

        Failures are logged but do not propagate — the graph
        write is the critical path.

        """
        embed_settings = settings.Embeddings()
        if not embed_settings.enabled:
            return
        fields = _embeddable_fields(node)
        if not fields:
            return
        try:
            from imbi_common.graph import chunk, embeddings

            node_label = type(node).__name__
            async with self.pool.connection() as conn:
                for attr, text, spec in fields:
                    if text is None:
                        await self._delete_embeddings_where(
                            conn,
                            node_label=node_label,
                            node_id=node.id,
                            attribute=attr,
                        )
                        continue
                    if spec.chunk:
                        chunks = list(
                            chunk.content(
                                spec.mimetype,
                                text,
                            ),
                        )
                    else:
                        chunks = [text]
                    vectors = await embeddings.aembed(
                        chunks,
                        spec.model_name,
                    )
                    await self._upsert_embeddings(
                        conn,
                        node_label,
                        node.id,
                        attr,
                        spec.model_name,
                        chunks,
                        vectors,
                    )
                    await self._delete_embeddings_where(
                        conn,
                        node_label=node_label,
                        node_id=node.id,
                        attribute=attr,
                        model_name=spec.model_name,
                        min_chunk_index=len(chunks),
                    )
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                'Failed to auto-embed node %s (id=%s)',
                type(node).__name__,
                node.id,
                exc_info=True,
            )

    @staticmethod
    async def _upsert_embeddings(
        conn: psycopg.AsyncConnection[typing.Any],
        node_label: str,
        node_id: str,
        attribute: str,
        model_name: str,
        chunks: list[str],
        vectors: list[list[float]],
    ) -> None:
        """Upsert embedding rows for a node's attribute."""
        query = (
            'INSERT INTO public.embeddings'
            '       (node_label, node_id, attribute,'
            '        chunk_index, model_name,'
            '        chunk_text, embedding)'
            ' VALUES (%(label)s, %(node_id)s,'
            '         %(attr)s, %(idx)s,'
            '         %(model)s, %(text)s,'
            '         %(vec)s)'
            ' ON CONFLICT (node_label, node_id,'
            '              attribute, chunk_index,'
            '              model_name)'
            ' DO UPDATE SET chunk_text = EXCLUDED.chunk_text,'
            '               embedding = EXCLUDED.embedding'
        )
        params_list = [
            {
                'label': node_label,
                'node_id': node_id,
                'attr': attribute,
                'idx': idx,
                'model': model_name,
                'text': text,
                'vec': vec,
            }
            for idx, (text, vec) in enumerate(
                zip(chunks, vectors, strict=True),
            )
        ]
        async with conn.cursor() as cur:
            await cur.executemany(query, params_list)

    @staticmethod
    async def _delete_embeddings_where(
        conn: psycopg.AsyncConnection[typing.Any],
        *,
        node_label: str,
        node_id: str,
        attribute: str | None = None,
        model_name: str | None = None,
        min_chunk_index: int | None = None,
    ) -> None:
        """Delete embedding rows matching the given filters.

        ``node_label`` and ``node_id`` are always required.  The
        remaining keyword arguments narrow the match:

        * ``attribute`` — restrict to one attribute.
        * ``model_name`` — restrict to one embedding model.
        * ``min_chunk_index`` — delete chunks with
          ``chunk_index >= min_chunk_index`` (used to prune
          stale trailing chunks after a re-embed).

        """
        conditions: list[sql.Composable] = [
            sql.SQL('node_label = {}').format(
                sql.Placeholder('node_label'),
            ),
            sql.SQL('node_id = {}').format(
                sql.Placeholder('node_id'),
            ),
        ]
        params: dict[str, typing.Any] = {
            'node_label': node_label,
            'node_id': node_id,
        }
        if attribute is not None:
            conditions.append(
                sql.SQL('attribute = {}').format(
                    sql.Placeholder('attribute'),
                ),
            )
            params['attribute'] = attribute
        if model_name is not None:
            conditions.append(
                sql.SQL('model_name = {}').format(
                    sql.Placeholder('model_name'),
                ),
            )
            params['model_name'] = model_name
        if min_chunk_index is not None:
            conditions.append(
                sql.SQL('chunk_index >= {}').format(
                    sql.Placeholder('min_chunk_index'),
                ),
            )
            params['min_chunk_index'] = min_chunk_index
        query = sql.SQL(
            'DELETE FROM public.embeddings WHERE {where}',
        ).format(where=sql.SQL(' AND ').join(conditions))
        await conn.execute(query, params)

    # ----------------------------------------------------------
    # Cypher execution
    # ----------------------------------------------------------

    async def _execute_batch(
        self,
        statements: list[cypher.Statement],
    ) -> None:
        """Execute multiple statements in a single transaction.

        Ensures atomicity so that partial writes do not leave
        the graph in an inconsistent state.  The pool's
        ``configure`` sets autocommit to True; psycopg's
        ``conn.transaction()`` context manager temporarily
        suspends autocommit for the block and restores it on
        exit, committing on success and rolling back on
        exception.  Using the context manager means a rollback
        failure does not mask the original exception the way
        a manual ``try/except`` calling ``rollback()`` would.

        """
        if not self.opened:
            raise RuntimeError('Graph pool is not open')
        async with self.pool.connection() as conn:
            async with conn.transaction():
                for stmt in statements:
                    await self._execute_on(
                        conn,
                        stmt.cypher,
                        stmt.params,
                    )

    @staticmethod
    def _cypher_param(value: typing.Any) -> sql.Composable:
        """Convert a Python value to a Cypher-safe SQL fragment.

        Parameters end up inside a ``$$``-quoted Cypher string,
        so they need Cypher escaping, not PostgreSQL escaping.
        ``sql.Literal`` doubles single quotes (``''``) which
        Cypher does not understand; Cypher uses ``\\'``.

        """
        if isinstance(value, sql.Composable):
            return value
        if isinstance(value, list):
            return sql.SQL(json.dumps(value))
        if isinstance(value, dict):
            value = json.dumps(value)
        if isinstance(value, str):
            escaped = value.replace('\\', '\\\\').replace("'", "\\'")
            return sql.SQL("'" + escaped + "'")
        if value is None:
            return sql.SQL('null')
        if isinstance(value, bool):
            return sql.SQL('true' if value else 'false')
        return sql.Literal(value)

    def _build_cypher_sql(
        self,
        conn: psycopg.AsyncConnection[typing.Any],
        query_template: str,
        params: dict[str, typing.Any] | None = None,
        columns: list[str] | None = None,
    ) -> sql.Composed:
        """Build the full SQL for an AGE ``cypher()`` call.

        AGE's ``cypher()`` function requires the query as a
        dollar-quoted string constant (``$$...$$``), not a
        single-quoted literal or a ``$1`` placeholder.

        *columns* lists the names used in the ``AS (...)``
        clause.  Each name becomes an ``agtype`` column.
        Defaults to ``['n']`` for single-column returns.

        The rendered Cypher is assembled via ``sql.Composed``
        directly; it is never round-tripped through
        ``sql.SQL(resolved_string)``.  That round-trip used
        to re-interpret literal ``{`` / ``}`` in user data as
        placeholders, raising ``IndexError`` at format time.

        """
        columns = columns or ['n']
        col_def = sql.SQL(', ').join(
            sql.SQL('{c} agtype').format(
                c=sql.Identifier(c),
            )
            for c in columns
        )
        literal_params = {
            k: self._cypher_param(v) for k, v in (params or {}).items()
        }
        query = sql.SQL(query_template).format(
            **literal_params,
        )
        # Render once to pick a dollar-quote tag that cannot
        # appear in the Cypher body, then reuse the already
        # composed ``query`` directly.
        tag = _dollar_quote_tag(query.as_string(conn))
        return sql.Composed(
            [
                sql.SQL('SELECT * FROM cypher('),
                sql.Literal(self.settings.graph_name),
                sql.SQL(', '),
                sql.SQL(tag),
                query,
                sql.SQL(tag),
                sql.SQL(') AS ('),
                col_def,
                sql.SQL(')'),
            ],
        )

    async def _execute_on(
        self,
        conn: psycopg.AsyncConnection[typing.Any],
        query_template: str,
        params: dict[str, typing.Any] | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, typing.Any]]:
        """Execute a single Cypher query on a connection."""
        cypher_sql = self._build_cypher_sql(
            conn,
            query_template,
            params,
            columns,
        )
        async with conn.cursor(
            row_factory=rows.dict_row,
        ) as cursor:
            await cursor.execute(cypher_sql)
            return await cursor.fetchall()

    async def execute(
        self,
        query_template: str,
        params: dict[str, typing.Any] | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, typing.Any]]:
        """Wrap a Cypher query in SQL and execute it.

        Parameters in *params* are serialized via
        ``_cypher_param()`` using Cypher-compatible escaping
        and interpolated into *query_template* via
        ``sql.SQL.format()``.

        The Cypher query is wrapped in AGE's ``cypher()``
        function.  *columns* defines the ``AS (...)`` clause
        — pass one name per value in the Cypher ``RETURN``
        clause.  Defaults to ``['n']`` for single-column
        returns.

        """
        if not self.opened:
            raise RuntimeError('Graph pool is not open')

        async with self.pool.connection() as conn:
            return await self._execute_on(
                conn,
                query_template,
                params,
                columns,
            )
