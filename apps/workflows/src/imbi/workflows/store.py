"""The engine's reads and writes of ``workflow_runtime`` (ADR 0021).

A claim takes one claimable run with ``FOR UPDATE SKIP LOCKED`` and
writes a lease in the same transaction, as the scheduler does. Every
later write of the claim checks the lease first, so a worker whose
lease expired and was taken over writes nothing.
"""

import contextlib
import datetime
import typing
import uuid
from collections import abc

import psycopg
import psycopg_pool
from psycopg import rows, sql
from psycopg.types import json as pg_json

from imbi.common.workflows import runtime

type Pool = psycopg_pool.AsyncConnectionPool[
    psycopg.AsyncConnection[typing.Any]
]
type Row = dict[str, typing.Any]
type Conn = psycopg.AsyncConnection[typing.Any]

#: A queued run starts when no run with its concurrency key is running
#: and no older run with the key is queued, so runs with one key start
#: in creation order. A run with a cancel request is always claimable,
#: so that it can close.
_CLAIM = """
SELECT r.* FROM workflow_runtime.runs AS r
 WHERE r.status IN ('queued', 'running') AND r.due_at <= NOW()
   AND NOT EXISTS (SELECT 1 FROM workflow_runtime.leases AS l
                    WHERE l.run_id = r.id AND l.expires_at > NOW())
   AND (r.status = 'running' OR r.cancel_requested
        OR r.concurrency_key IS NULL
        OR NOT EXISTS (
          SELECT 1 FROM workflow_runtime.runs AS o
           WHERE o.workflow_id = r.workflow_id
             AND o.concurrency_key = r.concurrency_key
             AND o.id <> r.id
             AND (o.status = 'running'
                  OR (o.status = 'queued'
                      AND (o.created_at, o.id) < (r.created_at, r.id)))))
 ORDER BY r.due_at
 LIMIT 1
   FOR UPDATE OF r SKIP LOCKED
"""


class LeaseLost(Exception):
    """Another worker holds the run now. Drop the claim."""


class Store:
    def __init__(self, pool: Pool, worker_id: str) -> None:
        self.pool = pool
        self.worker_id = worker_id

    async def claim(self, ttl: datetime.timedelta) -> Row | None:
        """Claim the claimable run that is due first."""
        async with (
            self.pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(_CLAIM)
            run = await cur.fetchone()
            if run is None:
                return None
            await cur.execute(
                'INSERT INTO workflow_runtime.leases'
                ' (run_id, worker_id, expires_at) VALUES (%s, %s, %s)'
                ' ON CONFLICT (run_id) DO UPDATE SET'
                ' worker_id = EXCLUDED.worker_id,'
                ' expires_at = EXCLUDED.expires_at',
                (
                    run['id'],
                    self.worker_id,
                    datetime.datetime.now(datetime.UTC) + ttl,
                ),
            )
            return run

    async def release(
        self, run_id: uuid.UUID, due_at: datetime.datetime | None
    ) -> None:
        """Drop the lease. ``due_at`` is when the run is claimable next."""
        async with self.pool.connection() as conn, conn.transaction():
            if due_at is not None:
                await conn.execute(
                    'UPDATE workflow_runtime.runs SET due_at = %s'
                    ' WHERE id = %s',
                    (due_at, run_id),
                )
            await conn.execute(
                'DELETE FROM workflow_runtime.leases'
                ' WHERE run_id = %s AND worker_id = %s',
                (run_id, self.worker_id),
            )

    async def load(self, run: Row) -> tuple[dict[str, Row], Row]:
        """Return the step rows by node id, and the pinned version with
        the workflow's slug and owner team."""
        async with (
            self.pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(
                'SELECT * FROM workflow_runtime.step_runs WHERE run_id = %s',
                (run['id'],),
            )
            steps = {s['node_id']: s for s in await cur.fetchall()}
            await cur.execute(
                'SELECT v.graph, v.settings, w.slug, w.name,'
                ' w.owner_team_id FROM workflows.workflow_versions AS v'
                ' JOIN workflows.workflows AS w ON w.id = v.workflow_id'
                ' WHERE v.workflow_id = %s AND v.version = %s',
                (run['workflow_id'], run['version']),
            )
            version = await cur.fetchone()
        if version is None:
            raise LookupError(
                f'Workflow {run["workflow_id"]} has no version '
                f'{run["version"]}'
            )
        return steps, version

    async def next_due(self) -> datetime.datetime | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT MIN(due_at) FROM workflow_runtime.runs'
                " WHERE status IN ('queued', 'running')"
            )
            row = await cur.fetchone()
            return row[0] if row else None

    @contextlib.asynccontextmanager
    async def write(self, run_id: uuid.UUID) -> abc.AsyncGenerator[Conn]:
        """Open a transaction that holds the run's lease.

        Raises:
            LeaseLost: This worker does not hold the lease any more.

        """
        async with self.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                'SELECT 1 FROM workflow_runtime.leases'
                ' WHERE run_id = %s AND worker_id = %s FOR UPDATE',
                (run_id, self.worker_id),
            )
            if await cur.fetchone() is None:
                raise LeaseLost(str(run_id))
            yield conn


async def update(
    conn: Conn, table: str, where: dict[str, typing.Any], **values: typing.Any
) -> None:
    """``UPDATE workflow_runtime.<table>``. Dicts are written as JSON."""
    await conn.execute(
        sql.SQL('UPDATE {table} SET {values} WHERE {where}').format(
            table=sql.Identifier(runtime.SCHEMA, table),
            values=sql.SQL(', ').join(
                sql.SQL('{} = %s').format(sql.Identifier(k)) for k in values
            ),
            where=sql.SQL(' AND ').join(
                sql.SQL('{} = %s').format(sql.Identifier(k)) for k in where
            ),
        ),
        [_value(v) for v in (*values.values(), *where.values())],
    )


def _value(value: typing.Any) -> typing.Any:
    return pg_json.Jsonb(value) if isinstance(value, dict) else value
