"""The record of each plugin step call (ADR 0032).

``workflow_runtime.plugin_step_calls`` holds one row for each call of
``POST .../workflow-steps/{name}/run``. :meth:`PluginCallStore.start`
inserts a ``running`` row before the plugin is called, so a repeat of
the idempotency key finds that row and makes no second call. The same
model as :mod:`imbi.api.model_calls`.
"""

import typing
import uuid

from psycopg import rows
from psycopg.types import json as pg_json

from imbi.api.workflows import store
from imbi.common.workflows import runtime

#: Rows older than this are deleted by ``plugin-step-calls-prune``,
#: except the rows of a workflow run that is still open.
RETENTION = '90 days'

_START: typing.LiteralString = """
INSERT INTO workflow_runtime.plugin_step_calls (
    id, organization_id, principal, idempotency_key, run_id,
    integration_slug, step_type
) VALUES (
    %(id)s, %(organization_id)s, %(principal)s, %(idempotency_key)s,
    %(run_id)s, %(integration_slug)s, %(step_type)s
)
ON CONFLICT (organization_id, principal, idempotency_key) DO UPDATE
SET status = CASE
    WHEN plugin_step_calls.status = 'running'
     AND plugin_step_calls.started_at
         < NOW() - make_interval(secs => %(stale)s)
    THEN 'outcome_unknown'
    ELSE plugin_step_calls.status
END
RETURNING *, (xmax = 0) AS inserted
"""


class PluginCallStore:
    """Reads and writes ``workflow_runtime.plugin_step_calls``."""

    def __init__(self, pool: store.Pool) -> None:
        self._pool = pool

    async def start(
        self, call: store.Row, stale_after: float
    ) -> tuple[store.Row, bool]:
        """Insert ``call`` as a ``running`` row.

        Return the row and ``True`` for a new row. For a repeat of the
        idempotency key, return the row of the first call and ``False``.
        A ``running`` first call older than ``stale_after`` seconds is
        set to ``outcome_unknown`` first: it will not finish now.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(
                _START, {**call, 'id': uuid.uuid4(), 'stale': stale_after}
            )
            row = typing.cast('store.Row', await cur.fetchone())
        return row, bool(row.pop('inserted'))

    async def finish(
        self,
        call_id: uuid.UUID,
        *,
        result: dict[str, typing.Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Close a ``running`` call: ``done`` with ``result``, else
        ``failed`` with ``error``.

        ``done`` also replaces ``outcome_unknown``: a repeat can mark the
        call stale while its finish waits for the database, and the
        result must stay available by its idempotency key.
        """
        status = 'failed' if error else 'done'
        async with self._pool.connection() as conn:
            await conn.execute(
                'UPDATE workflow_runtime.plugin_step_calls'
                ' SET status = %s, result = %s, error = %s,'
                ' finished_at = NOW()'
                " WHERE id = %s AND (status = 'running'"
                " OR (status = 'outcome_unknown' AND %s = 'done'))",
                (
                    status,
                    None if result is None else pg_json.Jsonb(result),
                    error,
                    call_id,
                    status,
                ),
            )

    async def prune(self) -> int:
        """Delete the calls older than :data:`RETENTION`, except those
        of an open workflow run; return the count."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                'DELETE FROM workflow_runtime.plugin_step_calls c'
                ' WHERE c.started_at < NOW() - %s::interval'
                ' AND NOT EXISTS (SELECT 1 FROM workflow_runtime.runs r'
                ' WHERE r.id::text = c.run_id'
                ' AND NOT (r.status = ANY(%s)))',
                (RETENTION, list(runtime.CLOSED)),
            )
            return cur.rowcount
