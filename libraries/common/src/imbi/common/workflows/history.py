"""The permanent run log in ClickHouse (ADR 0021, Run history).

Every run event goes through Iggy to ``workflow_run_events`` after its
Postgres transaction commits, and every run state (created, started,
closed) to ``workflow_runs``. A publish failure is logged and does not
fail the write: the archive sweep of imbi-api
(:mod:`imbi.api.workflows.sweeper`) publishes again what ClickHouse does
not have.

A step event carries a snapshot of the step row, so :func:`steps`
rebuilds the step records of a run from its events alone. Run detail
does that for a run whose Postgres log is archived.
"""

import datetime
import logging
import typing
import uuid
from collections import abc

import orjson
import psycopg
import psycopg_pool
from psycopg import rows

from imbi.common import clickhouse, iggy

LOGGER = logging.getLogger(__name__)

type Row = dict[str, typing.Any]
type Pool = psycopg_pool.AsyncConnectionPool[
    psycopg.AsyncConnection[typing.Any]
]

EVENTS_STREAM = 'workflow_run_events'
RUNS_STREAM = 'workflow_runs'
TOPIC = 'workflows'

_EPOCH = '1970-01-01T00:00:00+00:00'

# The latest row of each run, then per workflow. Inner aliases differ
# from the column names: an alias that shadows a column turns the outer
# argMax into an aggregate of an aggregate.
_STATS_QUERY = """
SELECT workflow_id,
       countIf(created >= now64() - INTERVAL 30 DAY) AS runs_30d,
       max(created) AS last_run_at,
       argMax(latest_status, created) AS last_status
FROM (
  SELECT workflow_id, run_id,
         any(run_created_at) AS created,
         argMax(status, _row_version) AS latest_status
  FROM imbi.workflow_runs
  WHERE organization_id = {organization_id:String}
  GROUP BY workflow_id, run_id
)
GROUP BY workflow_id
"""

_SUMMARIES_QUERY = """
SELECT run_id, argMax(status, _row_version) AS latest_status
FROM imbi.workflow_runs
WHERE organization_id = {organization_id:String}
  AND run_id IN {run_ids:Array(String)}
GROUP BY run_id
"""

_EVENT_COUNTS_QUERY = """
SELECT run_id, uniqExact(seq) AS events, min(seq) AS min_seq,
       max(seq) AS max_seq
FROM imbi.workflow_run_events
WHERE organization_id = {organization_id:String}
  AND run_id IN {run_ids:Array(String)}
GROUP BY run_id
"""

_STORED_SEQS_QUERY = """
SELECT DISTINCT seq
FROM imbi.workflow_run_events
WHERE organization_id = {organization_id:String}
  AND run_id = {run_id:String}
"""

_EVENTS_QUERY = """
SELECT seq, type, payload
FROM imbi.workflow_run_events FINAL
WHERE organization_id = {organization_id:String}
  AND run_id = {run_id:String}
ORDER BY seq
"""


def event_row(run: Row, event: Row) -> Row:
    """Return the ``workflow_run_events`` row of one Postgres event."""
    return {
        'organization_id': run['organization_id'],
        'workflow_id': str(run['workflow_id']),
        'run_id': str(run['id']),
        'run_created_at': run['created_at'],
        'seq': event['seq'],
        'event_id': str(event['event_id']),
        'type': event['type'],
        'at': event['at'],
        'payload': orjson.dumps(event['payload']).decode(),
    }


def run_row(run: Row) -> Row:
    """Return the ``workflow_runs`` row of the run's current state."""
    return {
        'organization_id': run['organization_id'],
        'workflow_id': str(run['workflow_id']),
        'run_id': str(run['id']),
        'version': run['version'],
        'origin_kind': run['origin_kind'],
        'origin_id': run['origin_id'],
        'status': run['status'],
        'error': run['error'] or '',
        'run_created_at': run['created_at'],
        'started_at': run['started_at'],
        'closed_at': run['closed_at'],
        '_row_version': run['last_seq'],
    }


