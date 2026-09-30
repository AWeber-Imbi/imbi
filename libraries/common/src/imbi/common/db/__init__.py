"""Relational PostgreSQL access: connection pools and RLS contexts.

Every relational query runs inside :func:`transaction` or
:func:`admin_transaction`. Each one starts a transaction, sets the
row-level security context, and rolls back on exit unless the caller
calls :meth:`Transaction.commit`. There is no autocommit path.

The contexts (``schemata/README.md``, "Row-level security"):

- organization: ``transaction(organization_id, principal_id)``
- principal only: ``transaction(principal_id=...)``
- none: ``transaction()``
- instance admin: ``admin_transaction()``, on the ``imbi_admin`` pool

The schema comes from ``pglifecycle deploy``, never from the
application. :meth:`Database.open` only checks that the schema is
there.

"""

import contextlib
import typing
from collections import abc

import fastapi
import psycopg
import psycopg_pool
from pgvector.psycopg import register_vector_async
from psycopg import pq
from psycopg import rows as psycopg_rows

from imbi.common import lifespan
from imbi.common.db import settings

type Connection = psycopg.AsyncConnection[psycopg_rows.DictRow]

_ADMIN_POOL_MAX_SIZE = 2

_REQUIRED_TABLES = ('organizations', 'tenants')

_SCHEMA_CHECK: typing.LiteralString = (
    'SELECT table_name FROM information_schema.tables'
    " WHERE table_schema = 'public' AND table_name = ANY(%s)"
)

_SET_ORGANIZATION: typing.LiteralString = (
    "SELECT set_config('imbi.organization_id', %s, true)"
)

_SET_PRINCIPAL: typing.LiteralString = (
    "SELECT set_config('imbi.principal_id', %s, true)"
)

_OPEN_STATES = frozenset(
    {pq.TransactionStatus.INTRANS, pq.TransactionStatus.INERROR}
)


class SchemaMissingError(RuntimeError):
    """The database has no relational schema."""


class Transaction:
    """One database transaction and its RLS context.

    Get one from :func:`transaction` or :func:`admin_transaction`, not
    from the constructor. After :meth:`commit`, or after the context
    exits, :attr:`connection` raises: a query after that point would
    run outside the RLS context.

    """

    def __init__(
        self,
        connection: Connection,
        organization_id: str | None,
        principal_id: str | None,
    ) -> None:
        self._connection = connection
        self._finished = False
        self.organization_id = organization_id
        self.principal_id = principal_id

    @property
    def connection(self) -> Connection:
        """The connection of the open transaction."""
        if self._finished:
            raise RuntimeError('The transaction is finished')
        return self._connection

    async def commit(self) -> None:
        """Commit the transaction. The transaction is then finished."""
        await self.connection.commit()
        self._finished = True

    def _finish(self) -> None:
        self._finished = True


async def _configure_connection(conn: Connection) -> None:
    """Register the pgvector types on each new pool connection."""
    await register_vector_async(conn)
    await conn.rollback()


