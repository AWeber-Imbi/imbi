"""Run history.

One row per firing in ``imbi.scheduler_runs``, rewritten as the run
transitions: the executor writes it ``running`` before attempting anything and
the engine writes the terminal state over it. ``_row_version`` increments on
that second write, so ReplacingMergeTree collapses the pair into one row.
Retries do not add rows — only the attempt that ended the run is recorded, and
its ``attempt`` says how many it took.

Nothing secret reaches this table: :func:`excerpt` scrubs credentials out of
response bodies and caps their length before anything is stored or logged.
"""

import datetime
import logging
import re
import typing
import uuid

import pydantic

from imbi.common import clickhouse
from imbi.scheduler import models

LOGGER = logging.getLogger(__name__)

TABLE = 'imbi.scheduler_runs'

#: Response bodies are evidence, not archives.
RESPONSE_EXCERPT_LIMIT = 8192

_REDACTED = '[redacted]'

#: Patterns for material that must never be persisted, each with the
#: replacement that keeps enough context to read a log without the secret.
#: Ordered most specific first so a bearer header is redacted whole rather
#: than leaving the scheme behind.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r'(?i)\b(bearer|basic)\s+[\w\-.~+/=]+'),
        rf'\1 {_REDACTED}',
    ),
    (re.compile(r'\bik_[A-Za-z0-9]{8,}'), _REDACTED),
    (re.compile(r'\beyJ[\w-]+\.[\w-]+\.[\w-]+'), _REDACTED),
    # The keyword may sit anywhere in the key rather than be the whole of it:
    # `access_token` and `refresh_token` are every bit as sensitive as
    # `token`, and requiring an exact match let them through into
    # `response_excerpt`. `client_secret` needs no separate alternative now
    # that `secret` matches as a substring. Deliberately over-broad —
    # redacting a `token_type` costs a log reader nothing, while missing an
    # access token costs a credential.
    (
        re.compile(
            r'(?i)"([\w-]*(?:password|secret|token|api_key)[\w-]*)"'
            r'\s*:\s*"[^"]*"'
        ),
        rf'"\1": "{_REDACTED}"',
    ),
)


