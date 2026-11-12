"""Postgres repository for workflow runs (ADR 0021).

imbi-api creates and cancels runs here; imbi-workflows executes them.
A change to a run and its event commit in one transaction.
"""

import dataclasses
import json
import typing
import uuid
from collections import abc

import fastapi
from psycopg import rows
from psycopg.types import json as pg_json

from imbi.api.workflows import store
from imbi.common.workflows import history, runtime

#: A side effect with no response for this long is stale: its call has
#: stopped (ADR 0021, unknown-outcome reconciliation).
STALE_AFTER = '15 minutes'

#: The principal of the engine: the slug of its service account
#: (``auth/internal_services.py``).
ENGINE_PRINCIPAL = 'imbi-workflows'

#: The stale side effects of runs of an organization. A key is
#: ``[principal, action, caller key]`` (:func:`side_effect_key`), and the
#: engine's caller key is ``<run_id>:<node_key>`` for a step, or
#: ``<run_id>/failure-notice``. Only keys of the engine principal are
#: listed: a key of another caller (a person who deploys with an
#: ``Idempotency-Key``) is not a workflow call, also when it starts
#: with a run ID.
#: ``retryable``: the step failed the run with ``outcome_unknown``, the
#: run is not archived, and its deadline has not passed.
_STALE = """
WITH e AS (
  SELECT key, created_at,
         CASE WHEN key LIKE '[%%' THEN key::jsonb ->> 1 END AS action,
         CASE WHEN key LIKE '[%%' THEN key::jsonb ->> 2 END AS caller_key
    FROM workflow_runtime.side_effects
   WHERE response IS NULL AND created_at < NOW() - %(stale)s::interval
     AND CASE WHEN key LIKE '[%%' THEN key::jsonb ->> 0 END = %(principal)s
)
SELECT e.key, e.action, e.created_at, r.id AS run_id,
       r.status AS run_status, r.error AS run_error,
       w.slug AS workflow_slug, w.name AS workflow_name,
       CASE WHEN substr(e.caller_key, 37, 1) = ':'
            THEN substr(e.caller_key, 38) END AS node_key,
       s.node_id, s.input AS step_input,
       COALESCE(e.action IN ('deployment', 'step-email')
         AND r.status = 'failed' AND r.error = 'outcome_unknown'
         AND r.log_archived_at IS NULL
         AND s.status = 'failed' AND s.error = 'outcome_unknown'
         AND r.created_at + make_interval(secs => COALESCE(
               (v.settings ->> 'max_run_time_seconds')::int, 7200))
             > NOW(), FALSE) AS retryable
  FROM e
  JOIN workflow_runtime.runs AS r ON r.id::text = left(e.caller_key, 36)
  JOIN workflows.workflows AS w ON w.id = r.workflow_id
  JOIN workflows.workflow_versions AS v
    ON v.workflow_id = r.workflow_id AND v.version = r.version
  LEFT JOIN workflow_runtime.step_runs AS s
    ON s.run_id = r.id AND substr(e.caller_key, 37, 1) = ':'
   AND s.node_key = substr(e.caller_key, 38)
 WHERE r.organization_id = %(org)s
   AND (%(key)s::text IS NULL OR e.key = %(key)s)
 ORDER BY e.created_at
"""


def side_effect_key(principal: str, action: str, idempotency_key: str) -> str:
    """Return the ``side_effects`` key. JSON, so no part can run into
    the next one."""
    return json.dumps([principal, action, idempotency_key])


class _ChangedError(Exception):
    """The run or the step changed: roll the transaction back."""


class NotActive(LookupError):
    """The workflow of a new run is gone or not active."""


@dataclasses.dataclass(frozen=True)
class NewRun:
    organization_id: str
    workflow_id: uuid.UUID
    version: int
    trigger_node_id: str
    origin_kind: str
    origin_id: str
    #: The origin record: the user, the scheduler task id, or the
    #: webhook id and the delivery id.
    origin: dict[str, typing.Any]
    idempotency_key: str | None
    payload: dict[str, typing.Any]
    concurrency_key: str | None
    activated_by: str


