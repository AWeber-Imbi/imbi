"""Per-process test databases, copied from two templates.

``moon run root:services`` builds two template databases:

* ``imbi_graph_template``: the graph setup of the AGE-era code (AGE, the
  graph, and the legacy ``public.embeddings``).
* ``imbi_template``: the relational schema of ``schemata/``, with no AGE.

:func:`isolated_database` copies each template into a database for the
test process, points the connection settings at the copies, and drops
the copies when the process exits. Two test processes then do not
share a database. There is no transaction rollback isolation, because
the application has pools and background tasks.

Test code only. The application does not import this module.
"""

import atexit
import dataclasses
import functools
import os
import secrets
import typing
import urllib.parse

import psycopg
from psycopg import sql

GRAPH_TEMPLATE = 'imbi_graph_template'
TEMPLATE = 'imbi_template'

#: The settings that point at the graph database (superuser).
GRAPH_URL = 'POSTGRES_URL'
#: The settings that point at the relational database, as ``imbi_app``
#: and as ``imbi_admin``.
APP_URL = 'DATABASE_URL'
ADMIN_URL = 'ADMIN_DATABASE_URL'
#: The ``imbi_maintenance`` login (BYPASSRLS) to the relational
#: database, for the tests of the ETL and the reconciliation.
MAINTENANCE_URL = 'MAINTENANCE_DATABASE_URL'
#: The superuser connection to the relational database that the test
#: factories use. It bypasses row-level security. Application code
#: never reads it.
FACTORY_URL = 'IMBI_TEST_FACTORY_URL'


@dataclasses.dataclass(frozen=True)
class IsolatedDatabases:
    """The databases of one test process, and their connection URLs."""

    graph: str
    relational: str
    graph_url: str
    app_url: str
    admin_url: str
    maintenance_url: str
    factory_url: str


def _with_database(url: str, database: str) -> str:
    """Return ``url`` with its database name changed to ``database``."""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(parts._replace(path=f'/{database}'))


def _environ(name: str) -> str:
    try:
        return os.environ[name]
    except KeyError:
        raise RuntimeError(
            f'{name} is not set: run `moon run root:services` and load '
            '.env.test (uv run --env-file .env.test ...)'
        ) from None


@functools.cache
def isolated_database() -> IsolatedDatabases:
    """Create the databases of this test process, once for each process.

    The first call creates ``imbi_graph_test_<pid>_<token>`` from
    ``imbi_graph_template`` and ``imbi_test_<pid>_<token>`` from
    ``imbi_template``, sets ``POSTGRES_URL``, ``DATABASE_URL``,
    ``ADMIN_DATABASE_URL``, ``MAINTENANCE_DATABASE_URL``, and
    ``IMBI_TEST_FACTORY_URL`` to them, and registers an exit handler
    that drops them. Later calls return the same result. Settings
    objects read the environment when they are made, so call this
    before the code under test makes one.

    The random token keeps the names unique when processes on two
    hosts (or in two containers) have the same process id and use one
    server. The process keeps one idle session open on each copy until
    it exits, so a copy with no session is a copy that a killed process
    left. ``moon run root:services`` drops those.

    """
    pid = os.getpid()
    suffix = f'{pid}_{secrets.token_hex(3)}'
    graph, relational = f'imbi_graph_test_{suffix}', f'imbi_test_{suffix}'
    superuser = _environ(GRAPH_URL)
    result = IsolatedDatabases(
        graph=graph,
        relational=relational,
        graph_url=_with_database(superuser, graph),
        app_url=_with_database(_environ(APP_URL), relational),
        admin_url=_with_database(_environ(ADMIN_URL), relational),
        maintenance_url=_with_database(_environ(MAINTENANCE_URL), relational),
        factory_url=_with_database(superuser, relational),
    )
    server = _with_database(superuser, 'postgres')
    with psycopg.connect(server, autocommit=True) as conn:
        for database, template in (
            (graph, GRAPH_TEMPLATE),
            (relational, TEMPLATE),
        ):
            try:
                conn.execute(
                    sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
                        sql.Identifier(database), sql.Identifier(template)
                    )
                )
            except psycopg.errors.InvalidCatalogName:
                raise RuntimeError(
                    f'The template database {template} does not exist: '
                    'run `moon run root:services`'
                ) from None
    keepers = [
        psycopg.connect(url) for url in (result.graph_url, result.factory_url)
    ]
    atexit.register(_drop, server, [graph, relational], keepers, pid)
    os.environ[GRAPH_URL] = result.graph_url
    os.environ[APP_URL] = result.app_url
    os.environ[ADMIN_URL] = result.admin_url
    os.environ[MAINTENANCE_URL] = result.maintenance_url
    os.environ[FACTORY_URL] = result.factory_url
    return result


def _drop(
    server: str,
    names: list[str],
    keepers: list[psycopg.Connection[typing.Any]],
    pid: int,
) -> None:
    """Drop the databases at exit, in the process that made them only."""
    if os.getpid() != pid:
        return
    for keeper in keepers:
        keeper.close()
    try:
        with psycopg.connect(server, autocommit=True) as conn:
            for name in names:
                conn.execute(
                    sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(
                        sql.Identifier(name)
                    )
                )
    except psycopg.OperationalError:
        # The server stopped before the tests ended. The next
        # `moon run root:services` drops the databases.
        return
