"""The permanent ticket log in ClickHouse (ADR 0020, ADR 0028).

Every ticket event goes through Iggy to ``ticket_events``, and every
budget ledger row to ``agent_usage``, after its Postgres transaction
commits. A publish failure is logged and does not fail the write: the
archive sweep (:mod:`imbi.api.tickets.sweeper`) finds the rows that
ClickHouse does not have and publishes them again.

Both tables are ReplacingMergeTree tables keyed on the identity of the
row, so a row that is published two times is stored one time.

Before ADR 0028 events went to ``agent_task_events``. Release B copied
that table to ``ticket_events``, and the release after B dropped it.

Ticket events do not go to the Operations Log. ADR 0020 projected
resolutions and outcomes there (I9, N9); that projection was removed
because ticket closes are not operational events.
"""

import decimal
import logging
import typing
import uuid

import orjson

from imbi.common import clickhouse, iggy

LOGGER = logging.getLogger(__name__)

type Row = dict[str, typing.Any]

EVENTS_STREAM = 'ticket_events'
EVENTS_TOPIC = 'tickets'
USAGE_STREAM = 'agent_usage'
USAGE_TOPIC = 'agent_tasks'

#: The table of ticket events. A row that the sweep published again can
#: be in it two times until a merge, so a read that needs each event one
#: time removes the copies with ``LIMIT 1 BY ticket_id, seq``.
EVENTS = 'imbi.ticket_events'

_ARCHIVED_EVENTS_QUERY = f"""
SELECT event_id, seq, type, schema_version, actor_kind, actor_id, channel,
       session_id, at, payload
FROM {EVENTS}
WHERE organization_id = {{organization_id:String}}
  AND ticket_id = {{ticket_id:String}}
  AND seq > {{after_seq:UInt64}}
  AND seq <= {{until_seq:UInt64}}
ORDER BY seq
LIMIT 1 BY seq
LIMIT {{limit:UInt32}}
"""  # noqa: S608 - EVENTS is a constant

_LAST_AGENT_TURN_QUERY = f"""
SELECT JSONExtractString(payload, 'body') AS body
FROM {EVENTS}
WHERE organization_id = {{organization_id:String}}
  AND ticket_id = {{ticket_id:String}}
  AND type = 'turn'
  AND actor_kind = 'agent'
ORDER BY seq DESC
LIMIT 1
"""  # noqa: S608 - EVENTS is a constant

#: The comments (human turns), handoffs, reopens, and the last agent
#: ``text`` turn of each session of a ticket up to a seq, for the
#: history of a new session (ADR 0028).
_HISTORY_QUERY = f"""
SELECT type, at, actor_id, actor_kind, payload
FROM (
    SELECT seq, type, at, actor_id, actor_kind, payload
    FROM {EVENTS}
    WHERE organization_id = {{organization_id:String}}
      AND ticket_id = {{ticket_id:String}}
      AND seq <= {{until_seq:UInt64}}
      AND ((type = 'turn' AND actor_kind = 'human')
           OR type IN ('handed_off', 'reopened'))
    ORDER BY seq
    LIMIT 1 BY seq
    UNION ALL
    SELECT seq, type, at, actor_id, actor_kind, payload
    FROM {EVENTS}
    WHERE organization_id = {{organization_id:String}}
      AND ticket_id = {{ticket_id:String}}
      AND seq <= {{until_seq:UInt64}}
      AND type = 'turn'
      AND actor_kind = 'agent'
      AND JSONExtractString(payload, 'kind') = 'text'
    ORDER BY seq DESC
    LIMIT 1 BY session_id
)
ORDER BY seq
"""  # noqa: S608 - EVENTS is a constant

_EVENT_COUNTS_QUERY = f"""
SELECT ticket_id, uniqExact(seq) AS events, max(seq) AS max_seq
FROM {EVENTS}
WHERE organization_id = {{organization_id:String}}
  AND ticket_id IN (SELECT id FROM task_ids)
GROUP BY ticket_id
"""  # noqa: S608 - EVENTS is a constant

_USAGE_COUNTS_QUERY = """
SELECT task_id, uniqExact(report_id) AS reports
FROM imbi.agent_usage
WHERE organization_id = {organization_id:String}
  AND task_id IN (SELECT id FROM task_ids)
GROUP BY task_id
"""

_STORED_SEQS_QUERY = f"""
SELECT DISTINCT seq
FROM {EVENTS}
WHERE organization_id = {{organization_id:String}}
  AND ticket_id = {{ticket_id:String}}
"""  # noqa: S608 - EVENTS is a constant

