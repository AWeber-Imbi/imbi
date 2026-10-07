"""Postgres repository for agent tasks (ADR 0020).

A change to a task and the event that records it commit in one
transaction. Each write method here does both, so nothing changes a task
without an event.

An event write increments ``tasks.last_seq`` and uses the new value as
the event ``seq``. The ``UPDATE`` locks the task row until the
transaction ends, so concurrent writers to one task get consecutive
numbers and the sequence has no gaps.

After the transaction commits, the events it wrote (and the budget
ledger rows) go to the permanent log in ClickHouse: see
:mod:`imbi.api.agent_tasks.log`. They go after the commit, never inside
the transaction, so ClickHouse never holds an event that Postgres rolled
back.
"""

import contextlib
import dataclasses
import datetime
import decimal
import typing
import uuid
from collections import abc

import psycopg
import psycopg.errors
import psycopg_pool
from psycopg import rows, sql
from psycopg.types import json as pg_json

from imbi.api.agent_tasks import log

type Pool = psycopg_pool.AsyncConnectionPool[
    psycopg.AsyncConnection[typing.Any]
]
type Row = dict[str, typing.Any]
type Conn = psycopg.AsyncConnection[typing.Any]

SCHEMA = 'agent_runtime'

Status = typing.Literal['queued', 'running', 'blocked', 'paused', 'closed']
Control = typing.Literal['run', 'pause', 'cancel']
ActorKind = typing.Literal['human', 'agent', 'subagent', 'system']
Channel = typing.Literal['web', 'slack', 'mcp', 'api', 'harness']
#: The closed F5 set of terminal outcomes.
Outcome = typing.Literal[
    'done_acted',
    'done_nothing_to_act_on',
    'no_reason_to_run',
    'partial_capped',
    'suppressed_duplicate',
    'superseded',
    'cancelled_by_human',
    'interrupted_by_operator',
    'failed_at_gate',
    'failed_external',
    'unmapped_subject',
    'exceeded_ceiling',
    'unhandled_no_actor',
    'request_expired',
    'refused_rate_ceiling',
]

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


class ConcurrencyLimit(ValueError):
    """The agent has its maximum number of open sessions."""


class SessionNotFound(LookupError):
    """The task has no session with this id."""


class SessionClosed(ValueError):
    """The session is closed."""


class EventIdConflict(ValueError):
    """An event of another task has this ``event_id``."""


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


@dataclasses.dataclass(frozen=True)
class NewEvent:
    """An event that a harness writes.

    The harness picks ``event_id``, so a batch that it sends again does
    not write its events two times.
    """

    event_id: uuid.UUID
    type: str
    payload: Row
    actor: Actor
    schema_version: int = 1
    at: datetime.datetime | None = None


@dataclasses.dataclass(frozen=True)
class Usage:
    """One model call that a harness reports.

    ``None`` for a token count means the harness did not measure it.
    """

    idempotency_key: str
    model_id: str
    tokens_in: int | None
    tokens_out: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    session_id: uuid.UUID | None


#: Each token count of a usage report, and the price column for it.
_TOKEN_PRICES: tuple[tuple[str, str], ...] = (
    ('tokens_in', 'input_cost_per_million'),
    ('tokens_out', 'output_cost_per_million'),
    ('cache_read_tokens', 'cache_read_cost_per_million'),
    ('cache_write_tokens', 'cache_write_cost_per_million'),
)

#: The scale of the NUMERIC(14, 6) cost columns.
_COST_SCALE = decimal.Decimal('0.000001')


def usage_cost(
    counts: dict[str, int | None],
    prices: dict[str, decimal.Decimal | None] | None,
) -> decimal.Decimal | None:
    """Return the USD cost of a usage report, or ``None`` when unknown.

    The cost is unknown when no count was measured, when the model is not
    in the catalog (``prices`` is ``None``), or when a count above zero
    has no price. Unknown is never recorded as zero (N2).
    """
    if prices is None or all(count is None for count in counts.values()):
        return None
    total = decimal.Decimal(0)
    for count_column, price_column in _TOKEN_PRICES:
        count = counts[count_column]
        if not count:
            continue
        price = prices[price_column]
        if price is None:
            return None
        total += count * price / 1_000_000
    return total.quantize(_COST_SCALE)


