"""Databases for the ETL tests.

Each test makes its own databases on the ``POSTGRES_URL`` server and
drops them after. A fake graph is plain tables with the layout of the
AGE label tables. An AGE graph is a real ``age`` extension graph.
"""

import atexit
import json
import os
import typing
import unittest
import uuid

import psycopg
from psycopg import conninfo, sql

#: The template of the relational schema that ``moon run root:services``
#: builds (plan WP1.4).
RELATIONAL_TEMPLATE = os.environ.get('IMBI_ETL_TEST_TEMPLATE', 'imbi_template')


def url(dbname: str, **options: str) -> str:
    """Return a connection string for *dbname* on the test server."""
    return conninfo.make_conninfo(
        os.environ['POSTGRES_URL'], dbname=dbname, **options
    )


def maintenance_url(dbname: str) -> str:
    """Return a connection string that runs as ``imbi_maintenance``.

    The test server login is a superuser. ``role`` changes the session
    to ``imbi_maintenance``, so the privileges are those of the ETL.

    """
    return url(dbname, options='-c role=imbi_maintenance')


async def _admin() -> psycopg.AsyncConnection[typing.Any]:
    return await psycopg.AsyncConnection.connect(
        url('postgres'), autocommit=True
    )


async def database_exists(name: str) -> bool:
    async with await _admin() as conn:
        cursor = await conn.execute(
            'SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)',
            (name,),
        )
        row = await cursor.fetchone()
        return bool(row and row[0])


async def create_database(prefix: str, template: str | None = None) -> str:
    """Create a database with the ``age`` extension and return its name.

    With AGE 1.8.0 in ``shared_preload_libraries``, a ``TRUNCATE`` fails
    with 'schema "ag_catalog" does not exist' in a database that does
    not have the extension. At the cutover, the target database has it
    (the graph is in the same database), so the tests have it too.

    """
    name = f'etl_{prefix}_{os.getpid()}_{uuid.uuid4().hex[:8]}'
    statement = sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name))
    if template is not None:
        statement += sql.SQL(' TEMPLATE {}').format(sql.Identifier(template))
    async with await _admin() as conn:
        await conn.execute(statement)
    async with await psycopg.AsyncConnection.connect(
        url(name), autocommit=True
    ) as conn:
        await conn.execute('CREATE EXTENSION IF NOT EXISTS age')
    return name


async def drop_database(name: str) -> None:
    async with await _admin() as conn:
        await conn.execute(
            sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(
                sql.Identifier(name)
            )
        )


_SCRATCH: list[str] = []


async def scratch_database() -> str:
    """Return one database for this test process, and make it once.

    A ``DROP DATABASE`` waits for a WAL flush, which takes seconds on
    some machines, so the tests share one database and reset its
    schemas (:func:`reset`). It is dropped when the process exits.

    """
    if not _SCRATCH:
        _SCRATCH.append(await create_database('scratch'))
        atexit.register(_drop_scratch, _SCRATCH[0])
    return _SCRATCH[0]


def _drop_scratch(name: str) -> None:
    with psycopg.connect(url('postgres'), autocommit=True) as conn:
        conn.execute(
            sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(
                sql.Identifier(name)
            )
        )


async def reset(
    conn: psycopg.AsyncConnection[typing.Any], *schemas: str
) -> None:
    """Drop *schemas* and the AGE graphs, and make ``public`` empty."""
    await conn.execute(
        'SELECT ag_catalog.drop_graph(name, true) FROM ag_catalog.ag_graph'
        if await _has_age(conn)
        else 'SELECT 1'
    )
    for schema in (*schemas, 'public'):
        await conn.execute(
            sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(
                sql.Identifier(schema)
            )
        )
    await conn.execute('CREATE SCHEMA public')
    await conn.commit()


async def _has_age(conn: psycopg.AsyncConnection[typing.Any]) -> bool:
    cursor = await conn.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'age')"
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def relational_database() -> str:
    """Create a database from the relational template, or skip.

    The template exists after ``moon run root:services`` (WP1.4). The
    caller drops the database.

    """
    if not await database_exists(RELATIONAL_TEMPLATE):
        message = (
            f'No {RELATIONAL_TEMPLATE} database: run moon run root:services'
        )
        if os.environ.get('CI'):
            raise AssertionError(message)
        raise unittest.SkipTest(message)
    return await create_database('target', RELATIONAL_TEMPLATE)


async def fake_graph(
    conn: psycopg.AsyncConnection[typing.Any],
    graph: str,
    vertices: dict[str, list[dict[str, typing.Any]]],
    edges: dict[str, list[tuple[str, str, str, str]]] | None = None,
) -> None:
    """Create a fake graph: one plain table per label and edge type.

    *vertices* gives the properties of each vertex, by label. *edges*
    gives ``(start_label, start_ref, end_label, end_ref)`` by edge type.
    A ref is the ``id`` property, or for a vertex with no ``id`` (E36)
    its ``_ref`` key, which is not stored.

    """
    await conn.execute(
        sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(graph))
    )
    graph_ids: dict[tuple[str, str], int] = {}
    for label, rows in vertices.items():
        await conn.execute(
            sql.SQL(
                'CREATE TABLE {} (id bigint PRIMARY KEY, properties text)'
            ).format(sql.Identifier(graph, label))
        )
        for row in rows:
            props = {k: v for k, v in row.items() if k != '_ref'}
            graph_id = len(graph_ids) + 1
            graph_ids[(label, str(row.get('_ref', row.get('id'))))] = graph_id
            await conn.execute(
                sql.SQL('INSERT INTO {} VALUES (%s, %s)').format(
                    sql.Identifier(graph, label)
                ),
                (graph_id, json.dumps(props)),
            )
    for edge_type, rows in (edges or {}).items():
        await conn.execute(
            sql.SQL(
                'CREATE TABLE {} (id bigint PRIMARY KEY,'
                ' start_id bigint, end_id bigint, properties text)'
            ).format(sql.Identifier(graph, edge_type))
        )
        for number, (start_label, start, end_label, end) in enumerate(rows):
            await conn.execute(
                sql.SQL('INSERT INTO {} VALUES (%s, %s, %s, %s)').format(
                    sql.Identifier(graph, edge_type)
                ),
                (
                    number + 1,
                    graph_ids[(start_label, start)],
                    graph_ids[(end_label, end)],
                    '{}',
                ),
            )
    await conn.commit()


async def age_graph(
    conn: psycopg.AsyncConnection[typing.Any], graph: str, *cypher: str
) -> None:
    """Create an AGE graph and run each *cypher* statement in it."""
    await conn.execute('CREATE EXTENSION IF NOT EXISTS age')
    await conn.execute("LOAD 'age'")
    await conn.execute('SET search_path = ag_catalog, "$user", public')
    await conn.execute('SELECT create_graph(%s)', (graph,))
    for statement in cypher:
        await conn.execute(
            sql.SQL('SELECT * FROM cypher(')
            + sql.Literal(graph)
            + sql.SQL(', $$' + statement + '$$) AS (v agtype)')
        )
    await conn.commit()