def scrub(text: str) -> str:
    """Return `text` with anything credential-shaped redacted."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def excerpt(text: str | None) -> str:
    """Return a scrubbed, length-capped excerpt of a response body."""
    if not text:
        return ''
    scrubbed = scrub(text)
    if len(scrubbed) <= RESPONSE_EXCERPT_LIMIT:
        return scrubbed
    return scrubbed[:RESPONSE_EXCERPT_LIMIT] + '…[truncated]'


class Run(pydantic.BaseModel):
    """A single firing attempt.

    Non-nullable ``LowCardinality(String)`` columns reject ``None``, so the
    optional fields default to empty strings rather than being nullable.
    """

    model_config = pydantic.ConfigDict(populate_by_name=True)

    run_id: str
    task_id: str
    task_slug: str
    organization: str = ''
    fired_at: datetime.datetime
    started_at: datetime.datetime | None = None
    finished_at: datetime.datetime | None = None
    duration_ms: int = 0
    state: models.RunState
    attempt: int = 1
    identity_kind: str = ''
    principal_name: str = ''
    actor_name: str = ''
    consent_id: str = ''
    target_kind: str
    target_summary: str
    http_status: int = 0
    response_excerpt: str = ''
    error_type: str = ''
    error_message: str = ''
    trace_id: str = ''
    row_version: int = pydantic.Field(default=1, alias='_row_version')

    @property
    def is_terminal(self) -> bool:
        """Return whether this run has reached a terminal state."""
        return self.state in models.TERMINAL_RUN_STATES


def start(  # noqa: PLR0913 -- every field is one column of the run record
    task: models.Task,
    fired_at: datetime.datetime,
    *,
    run_id: uuid.UUID | None = None,
    attempt: int = 1,
    actor_name: str = '',
    trace_id: str = '',
) -> Run:
    """Return a `running` run for `task`, ready to be recorded.

    The caller may supply `run_id`: the engine mints one before it takes the
    execution lease, because the lease row records the run and a cancel
    request finds the firing by that id. Left unset, a run gets a fresh one.
    """
    identity_kind = task.identity.kind if task.identity else 'none'
    return Run(
        run_id=str(run_id or uuid.uuid4()),
        task_id=str(task.id),
        task_slug=task.slug,
        organization=task.organization or '',
        fired_at=fired_at,
        started_at=fired_at,
        state='running',
        attempt=attempt,
        identity_kind=identity_kind,
        principal_name=task.principal_name,
        actor_name=actor_name,
        consent_id=(
            task.identity.consent_id or '' if task.identity is not None else ''
        ),
        target_kind=task.target.kind,
        target_summary=task.target_summary(),
        trace_id=trace_id,
    )


class Outcome(pydantic.BaseModel):
    """What came back from a firing.

    Grouped rather than passed as five keyword arguments so the executor can
    build one value and hand it straight to :func:`finish`.
    """

    http_status: int = 0
    response: str | None = None
    error_type: str = ''
    error_message: str = ''


def finish(
    run: Run,
    state: models.RunState,
    outcome: Outcome | None = None,
    *,
    finished_at: datetime.datetime | None = None,
) -> Run:
    """Return `run` transitioned to a terminal `state`.

    The version increments so the terminal row supersedes the `running` one
    rather than adding to it.
    """
    result = outcome or Outcome()
    finished = finished_at or datetime.datetime.now(datetime.UTC)
    started = run.started_at or run.fired_at
    return run.model_copy(
        update={
            'state': state,
            'finished_at': finished,
            'duration_ms': max(
                0, int((finished - started).total_seconds() * 1000)
            ),
            'http_status': result.http_status,
            'response_excerpt': excerpt(result.response),
            'error_type': result.error_type,
            # `excerpt`, not `scrub`: both redact, only `excerpt` also caps the
            # length. An embedded traceback or a verbose library error grows
            # this column without bound exactly as a response body would, and
            # the column has no more tolerance for one than the other. Named
            # for response bodies; applied here for the same reason.
            'error_message': excerpt(result.error_message),
            'row_version': run.row_version + 1,
        }
    )


def skipped(
    task: models.Task,
    fired_at: datetime.datetime,
    reason: str,
    *,
    actor_name: str = '',
    trace_id: str = '',
) -> Run:
    """Return a terminal `skipped` run.

    A skip is not a failure: identity that cannot be resolved means the task
    should stop quietly, so it neither consumes retries nor reads as an
    outage.
    """
    run = start(task, fired_at, actor_name=actor_name, trace_id=trace_id)
    return finish(
        run,
        'skipped',
        Outcome(error_type='skipped', error_message=reason),
        finished_at=fired_at,
    )


async def record(run: Run) -> None:
    """Write `run` to ClickHouse."""
    await clickhouse.insert(TABLE, [run])
    LOGGER.debug(
        'Recorded run %s for %s as %s', run.run_id, run.task_slug, run.state
    )


async def get(run_id: str) -> Run | None:
    """Return the current state of `run_id`, if it exists."""
    found = await clickhouse.query(
        # S608: TABLE is a module constant; every value is a bound parameter.
        f'SELECT * FROM {TABLE} FINAL WHERE run_id = {{run_id:String}}'  # noqa: S608
        ' ORDER BY _row_version DESC LIMIT 1',
        {'run_id': run_id},
    )
    return _as_run(found[0]) if found else None


async def for_task(
    task_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[Run]:
    """Return `task_id`'s run history, newest first."""
    found = await clickhouse.query(
        # S608: TABLE is a module constant; every value is a bound parameter.
        f'SELECT * FROM {TABLE} FINAL WHERE task_id = {{task_id:String}}'  # noqa: S608
        ' ORDER BY fired_at DESC, attempt DESC'
        ' LIMIT {limit:UInt32} OFFSET {offset:UInt32}',
        {'task_id': str(task_id), 'limit': limit, 'offset': offset},
    )
    return [_as_run(row) for row in found]


def _as_run(row: dict[str, typing.Any]) -> Run:
    """Build a run from a ClickHouse row."""
    return Run.model_validate(row)