@dataclasses.dataclass(frozen=True)
class NewRequest:
    """A feedback or approval request that a harness opens."""

    kind: typing.Literal['feedback', 'approval']
    title: str
    why: str | None
    options: list[typing.Any] | None
    artifacts: list[typing.Any] | None
    artifact_digests: list[str] | None
    expires_at: datetime.datetime | None
    session_id: uuid.UUID | None


@dataclasses.dataclass
class _Write:
    """One write transaction on a locked task.

    ``task`` is the newest row of the task. ``events`` and ``ledger``
    collect the rows to publish after the commit.
    """

    conn: Conn
    task: Row
    events: list[Row] = dataclasses.field(default_factory=list[Row])
    ledger: list[Row] = dataclasses.field(default_factory=list[Row])

    async def event(
        self, event_type: str, payload: Row, actor: Actor, **kwargs: typing.Any
    ) -> Row:
        """Write one event; see :func:`_append_event`."""
        row = await _append_event(
            self.conn, self.task['id'], event_type, payload, actor, **kwargs
        )
        self.events.append(row)
        return row

    async def update(self, changes: Row) -> Row:
        """Change columns of the task and keep the new row."""
        self.task = await _update_task(self.conn, self.task['id'], changes)
        return self.task


class TaskStore:
    """Repository over the ``agent_runtime`` schema."""

    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    @contextlib.asynccontextmanager
    async def _write(
        self, organization_id: str, short_id: str
    ) -> abc.AsyncGenerator[_Write]:
        """Lock an open task for a change, then publish what changed.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.

        """
        async with self._pool.connection() as conn:
            async with conn.transaction():
                write = _Write(
                    conn, await _lock_task(conn, organization_id, short_id)
                )
                yield write
                if write.events:
                    # Event writes change ``last_seq``.
                    write.task = await _fetch_task(conn, write.task['id'])
        await log.publish(write.task, write.events, write.ledger)

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
                event = await _append_event(
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
        await log.publish(row, [event])
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

    async def unarchived(self) -> list[Row]:
        """Return the tasks whose log is not archived, by organization.

        Each row also has ``ledger_count``, its number of ledger rows.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                'SELECT t.*, (SELECT count(*) FROM agent_runtime.budget_ledger'
                ' AS l WHERE l.task_id = t.id) AS ledger_count'
                ' FROM agent_runtime.tasks AS t'
                ' WHERE t.log_archived_at IS NULL'
                ' ORDER BY t.organization_id, t.id'
            )
            return await cursor.fetchall()

    async def events_with_seqs(
        self, task_id: uuid.UUID, seqs: list[int]
    ) -> list[Row]:
        """Return the events of a task with the given seqs, by seq."""
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                'SELECT * FROM agent_runtime.events'
                ' WHERE task_id = %s AND seq = ANY(%s) ORDER BY seq',
                (task_id, seqs),
            )
            return await cursor.fetchall()

    async def ledger(self, task_id: uuid.UUID) -> list[Row]:
        """Return the budget ledger rows of a task, oldest first."""
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                'SELECT * FROM agent_runtime.budget_ledger'
                ' WHERE task_id = %s ORDER BY recorded_at, id',
                (task_id,),
            )
            return await cursor.fetchall()

    async def archive(self, task_id: uuid.UUID, last_seq: int) -> bool:
        """Delete the events of a closed task and set ``log_archived_at``.

        Do this only after ClickHouse has every seq up to ``last_seq``.
        Return ``False`` and change nothing when the task is not closed,
        is archived, or has events after ``last_seq``.
        """
        async with self._pool.connection() as conn, conn.transaction():
            cursor = await conn.execute(
                'SELECT 1 FROM agent_runtime.tasks WHERE id = %s'
                " AND status = 'closed' AND log_archived_at IS NULL"
                ' AND last_seq = %s FOR UPDATE',
                (task_id, last_seq),
            )
            if await cursor.fetchone() is None:
                return False
            await conn.execute(
                'DELETE FROM agent_runtime.events WHERE task_id = %s',
                (task_id,),
            )
            await conn.execute(
                'UPDATE agent_runtime.tasks SET log_archived_at = NOW()'
                ' WHERE id = %s',
                (task_id,),
            )
        return True

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
        async with self._write(organization_id, short_id) as write:
            task = write.task
            if task['control'] == control:
                return task
            if task['control'] == 'cancel':
                raise CancelPending(short_id)
            await write.event(
                'control.changed',
                {'from': task['control'], 'to': control, 'actor': actor.id},
                actor,
            )
            changes: Row = {'control': control}
            if not await _session_open(write.conn, task['id']):
                status = _IDLE_STATUS[control]
                if status != task['status']:
                    changes['status'] = status
                    await write.event(
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
                    await write.event(
                        'outcome.set',
                        {
                            'outcome': changes['outcome'],
                            'reason': changes['outcome_reason'],
                        },
                        actor,
                    )
            await write.update(changes)
        return write.task

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
        async with self._write(organization_id, short_id) as write:
            if write.task['owner'] != owner:
                await write.event(
                    'owner.changed',
                    {'from': write.task['owner'], 'to': owner},
                    actor,
                )
                await write.update({'owner': owner})
        return write.task

    # --- Harness ------------------------------------------------------

    async def open_session(
        self,
        organization_id: str,
        short_id: str,
        *,
        key: str,
        harness_instance: str | None,
        max_concurrent: int | None,
        actor: Actor,
    ) -> tuple[Row, Row, bool]:
        """Open a harness session; return the task, it, and if it is new.

        A repeat with the same ``key`` returns the first session. A new
        session moves a ``queued`` task, or a ``blocked`` task with no
        open request, to ``running`` when the control value is ``run``.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            CancelPending: The control value is ``cancel``.
            ConcurrencyLimit: The agent has ``max_concurrent`` open
                sessions on its tasks.

        """
        async with self._write(organization_id, short_id) as write:
            task = write.task
            if task['control'] == 'cancel':
                raise CancelPending(short_id)
            session = await _fetch_one(
                write.conn,
                'SELECT * FROM agent_runtime.sessions'
                ' WHERE task_id = %s AND session_key = %s',
                (task['id'], key),
            )
            if session is not None:
                return task, session, False
            if max_concurrent is not None:
                await _check_concurrency(
                    write.conn, task['agent_id'], max_concurrent
                )
            session = await _fetch_one(
                write.conn,
                'INSERT INTO agent_runtime.sessions'
                ' (id, task_id, session_key, harness_instance)'
                ' VALUES (%s, %s, %s, %s) RETURNING *',
                (uuid.uuid4(), task['id'], key, harness_instance),
            )
            if session is None:  # pragma: no cover - RETURNING yields a row
                raise RuntimeError('session insert returned no row')
            await write.event(
                'session.opened',
                {
                    'session_id': str(session['id']),
                    'session_key': key,
                    'harness_instance': harness_instance,
                },
                actor,
                session_id=session['id'],
            )
            if task['control'] == 'run' and (
                task['status'] == 'queued'
                or (
                    task['status'] == 'blocked'
                    and not await _request_open(write.conn, task['id'])
                )
            ):
                await _set_status(write, 'running', 'session_opened', actor)
        return write.task, session, True

    async def heartbeat(
        self,
        organization_id: str,
        short_id: str,
        session_id: uuid.UUID,
        *,
        timeout_seconds: int | None,
        system: Actor,
    ) -> Row:
        """Record a heartbeat of an open session; return the task.

        When the task has run longer than ``timeout_seconds`` since its
        first session opened, close it with ``exceeded_ceiling``.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            SessionNotFound: The task has no such session.
            SessionClosed: The session is closed.

        """
        async with self._write(organization_id, short_id) as write:
            session = await _open_session(
                write.conn, write.task['id'], session_id
            )
            await write.conn.execute(
                'UPDATE agent_runtime.sessions SET heartbeat_at = NOW()'
                ' WHERE id = %s',
                (session['id'],),
            )
            if timeout_seconds is not None:
                cursor = await write.conn.execute(
                    'SELECT NOW() - min(opened_at) > make_interval(secs => %s)'
                    ' FROM agent_runtime.sessions WHERE task_id = %s',
                    (timeout_seconds, write.task['id']),
                )
                row = await cursor.fetchone()
                if row and row[0]:
                    await _close(
                        write, 'exceeded_ceiling', 'task_timeout', system
                    )
        return write.task

    async def close_session(
        self,
        organization_id: str,
        short_id: str,
        session_id: uuid.UUID,
        reason: str,
        actor: Actor,
        *,
        stale_seconds: int | None = None,
    ) -> Row:
        """Close a session and write ``session.closed``; return the task.

        A closed session stays closed; closing it again changes nothing.
        With ``stale_seconds``, the session closes only when its last
        sign of life (``heartbeat_at``, else ``opened_at``) is older.
        When no session remains open, the status follows the control
        value, as in :meth:`set_control`: ``pause`` moves the task to
        ``paused``, ``run`` moves a ``running`` task back to ``queued``,
        and ``cancel`` closes it with ``cancelled_by_human``.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            SessionNotFound: The task has no such session.

        """
        async with self._write(organization_id, short_id) as write:
            task = write.task
            session = await _session(write.conn, task['id'], session_id)
            if session['closed_at'] is not None:
                return task
            if stale_seconds is not None and not await _stale(
                write.conn, session_id, stale_seconds
            ):
                return task
            await write.conn.execute(
                'UPDATE agent_runtime.sessions'
                ' SET closed_at = NOW(), close_reason = %s WHERE id = %s',
                (reason, session_id),
            )
            await write.event(
                'session.closed',
                {'session_id': str(session_id), 'reason': reason},
                actor,
                session_id=session_id,
            )
            if not await _session_open(write.conn, task['id']):
                if task['control'] == 'cancel':
                    await _close(
                        write,
                        'cancelled_by_human',
                        CANCELLED_WITHOUT_SESSION,
                        actor,
                    )
                elif task['control'] == 'pause':
                    if task['status'] != 'paused':
                        await _set_status(
                            write, 'paused', 'session_closed', actor
                        )
                elif task['status'] == 'running':
                    await _set_status(write, 'queued', 'session_closed', actor)
        return write.task

    async def stale_sessions(self, stale_seconds: int) -> list[Row]:
        """Return open sessions with no sign of life in ``stale_seconds``.

        Each row has the session ``id`` and the ``organization_id`` and
        ``short_id`` of its task.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                'SELECT s.id, t.organization_id, t.short_id'
                ' FROM agent_runtime.sessions AS s'
                ' JOIN agent_runtime.tasks AS t ON t.id = s.task_id'
                ' WHERE s.closed_at IS NULL'
                ' AND COALESCE(s.heartbeat_at, s.opened_at)'
                ' < NOW() - make_interval(secs => %s)',
                (stale_seconds,),
            )
            return await cursor.fetchall()

    async def append_events(
        self,
        organization_id: str,
        short_id: str,
        events: list[NewEvent],
        session_id: uuid.UUID | None,
    ) -> tuple[Row, list[Row], list[uuid.UUID]]:
        """Write harness events; return the task, the events written,
        and the ids of the duplicates.

        An event whose ``event_id`` the task already has, or that comes
        earlier in the batch, is a duplicate. It is skipped before it
        takes a seq, so the sequence stays without gaps. A
        ``phase.changed`` event that is written also sets the ``phase``
        of the task.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            SessionNotFound: The task has no such session.
            SessionClosed: The session is closed.
            EventIdConflict: Another task has an event with an id.

        """
        try:
            async with self._write(organization_id, short_id) as write:
                if session_id is not None:
                    await _open_session(
                        write.conn, write.task['id'], session_id
                    )
                cursor = await write.conn.execute(
                    'SELECT event_id FROM agent_runtime.events'
                    ' WHERE task_id = %s AND event_id = ANY(%s)',
                    (write.task['id'], [event.event_id for event in events]),
                )
                seen: set[uuid.UUID] = {
                    row[0] for row in await cursor.fetchall()
                }
                written: list[Row] = []
                duplicates: list[uuid.UUID] = []
                phase: str | None = None
                for event in events:
                    if event.event_id in seen:
                        duplicates.append(event.event_id)
                        continue
                    seen.add(event.event_id)
                    written.append(
                        await write.event(
                            event.type,
                            event.payload,
                            event.actor,
                            event_id=event.event_id,
                            session_id=session_id,
                            schema_version=event.schema_version,
                            at=event.at,
                        )
                    )
                    if event.type == 'phase.changed':
                        phase = event.payload['phase']
                if phase is not None:
                    await write.update({'phase': phase})
        except psycopg.errors.UniqueViolation as err:
            if err.diag.constraint_name != 'events_event_id_key':
                raise
            raise EventIdConflict(short_id) from err
        return write.task, written, duplicates

    async def open_request(
        self,
        organization_id: str,
        short_id: str,
        request: NewRequest,
        actor: Actor,
    ) -> tuple[Row, Row]:
        """Open a request, write ``request.opened``, and block the task.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            SessionNotFound: The task has no such session.
            SessionClosed: The session is closed.

        """
        async with self._write(organization_id, short_id) as write:
            task = write.task
            if request.session_id is not None:
                await _open_session(write.conn, task['id'], request.session_id)
            row = await _fetch_one(
                write.conn,
                'INSERT INTO agent_runtime.requests (id, task_id,'
                ' session_id, kind, title, why, options, artifacts,'
                ' artifact_digests, expires_at)'
                ' VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'
                ' RETURNING *',
                (
                    uuid.uuid4(),
                    task['id'],
                    request.session_id,
                    request.kind,
                    request.title,
                    request.why,
                    _jsonb(request.options),
                    _jsonb(request.artifacts),
                    request.artifact_digests,
                    request.expires_at,
                ),
            )
            if row is None:  # pragma: no cover - RETURNING yields a row
                raise RuntimeError('request insert returned no row')
            await write.event(
                'request.opened',
                {
                    'request_id': str(row['id']),
                    'kind': request.kind,
                    'title': request.title,
                    'why': request.why,
                    'options': request.options,
                    'artifacts': request.artifacts,
                    'artifact_digests': request.artifact_digests,
                    'expires_at': (
                        None
                        if request.expires_at is None
                        else request.expires_at.isoformat()
                    ),
                },
                actor,
                session_id=request.session_id,
            )
            if task['status'] != 'blocked':
                await _set_status(write, 'blocked', 'request_opened', actor)
        return write.task, row

    async def report_usage(
        self,
        organization_id: str,
        short_id: str,
        usage: Usage,
        prices: dict[str, decimal.Decimal | None] | None,
        *,
        actor: Actor,
        system: Actor,
    ) -> tuple[Row, Row, bool]:
        """Record a usage report; return the task, the ledger row, and
        whether the row is new.

        The ledger row keeps the prices used, and the task totals change
        in the same transaction. When the cost total passes the budget,
        the task closes with ``exceeded_ceiling``. A repeat with the same
        idempotency key returns the first row, even when the first report
        closed the task.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            SessionNotFound: The task has no such session.
            SessionClosed: The session is closed.

        """
        repeat = await self._usage_repeat(
            organization_id, short_id, usage.idempotency_key
        )
        if repeat is not None:
            return *repeat, False
        try:
            async with self._write(organization_id, short_id) as write:
                task = write.task
                # Two reports with one key wait for the same task lock.
                existing = await _ledger_row(
                    write.conn, task['id'], usage.idempotency_key
                )
                if existing is not None:
                    return task, existing, False
                if usage.session_id is not None:
                    await _open_session(
                        write.conn, task['id'], usage.session_id
                    )
                counts: dict[str, int | None] = {
                    count_column: getattr(usage, count_column)
                    for count_column, _price_column in _TOKEN_PRICES
                }
                cost = usage_cost(counts, prices)
                row = await _fetch_one(
                    write.conn,
                    'INSERT INTO agent_runtime.budget_ledger (id, task_id,'
                    ' session_id, idempotency_key, model_id, tokens_in,'
                    ' tokens_out, cache_read_tokens, cache_write_tokens,'
                    ' input_cost_per_million, output_cost_per_million,'
                    ' cache_read_cost_per_million,'
                    ' cache_write_cost_per_million, cost) VALUES (%s, %s,'
                    ' %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'
                    ' RETURNING *',
                    (
                        uuid.uuid4(),
                        task['id'],
                        usage.session_id,
                        usage.idempotency_key,
                        usage.model_id,
                        *counts.values(),
                        *(
                            None if prices is None else prices[price_column]
                            for _count_column, price_column in _TOKEN_PRICES
                        ),
                        cost,
                    ),
                )
                if row is None:  # pragma: no cover - RETURNING yields a row
                    raise RuntimeError('ledger insert returned no row')
                write.ledger.append(row)
                totals: Row = {
                    column: task[column] + (count or 0)
                    for column, count in counts.items()
                }
                totals['cost_total'] = task['cost_total'] + (cost or 0)
                budget: decimal.Decimal | None = task['budget']
                remaining = (
                    None if budget is None else budget - totals['cost_total']
                )
                await write.event(
                    'usage.reported',
                    {
                        'report_id': str(row['id']),
                        'model_id': usage.model_id,
                        **counts,
                        'cost': None if cost is None else str(cost),
                        'budget_remaining': (
                            None if remaining is None else str(remaining)
                        ),
                    },
                    actor,
                    session_id=usage.session_id,
                )
                await write.update(totals)
                if remaining is not None and remaining < 0:
                    await _close(write, 'exceeded_ceiling', 'budget', system)
        except TaskClosed:
            repeat = await self._usage_repeat(
                organization_id, short_id, usage.idempotency_key
            )
            if repeat is None:
                raise
            return *repeat, False
        return write.task, row, True

    async def _usage_repeat(
        self, organization_id: str, short_id: str, key: str
    ) -> tuple[Row, Row] | None:
        """Return the task and its ledger row with ``key``, if any."""
        async with self._pool.connection() as conn:
            task = await _fetch_one(
                conn,
                'SELECT * FROM agent_runtime.tasks'
                ' WHERE organization_id = %s AND short_id = %s',
                (organization_id, short_id),
            )
            if task is None:
                raise TaskNotFound(short_id)
            row = await _ledger_row(conn, task['id'], key)
        return None if row is None else (task, row)

    async def set_outcome(
        self,
        organization_id: str,
        short_id: str,
        outcome: Outcome,
        reason: str | None,
        actor: Actor,
    ) -> Row:
        """Close the task with ``outcome``; see :func:`_close`.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.

        """
        async with self._write(organization_id, short_id) as write:
            await _close(write, outcome, reason, actor)
        return write.task


