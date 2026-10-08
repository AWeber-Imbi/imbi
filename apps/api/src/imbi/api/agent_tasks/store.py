"""Postgres repository for agent tasks (ADR 0020).

A change to a task and the event that records it commit in one
transaction. Each write method here does both, so nothing changes a task
without an event.

An event write increments ``tasks.last_seq`` and uses the new value as
the event ``seq``. The ``UPDATE`` locks the task row until the
transaction ends, so concurrent writers to one task get consecutive
numbers and the sequence has no gaps.
"""

import dataclasses
import datetime
import decimal
import typing
import uuid

import psycopg
import psycopg.errors
import psycopg_pool
from psycopg import rows, sql
from psycopg.types import json as pg_json

type Pool = psycopg_pool.AsyncConnectionPool[
    psycopg.AsyncConnection[typing.Any]
]
type Row = dict[str, typing.Any]

SCHEMA = 'agent_runtime'

Status = typing.Literal['queued', 'running', 'blocked', 'paused', 'closed']
Control = typing.Literal['run', 'pause', 'cancel']
ActorKind = typing.Literal['human', 'agent', 'subagent', 'system']
Channel = typing.Literal['web', 'slack', 'mcp', 'api', 'harness']

#: The status of a task with no open session, by control value.
_IDLE_STATUS: dict[Control, Status] = {
    'run': 'queued',
    'pause': 'paused',
    'cancel': 'closed',
}

#: ``outcome_reason`` of a task that a person cancels while no harness
#: session is open.
CANCELLED_WITHOUT_SESSION = 'cancelled_without_session'


class TaskNotFound(LookupError):
    """No task has this short id in the organization."""


class TaskClosed(ValueError):
    """The task is closed. A closed task does not change."""


class CancelPending(ValueError):
    """A cancel waits for the harness; the control cannot change."""


@dataclasses.dataclass(frozen=True)
class Actor:
    """Who caused an event, and through which channel."""

    kind: ActorKind
    id: str | None
    channel: Channel


@dataclasses.dataclass(frozen=True)
class NewTask:
    """The values of a task that the caller sets at creation."""

    organization_id: str
    agent_id: str
    agent_version: int
    prompt_version: int | None
    service_account_id: str
    project_id: str | None
    title: str
    description: str
    origin_kind: str
    origin_id: str
    origin: dict[str, typing.Any]
    idempotency_key: str | None
    owner: str
    budget: decimal.Decimal | None


