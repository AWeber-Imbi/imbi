"""Task repository.

The interesting method is :meth:`Tasks.claim_due`. Single firing across
replicas is a property of one statement — ``FOR UPDATE SKIP LOCKED`` — rather
than of a distributed lock: two replicas running it concurrently receive
disjoint task sets, and the claiming transaction advances ``next_run_at``
before committing, so a firing is consumed exactly once. See ADR 0001.
"""

import datetime
import logging
import typing
import uuid
from collections import abc

import psycopg
import psycopg_pool
from psycopg import rows, sql
from psycopg.types import json as pg_json

from imbi.scheduler import models, settings

LOGGER = logging.getLogger(__name__)

#: Channel the engine listens on so a task mutation wakes it immediately.
NOTIFY_CHANNEL = 'scheduler_tasks'

#: Columns in the order the model reads them back.
COLUMNS = (
    'id',
    'slug',
    'name',
    'description',
    'organization',
    'enabled',
    'kind',
    'trigger',
    'timezone',
    'identity',
    'target',
    'execution',
    'tags',
    'created_by',
    'created_at',
    'updated_at',
    'last_run_at',
    'next_run_at',
    'consecutive_skips',
    'consecutive_no_effect',
)

#: Columns holding JSON documents rather than scalars.
_JSON_COLUMNS = frozenset({'trigger', 'identity', 'target', 'execution'})

DEFAULT_CLAIM_LIMIT = 100