async def _set_status(
    write: _Write, status: Status, reason: str, actor: Actor
) -> None:
    """Change the status of the task and write ``state.changed``."""
    await write.event(
        'state.changed',
        {'from': write.task['status'], 'to': status, 'reason': reason},
        actor,
    )
    await write.update({'status': status})


async def _close(
    write: _Write, outcome: Outcome, reason: str | None, actor: Actor
) -> None:
    """Close the task with an outcome.

    Close each open session (``session.closed``), then write
    ``state.changed`` and ``outcome.set``.
    """
    cursor = await write.conn.execute(
        'UPDATE agent_runtime.sessions'
        " SET closed_at = NOW(), close_reason = 'task_closed'"
        ' WHERE task_id = %s AND closed_at IS NULL RETURNING id',
        (write.task['id'],),
    )
    for (session_id,) in await cursor.fetchall():
        await write.event(
            'session.closed',
            {'session_id': str(session_id), 'reason': 'task_closed'},
            actor,
            session_id=session_id,
        )
    await write.event(
        'state.changed',
        {
            'from': write.task['status'],
            'to': 'closed',
            'reason': 'outcome_set',
        },
        actor,
    )
    await write.event(
        'outcome.set', {'outcome': outcome, 'reason': reason}, actor
    )
    await write.update(
        {
            'status': 'closed',
            'outcome': outcome,
            'outcome_reason': reason,
            'closed_at': datetime.datetime.now(datetime.UTC),
        }
    )