async def publish(run: Row, events: list[Row], *, summary: bool) -> None:
    """Publish events of one run, and its summary row. Never raises.

    Call this only after the transaction that wrote the rows commits.
    """
    try:
        if events:
            await iggy.publish_rows(
                EVENTS_STREAM, TOPIC, [event_row(run, e) for e in events]
            )
        if summary:
            await iggy.publish_rows(RUNS_STREAM, TOPIC, [run_row(run)])
    except Exception:  # noqa: BLE001 - the sweep publishes the rows again
        LOGGER.warning(
            'Workflow run %s: publish failed; the sweep retries it',
            run['id'],
            exc_info=True,
        )


async def publish_since(pool: Pool, run_id: uuid.UUID, after_seq: int) -> None:
    """Publish the events of a run after ``after_seq``. Never raises.

    The summary row goes too when a run event is among them.
    """
    try:
        async with (
            pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(
                'SELECT * FROM workflow_runtime.runs WHERE id = %s',
                (run_id,),
            )
            run = await cur.fetchone()
            await cur.execute(
                'SELECT * FROM workflow_runtime.run_events'
                ' WHERE run_id = %s AND seq > %s ORDER BY seq',
                (run_id, after_seq),
            )
            events = await cur.fetchall()
    except Exception:  # noqa: BLE001 - the sweep publishes the rows again
        LOGGER.warning(
            'Workflow run %s: could not read events to publish',
            run_id,
            exc_info=True,
        )
        return
    if run is not None and events:
        summary = any(e['type'].startswith('run.') for e in events)
        await publish(run, events, summary=summary)


def steps(events: abc.Iterable[Row]) -> list[Row]:
    """Rebuild the step records of a run from its events.

    The last step event of a node holds its record. The order is the
    order of the step rows in Postgres: by start, then by node id.
    """
    found: dict[str, Row] = {}
    for event in sorted(events, key=lambda e: e['seq']):
        if event['type'].startswith('step.'):
            found[event['payload']['node_id']] = event['payload']
    # Postgres writes each timestamp in the session's time zone, so
    # compare them as times, not as text.
    return sorted(
        found.values(),
        key=lambda s: (
            s['started_at'] is None,
            datetime.datetime.fromisoformat(s['started_at'] or _EPOCH),
            s['node_id'],
        ),
    )


async def stats(organization_id: str) -> dict[str, Row]:
    """Return runs in 30 days, last run time, and last status, by
    workflow id."""
    found = await clickhouse.query(
        _STATS_QUERY, {'organization_id': organization_id}
    )
    return {
        row['workflow_id']: {
            'runs_30d': int(row['runs_30d']),
            'last_run_at': clickhouse.as_utc(row['last_run_at']),
            'last_status': row['last_status'],
        }
        for row in found
    }


async def summaries(
    organization_id: str, run_ids: list[str]
) -> dict[str, str]:
    """Return the latest status in ClickHouse, by run id."""
    found = await clickhouse.query(
        _SUMMARIES_QUERY,
        {'organization_id': organization_id, 'run_ids': run_ids},
    )
    return {row['run_id']: row['latest_status'] for row in found}


async def event_counts(
    organization_id: str, run_ids: list[str]
) -> dict[str, tuple[int, int, int]]:
    """Return ``(distinct seqs, min seq, max seq)``, by run id."""
    found = await clickhouse.query(
        _EVENT_COUNTS_QUERY,
        {'organization_id': organization_id, 'run_ids': run_ids},
    )
    return {
        row['run_id']: (
            int(row['events']),
            int(row['min_seq']),
            int(row['max_seq']),
        )
        for row in found
    }


async def stored_seqs(run: Row) -> set[int]:
    """Return the seqs of a run that ClickHouse has."""
    found = await clickhouse.query(
        _STORED_SEQS_QUERY,
        {'organization_id': run['organization_id'], 'run_id': str(run['id'])},
    )
    return {int(row['seq']) for row in found}


async def archived_steps(run: Row) -> list[Row]:
    """Return the step records of an archived run, from ClickHouse."""
    found = await clickhouse.query(
        _EVENTS_QUERY,
        {'organization_id': run['organization_id'], 'run_id': str(run['id'])},
    )
    return steps(
        {**row, 'payload': orjson.loads(row['payload'])} for row in found
    )