_STORED_REPORTS_QUERY = """
SELECT DISTINCT report_id
FROM imbi.agent_usage
WHERE organization_id = {organization_id:String}
  AND task_id = {task_id:String}
"""


def _optional_str(value: typing.Any) -> str | None:
    return None if value is None else str(value)


def _project_ids(task: Row) -> str:
    """The ids of the projects of a task, comma separated."""
    return ','.join(project['project_id'] for project in task['projects'])


def event_row(task: Row, event: Row) -> Row:
    """Return the ``ticket_events`` row of one Postgres event."""
    return {
        'organization_id': task['organization_id'],
        'ticket_id': str(task['id']),
        'short_id': task['short_id'],
        # Empty on a person ticket: the ClickHouse columns are not
        # nullable (ADR 0028).
        'agent_id': task['agent_id'] or '',
        'agent_version': task['agent_version'] or 0,
        'project_id': _project_ids(task),
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
        'project_id': _project_ids(task),
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
                EVENTS_STREAM,
                EVENTS_TOPIC,
                [event_row(task, e) for e in events],
            )
        if ledger:
            await iggy.publish_rows(
                USAGE_STREAM,
                USAGE_TOPIC,
                [usage_row(task, row) for row in ledger],
            )
    except Exception:  # noqa: BLE001 - the sweep publishes the rows again
        LOGGER.warning(
            'Ticket %s: publish failed; the sweep retries it',
            task['id'],
            exc_info=True,
        )


async def archived_events(
    task: Row, after_seq: int, limit: int, until_seq: int | None = None
) -> list[Row]:
    """Return events of an archived task from ClickHouse, by seq.

    ``until_seq`` is the last seq to read; the default is ``last_seq``.
    The rows have the shape of ``tickets.events`` rows.
    """
    rows = await clickhouse.query(
        _ARCHIVED_EVENTS_QUERY,
        {
            'organization_id': task['organization_id'],
            'ticket_id': str(task['id']),
            'after_seq': after_seq,
            'until_seq': task['last_seq'] if until_seq is None else until_seq,
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


async def archived_history(task: Row, until_seq: int) -> list[Row]:
    """Return the human turns, ``handed_off``, and ``reopened`` events,
    and the last agent ``text`` turn of each session, of a task in
    ClickHouse up to ``until_seq``, by seq, in the shape of
    :meth:`imbi.api.tickets.store.TicketStore.history`."""
    rows = await clickhouse.query(
        _HISTORY_QUERY,
        {
            'organization_id': task['organization_id'],
            'ticket_id': str(task['id']),
            'until_seq': until_seq,
        },
    )
    return [
        {
            **row,
            'at': clickhouse.as_utc(row['at']),
            'payload': orjson.loads(row['payload']),
        }
        for row in rows
    ]


async def last_archived_agent_turn(task: Row) -> str | None:
    """Return the body of the newest agent ``turn`` of an archived task.

    ``None`` when the agent wrote no turn.
    """
    rows = await clickhouse.query(
        _LAST_AGENT_TURN_QUERY,
        {
            'organization_id': task['organization_id'],
            'ticket_id': str(task['id']),
        },
    )
    return str(rows[0]['body']) if rows else None


async def event_counts(
    organization_id: str, task_ids: list[str]
) -> dict[str, tuple[int, int]]:
    """Return ``(distinct seqs, max seq)`` in ClickHouse, by task id."""
    rows = await clickhouse.query(
        _EVENT_COUNTS_QUERY,
        {'organization_id': organization_id},
        tables={'task_ids': task_ids},
    )
    return {
        row['ticket_id']: (int(row['events']), int(row['max_seq']))
        for row in rows
    }


async def usage_counts(
    organization_id: str, task_ids: list[str]
) -> dict[str, int]:
    """Return the number of distinct usage reports in ClickHouse."""
    rows = await clickhouse.query(
        _USAGE_COUNTS_QUERY,
        {'organization_id': organization_id},
        tables={'task_ids': task_ids},
    )
    return {row['task_id']: int(row['reports']) for row in rows}


async def stored_seqs(task: Row) -> set[int]:
    """Return the seqs of a task that ClickHouse has."""
    rows = await clickhouse.query(
        _STORED_SEQS_QUERY,
        {
            'organization_id': task['organization_id'],
            'ticket_id': str(task['id']),
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
