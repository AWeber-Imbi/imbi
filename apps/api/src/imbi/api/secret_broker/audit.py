"""Secret audit events (ADR 0022, plan section 9.9).

Each step writes one event through Iggy to the ClickHouse table
``secret_audit_events``, which has no TTL. An event holds ids, purpose,
delivery mode, result, and a safe reason code. It never holds material,
field values, handles, lease ids, authorization headers, or command
arguments: :class:`Event` has no field for any of them.

Events go after the Postgres commit. A publish failure is logged and
does not fail the operation.
"""

import datetime
import logging
import typing
import uuid

import pydantic

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


async def publish(events: list[Event]) -> None:
    """Publish audit events. Never raises."""
    if not events:
        return
    try:
        await iggy.publish(STREAM, TOPIC, list[pydantic.BaseModel](events))
    except Exception:  # noqa: BLE001 - audit must not fail the operation
        LOGGER.warning(
            'Secret audit publish failed for %d events (%s)',
            len(events),
            ', '.join(sorted({e.type for e in events})),
            exc_info=True,
        )


_QUERY = """
SELECT *
FROM imbi.secret_audit_events
WHERE organization_id = {organization_id:String}
  AND ({resolution_id:String} = '' OR resolution_id = {resolution_id:String})
  AND ({type:String} = '' OR type = {type:String})
  AND at < {before:DateTime64(6, 'UTC')}
ORDER BY at DESC, event_id
LIMIT {limit:UInt32}
"""


async def search(
    organization_id: str,
    *,
    resolution_id: str = '',
    event_type: str = '',
    before: datetime.datetime | None = None,
    limit: int = 100,
) -> list[dict[str, typing.Any]]:
    """Return the newest events of an organization first."""
    rows = await clickhouse.query(
        _QUERY,
        {
            'organization_id': organization_id,
            'resolution_id': resolution_id,
            'type': event_type,
            'before': before or datetime.datetime.now(datetime.UTC),
            'limit': limit,
        },
    )
    return [{**row, 'at': clickhouse.as_utc(row['at'])} for row in rows]
