"""Give each pytest-xdist worker its own Postgres database.

Tests share global graph nodes (for example ``Permission``) and global
rows, so workers that share one database collide. Each worker uses
``<database>_<worker>`` instead (``imbi_gw0``, ``imbi_gw1``, ...). The
application code creates the schema in an empty database, as it does
in production.

ClickHouse stays shared: its DDL names the ``imbi`` database, and the
tests scope their rows with unique ids.
"""

import contextlib
import os
import urllib.parse

import psycopg
from psycopg import sql


def pytest_configure() -> None:
    worker = os.environ.get('PYTEST_XDIST_WORKER')
    url = os.environ.get('POSTGRES_URL')
    if not worker or not url:
        return
    parts = urllib.parse.urlsplit(url)
    name = f'{parts.path.lstrip("/")}_{worker}'
    with (
        psycopg.connect(url, autocommit=True) as conn,
        contextlib.suppress(psycopg.errors.DuplicateDatabase),
    ):
        conn.execute(
            sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name))
        )
    os.environ['POSTGRES_URL'] = parts._replace(path=f'/{name}').geturl()
