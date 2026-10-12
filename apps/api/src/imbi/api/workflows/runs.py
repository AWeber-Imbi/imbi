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
from imbi.common.workflows import runtime


def side_effect_key(principal: str, action: str, idempotency_key: str) -> str:
    """Return the ``side_effects`` key. JSON, so no part can run into
    the next one."""
    return json.dumps([principal, action, idempotency_key])


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