class TaskStore:
    """Repository over the ``agent_runtime`` schema."""

    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def find_by_idempotency_key(
        self, organization_id: str, origin_kind: str, origin_id: str, key: str
    ) -> Row | None:
        """Return the task that the origin principal made with ``key``."""
        async with self._pool.connection() as conn:
            return await _fetch_one(
                conn,
                'SELECT * FROM agent_runtime.tasks'
                ' WHERE organization_id = %s AND origin_kind = %s'
                ' AND origin_id = %s AND idempotency_key = %s',
                (organization_id, origin_kind, origin_id, key),
            )

    async def create(
        self, task: NewTask, actor: Actor, event_payload: Row
    ) -> tuple[Row, bool]:
        """Insert ``task`` with its short id and ``task.created`` event.

        Return the task and ``True``. When a concurrent request made a
        task with the same idempotency key first, return that task and
        ``False``. The rollback also returns the short id to the counter.
        """
        task_id = uuid.uuid4()
        try:
            async with self._pool.connection() as conn, conn.transaction():
                short_id = await _next_short_id(conn, task.organization_id)
                await conn.execute(
                    'INSERT INTO agent_runtime.tasks (id, organization_id,'
                    ' short_id, agent_id, agent_version, prompt_version,'
                    ' service_account_id, project_id, title, description,'
                    ' origin_kind, origin_id, origin, idempotency_key, owner,'
                    ' budget) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,'
                    ' %s, %s, %s, %s, %s, %s)',
                    (
                        task_id,
                        task.organization_id,
                        short_id,
                        task.agent_id,
                        task.agent_version,
                        task.prompt_version,
                        task.service_account_id,
                        task.project_id,
                        task.title,
                        task.description,
                        task.origin_kind,
                        task.origin_id,
                        pg_json.Jsonb(task.origin),
                        task.idempotency_key,
                        task.owner,
                        task.budget,
                    ),
                )
                await _append_event(
                    conn, task_id, 'task.created', event_payload, actor
                )
                row = await _fetch_task(conn, task_id)
        except psycopg.errors.UniqueViolation as err:
            if (
                err.diag.constraint_name != 'tasks_origin_idempotency_key'
                or task.idempotency_key is None
            ):
                raise
            existing = await self.find_by_idempotency_key(
                task.organization_id,
                task.origin_kind,
                task.origin_id,
                task.idempotency_key,
            )
            if existing is None:  # pragma: no cover - the key just collided
                raise
            return existing, False
        return row, True

    async def get(self, organization_id: str, short_id: str) -> Row | None:
        """Return the task with ``short_id`` in the organization."""
        async with self._pool.connection() as conn:
            return await _fetch_one(
                conn,
                'SELECT * FROM agent_runtime.tasks'
                ' WHERE organization_id = %s AND short_id = %s',
                (organization_id, short_id),
            )

    async def search(
        self,
        organization_id: str,
        *,
        statuses: list[Status] | None = None,
        agent_id: str | None = None,
        owner: str | None = None,
        text: str | None = None,
        text_agent_ids: list[str] | None = None,
        text_project_ids: list[str] | None = None,
        before: tuple[datetime.datetime, uuid.UUID] | None = None,
        limit: int = 50,
    ) -> list[Row]:
        """Return tasks in the organization, newest first.

        ``text`` matches the title or the short id. A task also matches
        when its agent is in ``text_agent_ids`` or its project is in
        ``text_project_ids``; the caller finds those in the graph.
        ``before`` is the ``(created_at, id)`` keyset of the last row of
        the previous page.
        """
        conditions: list[sql.Composable] = [sql.SQL('organization_id = %s')]
        params: list[typing.Any] = [organization_id]
        if statuses:
            conditions.append(sql.SQL('status = ANY(%s)'))
            params.append(list(statuses))
        if agent_id is not None:
            conditions.append(sql.SQL('agent_id = %s'))
            params.append(agent_id)
        if owner is not None:
            conditions.append(sql.SQL('owner = %s'))
            params.append(owner)
        if text:
            pattern = '%' + _escape_like(text) + '%'
            conditions.append(
                sql.SQL(
                    '(title ILIKE %s OR short_id ILIKE %s'
                    ' OR agent_id = ANY(%s) OR project_id = ANY(%s))'
                )
            )
            params += [
                pattern,
                pattern,
                text_agent_ids or [],
                text_project_ids or [],
            ]
        if before is not None:
            conditions.append(sql.SQL('(created_at, id) < (%s, %s)'))
            params += list(before)
        statement = sql.SQL(
            'SELECT * FROM agent_runtime.tasks WHERE {where}'
            ' ORDER BY created_at DESC, id DESC LIMIT %s'
        ).format(where=sql.SQL(' AND ').join(conditions))
        params.append(limit)
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(statement, params)
            return await cursor.fetchall()

    async def events(
        self, task_id: uuid.UUID, after_seq: int, limit: int
    ) -> list[Row]:
        """Return the events of a task after ``after_seq``, by seq."""
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                'SELECT * FROM agent_runtime.events'
                ' WHERE task_id = %s AND seq > %s ORDER BY seq LIMIT %s',
                (task_id, after_seq, limit),
            )
            return await cursor.fetchall()

    async def set_control(
        self,
        organization_id: str,
        short_id: str,
        control: Control,
        actor: Actor,
    ) -> Row:
        """Set the control value of a task and write its events.

        When a harness session is open, only ``control`` changes; the
        harness acts on it at its next turn boundary. When no session is
        open, the status changes too: ``pause`` moves the task to
        ``paused``, ``run`` moves it back to ``queued``, and ``cancel``
        closes it with the outcome ``cancelled_by_human``.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            CancelPending: A cancel waits for the harness.

        """
        async with self._pool.connection() as conn, conn.transaction():
            task = await _lock_task(conn, organization_id, short_id)
            if task['control'] == control:
                return task
            if task['control'] == 'cancel':
                raise CancelPending(short_id)
            await _append_event(
                conn,
                task['id'],
                'control.changed',
                {'from': task['control'], 'to': control, 'actor': actor.id},
                actor,
            )
            changes: Row = {'control': control}
            if not await _session_open(conn, task['id']):
                status = _IDLE_STATUS[control]
                if status != task['status']:
                    changes['status'] = status
                    await _append_event(
                        conn,
                        task['id'],
                        'state.changed',
                        {
                            'from': task['status'],
                            'to': status,
                            'reason': 'control_changed',
                        },
                        actor,
                    )
                if status == 'closed':
                    changes['outcome'] = 'cancelled_by_human'
                    changes['outcome_reason'] = CANCELLED_WITHOUT_SESSION
                    changes['closed_at'] = datetime.datetime.now(datetime.UTC)
                    await _append_event(
                        conn,
                        task['id'],
                        'outcome.set',
                        {
                            'outcome': changes['outcome'],
                            'reason': changes['outcome_reason'],
                        },
                        actor,
                    )
            return await _update_task(conn, task['id'], changes)

    async def set_owner(
        self,
        organization_id: str,
        short_id: str,
        owner: str,
        actor: Actor,
    ) -> Row:
        """Give the task a new owner and write ``owner.changed``.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.

        """
        async with self._pool.connection() as conn, conn.transaction():
            task = await _lock_task(conn, organization_id, short_id)
            if task['owner'] == owner:
                return task
            await _append_event(
                conn,
                task['id'],
                'owner.changed',
                {'from': task['owner'], 'to': owner},
                actor,
            )
            return await _update_task(conn, task['id'], {'owner': owner})


