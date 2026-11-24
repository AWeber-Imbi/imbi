"""Give each pytest-xdist worker its own Postgres database.

Tests share global graph nodes (for example ``Permission``) and global
rows, so workers that share one database collide. Each worker uses
``<database>_<worker>`` instead (``imbi_gw0``, ``imbi_gw1``, ...). Each
run drops and creates that database again, so no state stays from an
earlier run. The graph initializer then runs, as it does when a
service starts, except that it skips pg_cron (see ``_skip_pg_cron``).

ClickHouse stays shared: its DDL names the ``imbi`` database, and the
tests scope their rows with unique ids.
"""

import asyncio
import os
import typing
import urllib.parse

import psycopg
import pytest
from psycopg import sql


@pytest.hookimpl(trylast=True)
def pytest_sessionstart() -> None:
    # After pytest-cov starts in the worker (also at session start),
    # so that it measures the modules that this imports.
    worker = os.environ.get('PYTEST_XDIST_WORKER')
    url = os.environ.get('POSTGRES_URL')
    if not worker or not url:
        return
    parts = urllib.parse.urlsplit(url)
    name = f'{parts.path.lstrip("/")}_{worker}'
    ident = sql.Identifier(name)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(ident)
        )
        conn.execute(sql.SQL('CREATE DATABASE {}').format(ident))
    os.environ['POSTGRES_URL'] = parts._replace(path=f'/{name}').geturl()
    _skip_pg_cron()
    # Some tests (for example the scheduler's) use the graph without
    # creating it, so create it before any test runs.
    from imbi.common.graph import initializer

    asyncio.run(initializer.initialize())


def _skip_pg_cron() -> None:
    """Do not create pg_cron in a worker database.

    pg_cron installs only in the database that ``cron.database_name``
    names (``imbi``), and no test uses it.
    """
    from imbi.common.graph import initializer

    create = initializer._create_extensions

    async def create_extensions(
        cursor: typing.Any, schemata: dict[str, typing.Any]
    ) -> None:
        extensions = [
            ext
            for ext in schemata.get('extensions', [])
            if ext['name'] != 'pg_cron'
        ]
        await create(cursor, {**schemata, 'extensions': extensions})

    initializer._create_extensions = create_extensions


@pytest.fixture(autouse=True)
def _fresh_clickhouse_client() -> None:
    """Give each test its own ClickHouse client.

    The client binds to the event loop that opened it, and each async
    test has its own loop. A client that an earlier test did not close
    is bound to a closed loop, so drop it before each test.
    """
    from imbi.common.clickhouse import client

    client.Clickhouse._instance = None
