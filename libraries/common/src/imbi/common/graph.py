"""
Apache AGE Database Interface

"""

import contextlib
import json
import re
import typing
from collections import abc

import fastapi
import psycopg
import psycopg_pool
import pydantic
from psycopg import rows, sql

from imbi_common import cypher, lifespan, models, settings

_AGTYPE_SUFFIX = re.compile(r'::(vertex|edge|path|numeric)$')

ModelT = typing.TypeVar('ModelT', bound=pydantic.BaseModel)


def _fill_edge_defaults(
    node_type: type[pydantic.BaseModel],
    props: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Supply ``None`` for missing relationship fields.

    AGE nodes only store scalar properties; edge fields are
    separate graph relationships never included in the vertex
    data.  Without defaults, ``model_validate`` would raise
    ``ValidationError`` for any required edge field.

    """
    for name, info in node_type.model_fields.items():
        if name in props:
            continue
        for md in info.metadata:
            if isinstance(md, models.Edge):
                props[name] = None
                break
    return props


def _parse_agtype(value: typing.Any) -> typing.Any:
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


class Graph:
    """Wrapper around the PostgreSQL connection pool for Apache AGE queries."""

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
        """Set up each pool connection for AGE queries.

        AGE is loaded via ``shared_preload_libraries`` in
        ``postgresql.conf``, so ``LOAD 'age'`` is not needed.
        Only the search path must include ``ag_catalog``.

        """
        await conn.set_autocommit(True)
        await conn.execute('SET search_path = ag_catalog, "$user", public')

    async def open(self) -> None:
        """Open the connection pool."""
        await self.pool.open()
        self.opened = True

    async def close(self) -> None:
        """Close the connection pool."""
        await self.pool.close()
        self.opened = False

    async def create(self, node: models.Node) -> models.Node:
        """Create a node and its relationships in the graph."""
        await self._execute_batch(cypher.create(node))
        return node

    async def delete(self, node: models.Node) -> None:
        """Delete a node and its relationships from the graph."""
        stmt = cypher.delete(node)
        await self.execute(stmt.cypher, stmt.params)

    async def match(
        self,
        node_type: type[ModelT],
        params: dict[str, typing.Any] | None = None,
        order_by: str | None = None,
    ) -> list[ModelT]:
        """Match nodes and return validated model instances."""
        stmt = cypher.match(node_type, params, order_by)
        raw_rows = await self.execute(stmt.cypher, stmt.params)
        results: list[ModelT] = []
        for row in raw_rows:
            for value in row.values():
                props = _parse_agtype(value)
                if isinstance(props, dict):
                    _fill_edge_defaults(node_type, props)
                    results.append(
                        node_type.model_validate(props),
                    )
        return results

    async def merge(
        self,
        node: pydantic.BaseModel,
        match_on: list[str] | None = None,
    ) -> pydantic.BaseModel:
        """Upsert a node and its relationships in the graph."""
        await self._execute_batch(cypher.merge(node, match_on))
        return node

    async def _execute_batch(
        self,
        statements: list[cypher.Statement],
    ) -> None:
        """Execute multiple statements in a single transaction.

        Ensures atomicity so that partial writes do not leave the
        graph in an inconsistent state.

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
    ) -> sql.Composed:
        """Build the full SQL statement for an AGE cypher() call.

        AGE's ``cypher()`` function requires the query as a
        dollar-quoted string constant (``$$...$$``), not a
        single-quoted literal or a ``$1`` placeholder.

        """
        literal_params = {
            k: (v if isinstance(v, sql.Composable) else sql.Literal(v))
            for k, v in (params or {}).items()
        }
        query = sql.SQL(query_template).format(**literal_params)
        resolved = query.as_string(conn)
        return sql.SQL(
            'SELECT * FROM cypher({graph_name}, $${query}$$) AS (n agtype)',
        ).format(
            graph_name=sql.Literal(self.settings.graph_name),
            query=sql.SQL(resolved),
        )

    async def _execute_on(
        self,
        conn: psycopg.AsyncConnection[typing.Any],
        query_template: str,
        params: dict[str, typing.Any] | None = None,
    ) -> list[dict[str, typing.Any]]:
        """Execute a single Cypher query on an existing connection."""
        cypher_sql = self._build_cypher_sql(
            conn,
            query_template,
            params,
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
    ) -> list[dict[str, typing.Any]]:
        """Wrap a Cypher query in SQL and execute it.

        Parameters in *params* are bound as ``sql.Literal`` values
        into the *query_template* via ``sql.SQL.format()``.

        The Cypher query is wrapped in AGE's ``cypher()`` function
        with the required ``AS (n agtype)`` column definition.

        """
        if not self.opened:
            raise RuntimeError('Graph pool is not open')

        async with self.pool.connection() as conn:
            return await self._execute_on(
                conn,
                query_template,
                params,
            )


@contextlib.asynccontextmanager
async def graph_lifespan() -> abc.AsyncIterator[Graph]:
    graph = Graph()
    await graph.open()
    yield graph
    await graph.close()


async def _inject_graph(
    context: lifespan.InjectLifespan,
) -> abc.AsyncIterator[Graph]:
    yield context.get_state(graph_lifespan)


Pool = typing.Annotated[Graph, fastapi.Depends(_inject_graph)]