async def _fetch_one(
    conn: psycopg.AsyncConnection[typing.Any],
    query: typing.LiteralString,
    params: tuple[typing.Any, ...],
) -> Row | None:
    async with conn.cursor(row_factory=rows.dict_row) as cursor:
        await cursor.execute(query, params)
        return await cursor.fetchone()


async def _fetch_task(
    conn: psycopg.AsyncConnection[typing.Any], task_id: uuid.UUID
) -> Row:
    row = await _fetch_one(
        conn,
        'SELECT * FROM agent_runtime.tasks WHERE id = %s',
        (task_id,),
    )
    if row is None:  # pragma: no cover - read inside the write transaction
        raise TaskNotFound(str(task_id))
    return row


async def _lock_task(
    conn: psycopg.AsyncConnection[typing.Any],
    organization_id: str,
    short_id: str,
) -> Row:
    """Lock and return an open task, for a change in this transaction."""
    task = await _fetch_one(
        conn,
        'SELECT * FROM agent_runtime.tasks'
        ' WHERE organization_id = %s AND short_id = %s FOR UPDATE',
        (organization_id, short_id),
    )
    if task is None:
        raise TaskNotFound(short_id)
    if task['status'] == 'closed':
        raise TaskClosed(short_id)
    return task


async def _update_task(
    conn: psycopg.AsyncConnection[typing.Any],
    task_id: uuid.UUID,
    changes: Row,
) -> Row:
    statement = sql.SQL(
        'UPDATE agent_runtime.tasks SET {sets}, updated_at = NOW()'
        ' WHERE id = %s RETURNING *'
    ).format(
        sets=sql.SQL(', ').join(
            sql.SQL('{col} = %s').format(col=sql.Identifier(col))
            for col in changes
        )
    )
    async with conn.cursor(row_factory=rows.dict_row) as cursor:
        await cursor.execute(statement, [*changes.values(), task_id])
        row = await cursor.fetchone()
    if row is None:  # pragma: no cover - the row is locked
        raise TaskNotFound(str(task_id))
    return row


async def _session_open(
    conn: psycopg.AsyncConnection[typing.Any], task_id: uuid.UUID
) -> bool:
    cursor = await conn.execute(
        'SELECT EXISTS (SELECT 1 FROM agent_runtime.sessions'
        ' WHERE task_id = %s AND closed_at IS NULL)',
        (task_id,),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def _next_short_id(
    conn: psycopg.AsyncConnection[typing.Any], organization_id: str
) -> str:
    """Take the next ``T-<n>`` of the organization.

    The row lock holds until the transaction ends, so a rollback returns
    the number.
    """
    cursor = await conn.execute(
        'INSERT INTO agent_runtime.task_id_sequences'
        ' (organization_id, last_value) VALUES (%s, 1)'
        ' ON CONFLICT (organization_id) DO UPDATE'
        ' SET last_value = task_id_sequences.last_value + 1'
        ' RETURNING last_value',
        (organization_id,),
    )
    row = await cursor.fetchone()
    if row is None:  # pragma: no cover - RETURNING always yields a row
        raise RuntimeError('task id sequence returned no row')
    return f'T-{row[0]}'


async def _append_event(
    conn: psycopg.AsyncConnection[typing.Any],
    task_id: uuid.UUID,
    event_type: str,
    payload: Row,
    actor: Actor,
) -> None:
    """Write one event with the next ``seq`` of the task."""
    cursor = await conn.execute(
        'UPDATE agent_runtime.tasks SET last_seq = last_seq + 1'
        ' WHERE id = %s RETURNING last_seq',
        (task_id,),
    )
    row = await cursor.fetchone()
    if row is None:  # pragma: no cover - callers hold the task
        raise TaskNotFound(str(task_id))
    await conn.execute(
        'INSERT INTO agent_runtime.events (task_id, seq, event_id, type,'
        ' actor_kind, actor_id, channel, payload)'
        ' VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
        (
            task_id,
            row[0],
            uuid.uuid4(),
            event_type,
            actor.kind,
            actor.id,
            actor.channel,
            pg_json.Jsonb(payload),
        ),
    )


def _escape_like(value: str) -> str:
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
