"""The record of each generative AI model call (LLM Call step plan, D6).

The ``ai_runtime`` schema holds one row for each call that
``POST /organizations/{org}/prompts/run`` makes to a generative model.
It is a plain Postgres schema next to the graph, managed like
``tickets``: the declarative ``schemata.toml`` is applied on every
start.

A caller that sends an idempotency key gets one model call for that
key: :meth:`ModelCallStore.start` inserts a ``running`` row, and a
repeat of the key finds that row instead of a new call.
"""

import contextlib
import decimal
import pathlib
import typing
import uuid
from collections import abc

import fastapi
import psycopg
import psycopg_pool
from psycopg import rows
from psycopg.types import json as pg_json

from imbi.api.tickets import create_pool
from imbi.common import lifespan, relational
from imbi.common.workflows import runtime

type Pool = psycopg_pool.AsyncConnectionPool[
    psycopg.AsyncConnection[typing.Any]
]
type Row = dict[str, typing.Any]

SCHEMA = 'ai_runtime'
SCHEMATA_PATH = pathlib.Path(__file__).parent / 'schemata.toml'

#: Rows older than this are deleted by ``ai-model-calls-prune``, except
#: the rows of a workflow run that is still open: a run has no upper
#: time limit, and its steps reuse their keys.
RETENTION = '90 days'

_INSERT: typing.LiteralString = """
INSERT INTO ai_runtime.ai_model_calls (
    id, organization_id, principal, origin, run_id, node_id, attempt,
    idempotency_key, prompt_ref, prompt_version, content_sha256, model,
    model_id, driver, system, messages, output_schema
) VALUES (
    %(id)s, %(organization_id)s, %(principal)s, %(origin)s, %(run_id)s,
    %(node_id)s, %(attempt)s, %(idempotency_key)s, %(prompt_ref)s,
    %(prompt_version)s, %(content_sha256)s, %(model)s, %(model_id)s,
    %(driver)s, %(system)s, %(messages)s, %(output_schema)s
)
ON CONFLICT (organization_id, principal, idempotency_key) DO UPDATE
SET status = CASE
    WHEN ai_model_calls.status = 'running'
     AND ai_model_calls.started_at
         < NOW() - make_interval(secs => %(stale)s)
    THEN 'outcome_unknown'
    ELSE ai_model_calls.status
END
RETURNING *, (xmax = 0) AS inserted
"""

_REPEAT: typing.LiteralString = """
UPDATE ai_runtime.ai_model_calls
SET status = CASE
    WHEN status = 'running'
     AND started_at < NOW() - make_interval(secs => %(stale)s)
    THEN 'outcome_unknown'
    ELSE status
END
WHERE organization_id = %(organization_id)s
  AND principal = %(principal)s
  AND idempotency_key = %(idempotency_key)s
RETURNING *
"""


class ModelCallStore:
    """Reads and writes ``ai_runtime.ai_model_calls``."""

    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def start(self, call: Row, stale_after: float) -> tuple[Row, bool]:
        """Insert ``call`` as a ``running`` row.

        Return the row and ``True`` for a new row. For a repeat of the
        idempotency key, return the row of the first call and ``False``.
        A ``running`` first call that started more than ``stale_after``
        seconds ago is set to ``outcome_unknown`` first: it may or may
        not have reached the model, and it will not finish now.
        """
        values = {
            **call,
            'id': uuid.uuid4(),
            'messages': pg_json.Jsonb(call['messages']),
            'output_schema': pg_json.Jsonb(call['output_schema']),
        }
        async with (
            self._pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await relational.lock_organization_shared(
                conn, str(call['organization_id'])
            )
            await cur.execute(_INSERT, {**values, 'stale': stale_after})
            row = typing.cast('Row', await cur.fetchone())
        return row, bool(row.pop('inserted'))

    async def repeat(
        self,
        organization_id: str,
        principal: str,
        idempotency_key: str,
        stale_after: float,
    ) -> Row | None:
        """Return the row of an earlier call with the idempotency key.

        Return ``None`` when no call has the key. Set a stale
        ``running`` row to ``outcome_unknown`` first, as :meth:`start`
        does.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(
                _REPEAT,
                {
                    'organization_id': organization_id,
                    'principal': principal,
                    'idempotency_key': idempotency_key,
                    'stale': stale_after,
                },
            )
            return await cur.fetchone()

    async def finish(
        self,
        call_id: uuid.UUID,
        status: str,
        *,
        error: str | None = None,
        text: str | None = None,
        result: dict[str, typing.Any] | None = None,
        usage: dict[str, typing.Any] | None = None,
        cost_usd: decimal.Decimal | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        """Close the call, unless it is no longer ``running``.

        A success also replaces ``outcome_unknown``: a repeat can mark
        the call stale while its finish waits for the database, and the
        answer must stay available by its idempotency key.
        """
        async with self._pool.connection() as conn:
            await conn.execute(
                'UPDATE ai_runtime.ai_model_calls'
                ' SET status = %s, error = %s, text = %s, result = %s,'
                ' usage = %s, cost_usd = %s, provider_request_id = %s,'
                ' finished_at = NOW()'
                " WHERE id = %s AND (status = 'running'"
                " OR (status = 'outcome_unknown' AND %s = 'succeeded'))",
                (
                    status,
                    error,
                    text,
                    None if result is None else pg_json.Jsonb(result),
                    pg_json.Jsonb(usage or {}),
                    cost_usd,
                    provider_request_id,
                    call_id,
                    status,
                ),
            )

    async def prune(self) -> int:
        """Delete the calls older than :data:`RETENTION`, except those
        of an open workflow run; return the count."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                'DELETE FROM ai_runtime.ai_model_calls c'
                ' WHERE c.started_at < NOW() - %s::interval'
                ' AND NOT EXISTS (SELECT 1 FROM workflow_runtime.runs r'
                ' WHERE r.id::text = c.run_id'
                ' AND NOT (r.status = ANY(%s)))',
                (RETENTION, list(runtime.CLOSED)),
            )
            return cur.rowcount


_store: ModelCallStore | None = None


async def initialize() -> None:
    """Create the ``ai_runtime`` schema, tables, and indexes."""
    await relational.initialize_deleted_organizations()
    await relational.initialize(
        SCHEMA,
        relational.load_schemata(SCHEMATA_PATH),
        f'imbi.api.initialize.{SCHEMA}',
    )


@contextlib.asynccontextmanager
async def store_lifespan() -> abc.AsyncGenerator[ModelCallStore]:
    """Initialize the schema and hold the store open."""
    global _store
    await initialize()
    pool = create_pool()
    try:
        await pool.open()
        _store = ModelCallStore(pool)
        try:
            yield _store
        finally:
            _store = None
    finally:
        await pool.close()


def get_store() -> ModelCallStore:
    """Return the store that :func:`store_lifespan` opened, for code
    outside a request (the maintenance worker)."""
    if _store is None:
        raise RuntimeError('store_lifespan has not opened the store')
    return _store


async def _inject_store(
    context: lifespan.InjectLifespan,
) -> abc.AsyncIterator[ModelCallStore]:
    yield context.get_state(store_lifespan)


Store = typing.Annotated[ModelCallStore, fastapi.Depends(_inject_store)]
