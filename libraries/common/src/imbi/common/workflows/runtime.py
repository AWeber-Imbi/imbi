"""The ``workflow_runtime`` schema that imbi-api and the engine share.

imbi-api owns and applies the schema; it creates and cancels runs. The
engine executes them. Both write run events with :func:`append_event`,
so the per-run sequence is the same whoever writes.
"""

import typing
import uuid

import psycopg
from psycopg.types import json as pg_json

SCHEMA = 'workflow_runtime'

#: ``NOTIFY`` channel that wakes the engine. A hint only: it polls.
NOTIFY_CHANNEL = 'workflow_runs'

#: Run statuses that are final.
CLOSED = ('succeeded', 'failed', 'cancelled', 'timed_out')

#: ``NOTIFY`` channel that wakes the trigger reconciler. A hint only: it
#: also runs on a schedule.
BINDINGS_CHANNEL = 'workflow_bindings'


async def pause_bindings(
    conn: psycopg.AsyncConnection[typing.Any], workflow_id: uuid.UUID
) -> None:
    """Disable the trigger bindings of a workflow that pauses.

    Call it in the transaction that pauses the workflow.
    """
    await conn.execute(
        'UPDATE workflows.trigger_bindings SET enabled = FALSE,'
        " sync_state = 'pending', updated_at = NOW()"
        ' WHERE workflow_id = %s',
        (workflow_id,),
    )
    await conn.execute(f'NOTIFY {BINDINGS_CHANNEL}')


async def append_event(
    conn: psycopg.AsyncConnection[typing.Any],
    run_id: uuid.UUID,
    event_type: str,
    payload: dict[str, typing.Any],
) -> None:
    """Write the next event of a run. Call it in the run's transaction.

    The ``UPDATE`` of ``last_seq`` locks the run row, so the sequence
    has no gaps.
    """
    cur = await conn.execute(
        'UPDATE workflow_runtime.runs SET last_seq = last_seq + 1'
        ' WHERE id = %s RETURNING last_seq',
        (run_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise LookupError(f'No run {run_id}')
    await conn.execute(
        'INSERT INTO workflow_runtime.run_events'
        ' (run_id, seq, event_id, type, payload)'
        ' VALUES (%s, %s, %s, %s, %s)',
        (run_id, row[0], uuid.uuid4(), event_type, pg_json.Jsonb(payload)),
    )
