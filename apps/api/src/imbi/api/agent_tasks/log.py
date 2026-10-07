"""The permanent task log in ClickHouse (ADR 0020).

Every task event goes through Iggy to ``agent_task_events``, and every
budget ledger row to ``agent_usage``, after its Postgres transaction
commits. A publish failure is logged and does not fail the write: the
archive sweep (:mod:`imbi.api.agent_tasks.sweeper`) finds the rows that
ClickHouse does not have and publishes them again.

Both tables are ReplacingMergeTree tables keyed on the identity of the
row, so a row that is published two times is stored one time.
"""

import decimal
import logging
import typing
import uuid

import orjson

from imbi.common import clickhouse, iggy

LOGGER = logging.getLogger(__name__)

type Row = dict[str, typing.Any]

EVENTS_STREAM = 'agent_task_events'
USAGE_STREAM = 'agent_usage'
TOPIC = 'agent_tasks'

_ARCHIVED_EVENTS_QUERY = """
SELECT event_id, seq, type, schema_version, actor_kind, actor_id, channel,
       session_id, at, payload
FROM imbi.agent_task_events FINAL
WHERE organization_id = {organization_id:String}
  AND task_id = {task_id:String}
  AND seq > {after_seq:UInt64}
ORDER BY seq
LIMIT {limit:UInt32}
"""

_EVENT_COUNTS_QUERY = """
SELECT task_id, uniqExact(seq) AS events, max(seq) AS max_seq
FROM imbi.agent_task_events
WHERE organization_id = {organization_id:String}
  AND task_id IN {task_ids:Array(String)}
GROUP BY task_id
"""

_USAGE_COUNTS_QUERY = """
SELECT task_id, uniqExact(report_id) AS reports
FROM imbi.agent_usage
WHERE organization_id = {organization_id:String}
  AND task_id IN {task_ids:Array(String)}
GROUP BY task_id
"""

_STORED_SEQS_QUERY = """
SELECT DISTINCT seq
FROM imbi.agent_task_events
WHERE organization_id = {organization_id:String}
  AND task_id = {task_id:String}
"""

_STORED_REPORTS_QUERY = """
SELECT DISTINCT report_id
FROM imbi.agent_usage
WHERE organization_id = {organization_id:String}
  AND task_id = {task_id:String}
"""


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


async def archived_events(task: Row, after_seq: int, limit: int) -> list[Row]:
    """Return events of an archived task from ClickHouse, by seq.

    The rows have the shape of ``agent_runtime.events`` rows.
    """
    rows = await clickhouse.query(
        _ARCHIVED_EVENTS_QUERY,
        {
            'organization_id': task['organization_id'],
            'task_id': str(task['id']),
            'after_seq': after_seq,
            'limit': limit,
        },
    )
    return [
        {
            **row,
            'event_id': uuid.UUID(row['event_id']),
            'session_id': (
                None
                if row['session_id'] is None
                else uuid.UUID(row['session_id'])
            ),
            'at': clickhouse.as_utc(row['at']),
            'payload': orjson.loads(row['payload']),
        }
        for row in rows
    ]


async def event_counts(
    organization_id: str, task_ids: list[str]
) -> dict[str, tuple[int, int]]:
    """Return ``(distinct seqs, max seq)`` in ClickHouse, by task id."""
    rows = await clickhouse.query(
        _EVENT_COUNTS_QUERY,
        {'organization_id': organization_id, 'task_ids': task_ids},
    )
    return {
        row['task_id']: (int(row['events']), int(row['max_seq']))
        for row in rows
    }


async def usage_counts(
    organization_id: str, task_ids: list[str]
) -> dict[str, int]:
    """Return the number of distinct usage reports in ClickHouse."""
    rows = await clickhouse.query(
        _USAGE_COUNTS_QUERY,
        {'organization_id': organization_id, 'task_ids': task_ids},
    )
    return {row['task_id']: int(row['reports']) for row in rows}


async def stored_seqs(task: Row) -> set[int]:
    """Return the seqs of a task that ClickHouse has."""
    rows = await clickhouse.query(
        _STORED_SEQS_QUERY,
        {
            'organization_id': task['organization_id'],
            'task_id': str(task['id']),
        },
    )
    return {int(row['seq']) for row in rows}


async def stored_reports(task: Row) -> set[str]:
    """Return the usage report ids of a task that ClickHouse has."""
    rows = await clickhouse.query(
        _STORED_REPORTS_QUERY,
        {
            'organization_id': task['organization_id'],
            'task_id': str(task['id']),
        },
    )
    return {str(row['report_id']) for row in rows}