async def _session(
    conn: Conn, task_id: uuid.UUID, session_id: uuid.UUID
) -> Row:
    session = await _fetch_one(
        conn,
        'SELECT * FROM agent_runtime.sessions WHERE id = %s AND task_id = %s',
        (session_id, task_id),
    )
    if session is None:
        raise SessionNotFound(str(session_id))
    return session


async def _open_session(
    conn: Conn, task_id: uuid.UUID, session_id: uuid.UUID
) -> Row:
    session = await _session(conn, task_id, session_id)
    if session['closed_at'] is not None:
        raise SessionClosed(str(session_id))
    return session


async def _stale(
    conn: Conn, session_id: uuid.UUID, stale_seconds: int
) -> bool:
    cursor = await conn.execute(
        'SELECT COALESCE(heartbeat_at, opened_at)'
        ' < NOW() - make_interval(secs => %s)'
        ' FROM agent_runtime.sessions WHERE id = %s',
        (stale_seconds, session_id),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def _check_concurrency(
    conn: Conn, agent_id: str, max_concurrent: int
) -> None:
    """Raise when the agent has ``max_concurrent`` open sessions.

    The advisory lock makes concurrent opens for one agent count one at
    a time, so two opens cannot both take the last place.
    """
    await conn.execute(
        'SELECT pg_advisory_xact_lock(hashtext(%s))',
        (f'agent_runtime.sessions:{agent_id}',),
    )
    cursor = await conn.execute(
        'SELECT count(*) FROM agent_runtime.sessions AS s'
        ' JOIN agent_runtime.tasks AS t ON t.id = s.task_id'
        ' WHERE t.agent_id = %s AND s.closed_at IS NULL',
        (agent_id,),
    )
    row = await cursor.fetchone()
    if row and row[0] >= max_concurrent:
        raise ConcurrencyLimit(agent_id)


async def _ledger_row(conn: Conn, task_id: uuid.UUID, key: str) -> Row | None:
    return await _fetch_one(
        conn,
        'SELECT * FROM agent_runtime.budget_ledger'
        ' WHERE task_id = %s AND idempotency_key = %s',
        (task_id, key),
    )


async def _request_open(conn: Conn, task_id: uuid.UUID) -> bool:
    cursor = await conn.execute(
        'SELECT EXISTS (SELECT 1 FROM agent_runtime.requests'
        " WHERE task_id = %s AND status = 'open')",
        (task_id,),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


def _jsonb(value: typing.Any) -> pg_json.Jsonb | None:
    return None if value is None else pg_json.Jsonb(value)


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
    conn: Conn,
    task_id: uuid.UUID,
    event_type: str,
    payload: Row,
    actor: Actor,
    *,
    event_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    schema_version: int = 1,
    at: datetime.datetime | None = None,
) -> Row:
    """Write one event with the next ``seq`` of the task; return it.

    ``event_id`` defaults to a new UUID.

    ``at`` is the time the event happened. The default is the start of
    the transaction.
    """
    cursor = await conn.execute(
        'UPDATE agent_runtime.tasks SET last_seq = last_seq + 1'
        ' WHERE id = %s RETURNING last_seq',
        (task_id,),
    )
    row = await cursor.fetchone()
    if row is None:  # pragma: no cover - callers hold the task
        raise TaskNotFound(str(task_id))
    event = await _fetch_one(
        conn,
        'INSERT INTO agent_runtime.events (task_id, seq, event_id, type,'
        ' schema_version, actor_kind, actor_id, channel, session_id, at,'
        ' payload) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,'
        ' COALESCE(%s, NOW()), %s) RETURNING *',
        (
            task_id,
            row[0],
            event_id or uuid.uuid4(),
            event_type,
            schema_version,
            actor.kind,
            actor.id,
            actor.channel,
            session_id,
            at,
            pg_json.Jsonb(payload),
        ),
    )
    if event is None:  # pragma: no cover - RETURNING always yields a row
        raise RuntimeError('event insert returned no row')
    return event


def _escape_like(value: str) -> str:
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
