"""Base class for the hand-written SQL repositories.

Rule: never format a value into SQL text. Every value goes in as a
bind parameter (``%s`` or ``%(name)s``). An identifier that the code
chooses at run time, such as a sort column from an allow list, goes in
as ``psycopg.sql.Identifier``, and the statement is built with
``psycopg.sql.SQL(...).format(...)``. The query argument of the methods
below is a ``LiteralString`` or a ``psycopg.sql`` composable, so a type
checker rejects an f-string or a ``str.format`` result.

Row-level security protects against a query that omits the
organization condition. It does not protect against SQL injection:
injected SQL can call ``set_config`` itself.

There is no ORM and no generic SQL generator (implementation plan
D15). Each domain writes its own statements.

"""

import typing

import pydantic
from psycopg import abc as psycopg_abc
from psycopg import sql

from imbi.common import db
from imbi.common.db import rows

type Query = typing.LiteralString | sql.SQL | sql.Composed
type Params = psycopg_abc.Params | None


class Repository:
    """Run statements in one :class:`imbi.common.db.Transaction`.

    A subclass is one domain's repository. Its methods call
    :meth:`_one`, :meth:`_many`, and :meth:`_execute`, and the caller
    owns the transaction:

    .. code-block:: python

        async with db.transaction(organization_id, principal_id) as tx:
            tag = await TagRepository(tx).create(...)
            await tx.commit()

    """

    def __init__(self, transaction: db.Transaction) -> None:
        self._transaction = transaction

    async def _one[ModelT: pydantic.BaseModel](
        self,
        model_cls: type[ModelT],
        query: Query,
        params: Params = None,
    ) -> ModelT | None:
        """Return the first row as *model_cls*, or ``None``."""
        cursor = await self._transaction.connection.execute(query, params)
        row = await cursor.fetchone()
        return None if row is None else rows.row_to_model(model_cls, row)

    async def _many[ModelT: pydantic.BaseModel](
        self,
        model_cls: type[ModelT],
        query: Query,
        params: Params = None,
    ) -> list[ModelT]:
        """Return every row as *model_cls*."""
        cursor = await self._transaction.connection.execute(query, params)
        return [
            rows.row_to_model(model_cls, row)
            for row in await cursor.fetchall()
        ]

    async def _execute(self, query: Query, params: Params = None) -> int:
        """Run a statement and return the number of rows it affected."""
        cursor = await self._transaction.connection.execute(query, params)
        return cursor.rowcount
