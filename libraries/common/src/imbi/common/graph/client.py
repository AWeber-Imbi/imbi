"""
Apache AGE Database Interface

"""

import dataclasses
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


def _embeddable_fields(
    node: models.Node,
) -> list[tuple[str, str | None, models.Embeddable]]:
    """Return ``(name, value, spec)`` for embeddable fields.

    Fields whose current value is ``None`` are included with
    a ``None`` value so callers can clean up stale embeddings.

    """
    result: list[tuple[str, str | None, models.Embeddable]] = []
    for name, info in type(node).model_fields.items():
        for md in info.metadata:
            if isinstance(md, models.Embeddable):
                value = getattr(node, name)
                result.append(
                    (
                        name,
                        str(value) if value is not None else None,
                        md,
                    )
                )
                break
    return result


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
    for name, info in node_type.model_fields.items():
        for md in info.metadata:
            if isinstance(md, models.Edge):
                props.pop(name, None)
                break
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
                await self._delete_embeddings(
                    conn,
                    type(node).__name__,
                    node.id,
                )

    async def match(
        self,
        node_type: type[ModelT],
        params: dict[str, typing.Any] | None = None,
        order_by: str | None = None,
    ) -> list[ModelT]:
        """Match nodes and return model instances.

        Uses ``model_construct`` so that missing edge fields
        (stored as separate graph relationships, never included
        in vertex data) do not trigger validation errors.

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
                    _strip_edge_fields(node_type, props)
                    try:
                        results.append(
                            node_type.model_validate(props),
                        )
                    except pydantic.ValidationError:
                        results.append(
                            node_type.model_construct(
                                **props,
                            ),
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
            '(embedding::vector({dims})) <=> {vec}',
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
                    _strip_edge_fields(node_type, props)
                    node = node_type.model_construct(
                        **props,
                    )
                    nid = props.get('id')
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
                        await self._delete_attr_embeddings(
                            conn,
                            node_label,
                            node.id,
                            attr,
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
                    await self._delete_orphan_chunks(
                        conn,
                        node_label,
                        node.id,
                        attr,
                        spec.model_name,
                        len(chunks),
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
    async def _delete_orphan_chunks(
        conn: psycopg.AsyncConnection[typing.Any],
        node_label: str,
        node_id: str,
        attribute: str,
        model_name: str,
        chunk_count: int,
    ) -> None:
        """Delete stale chunks with index >= chunk_count."""
        await conn.execute(
            'DELETE FROM public.embeddings'
            ' WHERE node_label = %s'
            '   AND node_id = %s'
            '   AND attribute = %s'
            '   AND model_name = %s'
            '   AND chunk_index >= %s',
            (
                node_label,
                node_id,
                attribute,
                model_name,
                chunk_count,
            ),
        )

    @staticmethod
    async def _delete_attr_embeddings(
        conn: psycopg.AsyncConnection[typing.Any],
        node_label: str,
        node_id: str,
        attribute: str,
    ) -> None:
        """Delete embeddings for a single attribute."""
        await conn.execute(
            'DELETE FROM public.embeddings'
            ' WHERE node_label = %s'
            '   AND node_id = %s'
            '   AND attribute = %s',
            (node_label, node_id, attribute),
        )

    @staticmethod
    async def _delete_embeddings(
        conn: psycopg.AsyncConnection[typing.Any],
        node_label: str,
        node_id: str,
    ) -> None:
        """Delete all embeddings for a node."""
        await conn.execute(
            'DELETE FROM public.embeddings'
            ' WHERE node_label = %s AND node_id = %s',
            (node_label, node_id),
        )

    # ----------------------------------------------------------
    # Cypher execution
    # ----------------------------------------------------------

    async def _execute_batch(
        self,
        statements: list[cypher.Statement],
    ) -> None:
        """Execute multiple statements in a single transaction.

        Ensures atomicity so that partial writes do not leave
        the graph in an inconsistent state.

        """
        if not self.opened:
            raise RuntimeError('Graph pool is not open')
        async with self.pool.connection() as conn:
            await conn.set_autocommit(False)
            try:
                for stmt in statements:
                    await self._execute_on(
                        conn,
                        stmt.cypher,
                        stmt.params,
                    )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
            finally:
                await conn.set_autocommit(True)

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

        """
        columns = columns or ['n']
        col_def = sql.SQL(', ').join(
            sql.SQL('{c} agtype').format(
                c=sql.Identifier(c),
            )
            for c in columns
        )
        literal_params = {
            k: (v if isinstance(v, sql.Composable) else sql.Literal(v))
            for k, v in (params or {}).items()
        }
        query = sql.SQL(query_template).format(
            **literal_params,
        )
        resolved = query.as_string(conn)
        return sql.SQL(
            'SELECT * FROM cypher({graph_name}, $${query}$$) AS ({col_def})',
        ).format(
            graph_name=sql.Literal(self.settings.graph_name),
            query=sql.SQL(resolved),
            col_def=col_def,
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

        Parameters in *params* are bound as ``sql.Literal``
        values into the *query_template* via
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
