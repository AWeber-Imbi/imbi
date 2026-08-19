"""Durable activity log for global maintenance operations.

Valkey stays authoritative for the *live* run -- counters, the pending
set, the lock. This module is the durable history of what the run did,
in the ClickHouse ``maintenance_log`` table, so a failure is still
answerable ("which project, and why?") long after the Valkey keys have
expired.

Three kinds of row, told apart by ``event_type``:

- ``run`` -- :func:`record_run`, once per finished run, carrying the
  final Valkey counters;
- ``attempt`` -- :meth:`ItemLog.attempt`, once per project per claim,
  written by the worker whatever the outcome;
- ``activity`` -- :meth:`ItemLog.record`, whatever the operation itself
  chose to say while working on that attempt.

Every write here is **best-effort**: the log is observability, not the
product, and a ClickHouse outage must never fail maintenance work or
wedge a run. Callers get no exception and no return value to check.

``record`` only buffers, so an operation can call it inside a loop
without paying a round trip per row; the worker flushes the buffer once
per item. The insert asks the server to batch (``async_insert``) because
a full sweep is tens of thousands of flushes, and one MergeTree part per
flush is how a table earns a "too many parts" complaint.
"""

from __future__ import annotations

import dataclasses
import logging
import typing

import orjson
import pydantic

from imbi.common import clickhouse, models

LOGGER = logging.getLogger(__name__)

TABLE = 'maintenance_log'

#: Let the server coalesce the many small inserts a sweep produces.
#: ``wait_for_async_insert`` keeps failures observable rather than
#: swallowing rows into a buffer nobody watches.
INSERT_SETTINGS: dict[str, typing.Any] = {
    'async_insert': 1,
    'wait_for_async_insert': 1,
}

MAX_MESSAGE_LEN = 2_000
MAX_DETAIL_BYTES = 8_192

#: Outcome of one attempt or activity. ``deferred`` is a rate-limit
#: requeue -- claimed, paused, handed back -- which is neither a failure
#: nor work done.
Disposition = typing.Literal['succeeded', 'skipped', 'failed', 'deferred']

#: Outcome of a whole run. ``abandoned`` is derived in Valkey from a
#: lapsed lock and is never written here: an abandoned run is one that
#: never reached a terminal row.
RunDisposition = typing.Literal['completed', 'cancelled']


def _sanitize_detail(detail: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Coerce *detail* to something the JSON column will accept.

    Values that will not serialize become their ``str()``; a payload over
    :data:`MAX_DETAIL_BYTES` is dropped entirely for a ``_truncated``
    marker, rather than failing the write. Callers pass ids, counts, and
    statuses they chose -- never raw remote payloads -- so this is a
    backstop, not a redaction pass.
    """
    if not detail:
        return {}
    coerced: dict[str, typing.Any] = {}
    for key, value in detail.items():
        try:
            orjson.dumps(value)
        except TypeError:
            value = str(value)
        coerced[str(key)] = value
    if len(orjson.dumps(coerced)) > MAX_DETAIL_BYTES:
        return {'_truncated': True}
    return coerced


async def _write(rows: list[models.MaintenanceLogRecord]) -> None:
    """Insert *rows*, swallowing every failure."""
    if not rows:
        return
    try:
        # ``insert`` takes ``list[BaseModel]``, which is invariant, so a
        # list of one concrete model type does not satisfy it directly.
        await clickhouse.insert(
            TABLE,
            typing.cast('list[pydantic.BaseModel]', rows),
            settings=INSERT_SETTINGS,
        )
    except Exception:
        LOGGER.exception(
            'maintenance log write dropped %d row(s) for run %s',
            len(rows),
            rows[0].run_id,
        )


async def record_run(
    slug: str,
    run_id: str,
    disposition: RunDisposition,
    started_by: str = '',
    **detail: typing.Any,
) -> None:
    """Write the terminal row for a whole run.

    ``detail`` carries the run's final Valkey counters, which are the
    authoritative ones. A run row claiming three failures beside two
    ``failed`` attempt rows is how a gap in this best-effort log becomes
    visible instead of silent.
    """
    await _write(
        [
            models.MaintenanceLogRecord(
                run_id=run_id,
                slug=slug,
                event_type='run',
                disposition=disposition,
                started_by=started_by,
                detail=_sanitize_detail(detail),
            )
        ]
    )


class ItemLog:
    """Buffers one claimed item's rows; the worker flushes them.

    An operation holds this through :class:`MaintenanceContext` and calls
    :meth:`record`; the worker owns :meth:`attempt` and :meth:`flush`.
    """

    def __init__(
        self,
        slug: str,
        run_id: str,
        attempt_id: str,
        item_id: str,
        project_id: str = '',
        project_slug: str = '',
        started_by: str = '',
    ) -> None:
        self.slug = slug
        self.run_id = run_id
        self.attempt_id = attempt_id
        self.item_id = item_id
        self.project_id = project_id
        self.project_slug = project_slug
        self.started_by = started_by
        self._rows: list[models.MaintenanceLogRecord] = []

    def record(
        self,
        disposition: Disposition,
        action: str,
        message: str = '',
        **detail: typing.Any,
    ) -> None:
        """Buffer one activity row. Synchronous -- does no I/O."""
        self._rows.append(
            self._row('activity', disposition, action, message, detail)
        )

    def attempt(
        self,
        disposition: Disposition,
        message: str = '',
        duration_ms: int = 0,
        **detail: typing.Any,
    ) -> None:
        """Buffer this item's terminal row (worker-owned)."""
        row = self._row('attempt', disposition, '', message, detail)
        row.duration_ms = duration_ms
        self._rows.append(row)

    async def flush(self) -> None:
        """Write and clear the buffer. Best-effort; never raises."""
        if not self._rows:
            return
        rows, self._rows = self._rows, []
        await _write(rows)

    @property
    def buffered(self) -> int:
        """How many rows are waiting on a flush (tests, diagnostics)."""
        return len(self._rows)

    def _row(
        self,
        event_type: typing.Literal['attempt', 'activity'],
        disposition: str,
        action: str,
        message: str,
        detail: dict[str, typing.Any],
    ) -> models.MaintenanceLogRecord:
        return models.MaintenanceLogRecord(
            run_id=self.run_id,
            attempt_id=self.attempt_id,
            item_id=self.item_id,
            slug=self.slug,
            event_type=event_type,
            disposition=disposition,
            action=action,
            project_id=self.project_id,
            project_slug=self.project_slug,
            message=message[:MAX_MESSAGE_LEN],
            detail=_sanitize_detail(detail),
            started_by=self.started_by,
        )


@dataclasses.dataclass(slots=True)
class MaintenanceContext:
    """Execution metadata for one claimed item.

    Passed keyword-only into every ``execute_*`` so the dependency is
    visible in the signature and assertable in tests -- rather than an
    ambient context variable, which would not survive an operation
    spawning its own tasks.
    """

    run_id: str
    attempt_id: str
    #: The work item this run enumerated. Every operation but
    #: ``search-reindex`` enumerates projects, so for all of those it is
    #: also :attr:`project_id`.
    item_id: str
    project_id: str
    project_slug: str
    log: ItemLog
