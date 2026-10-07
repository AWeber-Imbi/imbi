"""The permanent task log in ClickHouse (ADR 0020).

Every task event goes through Iggy to ``agent_task_events``, and every
budget ledger row to ``agent_usage``, after its Postgres transaction
commits. A publish failure is logged and does not fail the write.

Both tables are ReplacingMergeTree tables keyed on the identity of the
row, so a row that is published two times is stored one time.
"""

import decimal
import logging
import typing

import orjson

from imbi.common import iggy

LOGGER = logging.getLogger(__name__)

type Row = dict[str, typing.Any]

EVENTS_STREAM = 'agent_task_events'
USAGE_STREAM = 'agent_usage'
TOPIC = 'agent_tasks'


def _optional_str(value: typing.Any) -> str | None:
    return None if value is None else str(value)


def event_row(task: Row, event: Row) -> Row:
    """Return the ``agent_task_events`` row of one Postgres event."""
    return {
        'organization_id': task['organization_id'],
        'task_id': str(task['id']),
        'short_id': task['short_id'],
        'agent_id': task['agent_id'],
        'agent_version': task['agent_version'],
        'project_id': task['project_id'] or '',
        'seq': event['seq'],
        'event_id': str(event['event_id']),
        'type': event['type'],
        'schema_version': event['schema_version'],
        'actor_kind': event['actor_kind'],
        'actor_id': event['actor_id'],
        'channel': event['channel'],
        'session_id': _optional_str(event['session_id']),
        'at': event['at'],
        'payload': orjson.dumps(event['payload']).decode(),
    }


def usage_row(task: Row, ledger: Row) -> Row:
    """Return the ``agent_usage`` row of one budget ledger row."""
    row: Row = {
        'organization_id': task['organization_id'],
        'task_id': str(task['id']),
        'short_id': task['short_id'],
        'agent_id': task['agent_id'],
        'project_id': task['project_id'] or '',
        'session_id': _optional_str(ledger['session_id']),
        'report_id': str(ledger['id']),
        'model_id': ledger['model_id'] or '',
        'recorded_at': ledger['recorded_at'],
    }
    for column in (
        'tokens_in',
        'tokens_out',
        'cache_read_tokens',
        'cache_write_tokens',
    ):
        row[column] = ledger[column]
    for column in (
        'input_cost_per_million',
        'output_cost_per_million',
        'cache_read_cost_per_million',
        'cache_write_cost_per_million',
        'cost',
    ):
        # orjson does not encode Decimal. ClickHouse reads a Decimal
        # column from a JSON string with no loss.
        value: decimal.Decimal | None = ledger[column]
        row[column] = None if value is None else str(value)
    return row


async def publish(
    task: Row, events: list[Row], ledger: list[Row] | None = None
) -> None:
    """Publish events and ledger rows of one task. Never raises.

    Call this only after the Postgres transaction that wrote the rows
    commits. A failure is logged; the sweep publishes the rows later.
    """
    try:
        if events:
            await iggy.publish_rows(
                EVENTS_STREAM, TOPIC, [event_row(task, e) for e in events]
            )
        if ledger:
            await iggy.publish_rows(
                USAGE_STREAM, TOPIC, [usage_row(task, row) for row in ledger]
            )
    except Exception:  # noqa: BLE001 - the sweep publishes the rows again
        LOGGER.warning(
            'Agent task %s: publish failed; the sweep retries it',
            task['id'],
            exc_info=True,
        )