class RunStore:
    def __init__(self, pool: store.Pool) -> None:
        self._pool = pool

    async def _all(
        self, query: str, params: tuple[typing.Any, ...]
    ) -> list[store.Row]:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(query, params)  # pyright: ignore[reportArgumentType]
            return await cur.fetchall()

    async def create(self, run: NewRun) -> tuple[store.Row, bool]:
        """Write a queued run. Return it, and ``False`` for a repeat.

        A repeat of an idempotency key for the same workflow returns
        the first run.

        The workflow row is locked ``FOR SHARE`` first, so a delete,
        which locks it ``FOR UPDATE``, cannot pass between its open-run
        check and its ``DELETE`` while a run is written.

        Raises:
            NotActive: The workflow is gone or not active.

        """
        async with (
            self._pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(
                'SELECT status FROM workflows.workflows WHERE id = %s'
                ' FOR SHARE',
                (run.workflow_id,),
            )
            workflow = await cur.fetchone()
            if workflow is None or workflow['status'] != 'active':
                raise NotActive(str(run.workflow_id))
            await cur.execute(
                'INSERT INTO workflow_runtime.runs (id, organization_id,'
                ' workflow_id, version, trigger_node_id, origin_kind,'
                ' origin_id, origin, idempotency_key, payload,'
                ' concurrency_key, activated_by) VALUES'
                ' (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'
                ' ON CONFLICT (organization_id, workflow_id, origin_kind,'
                ' origin_id, idempotency_key) DO NOTHING RETURNING *',
                (
                    uuid.uuid4(),
                    run.organization_id,
                    run.workflow_id,
                    run.version,
                    run.trigger_node_id,
                    run.origin_kind,
                    run.origin_id,
                    pg_json.Jsonb(run.origin),
                    run.idempotency_key,
                    pg_json.Jsonb(run.payload),
                    run.concurrency_key,
                    run.activated_by,
                ),
            )
            created = await cur.fetchone()
            if created is None:
                await cur.execute(
                    'SELECT * FROM workflow_runtime.runs'
                    ' WHERE organization_id = %s AND workflow_id = %s'
                    ' AND origin_kind = %s AND origin_id = %s'
                    ' AND idempotency_key = %s',
                    (
                        run.organization_id,
                        run.workflow_id,
                        run.origin_kind,
                        run.origin_id,
                        run.idempotency_key,
                    ),
                )
                return typing.cast(store.Row, await cur.fetchone()), False
            await runtime.append_event(
                conn,
                created['id'],
                'run.created',
                {'origin_kind': run.origin_kind, 'origin_id': run.origin_id},
            )
            await conn.execute(f'NOTIFY {runtime.NOTIFY_CHANNEL}')
        await history.publish_since(self._pool, created['id'], 0)
        return created, True

    async def list_runs(
        self, workflow_id: uuid.UUID, limit: int
    ) -> list[store.Row]:
        """Return the runs of a workflow, newest first."""
        return await self._all(
            'SELECT * FROM workflow_runtime.runs WHERE workflow_id = %s'
            ' ORDER BY created_at DESC, id LIMIT %s',
            (workflow_id, limit),
        )

    async def get(
        self, workflow_id: uuid.UUID, run_id: uuid.UUID
    ) -> store.Row | None:
        found = await self._all(
            'SELECT * FROM workflow_runtime.runs'
            ' WHERE workflow_id = %s AND id = %s',
            (workflow_id, run_id),
        )
        return found[0] if found else None

    async def steps(self, run_id: uuid.UUID) -> list[store.Row]:
        return await self._all(
            'SELECT * FROM workflow_runtime.step_runs WHERE run_id = %s'
            ' ORDER BY started_at NULLS LAST, node_id',
            (run_id,),
        )

    async def cancel(self, run_id: uuid.UUID) -> bool:
        """Ask the engine to stop a run. ``False`` when it is closed."""
        async with self._pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                'UPDATE workflow_runtime.runs SET cancel_requested = TRUE,'
                ' due_at = LEAST(due_at, NOW())'
                ' WHERE id = %s AND NOT (status = ANY(%s))',
                (run_id, list(runtime.CLOSED)),
            )
            if not cur.rowcount:
                return False
            await conn.execute(f'NOTIFY {runtime.NOTIFY_CHANNEL}')
            return True

    async def attention(self, organization_id: str) -> list[store.Row]:
        """Return the runs that an admin should look at, newest first.

        ``failed``: a run failed or timed out in the last 7 days.
        ``stuck``: an open run that no engine works on: its lease expired
        and no worker took it again, or it is overdue by 5 minutes when
        nothing (no other run of its concurrency key) holds it back.
        """
        return await self._all(
            'SELECT r.*, w.slug AS workflow_slug, w.name AS workflow_name,'
            ' l.worker_id, l.expires_at AS lease_expires_at,'
            " CASE WHEN r.status IN ('failed', 'timed_out')"
            " THEN 'failed' ELSE 'stuck' END AS reason"
            ' FROM workflow_runtime.runs AS r'
            ' JOIN workflows.workflows AS w ON w.id = r.workflow_id'
            ' LEFT JOIN workflow_runtime.leases AS l ON l.run_id = r.id'
            ' WHERE r.organization_id = %s AND ('
            "  (r.status IN ('failed', 'timed_out')"
            "   AND r.closed_at > NOW() - INTERVAL '7 days')"
            # A closed run can keep a stale lease row: it is not stuck.
            " OR (l.expires_at < NOW() AND r.status IN ('queued', 'running'))"
            " OR (r.due_at < NOW() - INTERVAL '5 minutes'"
            "     AND (r.status = 'running'"
            "          OR (r.status = 'queued'"
            '              AND r.concurrency_key IS NULL))))'
            ' ORDER BY COALESCE(r.closed_at, r.created_at) DESC LIMIT 100',
            (organization_id,),
        )

    # --- Archive sweep (ADR 0021, Run history) ---------------------------

    async def unarchived(
        self, after: tuple[str, uuid.UUID] | None, limit: int
    ) -> list[store.Row]:
        """Return a page of the runs whose log is not archived.

        The page is ordered by organization and id, and starts after the
        ``(organization_id, id)`` that ended the page before.
        """
        return await self._all(
            'SELECT * FROM workflow_runtime.runs'
            ' WHERE log_archived_at IS NULL'
            ' AND (organization_id, id) > (%s, %s)'
            ' ORDER BY organization_id, id LIMIT %s',
            (*(after or ('', uuid.UUID(int=0))), limit),
        )

    async def orphan_agent_tasks(self) -> list[store.Row]:
        """Return the open agent tasks whose agent step has ended.

        An agent step writes its run id and node key in the origin of
        its task (ADR 0021). A task is an orphan when its run is closed
        or gone, or its step is not ``running``. The engine cancels the
        task when the step ends, but only as best effort. A task that
        waits for a cancel already is left out.
        """
        return await self._all(
            'SELECT t.organization_id, t.short_id'
            ' FROM agent_runtime.tasks AS t'
            ' LEFT JOIN workflow_runtime.runs AS r'
            " ON r.id::text = t.origin->>'workflow_run_id'"
            ' AND r.organization_id = t.organization_id'
            ' LEFT JOIN workflow_runtime.step_runs AS s'
            " ON s.run_id = r.id AND s.node_key = t.origin->>'node_key'"
            " WHERE t.status <> 'closed' AND t.control <> 'cancel'"
            " AND t.origin ? 'workflow_run_id'"
            ' AND (r.id IS NULL OR r.status = ANY(%s)'
            " OR s.status IS DISTINCT FROM 'running')",
            (list(runtime.CLOSED),),
        )

    async def events_with_seqs(
        self, run_id: uuid.UUID, seqs: list[int]
    ) -> list[store.Row]:
        """Return the events of a run with the given seqs, by seq."""
        return await self._all(
            'SELECT * FROM workflow_runtime.run_events'
            ' WHERE run_id = %s AND seq = ANY(%s) ORDER BY seq',
            (run_id, seqs),
        )

    async def archive(self, run_id: uuid.UUID, last_seq: int) -> bool:
        """Delete the events and step rows of a closed run, and set
        ``log_archived_at``. The ``runs`` row stays.

        Do this only after ClickHouse has every seq up to ``last_seq``
        and the terminal summary row. Return ``False`` and change nothing
        when the run is open, is archived, has events after
        ``last_seq``, or failed with ``outcome_unknown`` and has a side
        effect with no response.
        """
        async with self._pool.connection() as conn, conn.transaction():
            # A run that an unknown outcome failed keeps its step rows
            # while the key has no response, so an operator can resolve
            # it and retry the step. Other runs skip the key scan.
            cur = await conn.execute(
                'UPDATE workflow_runtime.runs SET log_archived_at = NOW()'
                ' WHERE id = %s AND status = ANY(%s)'
                ' AND log_archived_at IS NULL AND last_seq = %s'
                " AND (error IS DISTINCT FROM 'outcome_unknown'"
                ' OR NOT EXISTS (SELECT 1 FROM workflow_runtime.side_effects'
                " WHERE response IS NULL AND CASE WHEN key LIKE '[%%'"
                ' THEN key::jsonb ->> 0 = %s'
                ' AND left(key::jsonb ->> 2, 36) = %s END))',
                (
                    run_id,
                    list(runtime.CLOSED),
                    last_seq,
                    ENGINE_PRINCIPAL,
                    str(run_id),
                ),
            )
            if not cur.rowcount:
                return False
            await conn.execute(
                'DELETE FROM workflow_runtime.run_events WHERE run_id = %s',
                (run_id,),
            )
            await conn.execute(
                'DELETE FROM workflow_runtime.step_runs WHERE run_id = %s',
                (run_id,),
            )
        return True

    async def once(
        self,
        principal: str,
        action: str,
        idempotency_key: str,
        call: abc.Callable[[], abc.Awaitable[dict[str, typing.Any]]],
    ) -> dict[str, typing.Any]:
        """Run ``call`` once per key. A repeat returns the first result.

        The stored key is the principal, the action, and the caller's
        key together (:func:`side_effect_key`), so the same caller key
        on two routes, or from two principals, never meets.

        A refusal (``4xx``) acts before the side effect, so the key is
        released and a repeat may try again. Any other failure can come
        after it: the key stays.

        Raises:
            fastapi.HTTPException: ``409 outcome_unknown``: a call with
                the key started and did not finish, so it may or may
                not have acted.

        """
        key = side_effect_key(principal, action, idempotency_key)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                'INSERT INTO workflow_runtime.side_effects (key)'
                ' VALUES (%s) ON CONFLICT (key) DO NOTHING',
                (key,),
            )
            repeat = not cur.rowcount
        if repeat:
            found = await self._all(
                'SELECT response FROM workflow_runtime.side_effects'
                ' WHERE key = %s',
                (key,),
            )
            # No row: the first call was refused and released the key
            # after this INSERT saw it. Its outcome is still unknown here.
            if not found or found[0]['response'] is None:
                raise fastapi.HTTPException(
                    status_code=409,
                    detail={
                        'error': 'outcome_unknown',
                        'message': 'A call with this idempotency key '
                        'started and did not finish',
                    },
                )
            return typing.cast(dict[str, typing.Any], found[0]['response'])
        try:
            response = await call()
        except fastapi.HTTPException as e:
            if e.status_code < 500:
                async with self._pool.connection() as conn:
                    await conn.execute(
                        'DELETE FROM workflow_runtime.side_effects'
                        ' WHERE key = %s',
                        (key,),
                    )
            raise
        async with self._pool.connection() as conn:
            await conn.execute(
                'UPDATE workflow_runtime.side_effects SET response = %s'
                ' WHERE key = %s',
                (pg_json.Jsonb(response), key),
            )
        return response

    # --- Unknown outcomes (ADR 0021, unknown-outcome reconciliation) ----

    async def stale_side_effects(
        self, organization_id: str, key: str | None = None
    ) -> list[store.Row]:
        """Return the stale side effects of the organization's runs.

        ``key`` returns that one side effect only, if it is stale.
        """
        return await self._all(
            _STALE,
            typing.cast(
                typing.Any,
                {
                    'stale': STALE_AFTER,
                    'org': organization_id,
                    'key': key,
                    'principal': ENGINE_PRINCIPAL,
                },
            ),
        )

    async def resolve_side_effect(
        self,
        key: str,
        response: dict[str, typing.Any] | None,
        retry: tuple[uuid.UUID, str] | None,
    ) -> bool:
        """Resolve a side effect with no response. Never automatic.

        ``response`` is stored as its result, so a repeat of the key gets
        it and does not act; ``None`` deletes the key, so a repeat acts
        again. ``retry`` is a run id and a node id: the run opens again
        and the step runs again, from the start. The steps that the
        failure cancelled are ``pending`` again.

        Return ``False`` and change nothing when the key has a response
        or is gone, or the run or the step changed.
        """
        try:
            async with self._pool.connection() as conn, conn.transaction():
                if response is None:
                    cur = await conn.execute(
                        'DELETE FROM workflow_runtime.side_effects'
                        ' WHERE key = %s AND response IS NULL',
                        (key,),
                    )
                else:
                    cur = await conn.execute(
                        'UPDATE workflow_runtime.side_effects'
                        ' SET response = %s'
                        ' WHERE key = %s AND response IS NULL',
                        (pg_json.Jsonb(response), key),
                    )
                if not cur.rowcount:
                    return False
                if retry is None:
                    return True
                seq = await _reopen(conn, *retry)
        except _ChangedError:
            return False
        await history.publish_since(self._pool, retry[0], seq)
        return True


