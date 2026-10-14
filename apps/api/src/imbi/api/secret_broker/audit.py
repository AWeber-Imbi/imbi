"""Secret audit events (ADR 0022, plan section 9.9).

Each step writes one event through Iggy to the ClickHouse table
``secret_audit_events``, which has no TTL. An event holds ids, purpose,
delivery mode, result, and a safe reason code. It never holds material,
field values, handles, lease ids, authorization headers, or command
arguments: :class:`Event` has no field for any of them.

An event is not lost when Iggy is down: the operation writes it to the
outbox table ``secrets.audit_outbox`` in its own transaction
(:func:`write`). The broker sweep publishes the outbox rows
(:func:`flush`) and deletes each row only after Iggy accepts it. A row
that is published two times collapses in ClickHouse, which keys the
table on ``event_id``.
"""

import asyncio
import datetime
import logging
import typing
import uuid

import psycopg
import psycopg_pool
import pydantic
from psycopg.types import json as pg_json

from imbi.common import clickhouse, iggy

LOGGER = logging.getLogger(__name__)

STREAM = 'secret_audit_events'
TOPIC = 'secrets'

EventType = typing.Literal[
    'secret_provider_created',
    'secret_provider_updated',
    'secret_provider_deleted',
    'secret_provider_tested',
    'secret_binding_created',
    'secret_binding_updated',
    'secret_binding_deleted',
    'secret_grant_created',
    'secret_grant_updated',
    'secret_grant_deleted',
    'secret_resolution_allowed',
    'secret_resolution_denied',
    'secret_resolution_released',
    'secret_resolution_expired',
    'secret_materialized',
    'secret_lease_renewed',
    'secret_lease_revoked',
    'secret_lease_revocation_failed',
]
Result = typing.Literal['allowed', 'denied', 'succeeded', 'failed']


class Event(pydantic.BaseModel):
    event_id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    at: datetime.datetime = pydantic.Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )
    organization_id: str
    type: EventType
    result: Result = 'succeeded'
    reason: str = ''
    #: The principal name of a person, or ``runner:<id>``, or ``system``.
    actor: str = ''
    agent_id: str = ''
    project_id: str = ''
    task_id: str = ''
    runner_id: str = ''
    provider_id: str = ''
    binding_id: str = ''
    grant_id: str = ''
    resolution_id: str = ''
    purpose: str = ''
    delivery_mode: str = ''


type Conn = psycopg.AsyncConnection[typing.Any]
type Pool = psycopg_pool.AsyncConnectionPool[Conn]

#: The most outbox rows that one publish sends.
FLUSH_BATCH = 500
#: The longest wait for Iggy to accept one batch. Well under the 30 s
#: sweep interval. A timeout is a failure: the rows stay.
PUBLISH_TIMEOUT_SECONDS = 10


async def write(conn: Conn, events: list[Event]) -> None:
    """Add events to the outbox in the transaction of ``conn``."""
    if not events:
        return
    async with conn.cursor() as cur:
        await cur.executemany(
            'INSERT INTO secrets.audit_outbox (event_id, event)'
            ' VALUES (%s, %s)',
            [
                (e.event_id, pg_json.Jsonb(e.model_dump(mode='json')))
                for e in events
            ],
        )


async def record(pool: Pool, events: list[Event]) -> None:
    """Add events to the outbox in a transaction of their own.

    For an event whose operation has no transaction that commits (a
    denial), or that committed before the event was known.
    """
    if not events:
        return
    async with pool.connection() as conn, conn.transaction():
        await write(conn, events)


async def flush(pool: Pool) -> int:
    """Publish the outbox to Iggy, oldest first; return the count.

    Each batch is locked ``FOR UPDATE SKIP LOCKED``, so two instances
    do not publish one row, and is deleted only after Iggy accepts it.

    Raises:
        Exception: Iggy refused a batch, or did not accept it in
            :data:`PUBLISH_TIMEOUT_SECONDS` (``TimeoutError``). Its rows
            stay in the outbox.

    """
    total = 0
    while True:
        async with pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                'SELECT event_id, event FROM secrets.audit_outbox'
                ' ORDER BY seq LIMIT %s FOR UPDATE SKIP LOCKED',
                (FLUSH_BATCH,),
            )
            found = await cur.fetchall()
            if not found:
                return total
            # The rows stay locked during the send, so it has a limit.
            async with asyncio.timeout(PUBLISH_TIMEOUT_SECONDS):
                await iggy.publish(
                    STREAM,
                    TOPIC,
                    [Event.model_validate(event) for _, event in found],
                )
            await conn.execute(
                'DELETE FROM secrets.audit_outbox WHERE event_id = ANY(%s)',
                ([event_id for event_id, _ in found],),
            )
        total += len(found)
        if len(found) < FLUSH_BATCH:
            return total


_QUERY = """
SELECT *
FROM imbi.secret_audit_events
WHERE organization_id = {organization_id:String}
  AND ({resolution_id:String} = '' OR resolution_id = {resolution_id:String})
  AND ({type:String} = '' OR type = {type:String})
  AND (at < {before:DateTime64(6, 'UTC')}
       OR ({before_event_id:String} != ''
           AND at = {before:DateTime64(6, 'UTC')}
           AND event_id > {before_event_id:String}))
ORDER BY at DESC, event_id
LIMIT {limit:UInt32}
"""


async def search(
    organization_id: str,
    *,
    resolution_id: str = '',
    event_type: str = '',
    before: datetime.datetime | None = None,
    before_event_id: str = '',
    limit: int = 100,
) -> list[dict[str, typing.Any]]:
    """Return the newest events of an organization first.

    The cursor is ``(before, before_event_id)``, in the order of the
    query (``at`` descending, then ``event_id``). Without an event id,
    ``before`` is strict.
    """
    rows = await clickhouse.query(
        _QUERY,
        {
            'organization_id': organization_id,
            'resolution_id': resolution_id,
            'type': event_type,
            'before': before or datetime.datetime.now(datetime.UTC),
            'before_event_id': before_event_id,
            'limit': limit,
        },
    )
    return [{**row, 'at': clickhouse.as_utc(row['at'])} for row in rows]