class Tasks:
    """Repository over ``<schema>.tasks``."""

    def __init__(
        self,
        pool: psycopg_pool.AsyncConnectionPool[
            psycopg.AsyncConnection[typing.Any]
        ],
        schema: str | None = None,
    ) -> None:
        self._pool = pool
        self._schema = schema or settings.Scheduler().schema_name

    @property
    def _table(self) -> sql.Identifier:
        return sql.Identifier(self._schema, 'tasks')

    def _columns(self) -> sql.Composed:
        return sql.SQL(', ').join(sql.Identifier(col) for col in COLUMNS)

    async def create(self, task: models.Task) -> models.Task:
        """Insert `task`, returning it as stored."""
        statement = sql.SQL(
            'INSERT INTO {table} ({columns}) VALUES ({values})'
            ' RETURNING {columns}'
        ).format(
            table=self._table,
            columns=self._columns(),
            values=sql.SQL(', ').join(sql.Placeholder() * len(COLUMNS)),
        )
        async with self._pool.connection() as conn:
            row = await self._fetch_one(conn, statement, _as_params(task))
            await self._notify(conn)
        if row is None:  # pragma: no cover - RETURNING always yields a row
            raise RuntimeError('insert returned no row')
        return row

    async def get(self, slug: str) -> models.Task | None:
        """Return the task with `slug`, if it exists."""
        statement = sql.SQL(
            'SELECT {columns} FROM {table} WHERE slug = %s'
        ).format(columns=self._columns(), table=self._table)
        async with self._pool.connection() as conn:
            return await self._fetch_one(conn, statement, (slug,))

    async def get_by_id(self, task_id: uuid.UUID) -> models.Task | None:
        """Return the task with `task_id`, if it exists."""
        statement = sql.SQL(
            'SELECT {columns} FROM {table} WHERE id = %s'
        ).format(columns=self._columns(), table=self._table)
        async with self._pool.connection() as conn:
            return await self._fetch_one(conn, statement, (task_id,))

    async def search(
        self,
        *,
        organization: str | None = None,
        kind: str | None = None,
        enabled: bool | None = None,
        tag: str | None = None,
    ) -> list[models.Task]:
        """Return tasks matching every filter supplied."""
        conditions: list[sql.Composable] = []
        params: list[typing.Any] = []
        for column, value in (
            ('organization', organization),
            ('kind', kind),
            ('enabled', enabled),
        ):
            if value is not None:
                conditions.append(
                    sql.SQL('{col} = %s').format(col=sql.Identifier(column))
                )
                params.append(value)
        if tag is not None:
            conditions.append(sql.SQL('%s = ANY(tags)'))
            params.append(tag)
        where = (
            sql.SQL(' WHERE ') + sql.SQL(' AND ').join(conditions)
            if conditions
            else sql.SQL('')
        )
        statement = (
            sql.SQL('SELECT {columns} FROM {table}').format(
                columns=self._columns(), table=self._table
            )
            + where
            + sql.SQL(' ORDER BY slug')
        )
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(statement, params)
            found = await cursor.fetchall()
        return [_as_task(row) for row in found]

    async def update(self, task: models.Task) -> models.Task | None:
        """Replace the stored task with `task`, refreshing `updated_at`."""
        assignments = sql.SQL(', ').join(
            sql.SQL('{col} = %s').format(col=sql.Identifier(col))
            for col in COLUMNS
            if col != 'id'
        )
        statement = sql.SQL(
            'UPDATE {table} SET {assignments} WHERE id = %s'
            ' RETURNING {columns}'
        ).format(
            table=self._table,
            assignments=assignments,
            columns=self._columns(),
        )
        updated = task.model_copy(
            update={'updated_at': datetime.datetime.now(datetime.UTC)}
        )
        params = [*_as_params(updated)[1:], updated.id]
        async with self._pool.connection() as conn:
            row = await self._fetch_one(conn, statement, params)
            await self._notify(conn)
        return row

    async def delete(self, slug: str) -> bool:
        """Delete the task with `slug`, reporting whether it existed."""
        statement = sql.SQL('DELETE FROM {table} WHERE slug = %s').format(
            table=self._table
        )
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(statement, (slug,))
                deleted = cursor.rowcount
            await self._notify(conn)
        return deleted > 0

    async def claim_due(
        self,
        now: datetime.datetime,
        limit: int = DEFAULT_CLAIM_LIMIT,
    ) -> list[models.Task]:
        """Claim every task due at `now` and advance its schedule.

        Claiming and advancing happen in one transaction, so the returned
        tasks are this process's alone and no other replica will fire the
        same due timestamp. Execution happens after the transaction commits;
        a slow target must never hold a row lock.
        """
        statement = sql.SQL(
            'SELECT {columns} FROM {table}'
            ' WHERE enabled AND next_run_at IS NOT NULL AND next_run_at <= %s'
            ' ORDER BY next_run_at'
            ' LIMIT %s'
            ' FOR UPDATE SKIP LOCKED'
        ).format(columns=self._columns(), table=self._table)
        claimed: list[models.Task] = []
        async with (
            self._pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(statement, (now, limit))
            for row in await cursor.fetchall():
                task = _as_task(row)
                claimed.append(task)
                await self._advance(cursor, task, now)
        return claimed

    async def _advance(
        self,
        cursor: psycopg.AsyncCursor[typing.Any],
        task: models.Task,
        now: datetime.datetime,
    ) -> None:
        """Record the firing and compute the following one."""
        following = task.next_fire_time(now)
        await cursor.execute(
            sql.SQL(
                'UPDATE {table} SET last_run_at = %s, next_run_at = %s'
                ' WHERE id = %s'
            ).format(table=self._table),
            (now, following, task.id),
        )

    async def reschedule(self, task: models.Task) -> datetime.datetime | None:
        """Recompute and store `task`'s next firing from now."""
        following = task.next_fire_time(datetime.datetime.now(datetime.UTC))
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    sql.SQL(
                        'UPDATE {table} SET next_run_at = %s WHERE id = %s'
                    ).format(table=self._table),
                    (following, task.id),
                )
            await self._notify(conn)
        return following

    async def set_enabled(
        self, slug: str, *, enabled: bool
    ) -> models.Task | None:
        """Enable or disable a task without deleting it."""
        statement = sql.SQL(
            'UPDATE {table} SET enabled = %s, updated_at = %s'
            ' WHERE slug = %s RETURNING {columns}'
        ).format(table=self._table, columns=self._columns())
        now = datetime.datetime.now(datetime.UTC)
        async with self._pool.connection() as conn:
            row = await self._fetch_one(conn, statement, (enabled, now, slug))
            await self._notify(conn)
        return row

    async def record_outcome(
        self,
        task_id: uuid.UUID,
        *,
        skipped: bool = False,
        no_effect: bool = False,
    ) -> None:
        """Update the consecutive-outcome counters for a run.

        A counter resets on any other outcome, so only an unbroken streak
        trips the limits that disable a task or notify its owner.
        """
        statement = sql.SQL(
            'UPDATE {table} SET consecutive_skips = {skips},'
            ' consecutive_no_effect = {no_effect} WHERE id = %s'
        ).format(
            table=self._table,
            skips=(
                sql.SQL('consecutive_skips + 1') if skipped else sql.SQL('0')
            ),
            no_effect=(
                sql.SQL('consecutive_no_effect + 1')
                if no_effect
                else sql.SQL('0')
            ),
        )
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cursor,
        ):
            await cursor.execute(statement, (task_id,))

    async def next_due_at(self) -> datetime.datetime | None:
        """Return when the soonest enabled task is due, if any."""
        statement = sql.SQL(
            'SELECT MIN(next_run_at) AS due FROM {table} WHERE enabled'
        ).format(table=self._table)
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(statement)
            row = await cursor.fetchone()
        if row is None:
            return None
        due: datetime.datetime | None = row['due']
        return due

    async def _fetch_one(
        self,
        conn: psycopg.AsyncConnection[typing.Any],
        statement: sql.SQL | sql.Composed,
        params: 'abc.Sequence[typing.Any]',
    ) -> models.Task | None:
        async with conn.cursor(row_factory=rows.dict_row) as cursor:
            await cursor.execute(statement, params)
            row = await cursor.fetchone()
        return _as_task(row) if row is not None else None

    async def _notify(self, conn: psycopg.AsyncConnection[typing.Any]) -> None:
        """Wake any listening engine so a change applies immediately."""
        await conn.execute(
            sql.SQL('NOTIFY {channel}').format(
                channel=sql.Identifier(NOTIFY_CHANNEL)
            )
        )


def _as_task(row: dict[str, typing.Any]) -> models.Task:
    """Build a task from a database row."""
    return models.Task.model_validate(row)


def _as_params(task: models.Task) -> list[typing.Any]:
    """Return `task` as positional parameters in `COLUMNS` order.

    Scalars are passed as native Python objects (``uuid.UUID``,
    ``datetime``, ``list[str]``) so psycopg adapts them to the column type;
    JSON documents come from ``model_dump(mode='json')`` because they must be
    serializable all the way down.
    """
    documents = task.model_dump(mode='json')
    params: list[typing.Any] = []
    for column in COLUMNS:
        if column in _JSON_COLUMNS:
            value = documents[column]
            params.append(pg_json.Jsonb(value) if value is not None else None)
        else:
            params.append(getattr(task, column))
    return params