async def _reopen(conn: typing.Any, run_id: uuid.UUID, node_id: str) -> int:
    """Open a failed run again and run its ``outcome_unknown`` step again.

    Return the run's ``last_seq`` before the change.

    Raises:
        _ChangedError: The run is not failed, is archived, has a running
            run of its concurrency key, or the step did not fail with
            ``outcome_unknown``.

    """
    cur = await conn.execute(
        "UPDATE workflow_runtime.runs AS r SET status = 'running',"
        ' error = NULL, closed_at = NULL, due_at = NOW()'
        " WHERE r.id = %s AND r.status = 'failed'"
        ' AND r.log_archived_at IS NULL'
        # The engine claims a running run before it checks the
        # concurrency key, so do not open a run beside a running one.
        ' AND NOT EXISTS (SELECT 1 FROM workflow_runtime.runs AS o'
        ' WHERE o.workflow_id = r.workflow_id'
        ' AND o.concurrency_key = r.concurrency_key'
        " AND o.status = 'running') RETURNING r.last_seq",
        (run_id,),
    )
    seq = await cur.fetchone()
    step = await conn.execute(
        "UPDATE workflow_runtime.step_runs SET status = 'running',"
        " error = NULL, port = NULL, state = '{}',"
        ' call_started_at = NULL, finished_at = NULL, started_at = NOW()'
        ' WHERE run_id = %s AND node_id = %s'
        " AND status = 'failed' AND error = 'outcome_unknown'",
        (run_id, node_id),
    )
    if seq is None or not step.rowcount:
        raise _ChangedError
    reopened = await conn.execute(
        "UPDATE workflow_runtime.step_runs SET status = 'pending',"
        " finished_at = NULL WHERE run_id = %s AND status = 'cancelled'"
        ' RETURNING node_id',
        (run_id,),
    )
    await runtime.append_event(
        conn, run_id, 'run.retried', {'node_id': node_id}
    )
    await runtime.append_step_event(
        conn, run_id, node_id, 'step.started', retry_of='outcome_unknown'
    )
    for (pending,) in await reopened.fetchall():
        await runtime.append_step_event(conn, run_id, pending, 'step.pending')
    await conn.execute(f'NOTIFY {runtime.NOTIFY_CHANNEL}')
    return int(seq[0])