class Database:
    """The application pool (``imbi_app``) and the admin pool."""

    _instance: typing.ClassVar[Database | None] = None

    def __init__(self) -> None:
        self.opened = False
        self.settings = settings.Database()
        self._pool = self._make_pool(
            'imbi_app',
            str(self.settings.database_url),
            self.settings.database_min_pool_size,
            self.settings.database_max_pool_size,
        )
        self._admin_pool = self._make_pool(
            'imbi_admin',
            str(self.settings.admin_database_url),
            0,
            _ADMIN_POOL_MAX_SIZE,
        )

    @staticmethod
    def _make_pool(
        name: str, conninfo: str, min_size: int, max_size: int
    ) -> psycopg_pool.AsyncConnectionPool[Connection]:
        # No reset callback: psycopg_pool rolls back a connection that
        # comes back in a transaction, and logs a warning on
        # ``psycopg.pool``, before a reset callback runs. A callback
        # would also move each return into a worker task.
        return psycopg_pool.AsyncConnectionPool(
            conninfo=conninfo,
            connection_class=psycopg.AsyncConnection[psycopg_rows.DictRow],
            kwargs={'row_factory': psycopg_rows.dict_row},
            min_size=min_size,
            max_size=max_size,
            configure=_configure_connection,
            name=name,
            open=False,
        )

    @classmethod
    def get_instance(cls) -> Database:
        """Return the process-wide instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def open(self) -> None:
        """Check the schema, then open both pools.

        Raises:
            SchemaMissingError: ``tenants`` or ``organizations`` is not
                in the database.

        """
        await self._check_schema()
        await self._pool.open()
        await self._admin_pool.open()
        self.opened = True

    async def close(self) -> None:
        """Close both pools. A later :meth:`get_instance` makes a new one."""
        await self._pool.close()
        await self._admin_pool.close()
        self.opened = False
        if Database._instance is self:
            Database._instance = None

    async def _check_schema(self) -> None:
        """Raise unless the deploy made the tenancy tables.

        It uses a connection of its own, not the pool, because the pool
        configuration needs the ``vector`` type that the deploy makes.

        """
        async with await psycopg.AsyncConnection.connect(
            str(self.settings.database_url)
        ) as conn:
            cursor = await conn.execute(
                _SCHEMA_CHECK, (list(_REQUIRED_TABLES),)
            )
            found = {row[0] for row in await cursor.fetchall()}
        missing = sorted(set(_REQUIRED_TABLES) - found)
        if missing:
            raise SchemaMissingError(
                f'The relational schema is missing (no table '
                f'{", ".join(missing)}). Deploy it with '
                f'`moon run root:schema-apply`.'
            )

    def _require_open(self) -> None:
        # The pools are made with open=False, so a connection request
        # on an unopened pool waits until PoolTimeout.
        if not self.opened:
            raise RuntimeError('The database pools are not open')

    @contextlib.asynccontextmanager
    async def transaction(
        self,
        organization_id: str | None = None,
        principal_id: str | None = None,
    ) -> abc.AsyncGenerator[Transaction]:
        """Start a transaction on the application pool.

        Args:
            organization_id: The organization context. ``None`` for the
                principal-only context and for no context.
            principal_id: The principal of the request, if there is one.

        """
        self._require_open()
        async with self._transaction(
            self._pool, organization_id, principal_id
        ) as tx:
            yield tx

    @contextlib.asynccontextmanager
    async def admin_transaction(self) -> abc.AsyncGenerator[Transaction]:
        """Start a transaction on the admin pool.

        The admin pool takes no organization. The transaction sets the
        organization setting to empty, so a value that a connection kept
        from an earlier transaction has no effect.

        """
        self._require_open()
        async with self._transaction(self._admin_pool, None, None) as tx:
            yield tx

    @staticmethod
    @contextlib.asynccontextmanager
    async def _transaction(
        pool: psycopg_pool.AsyncConnectionPool[Connection],
        organization_id: str | None,
        principal_id: str | None,
    ) -> abc.AsyncGenerator[Transaction]:
        conn = await pool.getconn()
        tx = Transaction(conn, organization_id, principal_id)
        try:
            # Autocommit is off, so psycopg sends BEGIN before the
            # first statement. Each setting is its own statement, and
            # both come before any other query. An empty value is the
            # same as no setting: current_organization_id() is NULLIF
            # of the setting and ''.
            await conn.execute(_SET_ORGANIZATION, (organization_id or '',))
            await conn.execute(_SET_PRINCIPAL, (principal_id or '',))
            yield tx
        finally:
            tx._finish()  # pyright: ignore[reportPrivateUsage]
            try:
                if conn.info.transaction_status in _OPEN_STATES:
                    await conn.rollback()
            finally:
                await pool.putconn(conn)


def transaction(
    organization_id: str | None = None,
    principal_id: str | None = None,
) -> contextlib.AbstractAsyncContextManager[Transaction]:
    """:meth:`Database.transaction` on the process-wide instance."""
    return Database.get_instance().transaction(organization_id, principal_id)


def admin_transaction() -> contextlib.AbstractAsyncContextManager[Transaction]:
    """:meth:`Database.admin_transaction` on the process-wide instance."""
    return Database.get_instance().admin_transaction()


@contextlib.asynccontextmanager
async def database_lifespan() -> abc.AsyncGenerator[Database]:
    """Open the process-wide instance for the life of the app.

    When another app of the process has the instance open already (two
    apps in one test process), this app gets an instance of its own.
    Its pools then belong to the event loop of this app.

    """
    database = Database.get_instance()
    if database.opened:
        database = Database()
    await database.open()
    try:
        yield database
    finally:
        await database.close()


async def _inject_database(context: lifespan.InjectLifespan) -> Database:
    return context.get_state(database_lifespan)


Pool = typing.Annotated[Database, fastapi.Depends(_inject_database)]


__all__ = [
    'Connection',
    'Database',
    'Pool',
    'SchemaMissingError',
    'Transaction',
    'admin_transaction',
    'database_lifespan',
    'transaction',
]
