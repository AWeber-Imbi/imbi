"""Postgres repository for agent tasks (ADR 0020).

A change to a task and the event that records it commit in one
transaction. Each write method here does both, so nothing changes a task
without an event.

An event write increments ``tasks.last_seq`` and uses the new value as
the event ``seq``. The ``UPDATE`` locks the task row until the
transaction ends, so concurrent writers to one task get consecutive
numbers and the sequence has no gaps.

After the transaction commits, the events it wrote (and the budget
ledger rows) go to the permanent log in ClickHouse: see
:mod:`imbi.api.tickets.log`. They go after the commit, never inside
the transaction, so ClickHouse never holds an event that Postgres rolled
back. When the transaction created the ticket or changed its status,
the change hooks run next (:func:`register_change_hook`).
"""

import contextlib
import dataclasses
import datetime
import decimal
import functools
import logging
import re
import typing
import uuid
from collections import abc

import psycopg
import psycopg.errors
import psycopg_pool
from psycopg import rows, sql
from psycopg.types import json as pg_json

from imbi.api.tickets import log
from imbi.common import relational
from imbi.common.workflows.registry import agent as agent_step

type Pool = psycopg_pool.AsyncConnectionPool[
    psycopg.AsyncConnection[typing.Any]
]
type Row = dict[str, typing.Any]
type Conn = psycopg.AsyncConnection[typing.Any]

LOGGER = logging.getLogger(__name__)

SCHEMA = 'tickets'

#: The origin kinds of a child ticket, which an agent made from its own
#: ticket. Release B writes ``ticket``; older releases wrote ``task``
#: (ADR 0028). Both are read. The unique index of idempotency keys makes
#: them one kind, so pods of two releases cannot make two children for
#: one key.
CHILD_ORIGIN_KINDS = ('task', 'ticket')

#: The names of the unique index of idempotency keys. It keeps its ADR
#: 0020 name until a later release renames it (ADR 0028).
ORIGIN_IDEMPOTENCY_KEYS = frozenset(
    {'tasks_origin_idempotency_key', 'tickets_origin_idempotency_key'}
)

#: A change hook gets the ticket row after a transaction that created
#: the ticket or changed its status commits, and whether the
#: transaction wrote a ``trigger_outbox`` row. The secrets broker
#: releases the resolutions of a closed ticket here; the workflow
#: ``ticket_state_changed`` trigger starts its runs.
type ChangeHook = abc.Callable[[Row, bool], abc.Awaitable[None]]

#: Tells, in the transaction of a change, whether the org of the ticket
#: can start ``ticket_state_changed`` runs, so that a ``trigger_outbox``
#: row is needed. The workflow trigger registers it.
type OutboxFilter = abc.Callable[[Conn, str], abc.Awaitable[bool]]

_change_hooks: list[ChangeHook] = []
_outbox_filter: OutboxFilter | None = None

#: The event types of a creation and a status change.
_CHANGE_EVENTS = frozenset({'ticket.created', 'state.changed'})


def register_change_hook(hook: ChangeHook) -> None:
    """Add a change hook."""
    if hook not in _change_hooks:
        _change_hooks.append(hook)


def unregister_change_hook(hook: ChangeHook) -> None:
    """Remove a change hook."""
    if hook in _change_hooks:
        _change_hooks.remove(hook)


def register_outbox_filter(outbox_filter: OutboxFilter | None) -> None:
    """Set the outbox filter. ``None`` writes no ``trigger_outbox``
    rows."""
    global _outbox_filter
    _outbox_filter = outbox_filter


async def after_commit(
    task: Row,
    events: list[Row],
    ledger: list[Row] | None = None,
    *,
    outbox: bool = False,
) -> None:
    """Publish the events of a commit, then call every change hook when
    they created the ticket or changed its status. A hook failure is
    logged; the change stays."""
    await log.publish(task, events, ledger)
    if not any(event['type'] in _CHANGE_EVENTS for event in events):
        return
    for hook in list(_change_hooks):
        try:
            await hook(task, outbox)
        except Exception:  # noqa: BLE001 - the change committed already
            LOGGER.warning(
                'Change hook %s failed for ticket %s',
                getattr(hook, '__qualname__', repr(hook)),
                task['id'],
                exc_info=True,
            )


#: ``held`` is the status of a ticket that an open gating prerequisite
#: holds (ADR 0028). ``open`` and ``in_progress`` are the statuses of a
#: person ticket that is not held, blocked, or closed.
Status = typing.Literal[
    'held',
    'queued',
    'running',
    'paused',
    'open',
    'in_progress',
    'blocked',
    'closed',
]
Control = typing.Literal['run', 'pause', 'cancel']
Priority = typing.Literal['low', 'normal', 'high', 'urgent']
ActorKind = typing.Literal['human', 'agent', 'subagent', 'system']
Channel = typing.Literal['web', 'slack', 'mcp', 'api', 'harness']
Outcome = agent_step.Outcome
AssigneeKind = typing.Literal['agent', 'person']
TicketType = typing.Literal['bug', 'task', 'feature']

#: The longest label or role name, after normalization.
MAX_LABEL_LENGTH = 50

_LABEL_SPACES = re.compile(r'[\s_]+')
_LABEL_HYPHENS = re.compile(r'-{2,}')
_LABEL_EDGES = re.compile(r'^[^a-z0-9]+|[^a-z0-9]+$')


def normalize_label(value: str) -> str:
    """Return the stored form of a label or role name.

    Lowercase; each run of spaces and underscores becomes one hyphen,
    and so does each run of hyphens; leading and trailing punctuation
    goes. ``"API"``, ``"api-"``, and ``" Api "`` are all ``"api"``. An
    empty result means the value has no letter or digit.
    """
    value = _LABEL_SPACES.sub('-', value.strip().lower())
    return _LABEL_EDGES.sub('', _LABEL_HYPHENS.sub('-', value))


def normalize_labels(values: abc.Iterable[str]) -> list[str]:
    """Return the normalized labels without repeats, in order."""
    return list(dict.fromkeys(normalize_label(v) for v in values))


#: The statuses that a person sets on a person ticket, and the statuses
#: that each one can come from (ADR 0028). ``held`` changes only by its
#: gates, and ``closed`` comes from every other status.
PERSON_TRANSITIONS: dict[Status, tuple[Status, ...]] = {
    'open': ('blocked',),
    'in_progress': ('open', 'blocked'),
    'blocked': ('open', 'in_progress'),
}

#: The outcomes of a person ticket (ADR 0028).
PersonOutcome = typing.Literal[
    'done_acted',
    'done_nothing_to_act_on',
    'superseded',
    'cancelled_by_human',
]

#: The outcomes that release the dependents of a gating prerequisite.
DONE_OUTCOMES: tuple[Outcome, ...] = ('done_acted', 'done_nothing_to_act_on')

#: The open requests of the task ``t`` that a person can still resolve.
#: A task that is not closed and has one waits on a person (O1), also
#: when it is paused (Reply and hold).
_OPEN_REQUESTS = sql.SQL(
    'FROM tickets.requests AS r WHERE r.ticket_id = t.id'
    " AND r.status = 'open'"
    ' AND (r.expires_at IS NULL OR r.expires_at > NOW())'
)

#: The open requests on the open tickets of ``%(email)s``.
_WAITING_REQUESTS: typing.LiteralString = (
    ' FROM tickets.requests AS r'
    ' JOIN tickets.tickets AS t ON t.id = r.ticket_id'
    ' WHERE t.organization_id = %(org)s AND lower(t.owner) = %(email)s'
    " AND t.status <> 'closed' AND r.status = 'open'"
    ' AND (r.expires_at IS NULL OR r.expires_at > NOW())'
)

#: The open person tickets assigned to ``%(email)s``.
_WAITING_ASSIGNED: typing.LiteralString = (
    ' FROM tickets.tickets AS t WHERE t.organization_id = %(org)s'
    " AND t.assignee_kind = 'person' AND lower(t.assignee) = %(email)s"
    " AND t.status <> 'closed'"
)

#: The gating prerequisites of ticket ``t`` that closed with an outcome
#: that does not release it (not in ``%(done)s``).
_FAILED_GATES: typing.LiteralString = (
    'SELECT p.short_id FROM tickets.ticket_dependencies AS d'
    ' JOIN tickets.tickets AS p ON p.organization_id = d.organization_id'
    ' AND p.id = d.prerequisite_ticket_id'
    ' WHERE d.dependent_ticket_id = t.id AND d.gates'
    " AND p.status = 'closed' AND NOT p.outcome = ANY(%(done)s)"
)

#: The held tickets of ``%(email)s`` with a failed gating prerequisite.
_WAITING_HELD: typing.LiteralString = (
    ' FROM tickets.tickets AS t WHERE t.organization_id = %(org)s'
    " AND lower(t.owner) = %(email)s AND t.status = 'held'"
    ' AND EXISTS (' + _FAILED_GATES + ')'
)

#: The lists of :meth:`TicketStore.waiting`, oldest first.
_WAITING_LISTS: dict[str, typing.LiteralString] = {
    'requests': 'SELECT r.*, t.short_id, t.title AS ticket_title'
    + _WAITING_REQUESTS
    + ' ORDER BY r.opened_at, r.id',
    'assigned': 'SELECT t.*'
    + _WAITING_ASSIGNED
    + ' ORDER BY t.created_at, t.id',
    'held': 'SELECT t.*, ARRAY('
    + _FAILED_GATES
    + ' ORDER BY p.created_at, p.id) AS failed'
    + _WAITING_HELD
    + ' ORDER BY t.created_at, t.id',
}

#: The number of items in the lists of :meth:`TicketStore.waiting`.
_WAITING_COUNT: typing.LiteralString = (
    'SELECT (SELECT count(*)'
    + _WAITING_REQUESTS
    + ') + (SELECT count(*)'
    + _WAITING_ASSIGNED
    + ') + (SELECT count(*)'
    + _WAITING_HELD
    + ') AS count'
)

#: The inbox groups of the task list, in order.
Group = typing.Literal['input', 'running', 'paused', 'queued', 'closed']

#: The inbox group of task ``t``: ``input`` when it waits on a person
#: (blocked, or not closed with an open request), else its status. A
#: ticket that has not started (``held``, ``open``) is ``queued``; a
#: person ticket in work (``in_progress``) is ``running``.
_GROUP = sql.SQL(
    "CASE WHEN t.status = 'blocked' OR (t.status <> 'closed'"
    ' AND EXISTS (SELECT 1 {open})) THEN {input}'
    " WHEN t.status IN ('held', 'open') THEN 'queued'"
    " WHEN t.status = 'in_progress' THEN 'running'"
    ' ELSE t.status::text END'
).format(open=_OPEN_REQUESTS, input=sql.Literal('input'))

#: The order of the tasks in each inbox group: oldest block first (O2)
#: for ``input``, newest close first for ``closed``, the backlog rank
#: for ``queued`` (unranked last), else newest first.
_GROUP_ORDER: dict[str, sql.SQL] = {
    'input': sql.SQL('blocked_since ASC NULLS LAST, created_at DESC, id DESC'),
    'closed': sql.SQL('closed_at DESC NULLS LAST, id DESC'),
    'queued': sql.SQL('backlog_rank ASC NULLS LAST, created_at DESC, id DESC'),
}

#: The tickets that have not started: the backlog, which a person
#: orders by rank. Their inbox group is ``queued``.
BACKLOG_STATUSES: tuple[Status, ...] = ('held', 'queued', 'open')

#: The smallest gap between two ranks before :meth:`TicketStore.rank`
#: numbers the ranks again.
_MIN_RANK_GAP = 1e-9

#: The projects of task ``t`` (F13), oldest first, as a JSON list of
#: ``project_id`` and ``project_slug``. Every task row has it.
PROJECTS: typing.LiteralString = (
    '(SELECT coalesce(jsonb_agg(jsonb_build_object('
    "'project_id', p.project_id, 'project_slug', p.project_slug)"
    " ORDER BY p.added_at, p.project_id), '[]'::jsonb)"
    ' FROM tickets.ticket_projects AS p'
    ' WHERE p.organization_id = t.organization_id AND p.ticket_id = t.id)'
    ' AS projects'
)

#: A task row with its projects. Continue it with a WHERE clause.
_SELECT_TASKS: typing.LiteralString = (
    'SELECT t.*, ' + PROJECTS + ' FROM tickets.tickets AS t'  # noqa: S608
)

#: The tasks at the other end of the dependencies of a task, with the
#: link. ``this`` is the column of the task, ``other`` the other column.
_LINKED_TASKS = sql.SQL(
    'SELECT t.*, d.created_by_kind AS linked_by_kind,'
    ' d.created_by AS linked_by, d.created_at AS linked_at, d.gates'
    ' FROM tickets.ticket_dependencies AS d'
    ' JOIN tickets.tickets AS t'
    ' ON t.organization_id = d.organization_id AND t.id = d.{other}'
    ' WHERE d.organization_id = %s AND d.{this} = %s'
    ' ORDER BY d.created_at, t.id'
)

#: True when a gating prerequisite holds the ticket ``%s``: one that
#: is not closed with an outcome in ``%s`` (:data:`DONE_OUTCOMES`).
_GATED: typing.LiteralString = (
    'SELECT EXISTS (SELECT 1 FROM tickets.ticket_dependencies AS d'
    ' JOIN tickets.tickets AS p ON p.organization_id = d.organization_id'
    ' AND p.id = d.prerequisite_ticket_id'
    ' WHERE d.dependent_ticket_id = %s AND d.gates'
    " AND NOT (p.status = 'closed' AND p.outcome = ANY(%s)))"
)

#: The ticket ``%s`` and its ancestors, as ``up (id, parent_id)``.
#: UNION, not UNION ALL, so that the walk ends.
_UP: typing.LiteralString = (
    'WITH RECURSIVE up (id, parent_id) AS ('
    ' SELECT id, parent_id FROM tickets.tickets WHERE id = %s'
    ' UNION SELECT t.id, t.parent_id FROM tickets.tickets AS t'
    ' JOIN up ON t.id = up.parent_id)'
)

#: A row when the ticket ``%s`` is the ticket ``%s`` or one of its
#: descendants.
_IS_ANCESTOR: typing.LiteralString = (
    _UP + ' SELECT 1 FROM up WHERE id = %s'  # noqa: S608
)

#: The tree of the ticket ``%s``: the short id and title of its root,
#: the number of tickets in the tree, and the number that are not
#: closed. The foreign key keeps a tree in one organization; the
#: descendant join also matches ``organization_id`` so that it can use
#: ``tickets_parent_idx``.
_TREE: typing.LiteralString = (
    _UP  # noqa: S608
    + ', down (organization_id, id, status, root_short_id, root_title) AS ('
    ' SELECT t.organization_id, t.id, t.status, t.short_id, t.title'
    ' FROM tickets.tickets AS t'
    ' JOIN up ON t.id = up.id WHERE up.parent_id IS NULL'
    ' UNION SELECT t.organization_id, t.id, t.status, down.root_short_id,'
    ' down.root_title FROM tickets.tickets AS t JOIN down'
    ' ON t.organization_id = down.organization_id AND t.parent_id = down.id)'
    ' SELECT min(root_short_id) AS root_short_id,'
    ' min(root_title) AS root_title, count(*) AS tickets,'
    " count(*) FILTER (WHERE status <> 'closed') AS open FROM down"
)

#: The chain states in which a runner holds a chain (ADR 0022); see
#: :data:`imbi.api.harness.store.PINNED`.
PINNED_CHAIN_STATES: tuple[
    typing.Literal['running', 'fencing', 'stuck'], ...
] = ('running', 'fencing', 'stuck')

#: The statuses of a ticket that has not started: a gating
#: prerequisite can still hold it.
_NOT_STARTED: tuple[Status, ...] = ('queued', 'open', 'held')

#: The status of a task with no open session, by control value.
_IDLE_STATUS: dict[Control, Status] = {
    'run': 'queued',
    'pause': 'paused',
    'cancel': 'closed',
}

#: ``outcome_reason`` of a task that a person cancels while no harness
#: session is open.
CANCELLED_WITHOUT_SESSION = 'cancelled_without_session'


class TaskNotFound(LookupError):
    """No task has this short id in the organization."""


class TaskClosed(ValueError):
    """The task is closed. A closed task does not change."""


class RolesChanged(ValueError):
    """The roles of the task are not the roles that the caller read."""


class TaskOpen(ValueError):
    """The task, or a task that it delegated to, is not closed."""


class CancelPending(ValueError):
    """A cancel waits for the harness; the control cannot change."""


class ConcurrencyLimit(ValueError):
    """The agent has its maximum number of open sessions."""


class SessionNotFound(LookupError):
    """The task has no session with this id."""


class SessionClosed(ValueError):
    """The session is closed."""


class EventIdConflict(ValueError):
    """An event of another task has this ``event_id``."""


class RequestNotFound(LookupError):
    """The task has no request with this id."""


class RequestNotOpen(ValueError):
    """The request is resolved or expired. ``request`` is its row."""

    def __init__(self, request: dict[str, typing.Any]) -> None:
        super().__init__(str(request['id']))
        self.request = request


class DigestMismatch(ValueError):
    """The approved digests are not the digests of the request (I3)."""


class ResolutionInvalid(ValueError):
    """The resolution does not fit the kind of the request."""


class RequestKeyConflict(ValueError):
    """The request with this key binds to other digests."""


class TaskArchived(ValueError):
    """Every task in the change is archived. Its log is sealed."""


class ParentCycle(ValueError):
    """The move makes a ticket its own ancestor."""


class SelfDependency(ValueError):
    """A task cannot depend on itself."""


class TicketStarted(ValueError):
    """The ticket has started, so a gating dependency cannot hold it."""


class TicketHeld(ValueError):
    """An open gating prerequisite holds the ticket; it cannot start."""


class WrongAssigneeKind(ValueError):
    """The change does not apply to the assignee kind of the ticket:
    control, sessions, and usage apply only to an agent ticket, and
    person statuses only to a person ticket (ADR 0028)."""


class ReopenRefused(ValueError):
    """The closed ticket cannot reopen now (ADR 0028).

    ``reason`` is ``chain_pinned`` (a runner holds the chain of the
    ticket) or ``triggers_pending`` (the workflow runs of an earlier
    change have not all started).
    """

    def __init__(self, short_id: str, reason: str) -> None:
        super().__init__(f'{short_id} cannot reopen: {reason}')
        self.reason = reason


class SessionOpen(ValueError):
    """A harness session is open on the ticket."""


class ChainPinned(ValueError):
    """A runner holds the chain of the ticket (ADR 0022): it is
    ``running``, ``fencing``, or ``stuck``."""


class TransitionInvalid(ValueError):
    """A person ticket cannot move from its status to the one asked."""

    def __init__(self, short_id: str, status: str, to: str) -> None:
        super().__init__(f'{short_id} cannot move from {status} to {to}')


@dataclasses.dataclass(frozen=True)
class Actor:
    """Who caused an event, and through which channel."""

    kind: ActorKind
    id: str | None
    channel: Channel


@dataclasses.dataclass(frozen=True)
class NewTask:
    """The values of a task that the caller sets at creation."""

    organization_id: str
    #: The agent columns are ``None`` on a person ticket.
    agent_id: str | None
    agent_version: int | None
    prompt_version: int | None
    service_account_id: str | None
    title: str
    description: str
    origin_kind: str
    origin_id: str
    origin: dict[str, typing.Any]
    idempotency_key: str | None
    owner: str
    budget: decimal.Decimal | None
    #: The ``(project_id, project_slug)`` of each project of the task.
    #: A child task (origin ``task``) gets the projects of its parent
    #: instead.
    projects: abc.Sequence[tuple[str, str]] = ()
    #: The root task of the chain of a child task. ``None`` makes the
    #: task the root of its own chain.
    chain_id: uuid.UUID | None = None
    #: The JSON Schema of the structured output that the agent must
    #: return. ``None``: the task asks for none.
    output_schema: Row | None = None
    priority: Priority = 'normal'
    assignee_kind: AssigneeKind = 'agent'
    #: The email of the person on a person ticket.
    assignee: str | None = None
    #: The short ids of the prerequisites of the ticket, each with its
    #: ``gates`` value (ADR 0028).
    requires: abc.Sequence[tuple[str, bool]] = ()
    type: TicketType = 'task'
    due_date: datetime.date | None = None
    #: Normalized labels (:func:`normalize_labels`).
    labels: abc.Sequence[str] = ()
    #: ``{role: email}``, with normalized role names.
    roles: Row = dataclasses.field(default_factory=dict[str, typing.Any])


@dataclasses.dataclass(frozen=True)
class HandOff:
    """The new assignee of a ticket in a handoff (ADR 0028).

    A person has ``assignee``; an agent has the agent columns, with the
    version of the agent now. ``budget`` is the task budget of the
    agent: it caps the budget of the ticket.
    """

    assignee_kind: AssigneeKind
    assignee: str | None = None
    agent_id: str | None = None
    agent_version: int | None = None
    prompt_version: int | None = None
    service_account_id: str | None = None
    budget: decimal.Decimal | None = None
    note: str | None = None


@dataclasses.dataclass(frozen=True)
class NewEvent:
    """An event that a harness writes.

    The harness picks ``event_id``, so a batch that it sends again does
    not write its events two times.
    """

    event_id: uuid.UUID
    type: str
    payload: Row
    actor: Actor
    schema_version: int = 1
    at: datetime.datetime | None = None


@dataclasses.dataclass(frozen=True)
class Usage:
    """One model call that a harness reports.

    ``None`` for a token count means the harness did not measure it.
    ``message_id`` is the model's id for the reply; the task events of
    that reply have it too.
    """

    idempotency_key: str
    model_id: str
    tokens_in: int | None
    tokens_out: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    session_id: uuid.UUID | None
    message_id: str | None = None


#: Each token count of a usage report, and the price column for it.
_TOKEN_PRICES: tuple[tuple[str, str], ...] = (
    ('tokens_in', 'input_cost_per_million'),
    ('tokens_out', 'output_cost_per_million'),
    ('cache_read_tokens', 'cache_read_cost_per_million'),
    ('cache_write_tokens', 'cache_write_cost_per_million'),
)

#: The scale of the NUMERIC(14, 6) cost columns.
_COST_SCALE = decimal.Decimal('0.000001')


def usage_cost(
    counts: dict[str, int | None],
    prices: dict[str, decimal.Decimal | None] | None,
) -> decimal.Decimal | None:
    """Return the USD cost of a usage report, or ``None`` when unknown.

    The cost is unknown when no count was measured, when the model is not
    in the catalog (``prices`` is ``None``), or when a count above zero
    has no price. Unknown is never recorded as zero (N2).
    """
    if prices is None or all(count is None for count in counts.values()):
        return None
    total = decimal.Decimal(0)
    for count_column, price_column in _TOKEN_PRICES:
        count = counts[count_column]
        if not count:
            continue
        price = prices[price_column]
        if price is None:
            return None
        total += count * price / 1_000_000
    return total.quantize(_COST_SCALE)


@dataclasses.dataclass(frozen=True)
class NewRequest:
    """A feedback or approval request that a harness opens."""

    kind: typing.Literal['feedback', 'approval']
    title: str
    why: str | None
    options: list[typing.Any] | None
    artifacts: list[typing.Any] | None
    artifact_digests: list[str] | None
    expires_at: datetime.datetime | None
    session_id: uuid.UUID | None
    request_key: str | None = None


#: The status of a resolved request, by kind: feedback is answered,
#: approval is approved or rejected.
ResolvedStatus = typing.Literal['answered', 'approved', 'rejected']
_RESOLVED_STATUSES: dict[str, tuple[ResolvedStatus, ...]] = {
    'feedback': ('answered',),
    'approval': ('approved', 'rejected'),
}


@dataclasses.dataclass(frozen=True)
class Resolution:
    """How a person resolves a request (I9).

    ``artifact_digests`` are the digests that the person approves. They
    must be the digests of the request (I3).
    """

    status: ResolvedStatus
    answer: str | None
    constraints: list[str] | None
    artifact_digests: list[str] | None


@dataclasses.dataclass
class _Write:
    """One write transaction on a locked task.

    ``task`` is the newest row of the task. ``events`` and ``ledger``
    collect the rows to publish after the commit.
    """

    conn: Conn
    task: Row
    events: list[Row] = dataclasses.field(default_factory=list[Row])
    ledger: list[Row] = dataclasses.field(default_factory=list[Row])
    #: Whether the transaction wrote a ``trigger_outbox`` row.
    outbox: bool = False
    #: The writes of the dependents that a close released.
    released: list[_Write] = dataclasses.field(default_factory=list)

    async def event(
        self, event_type: str, payload: Row, actor: Actor, **kwargs: typing.Any
    ) -> Row:
        """Write one event; see :func:`_append_event`."""
        row = await _append_event(
            self.conn, self.task['id'], event_type, payload, actor, **kwargs
        )
        self.events.append(row)
        return row

    async def update(self, changes: Row) -> Row:
        """Change columns of the task and keep the new row.

        A change of the status also writes its ``trigger_outbox`` row
        (:func:`_write_outbox`).
        """
        old = self.task['status']
        self.task = await _update_task(self.conn, self.task['id'], changes)
        if self.task['status'] != old:
            self.outbox |= await _write_outbox(self.conn, self.task, old)
        return self.task


@dataclasses.dataclass
class _Relate:
    """One change to the relations of locked tasks.

    ``tasks`` are in lock order. An event goes to each task whose log
    is not archived; an archived task is sealed. All events of the change
    share ``operation_id``.
    """

    conn: Conn
    tasks: list[Row]
    operation_id: uuid.UUID = dataclasses.field(default_factory=uuid.uuid4)
    events: dict[uuid.UUID, list[Row]] = dataclasses.field(
        default_factory=dict[uuid.UUID, list[Row]]
    )
    #: The tasks that got a ``trigger_outbox`` row.
    outbox: set[uuid.UUID] = dataclasses.field(default_factory=set[uuid.UUID])

    async def event(
        self,
        event_type: str,
        payload: abc.Callable[[Row], Row],
        actor: Actor,
    ) -> None:
        """Write ``event_type`` on each live task, with ``payload(task)``."""
        for task in self.tasks:
            if task['log_archived_at'] is not None:
                continue
            row = await _append_event(
                self.conn,
                task['id'],
                event_type,
                {'operation_id': str(self.operation_id), **payload(task)},
                actor,
            )
            self.events.setdefault(task['id'], []).append(row)

    async def sync_gate(self, task: Row, actor: Actor) -> None:
        """Hold or release ``task`` by its gates; see :func:`_sync_gate`."""
        write = _Write(self.conn, task)
        await _sync_gate(write, actor)
        self.events.setdefault(task['id'], []).extend(write.events)
        if write.outbox:
            self.outbox.add(task['id'])


def _search_filters(
    organization_id: str,
    statuses: list[Status] | None,
    agent_ids: list[str] | None,
    owners: list[str] | None,
    text: str | None,
    text_agent_ids: list[str] | None,
    text_project_ids: list[str] | None,
    labels: list[str] | None = None,
) -> tuple[list[sql.Composable], list[typing.Any]]:
    """The ``WHERE`` conditions of :meth:`Store.search` and their
    parameters.
    """
    conditions: list[sql.Composable] = [sql.SQL('organization_id = %s')]
    params: list[typing.Any] = [organization_id]
    if statuses:
        if 'blocked' in statuses:
            conditions.append(
                sql.SQL(
                    "(status = ANY(%s) OR (status <> 'closed'"
                    ' AND EXISTS (SELECT 1 {open})))'
                ).format(open=_OPEN_REQUESTS)
            )
        else:
            conditions.append(sql.SQL('status = ANY(%s)'))
        params.append(list(statuses))
    if agent_ids:
        conditions.append(sql.SQL('agent_id = ANY(%s)'))
        params.append(list(agent_ids))
    if owners:
        conditions.append(sql.SQL('owner = ANY(%s)'))
        params.append(list(owners))
    if labels:
        conditions.append(sql.SQL('labels @> %s'))
        params.append(normalize_labels(labels))
    if text:
        pattern = '%' + _escape_like(text) + '%'
        conditions.append(
            sql.SQL(
                '(title ILIKE %s OR short_id ILIKE %s'
                ' OR agent_id = ANY(%s) OR EXISTS (SELECT 1'
                ' FROM tickets.ticket_projects AS tp'
                ' WHERE tp.organization_id = t.organization_id'
                ' AND tp.ticket_id = t.id AND tp.project_id = ANY(%s)))'
            )
        )
        params += [
            pattern,
            pattern,
            text_agent_ids or [],
            text_project_ids or [],
        ]
    return conditions, params


def _retry_deadlock[**P, R](
    method: abc.Callable[P, abc.Awaitable[R]],
) -> abc.Callable[P, abc.Awaitable[R]]:
    """Run ``method`` again once when PostgreSQL aborts it in a deadlock.

    A change that locks two or more tickets cannot use one lock order
    for all others: a parent move locks the child, then the parent; a
    dependency change locks the prerequisite, then the dependent; a
    ``done_*`` close locks the ticket, then its held dependents. When
    the orders cross, PostgreSQL aborts one transaction. The aborted
    transaction wrote nothing and published nothing, so it runs again
    after the other one ends.
    """

    @functools.wraps(method)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await method(*args, **kwargs)
        except psycopg.errors.DeadlockDetected:
            # ponytail: one retry covers a pair; loop if three-way
            # deadlocks show up.
            LOGGER.warning('Deadlock in %s; retrying', method.__name__)
            return await method(*args, **kwargs)

    return wrapper


class TicketStore:
    """Repository over the ``tickets`` schema."""

    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    @contextlib.asynccontextmanager
    async def _write(
        self,
        organization_id: str,
        short_id: str,
        *,
        closed: bool = False,
        advisory: str | None = None,
    ) -> abc.AsyncGenerator[_Write]:
        """Lock an open task for a change, then publish what changed.

        With ``closed``, lock a closed task instead (a reopen). With
        ``advisory``, take that advisory lock before the task row lock.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            TaskOpen: ``closed`` and the task is not closed.

        """
        async with self._pool.connection() as conn:
            async with conn.transaction():
                if advisory is not None:
                    await conn.execute(
                        'SELECT pg_advisory_xact_lock(hashtext(%s))',
                        (advisory,),
                    )
                write = _Write(
                    conn,
                    await _lock_task(
                        conn, organization_id, short_id, closed=closed
                    ),
                )
                yield write
                if write.events:
                    # Event writes change ``last_seq``.
                    write.task = await _fetch_task(conn, write.task['id'])
        await after_commit(
            write.task, write.events, write.ledger, outbox=write.outbox
        )
        for released in write.released:
            await after_commit(
                released.task, released.events, outbox=released.outbox
            )

    async def move_legacy_projects(self) -> int:
        """Move the old single project of each task (``tasks.project_id``)
        to ``task_projects``, and clear it. Return the number of tasks.

        A task had one primary project before it had a project list. A
        second run moves nothing, so each start runs it.
        """
        async with self._pool.connection() as conn, conn.transaction():
            cursor = await conn.execute(
                'WITH moved AS (UPDATE tickets.tickets AS t'
                ' SET project_id = NULL, project_slug = NULL'
                ' FROM tickets.tickets AS o'
                ' WHERE o.id = t.id AND o.project_id IS NOT NULL'
                ' RETURNING t.organization_id, t.id, t.created_at,'
                ' o.project_id, o.project_slug)'
                ' INSERT INTO tickets.ticket_projects (organization_id,'
                ' ticket_id, project_id, project_slug, added_by_kind,'
                ' added_by, added_at)'
                ' SELECT organization_id, id, project_id,'
                " coalesce(project_slug, project_id), 'system', 'migration',"
                ' created_at FROM moved ON CONFLICT DO NOTHING'
            )
            return cursor.rowcount

    async def find_by_idempotency_key(
        self, organization_id: str, origin_kind: str, origin_id: str, key: str
    ) -> Row | None:
        """Return the task that the origin principal made with ``key``.

        A child kind matches every child kind, so a retry finds the child
        that a pod of the previous release wrote as ``task``.
        """
        kinds = (
            list(CHILD_ORIGIN_KINDS)
            if origin_kind in CHILD_ORIGIN_KINDS
            else [origin_kind]
        )
        async with self._pool.connection() as conn:
            return await _fetch_one(
                conn,
                _SELECT_TASKS
                + ' WHERE organization_id = %s AND origin_kind = ANY(%s)'
                ' AND origin_id = %s AND idempotency_key = %s',
                (organization_id, kinds, origin_id, key),
            )

    @_retry_deadlock
    async def create(
        self, task: NewTask, actor: Actor, event_payload: Row
    ) -> tuple[Row, bool]:
        """Insert ``task`` with its short id and ``ticket.created`` event.

        Return the task and ``True``. When a concurrent request made a
        task with the same idempotency key first, return that task and
        ``False``. The rollback also returns the short id to the counter.

        An agent ticket starts ``queued`` and a person ticket ``open``.
        Each prerequisite in ``task.requires`` gets ``dependency.added``
        on both tickets, as :meth:`add_dependency` writes it. An open
        gating prerequisite makes the ticket start ``held``.

        Raises:
            TaskClosed: The origin is a task that is closed or gone.
            TaskNotFound: A prerequisite is not in the organization.

        """
        task_id = uuid.uuid4()
        linked: list[tuple[Row, list[Row]]] = []
        try:
            async with self._pool.connection() as conn, conn.transaction():
                await relational.lock_organization_shared(
                    conn, task.organization_id
                )
                if task.origin_kind in CHILD_ORIGIN_KINDS:
                    # The lock conflicts with the lock in delete, so a
                    # parent cannot go while its child is made.
                    cursor = await conn.execute(
                        'SELECT 1 FROM tickets.tickets WHERE id = %s::uuid'
                        " AND status <> 'closed' FOR KEY SHARE",
                        (task.origin_id,),
                    )
                    if await cursor.fetchone() is None:
                        raise TaskClosed(task.origin_id)
                # Locked as a close locks them, so a prerequisite that
                # closes now waits, then sees the new dependency rows.
                gates = dict(task.requires)
                prerequisites = await _lock_tasks(
                    conn, task.organization_id, sorted(gates)
                )
                status: Status = (
                    'open' if task.assignee_kind == 'person' else 'queued'
                )
                if any(
                    gates[p['short_id']] and not _done(p)
                    for p in prerequisites
                ):
                    status = 'held'
                short_id = await _next_short_id(conn, task.organization_id)
                await conn.execute(
                    'INSERT INTO tickets.tickets (id, organization_id,'
                    ' short_id, agent_id, agent_version, prompt_version,'
                    ' service_account_id, title,'
                    ' description, origin_kind, origin_id, origin,'
                    ' idempotency_key, owner, budget, chain_id,'
                    ' output_schema, parent_id, priority,'
                    ' assignee_kind, assignee, status,'
                    ' type, due_date, labels, roles,'
                    ' platform_config_version)'
                    ' VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,'
                    ' %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,'
                    ' %s, %s, %s, %s,'
                    ' (SELECT max(version) FROM harness.platform_configs'
                    ' WHERE organization_id = %s))',
                    (
                        task_id,
                        task.organization_id,
                        short_id,
                        task.agent_id,
                        task.agent_version,
                        task.prompt_version,
                        task.service_account_id,
                        task.title,
                        task.description,
                        task.origin_kind,
                        task.origin_id,
                        pg_json.Jsonb(task.origin),
                        task.idempotency_key,
                        task.owner,
                        task.budget,
                        task.chain_id or task_id,
                        _jsonb(task.output_schema),
                        task.origin_id
                        if task.origin_kind in CHILD_ORIGIN_KINDS
                        else None,
                        task.priority,
                        task.assignee_kind,
                        task.assignee,
                        status,
                        task.type,
                        task.due_date,
                        list(task.labels),
                        pg_json.Jsonb(task.roles),
                        task.organization_id,
                    ),
                )
                if task.origin_kind in CHILD_ORIGIN_KINDS:
                    # The parent row is locked, so its projects cannot
                    # change until this commits.
                    await conn.execute(
                        'INSERT INTO tickets.ticket_projects'
                        ' (organization_id, ticket_id, project_id,'
                        ' project_slug, added_by_kind, added_by)'
                        ' SELECT organization_id, %s, project_id,'
                        ' project_slug, %s, %s'
                        ' FROM tickets.ticket_projects'
                        ' WHERE organization_id = %s AND ticket_id = %s::uuid',
                        (
                            task_id,
                            actor.kind,
                            actor.id,
                            task.organization_id,
                            task.origin_id,
                        ),
                    )
                elif task.projects:
                    async with conn.cursor() as cursor:
                        await cursor.executemany(
                            'INSERT INTO tickets.ticket_projects'
                            ' (organization_id, ticket_id, project_id,'
                            ' project_slug, added_by_kind, added_by)'
                            ' VALUES (%s, %s, %s, %s, %s, %s)'
                            ' ON CONFLICT DO NOTHING',
                            [
                                (
                                    task.organization_id,
                                    task_id,
                                    project_id,
                                    project_slug,
                                    actor.kind,
                                    actor.id,
                                )
                                for project_id, project_slug in task.projects
                            ],
                        )
                event = await _append_event(
                    conn, task_id, 'ticket.created', event_payload, actor
                )
                row = await _fetch_task(conn, task_id)
                outbox = await _write_outbox(conn, row, None)
                for prerequisite in prerequisites:
                    relate = _Relate(conn, [prerequisite, row])
                    link = await _fetch_one(
                        conn,
                        'INSERT INTO tickets.ticket_dependencies'
                        ' (organization_id, dependent_ticket_id,'
                        ' prerequisite_ticket_id, created_by_kind,'
                        ' created_by, gates) VALUES (%s, %s, %s, %s, %s, %s)'
                        ' RETURNING *',
                        (
                            task.organization_id,
                            task_id,
                            prerequisite['id'],
                            actor.kind,
                            actor.id,
                            gates[prerequisite['short_id']],
                        ),
                    )
                    if link is None:  # pragma: no cover - RETURNING
                        raise RuntimeError('dependency insert returned no row')
                    await relate.event(
                        'dependency.added',
                        _dependency_payload(relate, link),
                        actor,
                    )
                    # The publish reads no column that the events change.
                    linked += [
                        (t, relate.events[t['id']])
                        for t in relate.tasks
                        if t['id'] in relate.events
                    ]
                if prerequisites:
                    row = await _fetch_task(conn, task_id)
        except psycopg.errors.UniqueViolation as err:
            if (
                err.diag.constraint_name not in ORIGIN_IDEMPOTENCY_KEYS
                or task.idempotency_key is None
            ):
                raise
            existing = await self.find_by_idempotency_key(
                task.organization_id,
                task.origin_kind,
                task.origin_id,
                task.idempotency_key,
            )
            if existing is None:  # pragma: no cover - the key just collided
                raise
            return existing, False
        await after_commit(row, [event], outbox=outbox)
        for ticket, events in linked:
            await log.publish(ticket, events)
        return row, True

    async def get(self, organization_id: str, short_id: str) -> Row | None:
        """Return the task with ``short_id`` in the organization."""
        async with self._pool.connection() as conn:
            return await _fetch_one(
                conn,
                _SELECT_TASKS
                + ' WHERE organization_id = %s AND short_id = %s',
                (organization_id, short_id),
            )

    async def chain_root(self, task: Row) -> Row | None:
        """Return the root task of the chain of ``task`` (ADR 0022)."""
        chain_id = task['chain_id'] or task['id']
        if chain_id == task['id']:
            return task
        async with self._pool.connection() as conn:
            return await _fetch_one(
                conn, _SELECT_TASKS + ' WHERE t.id = %s', (chain_id,)
            )

    async def search(
        self,
        organization_id: str,
        *,
        statuses: list[Status] | None = None,
        agent_ids: list[str] | None = None,
        owners: list[str] | None = None,
        text: str | None = None,
        text_agent_ids: list[str] | None = None,
        text_project_ids: list[str] | None = None,
        labels: list[str] | None = None,
        group: Group | None = None,
        before: tuple[datetime.datetime, uuid.UUID] | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Row]:
        """Return tasks in the organization, newest first.

        ``text`` matches the title or the short id. A task also matches
        when its agent is in ``text_agent_ids`` or one of its projects is
        in ``text_project_ids``; the caller finds those in the graph.
        ``blocked`` in ``statuses`` also matches every task that waits on
        a person. ``group`` keeps the tasks of one inbox group, in the
        order of that group. ``before`` is the ``(created_at, id)``
        keyset of the last row of the previous page; ``offset`` skips
        rows. Each row also has ``blocked_since``: for a task that waits
        on a person (see :data:`_OPEN_REQUESTS`), the time its oldest
        open request opened, so the queue can sort oldest block first
        (O2); else ``None``.
        """
        conditions, params = _search_filters(
            organization_id,
            statuses,
            agent_ids,
            owners,
            text,
            text_agent_ids,
            text_project_ids,
            labels,
        )
        if group is not None:
            conditions.append(sql.SQL('{group} = %s').format(group=_GROUP))
            params.append(group)
        if before is not None:
            conditions.append(sql.SQL('(created_at, id) < (%s, %s)'))
            params += list(before)
        order = _GROUP_ORDER.get(
            group or '', sql.SQL('created_at DESC, id DESC')
        )
        statement = sql.SQL(
            'SELECT t.*, ' + PROJECTS + ','  # noqa: S608
            " CASE WHEN t.status <> 'closed' THEN"
            ' (SELECT min(r.opened_at) {open}) END AS blocked_since'
            ' FROM tickets.tickets AS t WHERE {where}'
            ' ORDER BY {order} LIMIT %s OFFSET %s'
        ).format(
            open=_OPEN_REQUESTS,
            where=sql.SQL(' AND ').join(conditions),
            order=order,
        )
        params += [limit, offset]
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(statement, params)
            return await cursor.fetchall()

    async def position(
        self,
        organization_id: str,
        short_id: str,
        *,
        statuses: list[Status] | None = None,
        agent_ids: list[str] | None = None,
        owners: list[str] | None = None,
        text: str | None = None,
        text_agent_ids: list[str] | None = None,
        text_project_ids: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> tuple[str, int] | None:
        """Return the inbox group of the task ``short_id`` and its index
        in that group, in the order of :meth:`search` with the same
        filters; ``None`` when the filters do not find the task.
        """
        conditions, params = _search_filters(
            organization_id,
            statuses,
            agent_ids,
            owners,
            text,
            text_agent_ids,
            text_project_ids,
            labels,
        )
        statement = sql.SQL(
            'SELECT inbox_group, n FROM (SELECT t.short_id,'
            ' {group} AS inbox_group, row_number() OVER (PARTITION BY {group}'
            ' ORDER BY CASE WHEN {group} = {input} THEN {waiting} END'
            ' ASC NULLS LAST, CASE WHEN {group} = {closed} THEN t.closed_at'
            ' END DESC NULLS LAST, CASE WHEN {group} = {queued}'
            ' THEN t.backlog_rank END ASC NULLS LAST,'
            ' CASE WHEN {group} <> {closed}'
            ' THEN t.created_at END DESC, t.id DESC) - 1 AS n'
            ' FROM tickets.tickets AS t WHERE {where}) AS s'
            ' WHERE short_id = %s'
        ).format(
            group=_GROUP,
            input=sql.Literal('input'),
            closed=sql.Literal('closed'),
            queued=sql.Literal('queued'),
            waiting=sql.SQL(
                "CASE WHEN t.status <> 'closed' THEN"
                ' (SELECT min(r.opened_at) {open}) END'
            ).format(open=_OPEN_REQUESTS),
            where=sql.SQL(' AND ').join(conditions),
        )
        async with self._pool.connection() as conn:
            cursor = await conn.execute(statement, [*params, short_id.upper()])
            found = await cursor.fetchone()
        return (str(found[0]), int(found[1])) if found else None

    async def count_groups(
        self,
        organization_id: str,
        *,
        statuses: list[Status] | None = None,
        agent_ids: list[str] | None = None,
        owners: list[str] | None = None,
        text: str | None = None,
        text_agent_ids: list[str] | None = None,
        text_project_ids: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, int]:
        """Return the number of tasks in each inbox group that
        :meth:`search` with the same filters finds. A group with no
        tasks has no key.
        """
        conditions, params = _search_filters(
            organization_id,
            statuses,
            agent_ids,
            owners,
            text,
            text_agent_ids,
            text_project_ids,
            labels,
        )
        statement = sql.SQL(
            'SELECT {group} AS inbox_group, count(*)'
            ' FROM tickets.tickets AS t WHERE {where} GROUP BY 1'
        ).format(group=_GROUP, where=sql.SQL(' AND ').join(conditions))
        async with self._pool.connection() as conn:
            cursor = await conn.execute(statement, params)
            found = await cursor.fetchall()
        return {str(group): int(count) for group, count in found}

    async def waiting(
        self, organization_id: str, email: str, *, lists: bool = True
    ) -> Row:
        """Return what waits on the person ``email`` (ADR 0028):

        - ``requests``: the open requests on the tickets that they own
          and that are not closed, oldest first, with ``short_id`` and
          ``ticket_title`` of the ticket.
        - ``assigned``: the person tickets assigned to them that are
          not closed, oldest first.
        - ``held``: the held tickets that they own with a gating
          prerequisite that closed with an outcome that does not release
          them, oldest first, with those prerequisites in ``failed``.

        ``count`` is the number of items in the three lists. Without
        ``lists``, only ``count`` is returned, from one query: the
        navigation badge polls it. Emails match without case.
        """
        params = {
            'org': organization_id,
            'email': email.lower(),
            'done': list(DONE_OUTCOMES),
        }
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            if not lists:
                await cursor.execute(_WAITING_COUNT, params)
                row = await cursor.fetchone()
                return {'count': int(row['count']) if row else 0}
            found: Row = {}
            for key, query in _WAITING_LISTS.items():
                await cursor.execute(query, params)
                found[key] = await cursor.fetchall()
        return {'count': sum(map(len, found.values())), **found}

    async def events(
        self, task_id: uuid.UUID, after_seq: int, limit: int
    ) -> list[Row]:
        """Return the events of a task after ``after_seq``, by seq."""
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                'SELECT * FROM tickets.events'
                ' WHERE ticket_id = %s AND seq > %s ORDER BY seq LIMIT %s',
                (task_id, after_seq, limit),
            )
            return await cursor.fetchall()

    async def read_log(
        self, task: Row, after_seq: int, limit: int
    ) -> list[Row]:
        """Return events of a task with ``seq`` after ``after_seq``.

        An archived log comes from ClickHouse. A task that was reopened
        after an archive has the events up to ``archived_seq`` in
        ClickHouse and the later events in Postgres (ADR 0028).
        """
        if task['log_archived_at'] is not None:
            return await log.archived_events(task, after_seq, limit)
        archived_seq = task['archived_seq'] or 0
        events: list[Row] = []
        if after_seq < archived_seq:
            events = await log.archived_events(
                task, after_seq, limit, archived_seq
            )
            if len(events) == limit:
                return events
            after_seq = archived_seq
        return events + await self.events(
            task['id'], after_seq, limit - len(events)
        )

    async def last_agent_turn(self, task: Row) -> str | None:
        """Return the body of the newest ``turn`` of the agent.

        It reads ClickHouse when the log of the task is archived, or
        when Postgres has no turn and an earlier log is archived.
        ``None`` when the agent wrote no turn.
        """
        if task['log_archived_at'] is not None:
            return await log.last_archived_agent_turn(task)
        # One statement reads the archive state and the turn from the same
        # snapshot, so an archive that commits after the caller read
        # ``task`` cannot hide the turn.
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                'SELECT t.log_archived_at IS NOT NULL,'
                " (SELECT e.payload->>'body' FROM tickets.events AS e"
                "   WHERE e.ticket_id = t.id AND e.type = 'turn'"
                "   AND e.actor_kind = 'agent' ORDER BY e.seq DESC LIMIT 1)"
                ' FROM tickets.tickets AS t WHERE t.id = %s',
                (task['id'],),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        archived, body = row
        if archived or (body is None and task['archived_seq']):
            return await log.last_archived_agent_turn(task)
        return None if body is None else str(body)

    async def pending_triggers(self) -> list[Row]:
        """Return the tickets that have a ``trigger_outbox`` row."""
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                _SELECT_TASKS  # noqa: S608 - constant SQL
                + ' WHERE t.id IN'
                ' (SELECT ticket_id FROM tickets.trigger_outbox)'
            )
            return await cursor.fetchall()

    async def state_changes(self, task_id: uuid.UUID) -> list[Row]:
        """Return the ``trigger_outbox`` rows of a ticket, oldest first."""
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                'SELECT * FROM tickets.trigger_outbox WHERE ticket_id = %s'
                ' ORDER BY created_at, id',
                (task_id,),
            )
            return await cursor.fetchall()

    async def triggers_started(self, change_ids: list[uuid.UUID]) -> None:
        """Delete ``trigger_outbox`` rows."""
        if not change_ids:
            return
        async with self._pool.connection() as conn:
            await conn.execute(
                'DELETE FROM tickets.trigger_outbox WHERE id = ANY(%s)',
                (change_ids,),
            )

    async def unarchived(self) -> list[Row]:
        """Return the tasks whose log is not archived, by organization.

        Each row also has ``ledger_count``, its number of ledger rows.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                'SELECT t.*, ' + PROJECTS + ','  # noqa: S608
                ' (SELECT count(*) FROM tickets.budget_ledger'
                ' AS l WHERE l.ticket_id = t.id) AS ledger_count'
                ' FROM tickets.tickets AS t'
                ' WHERE t.log_archived_at IS NULL'
                ' ORDER BY t.organization_id, t.id'
            )
            return await cursor.fetchall()

    async def events_with_seqs(
        self, task_id: uuid.UUID, seqs: list[int]
    ) -> list[Row]:
        """Return the events of a task with the given seqs, by seq."""
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                'SELECT * FROM tickets.events'
                ' WHERE ticket_id = %s AND seq = ANY(%s) ORDER BY seq',
                (task_id, seqs),
            )
            return await cursor.fetchall()

    async def ledger(self, task_id: uuid.UUID) -> list[Row]:
        """Return the budget ledger rows of a task, oldest first."""
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                'SELECT * FROM tickets.budget_ledger'
                ' WHERE ticket_id = %s ORDER BY recorded_at, id',
                (task_id,),
            )
            return await cursor.fetchall()

    async def archive(self, task_id: uuid.UUID, last_seq: int) -> bool:
        """Delete the events of a closed task and set ``log_archived_at``.

        Do this only after ClickHouse has every seq up to ``last_seq``.
        Return ``False`` and change nothing when the task is not closed,
        is archived, or has events after ``last_seq``.
        """
        async with self._pool.connection() as conn, conn.transaction():
            cursor = await conn.execute(
                'SELECT 1 FROM tickets.tickets WHERE id = %s'
                " AND status = 'closed' AND log_archived_at IS NULL"
                ' AND last_seq = %s FOR UPDATE',
                (task_id, last_seq),
            )
            if await cursor.fetchone() is None:
                return False
            await conn.execute(
                'DELETE FROM tickets.events WHERE ticket_id = %s',
                (task_id,),
            )
            await conn.execute(
                'UPDATE tickets.tickets SET log_archived_at = NOW()'
                ' WHERE id = %s',
                (task_id,),
            )
        return True

    @_retry_deadlock
    async def delete(
        self, organization_id: str, short_id: str, actor: Actor
    ) -> Row:
        """Delete a closed task and return its row.

        Its events, sessions, requests, budget ledger, and harness rows
        go by cascade; its dependency and project rows go here. A
        ``held`` dependent that no other gate holds is released. The
        secret resolutions and the ClickHouse rows (archived events,
        usage) stay, for the security and cost history.

        Raises:
            TaskNotFound: No such task.
            TaskOpen: The task, or a child or chain task, is not closed,
                the log of the task is not archived, its harness chain
                is not done, it has open secret resolutions, or it or a
                task in its chain has a ``trigger_outbox`` row.

        """
        async with self._pool.connection() as conn, conn.transaction():
            task = await _fetch_one(
                conn,
                _SELECT_TASKS
                + ' WHERE organization_id = %s AND short_id = %s FOR UPDATE',
                (organization_id, short_id),
            )
            if task is None:
                raise TaskNotFound(short_id)
            # The cascade would remove events and ledger rows that the
            # sweep has not yet put in ClickHouse.
            if task['log_archived_at'] is None:
                raise TaskOpen(short_id)
            # The harness chain row of a root task cascades, so an open
            # task in its chain must not lose it. A legacy root has no
            # stored chain_id.
            chain_id = task['chain_id'] or task['id']
            cursor = await conn.execute(
                'SELECT 1 FROM tickets.tickets'
                " WHERE status <> 'closed' AND (id = %s OR chain_id = %s"
                ' OR (chain_id IS NULL AND id = %s)'
                ' OR (origin_kind = ANY(%s) AND origin_id = %s))'
                ' LIMIT 1',
                (
                    task['id'],
                    chain_id,
                    chain_id,
                    list(CHILD_ORIGIN_KINDS),
                    str(task['id']),
                ),
            )
            if await cursor.fetchone() is not None:
                raise TaskOpen(short_id)
            # The lease sweep still needs the chain row of a root that
            # waits for its fencers, and Broker.sweep joins the open
            # resolutions of a failed change hook to the task. A pending
            # trigger_outbox row of the task, or of a task in the chain
            # of a root, needs the root for its depth (ticket_trigger).
            cursor = await conn.execute(
                'SELECT 1 FROM harness.chains WHERE root_ticket_id = %s'
                " AND state IN ('running', 'fencing', 'stuck')"
                ' UNION ALL SELECT 1 FROM secrets.resolutions'
                " WHERE task_id = %s AND state IN ('pending', 'active')"
                ' UNION ALL SELECT 1 FROM tickets.trigger_outbox AS o'
                ' JOIN tickets.tickets AS c ON c.id = o.ticket_id'
                ' WHERE c.id = %s OR c.chain_id = %s'
                ' LIMIT 1',
                (task['id'], task['id'], task['id'], task['id']),
            )
            if await cursor.fetchone() is not None:
                raise TaskOpen(short_id)
            cursor = await conn.execute(
                'DELETE FROM tickets.ticket_dependencies'
                ' WHERE organization_id = %s'
                ' AND (dependent_ticket_id = %s'
                ' OR prerequisite_ticket_id = %s)'
                ' RETURNING dependent_ticket_id, gates',
                (organization_id, task['id'], task['id']),
            )
            # A held dependent of the task loses a gate.
            released = await _release_dependents(
                conn,
                [row[0] for row in await cursor.fetchall() if row[1]],
                actor,
            )
            await conn.execute(
                'DELETE FROM tickets.ticket_projects'
                ' WHERE organization_id = %s AND ticket_id = %s',
                (organization_id, task['id']),
            )
            await conn.execute(
                'DELETE FROM tickets.tickets WHERE id = %s', (task['id'],)
            )
        for dependent in released:
            await after_commit(
                dependent.task, dependent.events, outbox=dependent.outbox
            )
        return task

    async def set_control(
        self,
        organization_id: str,
        short_id: str,
        control: Control,
        actor: Actor,
    ) -> Row:
        """Set the control value of a task and write its events.

        When a harness session is open, only ``control`` changes; the
        harness acts on it at its next turn boundary. One exception:
        ``run`` moves a ``paused`` task to ``running`` (``blocked`` when
        a request is open), because the harness works it. When no session is
        open, the status changes too: ``pause`` moves the task to
        ``paused``, ``run`` moves it back to ``queued`` (``blocked``
        when a request is open), and ``cancel`` closes it with the
        outcome ``cancelled_by_human``.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            CancelPending: A cancel waits for the harness.
            WrongAssigneeKind: The task is a person ticket.

        """
        async with self._write(organization_id, short_id) as write:
            await _apply_control(write, control, actor, short_id)
        return write.task

    async def reply(
        self,
        organization_id: str,
        short_id: str,
        body: str,
        actor: Actor,
        *,
        hold: bool = False,
    ) -> Row:
        """Write a human ``turn`` (H3); with ``hold``, also pause.

        The harness reads the turn by seq at its next turn boundary
        (H7). The turn and the pause commit together.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            CancelPending: ``hold`` and a cancel waits for the harness.
            WrongAssigneeKind: ``hold`` on a person ticket.

        """
        async with self._write(organization_id, short_id) as write:
            await write.event('turn', {'body': body}, actor)
            if hold:
                await _apply_control(write, 'pause', actor, short_id)
        return write.task

    async def set_owner(
        self,
        organization_id: str,
        short_id: str,
        owner: str,
        actor: Actor,
    ) -> Row:
        """Give the task a new owner and write ``owner.changed``.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.

        """
        async with self._write(organization_id, short_id) as write:
            if write.task['owner'] != owner:
                await write.event(
                    'owner.changed',
                    {'from': write.task['owner'], 'to': owner},
                    actor,
                )
                await write.update({'owner': owner})
        return write.task

    async def set_priority(
        self,
        organization_id: str,
        short_id: str,
        priority: Priority,
        actor: Actor,
    ) -> Row:
        """Set the priority of the task and write ``priority.changed``.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.

        """
        async with self._write(organization_id, short_id) as write:
            if write.task['priority'] != priority:
                await write.event(
                    'priority.changed',
                    {'from': write.task['priority'], 'to': priority},
                    actor,
                )
                await write.update({'priority': priority})
        return write.task

    async def set_fields(
        self,
        organization_id: str,
        short_id: str,
        changes: Row,
        actor: Actor,
        *,
        roles_read: Row | None = None,
    ) -> Row:
        """Change ``type``, ``due_date``, ``labels``, or ``roles`` of the
        task. Each value that differs writes ``<field>.changed`` with
        ``from`` and ``to``. Labels and role names must be normalized.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            RolesChanged: ``roles_read`` is given and the task has other
                roles now.

        """
        async with self._write(organization_id, short_id) as write:
            if roles_read is not None and (write.task['roles'] or {}) != (
                roles_read
            ):
                raise RolesChanged(short_id)
            changed: Row = {}
            for field, value in changes.items():
                old = write.task[field]
                if old == value:
                    continue
                await write.event(
                    f'{field}.changed',
                    {'from': _event_value(old), 'to': _event_value(value)},
                    actor,
                )
                changed[field] = (
                    pg_json.Jsonb(value) if field == 'roles' else value
                )
            if changed:
                await write.update(changed)
        return write.task

    async def rank(
        self,
        organization_id: str,
        short_id: str,
        after: str | None,
        actor: Actor,
    ) -> Row:
        """Put the task in the backlog right after the task ``after``,
        or first when ``after`` is ``None``, and write ``rank.changed``.

        The backlog is the ``queued`` inbox group: ranked tickets by
        rank, then unranked tickets newest first. When ``after`` is not
        ranked, it and each unranked backlog ticket before it get ranks
        first, in that order, so the backlog keeps the order a person
        saw. When two ranks get too close, every ranked ticket of the
        org gets a new rank in the same order.

        Raises:
            TaskNotFound: No such task, or no open task ``after``.
            TaskClosed: The task is closed.

        """
        # One ranking at a time in an org, so two cannot read the same
        # gap. The org lock comes before the row lock: a ranking that
        # holds it updates the rows of other tickets.
        async with self._write(
            organization_id,
            short_id,
            advisory=f'tickets.rank:{organization_id}',
        ) as write:
            rank = await _rank_after(
                write.conn, organization_id, write.task['id'], after
            )
            # A renumber can change the stored rank of this task too,
            # so read it again.
            cursor = await write.conn.execute(
                'SELECT backlog_rank FROM tickets.tickets WHERE id = %s',
                (write.task['id'],),
            )
            found = await cursor.fetchone()
            old = found[0] if found else None
            if old != rank:
                await write.event(
                    'rank.changed',
                    {
                        'from': old,
                        'to': rank,
                        'after': after,
                    },
                    actor,
                )
                await write.update({'backlog_rank': rank})
        return write.task

    async def label_counts(
        self, organization_id: str, prefix: str, limit: int
    ) -> list[Row]:
        """Return the labels of the org that start with ``prefix`` (a
        normalized label), each with its number of tickets: the label
        ``prefix`` itself first, then the most used.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                'SELECT label AS name, count(*) AS count'
                ' FROM tickets.tickets, unnest(labels) AS label'
                ' WHERE organization_id = %s AND label LIKE %s'
                ' GROUP BY label'
                ' ORDER BY label = %s DESC, count(*) DESC, label LIMIT %s',
                (organization_id, _escape_like(prefix) + '%', prefix, limit),
            )
            return await cursor.fetchall()

    async def acknowledge(
        self, organization_id: str, short_id: str, actor_id: str | None
    ) -> Row:
        """Mark a closed task as seen by ``actor_id``, and return it.

        The first acknowledgement stays. A closed task does not take
        events, so this changes only the row.

        Raises:
            TaskNotFound: No such task.
            TaskOpen: The task is not closed.

        """
        async with self._pool.connection() as conn:
            task = await _fetch_one(
                conn,
                'UPDATE tickets.tickets AS t'  # noqa: S608
                ' SET acknowledged_at = COALESCE(acknowledged_at, NOW()),'
                ' acknowledged_by = COALESCE(acknowledged_by, %s)'
                ' WHERE organization_id = %s AND short_id = %s'
                " AND status = 'closed' RETURNING t.*, " + PROJECTS,
                (actor_id, organization_id, short_id),
            )
            if task is not None:
                return task
            cursor = await conn.execute(
                'SELECT 1 FROM tickets.tickets'
                ' WHERE organization_id = %s AND short_id = %s',
                (organization_id, short_id),
            )
            if await cursor.fetchone() is None:
                raise TaskNotFound(short_id)
            raise TaskOpen(short_id)

    # --- Relations ----------------------------------------------------

    @contextlib.asynccontextmanager
    async def _relate(
        self, organization_id: str, short_ids: list[str]
    ) -> abc.AsyncGenerator[_Relate]:
        """Lock tasks for a change to their relations, then publish.

        The tasks lock in the order of ``short_ids``. A dependency change
        gives the prerequisite first, as a close that releases dependents
        locks them (:func:`_release_dependents`), so the two cannot
        deadlock. A closed task takes relation events until its log is
        archived.

        Raises:
            TaskNotFound: No such task.
            TaskArchived: Every task is archived.

        """
        async with self._pool.connection() as conn:
            async with conn.transaction():
                tasks = await _lock_tasks(conn, organization_id, short_ids)
                if all(task['log_archived_at'] is not None for task in tasks):
                    raise TaskArchived(', '.join(short_ids))
                relate = _Relate(conn, tasks)
                yield relate
                # Event writes change ``last_seq``.
                published = [
                    (await _fetch_task(conn, task_id), events)
                    for task_id, events in relate.events.items()
                ]
        for task, events in published:
            await after_commit(
                task, events, outbox=task['id'] in relate.outbox
            )

    @_retry_deadlock
    async def add_dependency(
        self,
        organization_id: str,
        dependent: str,
        prerequisite: str,
        actor: Actor,
        *,
        gates: bool = False,
    ) -> bool:
        """Make ``dependent`` require ``prerequisite``.

        Write ``dependency.added`` on both tasks, or only on the one that
        is not archived. With ``gates``, an open prerequisite holds the
        dependent (ADR 0028): a ``queued`` dependent becomes ``held``.
        A prerequisite that is closed with a ``done_*`` outcome does not
        hold it. When the dependency exists with another ``gates``
        value, the value changes and the event is written again, with
        the new row. Return ``False`` and write no event when the
        dependency exists with the same value.

        Raises:
            SelfDependency: The two short ids are the same.
            TaskNotFound: No such task.
            TaskArchived: Both tasks are archived.
            TicketStarted: ``gates``, the dependent is not ``queued``,
                ``open``, or ``held``, and the dependency does not gate
                already.

        """
        if dependent == prerequisite:
            raise SelfDependency(dependent)
        async with self._relate(
            organization_id, [prerequisite, dependent]
        ) as relate:
            by_short_id = {task['short_id']: task for task in relate.tasks}
            task = by_short_id[dependent]
            if gates and task['status'] not in _NOT_STARTED:
                cursor = await relate.conn.execute(
                    'SELECT 1 FROM tickets.ticket_dependencies'
                    ' WHERE organization_id = %s AND dependent_ticket_id = %s'
                    ' AND prerequisite_ticket_id = %s AND gates',
                    (
                        organization_id,
                        task['id'],
                        by_short_id[prerequisite]['id'],
                    ),
                )
                if await cursor.fetchone() is None:
                    raise TicketStarted(dependent)
                return False  # The same value: nothing changes.
            row = await _fetch_one(
                relate.conn,
                'INSERT INTO tickets.ticket_dependencies'
                ' (organization_id, dependent_ticket_id,'
                ' prerequisite_ticket_id, created_by_kind, created_by,'
                ' gates) VALUES (%s, %s, %s, %s, %s, %s)'
                ' ON CONFLICT (organization_id, dependent_ticket_id,'
                ' prerequisite_ticket_id) DO UPDATE SET gates = EXCLUDED.gates'
                ' WHERE ticket_dependencies.gates <> EXCLUDED.gates'
                ' RETURNING *',
                (
                    organization_id,
                    task['id'],
                    by_short_id[prerequisite]['id'],
                    actor.kind,
                    actor.id,
                    gates,
                ),
            )
            if row is not None:
                await relate.event(
                    'dependency.added', _dependency_payload(relate, row), actor
                )
                if gates or task['status'] == 'held':
                    await relate.sync_gate(task, actor)
        return row is not None

    @_retry_deadlock
    async def remove_dependency(
        self,
        organization_id: str,
        dependent: str,
        prerequisite: str,
        actor: Actor,
    ) -> bool:
        """Remove the dependency of ``dependent`` on ``prerequisite``.

        Write ``dependency.removed``, with the removed row, as
        :meth:`add_dependency` writes ``dependency.added``. A ``held``
        dependent that no other gate holds is released. Return ``False``
        and write no event when there is no such dependency.

        Raises:
            TaskNotFound: No such task.
            TaskArchived: Both tasks are archived.

        """
        async with self._relate(
            organization_id, [prerequisite, dependent]
        ) as relate:
            by_short_id = {task['short_id']: task for task in relate.tasks}
            task = by_short_id[dependent]
            row = await _fetch_one(
                relate.conn,
                'DELETE FROM tickets.ticket_dependencies'
                ' WHERE organization_id = %s AND dependent_ticket_id = %s'
                ' AND prerequisite_ticket_id = %s RETURNING *',
                (organization_id, task['id'], by_short_id[prerequisite]['id']),
            )
            if row is not None:
                await relate.event(
                    'dependency.removed',
                    _dependency_payload(relate, row),
                    actor,
                )
                if row['gates']:
                    await relate.sync_gate(task, actor)
        return row is not None

    async def associate_project(
        self,
        organization_id: str,
        short_id: str,
        project_id: str,
        project_slug: str,
        actor: Actor,
    ) -> bool:
        """Associate a project with a task.

        The caller checks that the project is in the organization. Write
        ``project.associated``. Return ``False`` and write no event when
        the project is associated.

        Raises:
            TaskNotFound: No such task.
            TaskArchived: The task is archived.

        """
        async with self._relate(organization_id, [short_id]) as relate:
            row = await _fetch_one(
                relate.conn,
                'INSERT INTO tickets.ticket_projects (organization_id,'
                ' ticket_id, project_id, project_slug, added_by_kind,'
                ' added_by)'
                ' VALUES (%s, %s, %s, %s, %s, %s)'
                ' ON CONFLICT DO NOTHING RETURNING *',
                (
                    organization_id,
                    relate.tasks[0]['id'],
                    project_id,
                    project_slug,
                    actor.kind,
                    actor.id,
                ),
            )
            if row is not None:
                await relate.event(
                    'project.associated', lambda _: _json_row(row), actor
                )
        return row is not None

    async def dissociate_project(
        self,
        organization_id: str,
        short_id: str,
        project_id: str,
        actor: Actor,
    ) -> bool:
        """Remove a project association; write ``project.dissociated``
        with the removed row. Return ``False`` and write no event when
        the project is not associated.

        Raises:
            TaskNotFound: No such task.
            TaskArchived: The task is archived.

        """
        async with self._relate(organization_id, [short_id]) as relate:
            row = await _fetch_one(
                relate.conn,
                'DELETE FROM tickets.ticket_projects'
                ' WHERE organization_id = %s AND ticket_id = %s'
                ' AND project_id = %s RETURNING *',
                (organization_id, relate.tasks[0]['id'], project_id),
            )
            if row is not None:
                await relate.event(
                    'project.dissociated', lambda _: _json_row(row), actor
                )
        return row is not None

    async def relations(self, task: Row) -> dict[str, typing.Any]:
        """Return the tasks related to ``task``.

        ``requires`` and ``required_by`` are its dependencies in the two
        directions, oldest link first. Each is the other task, with the
        ``linked_by_kind``, ``linked_by``, and ``linked_at`` of the link.
        ``parent`` and ``children`` come from ``parent_id``. ``tree``
        is the state of the tree of the task, computed now: its root
        ticket, and the number of tickets in the tree and of those that
        are not closed.

        All reads use one snapshot, and the parent comes from the current
        row, not from ``task``. Thus a move that occurs after the caller
        read ``task`` cannot give a parent and a tree that disagree.
        """
        params = (task['organization_id'], task['id'])
        async with (
            self._pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'
            )
            await cursor.execute(
                _LINKED_TASKS.format(
                    other=sql.Identifier('prerequisite_ticket_id'),
                    this=sql.Identifier('dependent_ticket_id'),
                ),
                params,
            )
            requires = await cursor.fetchall()
            await cursor.execute(
                _LINKED_TASKS.format(
                    other=sql.Identifier('dependent_ticket_id'),
                    this=sql.Identifier('prerequisite_ticket_id'),
                ),
                params,
            )
            required_by = await cursor.fetchall()
            await cursor.execute(
                _SELECT_TASKS  # noqa: S608
                + ' WHERE t.organization_id = %s AND t.id = ('
                'SELECT c.parent_id FROM tickets.tickets AS c'
                ' WHERE c.organization_id = %s AND c.id = %s)',
                (task['organization_id'], *params),
            )
            parent = await cursor.fetchone()
            await cursor.execute(
                _SELECT_TASKS + ' WHERE organization_id = %s'
                ' AND parent_id = %s ORDER BY created_at, id',
                params,
            )
            children = await cursor.fetchall()
            await cursor.execute(_TREE, (task['id'],))
            tree = await cursor.fetchone()
        return {
            'requires': requires,
            'required_by': required_by,
            'parent': parent,
            'children': children,
            'tree': tree,
        }

    @_retry_deadlock
    async def set_parent(
        self,
        organization_id: str,
        short_id: str,
        parent: str | None,
        actor: Actor,
    ) -> None:
        """Move the task, with its descendants, under ``parent``, or make
        it a root when ``parent`` is ``None``.

        The ancestors of the new parent are read under an advisory lock
        on the organization, so two moves at once cannot make a cycle.
        Write ``parent.changed`` with the old and new parent. Write no
        event when the parent does not change.

        Raises:
            TaskNotFound: No such task.
            TaskArchived: The log of the task is archived.
            ParentCycle: The task is ``parent`` or one of its ancestors.

        """
        async with self._pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    'SELECT pg_advisory_xact_lock('
                    "hashtextextended('imbi.api.tickets.parent:' || %s, 0))",
                    (organization_id,),
                )
                tasks = await _lock_tasks(
                    conn,
                    organization_id,
                    [short_id] if parent is None else [short_id, parent],
                )
                by_short_id = {t['short_id']: t for t in tasks}
                task = by_short_id[short_id]
                if task['log_archived_at'] is not None:
                    raise TaskArchived(short_id)
                new = None if parent is None else by_short_id[parent]
                new_id = None if new is None else new['id']
                if task['parent_id'] == new_id:
                    return
                if new is not None:
                    cursor = await conn.execute(
                        _IS_ANCESTOR, (new_id, task['id'])
                    )
                    if await cursor.fetchone() is not None:
                        raise ParentCycle(short_id)
                old = None
                if task['parent_id'] is not None:
                    cursor = await conn.execute(
                        'SELECT short_id FROM tickets.tickets WHERE id = %s',
                        (task['parent_id'],),
                    )
                    (old,) = await cursor.fetchone() or (None,)
                event = await _append_event(
                    conn,
                    task['id'],
                    'parent.changed',
                    {'from': old, 'to': parent},
                    actor,
                )
                # After the event, so that the row has its new last_seq.
                task = await _update_task(
                    conn, task['id'], {'parent_id': new_id}
                )
        await log.publish(task, [event])

    async def projects(self, task: Row) -> list[Row]:
        """Return the projects associated with ``task``, oldest first."""
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                'SELECT * FROM tickets.ticket_projects'
                ' WHERE organization_id = %s AND ticket_id = %s'
                ' ORDER BY added_at, project_id',
                (task['organization_id'], task['id']),
            )
            return await cursor.fetchall()

    async def history(
        self, task: Row, max_seq: int | None = None
    ) -> tuple[list[Row], list[Row]]:
        """Return the human ``turn``, ``handed_off``, and ``reopened``
        events and the resolved requests of ``task``, oldest first, for
        the history of a new session. A withdrawn request is resolved.

        When ``max_seq`` is set, only events with ``seq <= max_seq`` are
        returned. The session reads the later events as events.

        A closed task opens no session, so the log is not archived. The
        turns up to ``archived_seq`` of a task that was reopened after
        an archive come from ClickHouse.
        """
        archived: list[Row] = []
        if task['archived_seq']:
            until = task['archived_seq']
            if max_seq is not None:
                until = min(until, max_seq)
            archived = await log.archived_history(task, until)
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                'SELECT type, at, actor_id, payload'
                ' FROM tickets.events WHERE ticket_id = %s'
                " AND ((type = 'turn' AND actor_kind = 'human')"
                " OR type IN ('handed_off', 'reopened'))"
                ' AND (%s::bigint IS NULL OR seq <= %s) ORDER BY seq',
                (task['id'], max_seq, max_seq),
            )
            turns = archived + await cursor.fetchall()
            await cursor.execute(
                'SELECT * FROM tickets.requests WHERE ticket_id = %s'
                ' AND resolved_at IS NOT NULL ORDER BY resolved_at, id',
                (task['id'],),
            )
            return turns, await cursor.fetchall()

    async def delegated(self, task: Row) -> list[Row]:
        """Return the tickets that ``task`` delegated, oldest first.

        They come from the origin link, not from ``parent_id``, so a
        ticket that a person moves to another parent stays in the
        history of the ticket that delegated it.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                _SELECT_TASKS + ' WHERE organization_id = %s'
                ' AND origin_kind = ANY(%s) AND origin_id = %s'
                ' ORDER BY created_at, id',
                (
                    task['organization_id'],
                    list(CHILD_ORIGIN_KINDS),
                    str(task['id']),
                ),
            )
            return await cursor.fetchall()

    # --- Harness ------------------------------------------------------

    async def open_session(
        self,
        organization_id: str,
        short_id: str,
        *,
        key: str,
        harness_instance: str | None,
        max_concurrent: int | None,
        actor: Actor,
    ) -> tuple[Row, Row, bool]:
        """Open a harness session; return the task, it, and if it is new.

        A repeat with the same ``key`` returns the first session. A new
        session moves a ``queued`` or ``blocked`` task with no open
        request to ``running`` when the control value is ``run``.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            CancelPending: The control value is ``cancel``.
            ConcurrencyLimit: ``max_concurrent`` other tasks of the
                agent have an open session.
            TicketHeld: An open gating prerequisite holds the task.
            WrongAssigneeKind: The task is a person ticket.

        """
        async with self._write(organization_id, short_id) as write:
            task = write.task
            if task['assignee_kind'] == 'person':
                raise WrongAssigneeKind(short_id)
            if task['control'] == 'cancel':
                raise CancelPending(short_id)
            session = await _fetch_one(
                write.conn,
                'SELECT * FROM tickets.sessions'
                ' WHERE ticket_id = %s AND session_key = %s',
                (task['id'], key),
            )
            if session is not None:
                return task, session, False
            if task['status'] == 'held':
                raise TicketHeld(short_id)
            if max_concurrent is not None:
                await _check_concurrency(
                    write.conn,
                    task['agent_id'],
                    task['id'],
                    max_concurrent,
                )
            session = await _fetch_one(
                write.conn,
                'INSERT INTO tickets.sessions'
                ' (id, ticket_id, session_key, harness_instance)'
                ' VALUES (%s, %s, %s, %s) RETURNING *',
                (uuid.uuid4(), task['id'], key, harness_instance),
            )
            if session is None:  # pragma: no cover - RETURNING yields a row
                raise RuntimeError('session insert returned no row')
            await write.event(
                'session.opened',
                {
                    'session_id': str(session['id']),
                    'session_key': key,
                    'harness_instance': harness_instance,
                },
                actor,
                session_id=session['id'],
            )
            if (
                task['control'] == 'run'
                and task['status'] in ('queued', 'blocked')
                and not await _request_open(write.conn, task['id'])
            ):
                await _set_status(write, 'running', 'session_opened', actor)
        return write.task, session, True

    async def heartbeat(
        self,
        organization_id: str,
        short_id: str,
        session_id: uuid.UUID,
        *,
        timeout_seconds: int | None,
        system: Actor,
    ) -> Row:
        """Record a heartbeat of an open session; return the task.

        When the task has run longer than ``timeout_seconds`` since its
        first session after its last handoff opened, close it with
        ``exceeded_ceiling``.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            SessionNotFound: The task has no such session.
            SessionClosed: The session is closed.

        """
        async with self._write(organization_id, short_id) as write:
            session = await _open_session(
                write.conn, write.task['id'], session_id
            )
            await write.conn.execute(
                'UPDATE tickets.sessions SET heartbeat_at = NOW()'
                ' WHERE id = %s',
                (session['id'],),
            )
            if timeout_seconds is not None:
                # The timeout counts from the first session after the
                # last handoff: an agent period starts there (ADR 0028).
                cursor = await write.conn.execute(
                    'SELECT NOW() - min(opened_at) > make_interval(secs => %s)'
                    ' FROM tickets.sessions WHERE ticket_id = %s'
                    " AND opened_at > COALESCE(%s::timestamptz, '-infinity')",
                    (
                        timeout_seconds,
                        write.task['id'],
                        write.task['period_started_at'],
                    ),
                )
                row = await cursor.fetchone()
                if row and row[0]:
                    await _close(
                        write, 'exceeded_ceiling', 'task_timeout', system
                    )
        return write.task

    async def close_session(
        self,
        organization_id: str,
        short_id: str,
        session_id: uuid.UUID,
        reason: str,
        actor: Actor,
        *,
        stale_seconds: int | None = None,
    ) -> Row:
        """Close a session and write ``session.closed``; return the task.

        A closed session stays closed; closing it again changes nothing.
        With ``stale_seconds``, the session closes only when its last
        sign of life (``heartbeat_at``, else ``opened_at``) is older.
        When no session remains open, the status follows the control
        value, as in :meth:`set_control`: ``pause`` moves the task to
        ``paused`` (a ``held`` task stays ``held``), ``run`` moves a
        ``running`` task back to ``queued``, and ``cancel`` closes it with
        ``cancelled_by_human``.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            SessionNotFound: The task has no such session.

        """
        async with self._write(organization_id, short_id) as write:
            task = write.task
            session = await _session(write.conn, task['id'], session_id)
            if session['closed_at'] is not None:
                return task
            if stale_seconds is not None and not await _stale(
                write.conn, session_id, stale_seconds
            ):
                return task
            await write.conn.execute(
                'UPDATE tickets.sessions'
                ' SET closed_at = NOW(), close_reason = %s WHERE id = %s',
                (reason, session_id),
            )
            await write.event(
                'session.closed',
                {'session_id': str(session_id), 'reason': reason},
                actor,
                session_id=session_id,
            )
            if not await _session_open(write.conn, task['id']):
                if task['control'] == 'cancel':
                    await _close(
                        write,
                        'cancelled_by_human',
                        CANCELLED_WITHOUT_SESSION,
                        actor,
                    )
                elif task['control'] == 'pause':
                    if task['status'] not in ('paused', 'held'):
                        await _set_status(
                            write, 'paused', 'session_closed', actor
                        )
                elif task['status'] == 'running':
                    await _set_status(write, 'queued', 'session_closed', actor)
        return write.task

    async def stale_sessions(self, stale_seconds: int) -> list[Row]:
        """Return open sessions with no sign of life in ``stale_seconds``.

        Each row has the session ``id`` and the ``organization_id`` and
        ``short_id`` of its task.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                'SELECT s.id, t.organization_id, t.short_id'
                ' FROM tickets.sessions AS s'
                ' JOIN tickets.tickets AS t ON t.id = s.ticket_id'
                ' WHERE s.closed_at IS NULL'
                ' AND COALESCE(s.heartbeat_at, s.opened_at)'
                ' < NOW() - make_interval(secs => %s)',
                (stale_seconds,),
            )
            return await cursor.fetchall()

    async def append_events(
        self,
        organization_id: str,
        short_id: str,
        events: list[NewEvent],
        session_id: uuid.UUID | None,
    ) -> tuple[Row, list[Row], list[uuid.UUID]]:
        """Write harness events; return the task, the events written,
        and the ids of the duplicates.

        An event whose ``event_id`` the task already has, or that comes
        earlier in the batch, is a duplicate. It is skipped before it
        takes a seq, so the sequence stays without gaps. A
        ``phase.changed`` event that is written also sets the ``phase``
        of the task.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            SessionNotFound: The task has no such session.
            SessionClosed: The session is closed.
            EventIdConflict: Another task has an event with an id.

        """
        try:
            async with self._write(organization_id, short_id) as write:
                if session_id is not None:
                    await _open_session(
                        write.conn, write.task['id'], session_id
                    )
                cursor = await write.conn.execute(
                    'SELECT event_id FROM tickets.events'
                    ' WHERE ticket_id = %s AND event_id = ANY(%s)',
                    (write.task['id'], [event.event_id for event in events]),
                )
                seen: set[uuid.UUID] = {
                    row[0] for row in await cursor.fetchall()
                }
                written: list[Row] = []
                duplicates: list[uuid.UUID] = []
                phase: str | None = None
                for event in events:
                    if event.event_id in seen:
                        duplicates.append(event.event_id)
                        continue
                    seen.add(event.event_id)
                    written.append(
                        await write.event(
                            event.type,
                            event.payload,
                            event.actor,
                            event_id=event.event_id,
                            session_id=session_id,
                            schema_version=event.schema_version,
                            at=event.at,
                        )
                    )
                    if event.type == 'phase.changed':
                        phase = event.payload['phase']
                if phase is not None:
                    await write.update({'phase': phase})
        except psycopg.errors.UniqueViolation as err:
            if err.diag.constraint_name != 'events_event_id_key':
                raise
            raise EventIdConflict(short_id) from err
        return write.task, written, duplicates

    async def open_request(
        self,
        organization_id: str,
        short_id: str,
        request: NewRequest,
        actor: Actor,
    ) -> tuple[Row, Row, bool]:
        """Open a request, write ``request.opened``, and block the task.

        Return the task, the request, and whether the request is new. A
        repeat with the same ``request_key`` returns the first request
        of the task. A ``held`` task stays ``held``.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            SessionNotFound: The task has no such session.
            SessionClosed: The session is closed.
            RequestKeyConflict: The request with the key has other
                ``artifact_digests``. Changed digests need a new request
                (I3).

        """
        async with self._write(organization_id, short_id) as write:
            task = write.task
            if request.request_key is not None:
                # Two opens with one key wait for the same task lock.
                existing = await _fetch_one(
                    write.conn,
                    'SELECT * FROM tickets.requests'
                    ' WHERE ticket_id = %s AND request_key = %s',
                    (task['id'], request.request_key),
                )
                if existing is not None:
                    if existing['artifact_digests'] != (
                        request.artifact_digests
                    ):
                        raise RequestKeyConflict(request.request_key)
                    return task, existing, False
            if request.session_id is not None:
                await _open_session(write.conn, task['id'], request.session_id)
            row = await _fetch_one(
                write.conn,
                'INSERT INTO tickets.requests (id, ticket_id,'
                ' session_id, kind, title, why, options, artifacts,'
                ' artifact_digests, expires_at, request_key)'
                ' VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'
                ' RETURNING *',
                (
                    uuid.uuid4(),
                    task['id'],
                    request.session_id,
                    request.kind,
                    request.title,
                    request.why,
                    _jsonb(request.options),
                    _jsonb(request.artifacts),
                    request.artifact_digests,
                    request.expires_at,
                    request.request_key,
                ),
            )
            if row is None:  # pragma: no cover - RETURNING yields a row
                raise RuntimeError('request insert returned no row')
            await write.event(
                'request.opened',
                {
                    'request_id': str(row['id']),
                    'kind': request.kind,
                    'title': request.title,
                    'why': request.why,
                    'options': request.options,
                    'artifacts': request.artifacts,
                    'artifact_digests': request.artifact_digests,
                    'expires_at': (
                        None
                        if request.expires_at is None
                        else request.expires_at.isoformat()
                    ),
                },
                actor,
                session_id=request.session_id,
            )
            # Only a release moves a held ticket on.
            if task['status'] not in ('blocked', 'held'):
                await _set_status(write, 'blocked', 'request_opened', actor)
        return write.task, row, True

    async def resolve_request(
        self,
        organization_id: str,
        short_id: str,
        request_id: uuid.UUID,
        resolution: Resolution,
        actor: Actor,
    ) -> tuple[Row, Row, bool]:
        """Resolve an open request and write ``request.resolved``.

        Return the task, the request, and whether this call resolved
        it. The same actor that sends the same resolution again gets the
        request back unchanged (I4). When no open request remains, a
        ``blocked`` task goes back to ``running`` if a session is open
        and the control value is ``run``; with no session open, it goes
        to ``queued`` (``paused`` when the control value is ``pause``).

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            RequestNotFound: The task has no such request.
            RequestNotOpen: Another resolution, or the request expired.
            ResolutionInvalid: The status does not fit the kind.
            DigestMismatch: An approval of other digests (I3).

        """
        async with self._write(organization_id, short_id) as write:
            task = write.task
            request = await _fetch_one(
                write.conn,
                'SELECT * FROM tickets.requests'
                ' WHERE id = %s AND ticket_id = %s FOR UPDATE',
                (request_id, task['id']),
            )
            if request is None:
                raise RequestNotFound(str(request_id))
            if request['status'] != 'open':
                stored: Row = request['resolution'] or {}
                if (
                    request['resolved_by'] == actor.id
                    and request['status'] == resolution.status
                    and stored.get('answer') == resolution.answer
                    and stored.get('constraints') == resolution.constraints
                    and (
                        resolution.status != 'approved'
                        or sorted(stored.get('artifact_digests') or [])
                        == sorted(resolution.artifact_digests or [])
                    )
                ):
                    return task, request, False
                raise RequestNotOpen(request)
            now = datetime.datetime.now(datetime.UTC)
            if request['expires_at'] is not None and (
                request['expires_at'] <= now
            ):
                raise RequestNotOpen(request)
            if resolution.status not in _RESOLVED_STATUSES[request['kind']]:
                raise ResolutionInvalid(
                    f'a {request["kind"]} request cannot be '
                    f'{resolution.status}'
                )
            if resolution.status == 'approved' and sorted(
                resolution.artifact_digests or []
            ) != sorted(request['artifact_digests'] or []):
                raise DigestMismatch(str(request_id))
            record: Row = {
                'answer': resolution.answer,
                'constraints': resolution.constraints,
                'artifact_digests': (
                    request['artifact_digests']
                    if resolution.status == 'approved'
                    else None
                ),
                'channel': actor.channel,
            }
            request = await _fetch_one(
                write.conn,
                'UPDATE tickets.requests SET status = %s,'
                ' resolved_by = %s, resolved_at = %s, resolution = %s'
                ' WHERE id = %s RETURNING *',
                (
                    resolution.status,
                    actor.id,
                    now,
                    pg_json.Jsonb(record),
                    request_id,
                ),
            )
            if request is None:  # pragma: no cover - the row is locked
                raise RequestNotFound(str(request_id))
            await write.event(
                'request.resolved',
                {
                    'request_id': str(request_id),
                    'kind': request['kind'],
                    'status': resolution.status,
                    'resolved_by': actor.id,
                    **record,
                },
                actor,
            )
            if task['status'] == 'blocked' and not await _request_open(
                write.conn, task['id']
            ):
                if not await _session_open(write.conn, task['id']):
                    await _set_status(
                        write,
                        _IDLE_STATUS[task['control']],
                        'request_resolved',
                        actor,
                    )
                elif task['control'] == 'run':
                    await _set_status(
                        write, 'running', 'request_resolved', actor
                    )
        return write.task, request, True

    async def report_usage(
        self,
        organization_id: str,
        short_id: str,
        usage: Usage,
        prices: dict[str, decimal.Decimal | None] | None,
        *,
        actor: Actor,
        system: Actor,
    ) -> tuple[Row, Row, bool]:
        """Record a usage report; return the task, the ledger row, and
        whether the row is new.

        The ledger row keeps the prices used, and the task totals change
        in the same transaction. When the cost total passes the budget,
        the task closes with ``exceeded_ceiling``. A repeat with the same
        idempotency key returns the first row, even when the first report
        closed the task.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            SessionNotFound: The task has no such session.
            SessionClosed: The session is closed.
            WrongAssigneeKind: The task is a person ticket.

        """
        repeat = await self._usage_repeat(
            organization_id, short_id, usage.idempotency_key
        )
        if repeat is not None:
            return *repeat, False
        try:
            async with self._write(organization_id, short_id) as write:
                task = write.task
                if task['assignee_kind'] == 'person':
                    raise WrongAssigneeKind(short_id)
                # Two reports with one key wait for the same task lock.
                existing = await _ledger_row(
                    write.conn, task['id'], usage.idempotency_key
                )
                if existing is not None:
                    return task, existing, False
                if usage.session_id is not None:
                    await _open_session(
                        write.conn, task['id'], usage.session_id
                    )
                counts: dict[str, int | None] = {
                    count_column: getattr(usage, count_column)
                    for count_column, _price_column in _TOKEN_PRICES
                }
                cost = usage_cost(counts, prices)
                row = await _fetch_one(
                    write.conn,
                    'INSERT INTO tickets.budget_ledger (id, ticket_id,'
                    ' session_id, idempotency_key, model_id, tokens_in,'
                    ' tokens_out, cache_read_tokens, cache_write_tokens,'
                    ' input_cost_per_million, output_cost_per_million,'
                    ' cache_read_cost_per_million,'
                    ' cache_write_cost_per_million, cost) VALUES (%s, %s,'
                    ' %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'
                    ' RETURNING *',
                    (
                        uuid.uuid4(),
                        task['id'],
                        usage.session_id,
                        usage.idempotency_key,
                        usage.model_id,
                        *counts.values(),
                        *(
                            None if prices is None else prices[price_column]
                            for _count_column, price_column in _TOKEN_PRICES
                        ),
                        cost,
                    ),
                )
                if row is None:  # pragma: no cover - RETURNING yields a row
                    raise RuntimeError('ledger insert returned no row')
                write.ledger.append(row)
                totals: Row = {
                    column: task[column] + (count or 0)
                    for column, count in counts.items()
                }
                totals['cost_total'] = task['cost_total'] + (cost or 0)
                budget: decimal.Decimal | None = task['budget']
                remaining = (
                    None if budget is None else budget - totals['cost_total']
                )
                await write.event(
                    'usage.reported',
                    {
                        'report_id': str(row['id']),
                        'model_id': usage.model_id,
                        **counts,
                        'cost': None if cost is None else str(cost),
                        'budget_remaining': (
                            None if remaining is None else str(remaining)
                        ),
                        **(
                            {'message_id': usage.message_id}
                            if usage.message_id is not None
                            else {}
                        ),
                    },
                    actor,
                    session_id=usage.session_id,
                )
                await write.update(totals)
                if remaining is not None and remaining < 0:
                    await _close(write, 'exceeded_ceiling', 'budget', system)
        except TaskClosed:
            repeat = await self._usage_repeat(
                organization_id, short_id, usage.idempotency_key
            )
            if repeat is None:
                raise
            return *repeat, False
        return write.task, row, True

    async def _usage_repeat(
        self, organization_id: str, short_id: str, key: str
    ) -> tuple[Row, Row] | None:
        """Return the task and its ledger row with ``key``, if any."""
        async with self._pool.connection() as conn:
            task = await _fetch_one(
                conn,
                _SELECT_TASKS
                + ' WHERE organization_id = %s AND short_id = %s',
                (organization_id, short_id),
            )
            if task is None:
                raise TaskNotFound(short_id)
            row = await _ledger_row(conn, task['id'], key)
        return None if row is None else (task, row)

    @_retry_deadlock
    async def set_outcome(
        self,
        organization_id: str,
        short_id: str,
        outcome: Outcome,
        reason: str | None,
        actor: Actor,
        structured_output: Row | None = None,
    ) -> Row:
        """Close the task with ``outcome``; see :func:`_close`.

        Keep the ``structured_output`` that the agent returned, if any.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.

        """
        async with self._write(organization_id, short_id) as write:
            await _close(write, outcome, reason, actor)
            if structured_output is not None:
                await write.update(
                    {'structured_output': _jsonb(structured_output)}
                )
        return write.task

    @_retry_deadlock
    async def set_person_status(
        self,
        organization_id: str,
        short_id: str,
        status: Status,
        actor: Actor,
        *,
        outcome: PersonOutcome | None = None,
        reason: str | None = None,
    ) -> Row:
        """Move a person ticket to ``status`` (ADR 0028).

        ``closed`` closes it with ``outcome`` from every status; see
        :func:`_close`. Other moves follow :data:`PERSON_TRANSITIONS`
        and write ``state.changed`` with the reason ``started``,
        ``blocked``, or ``unblocked``, and ``reason`` as ``note``. A
        move to the current status changes nothing.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            WrongAssigneeKind: The task is an agent ticket.
            TransitionInvalid: The move is not in
                :data:`PERSON_TRANSITIONS`.

        """
        async with self._write(organization_id, short_id) as write:
            task = write.task
            if task['assignee_kind'] != 'person':
                raise WrongAssigneeKind(short_id)
            if status == 'closed' and outcome is not None:
                await _close(write, outcome, reason, actor)
            elif task['status'] in PERSON_TRANSITIONS.get(status, ()):
                code = 'started'
                if status == 'blocked':
                    code = 'blocked'
                elif task['status'] == 'blocked':
                    code = 'unblocked'
                await write.event(
                    'state.changed',
                    {
                        'from': task['status'],
                        'to': status,
                        'reason': code,
                        'note': reason,
                    },
                    actor,
                )
                await write.update({'status': status})
            elif task['status'] != status:
                raise TransitionInvalid(short_id, task['status'], status)
        return write.task

    @_retry_deadlock
    async def reopen(
        self,
        organization_id: str,
        short_id: str,
        reason: str,
        actor: Actor,
        to: HandOff,
    ) -> Row:
        """Reopen a closed ticket (ADR 0028).

        Clear the outcome and ``closed_at``, write ``reopened`` with the
        old outcome and ``reason``, and ``state.changed``. ``to`` is the
        assignee of either kind, also when it does not change, as in a
        handoff: an agent at the version and the platform configuration
        that it has now, whose task budget caps the budget of the
        ticket. A person ticket
        returns to ``open``, an agent ticket to ``queued``, or to
        ``held`` when a gating prerequisite holds it. The reopen starts
        a new agent period, as a handoff does: the task timeout counts
        from the first session after it (``period_started_at``).

        The ticket starts a new chain (``chain_id`` is its id), so a
        reopened child can be claimed. When it is an agent ticket and
        its chain row is ``done``, the row returns to ``queued`` with a
        new attempt. An archived log is not archived after this:
        ``archived_seq`` keeps the last seq that only ClickHouse has.

        Raises:
            TaskNotFound: No such task.
            TaskOpen: The task is not closed.
            ReopenRefused: The chain of the ticket is pinned, or the
                workflow runs of an earlier change have not all started.

        """
        async with self._write(
            organization_id, short_id, closed=True
        ) as write:
            task = write.task
            cursor = await write.conn.execute(
                'SELECT EXISTS (SELECT 1 FROM tickets.trigger_outbox'
                ' WHERE ticket_id = %s)',
                (task['id'],),
            )
            row = await cursor.fetchone()
            if row and row[0]:
                raise ReopenRefused(short_id, 'triggers_pending')
            # A chain never changes while a runner holds it. The lock
            # makes a claim of the chain wait for this change.
            if await _chain_state(write.conn, task) in PINNED_CHAIN_STATES:
                raise ReopenRefused(short_id, 'chain_pinned')
            changes: Row = {
                'outcome': None,
                'outcome_reason': None,
                'closed_at': None,
                'control': 'run',
                'acknowledged_at': None,
                'acknowledged_by': None,
                'chain_id': task['id'],
                'period_started_at': datetime.datetime.now(datetime.UTC),
                **await _assignee_columns(write.conn, task, to),
            }
            payload: Row = {
                'outcome': task['outcome'],
                'outcome_reason': task['outcome_reason'],
                'reason': reason,
            }
            before, after = _assignee_of(task), _assignee_of(changes)
            if before != after:
                payload['assignee'] = {'from': before, 'to': after}
            if task['log_archived_at'] is not None:
                changes['log_archived_at'] = None
                changes['archived_seq'] = task['last_seq']
            agent = to.assignee_kind == 'agent'
            status: Status = 'queued' if agent else 'open'
            await write.event('reopened', payload, actor)
            await write.event(
                'state.changed',
                {'from': 'closed', 'to': status, 'reason': 'reopened'},
                actor,
            )
            await write.update({**changes, 'status': status})
            if agent:
                await _queue_done_chain(write.conn, task['id'])
            await _sync_gate(write, actor)
        return write.task

    async def handed_off(
        self, organization_id: str, short_id: str, session_id: uuid.UUID
    ) -> Row | None:
        """Return the ticket when the session handed it to a person (the
        session closed with the reason ``handed_off``) and it is still a
        person ticket; else ``None``."""
        async with self._pool.connection() as conn:
            return await _fetch_one(
                conn,
                _SELECT_TASKS + ' JOIN tickets.sessions AS s'
                ' ON s.ticket_id = t.id AND s.id = %s'
                " AND s.close_reason = 'handed_off'"
                ' WHERE t.organization_id = %s AND t.short_id = %s'
                " AND t.assignee_kind = 'person'",
                (session_id, organization_id, short_id),
            )

    async def hand_off(
        self,
        organization_id: str,
        short_id: str,
        to: HandOff,
        actor: Actor,
        *,
        session_id: uuid.UUID | None = None,
    ) -> Row:
        """Give the ticket to another assignee (ADR 0028).

        A change of kind writes ``handed_off`` and changes the status in
        the same write: ``held`` stays ``held``, every other status
        becomes ``open`` (to a person) or ``queued`` (to an agent). The
        control value goes back to ``run``. Each open request closes as
        ``withdrawn`` with a ``request.withdrawn`` event. To an agent,
        the agent columns are set; the budget becomes the lower of the
        budget of the ticket and ``to.budget`` (the task budget of the
        agent), and the cost total stays, so the budget counts every
        agent period. A ``done`` chain goes back to
        ``queued`` with a new attempt, so that a runner claims the
        ticket. From a person to another person, only ``assignee``
        changes, with ``assignee.changed``.

        Without ``session_id``, the handoff is refused while a session is
        open or the chain is pinned, except from a person to a person: no
        agent works the ticket then. An agent target gets the platform
        configuration that the organization has now. With
        ``session_id``, the agent of that open session hands its own
        ticket to a person: its sessions
        close (reason ``handed_off``) in the same write, and the runner
        keeps the chain.

        Raises:
            TaskNotFound: No such task.
            TaskClosed: The task is closed.
            SessionNotFound: The task has no such session.
            SessionClosed: The session is closed.
            SessionOpen: A session is open.
            ChainPinned: A runner holds the chain.
            WrongAssigneeKind: An agent ticket goes to an agent.
            CancelPending: A cancel waits for the harness.

        """
        async with self._write(organization_id, short_id) as write:
            task = write.task
            if to.assignee_kind == 'agent' == task['assignee_kind']:
                raise WrongAssigneeKind(short_id)
            if task['control'] == 'cancel':
                raise CancelPending(short_id)
            if session_id is not None:
                await _open_session(write.conn, task['id'], session_id)
                await _close_sessions(write, 'handed_off', actor)
            elif 'agent' in (task['assignee_kind'], to.assignee_kind):
                # Only a change that involves an agent waits for it.
                if await _session_open(write.conn, task['id']):
                    raise SessionOpen(short_id)
                if await _chain_state(write.conn, task) in PINNED_CHAIN_STATES:
                    raise ChainPinned(short_id)
            if to.assignee_kind == task['assignee_kind']:
                if to.assignee != task['assignee']:
                    await write.event(
                        'assignee.changed',
                        {
                            'from': task['assignee'],
                            'to': to.assignee,
                            'note': to.note,
                        },
                        actor,
                    )
                    await write.update({'assignee': to.assignee})
            else:
                await _hand_off(write, to, actor)
        return write.task


async def requeue_chain(
    conn: Conn, chain_id: uuid.UUID, attempt: int, actor: Actor
) -> list[_Write]:
    """Put the open tasks of a chain back in the queue (ADR 0022).

    Use this in the transaction that unpins the chain from a lost
    runner. For each task that is not closed, in task id order: close
    its open sessions (reason ``runner_lost``), write ``attempt_marker``
    with the new ``attempt``, and set the status as for a task with no
    session (see :meth:`TicketStore.close_session`): ``cancel`` closes
    it, ``pause`` makes it ``paused``, an open request makes it
    ``blocked``, else it is ``queued``.

    Return the write of each task, to publish after the commit
    (:func:`after_commit`).
    """
    async with conn.cursor(row_factory=rows.dict_row) as cursor:
        await cursor.execute(
            _SELECT_TASKS
            + ' WHERE (chain_id = %s OR (chain_id IS NULL AND id = %s))'
            " AND status <> 'closed' AND assignee_kind = 'agent'"
            ' ORDER BY id FOR UPDATE',
            (chain_id, chain_id),
        )
        tasks = await cursor.fetchall()
    published: list[_Write] = []
    for task in tasks:
        write = _Write(conn, task)
        cursor = await conn.execute(
            'UPDATE tickets.sessions'
            " SET closed_at = NOW(), close_reason = 'runner_lost'"
            ' WHERE ticket_id = %s AND closed_at IS NULL RETURNING id',
            (task['id'],),
        )
        for (session_id,) in await cursor.fetchall():
            await write.event(
                'session.closed',
                {'session_id': str(session_id), 'reason': 'runner_lost'},
                actor,
                session_id=session_id,
            )
        await write.event(
            'attempt_marker',
            {'attempt': attempt, 'reason': 'runner_lost'},
            actor,
        )
        status: Status = 'queued'
        if task['status'] == 'held':
            status = 'held'
        elif task['control'] == 'pause':
            status = 'paused'
        elif await _request_open(conn, task['id']):
            status = 'blocked'
        if task['control'] == 'cancel':
            await _close(
                write, 'cancelled_by_human', CANCELLED_WITHOUT_SESSION, actor
            )
        elif task['status'] != status:
            await _set_status(write, status, 'runner_lost', actor)
        write.task = await _fetch_task(conn, task['id'])
        published.append(write)
    return published


async def append_event(
    conn: Conn,
    organization_id: str,
    task_id: uuid.UUID,
    event_type: str,
    payload: Row,
    actor: Actor,
) -> tuple[Row, Row] | None:
    """Write one event on a task in the transaction of ``conn``.

    For a change in another schema that the task shows, such as a
    secret resolution (ADR 0022). The task row is locked until the
    transaction ends. A closed task gets the event while its log is not
    archived. Return the task and the event, to publish after the
    commit, or ``None`` when the organization has no such task or its
    log is archived.
    """
    task = await _fetch_one(
        conn,
        _SELECT_TASKS + ' WHERE id = %s'
        ' AND organization_id = %s AND log_archived_at IS NULL FOR UPDATE',
        (task_id, organization_id),
    )
    if task is None:
        return None
    return task, await _append_event(conn, task_id, event_type, payload, actor)


async def _apply_control(
    write: _Write, control: Control, actor: Actor, short_id: str
) -> None:
    """Set the control value; see :meth:`TicketStore.set_control`."""
    task = write.task
    if task['assignee_kind'] == 'person':
        raise WrongAssigneeKind(short_id)
    if task['control'] == control:
        return
    if task['control'] == 'cancel':
        raise CancelPending(short_id)
    await write.event(
        'control.changed',
        {'from': task['control'], 'to': control, 'actor': actor.id},
        actor,
    )
    changes: Row = {'control': control}
    status = task['status']
    if not await _session_open(write.conn, task['id']):
        status = _IDLE_STATUS[control]
        if status == 'queued' and await _request_open(write.conn, task['id']):
            status = 'blocked'
    elif control == 'run' and status == 'paused':
        status = (
            'blocked'
            if await _request_open(write.conn, task['id'])
            else 'running'
        )
    # Only a release moves a held ticket on; it reads the control.
    if task['status'] == 'held' and status != 'closed':
        status = 'held'
    if status != task['status']:
        changes['status'] = status
        await write.event(
            'state.changed',
            {
                'from': task['status'],
                'to': status,
                'reason': 'control_changed',
            },
            actor,
        )
    if status == 'closed':
        changes['outcome'] = 'cancelled_by_human'
        changes['outcome_reason'] = CANCELLED_WITHOUT_SESSION
        changes['closed_at'] = datetime.datetime.now(datetime.UTC)
        await write.event(
            'outcome.set',
            {
                'outcome': changes['outcome'],
                'reason': changes['outcome_reason'],
            },
            actor,
        )
    await write.update(changes)


async def _set_status(
    write: _Write, status: Status, reason: str, actor: Actor
) -> None:
    """Change the status of the task and write ``state.changed``."""
    await write.event(
        'state.changed',
        {'from': write.task['status'], 'to': status, 'reason': reason},
        actor,
    )
    await write.update({'status': status})


async def _sync_gate(write: _Write, actor: Actor) -> None:
    """Hold or release a ticket that has not started, by its gates.

    A ``queued`` (agent) or ``open`` (person) ticket that an open gating
    prerequisite holds becomes ``held``. A ``held`` person ticket that
    nothing holds becomes ``open``. A ``held`` agent ticket becomes
    ``queued``, ``paused`` when its control is ``pause``, or ``blocked``
    when it has an open request. Other statuses do not change. The
    caller holds the row lock of the ticket.
    """
    task = write.task
    if task['status'] not in _NOT_STARTED:
        return
    cursor = await write.conn.execute(
        _GATED, (task['id'], list(DONE_OUTCOMES))
    )
    row = await cursor.fetchone()
    if row and row[0]:
        if task['status'] != 'held':
            await _set_status(write, 'held', 'gated', actor)
    elif task['status'] == 'held':
        status: Status = 'queued'
        if task['assignee_kind'] == 'person':
            status = 'open'
        elif task['control'] == 'pause':
            status = 'paused'
        elif await _request_open(write.conn, task['id']):
            status = 'blocked'  # It still waits for an answer.
        await _set_status(write, status, 'released', actor)


def _done(task: Row) -> bool:
    """Whether ``task`` closed with an outcome that releases the tickets
    that it gates."""
    return task['status'] == 'closed' and task['outcome'] in DONE_OUTCOMES


async def _release_dependents(
    conn: Conn, dependent_ids: list[uuid.UUID], actor: Actor
) -> list[_Write]:
    """Release each ``held`` ticket of ``dependent_ids`` that no gate
    holds; see :func:`_sync_gate`.

    The caller holds the lock of the prerequisite. The dependents lock
    after it, in task id order. Every change to a dependency locks the
    prerequisite first, so it waits for this transaction or this one
    waits for it. Return the write of each released ticket, to publish
    after the commit.
    """
    if not dependent_ids:
        return []
    async with conn.cursor(row_factory=rows.dict_row) as cursor:
        await cursor.execute(
            _SELECT_TASKS + " WHERE t.status = 'held' AND t.id = ANY(%s)"
            ' ORDER BY t.id FOR UPDATE',
            (dependent_ids,),
        )
        dependents = await cursor.fetchall()
    released: list[_Write] = []
    for dependent in dependents:
        write = _Write(conn, dependent)
        await _sync_gate(write, actor)
        if write.events:
            released.append(write)
    return released


async def _close(
    write: _Write, outcome: Outcome, reason: str | None, actor: Actor
) -> None:
    """Close the task with an outcome.

    Close each open session (``session.closed``), then write
    ``state.changed`` and ``outcome.set``. A ``done_*`` outcome
    releases the dependents that the task gates, in this transaction.
    """
    await _close_sessions(write, 'task_closed', actor)
    await write.event(
        'state.changed',
        {
            'from': write.task['status'],
            'to': 'closed',
            'reason': 'outcome_set',
        },
        actor,
    )
    await write.event(
        'outcome.set', {'outcome': outcome, 'reason': reason}, actor
    )
    await write.update(
        {
            'status': 'closed',
            'outcome': outcome,
            'outcome_reason': reason,
            'closed_at': datetime.datetime.now(datetime.UTC),
        }
    )
    if outcome in DONE_OUTCOMES:
        cursor = await write.conn.execute(
            'SELECT dependent_ticket_id FROM tickets.ticket_dependencies'
            ' WHERE prerequisite_ticket_id = %s AND gates',
            (write.task['id'],),
        )
        write.released = await _release_dependents(
            write.conn, [row[0] for row in await cursor.fetchall()], actor
        )


async def _chain_state(conn: Conn, task: Row) -> str | None:
    """Lock the chain row of ``task`` and return its state; ``None``
    when no runner claimed the chain yet."""
    cursor = await conn.execute(
        'SELECT state FROM harness.chains WHERE root_ticket_id = %s'
        ' FOR UPDATE',
        (task['chain_id'] or task['id'],),
    )
    row = await cursor.fetchone()
    return None if row is None else str(row[0])


def _assignee_of(row: Row) -> Row:
    """One side of a ``handed_off`` event."""
    if row['assignee_kind'] == 'person':
        return {'kind': 'person', 'assignee': row['assignee']}
    return {
        'kind': 'agent',
        'agent_id': row['agent_id'],
        'agent_version': row['agent_version'],
    }


async def _assignee_columns(conn: Conn, task: Row, to: HandOff) -> Row:
    """The assignee columns of ``task`` for the assignee ``to``.

    The task budget of an agent caps the budget of the ticket, as for a
    create. A person ticket keeps its budget, which the agent periods
    count against. An agent works under the platform configuration that
    the organization has now, as a new ticket does, not the one of the
    create.
    """
    columns: Row = {
        'assignee_kind': to.assignee_kind,
        'assignee': to.assignee,
        'agent_id': to.agent_id,
        'agent_version': to.agent_version,
        'prompt_version': to.prompt_version,
        'service_account_id': to.service_account_id,
    }
    if to.assignee_kind == 'agent':
        budgets = [b for b in (task['budget'], to.budget) if b is not None]
        columns['budget'] = min(budgets, default=None)
        cursor = await conn.execute(
            'SELECT max(version) FROM harness.platform_configs'
            ' WHERE organization_id = %s',
            (task['organization_id'],),
        )
        row = await cursor.fetchone()
        columns['platform_config_version'] = row[0] if row else None
    return columns


async def _queue_done_chain(conn: Conn, chain_id: uuid.UUID) -> None:
    """Put a ``done`` chain back in the queue with a new attempt, so
    that a runner claims its ticket again."""
    await conn.execute(
        "UPDATE harness.chains SET state = 'queued',"
        ' attempt = attempt + 1, runner_id = NULL, updated_at = NOW()'
        " WHERE root_ticket_id = %s AND state = 'done'",
        (chain_id,),
    )


async def _hand_off(write: _Write, to: HandOff, actor: Actor) -> None:
    """Change the assignee kind; see :meth:`TicketStore.hand_off`."""
    task = write.task
    cursor = await write.conn.execute(
        "UPDATE tickets.requests SET status = 'withdrawn',"
        ' resolved_at = NOW(), resolved_by = %s'
        " WHERE ticket_id = %s AND status = 'open'"
        ' RETURNING id',
        (actor.id, task['id']),
    )
    for (request_id,) in sorted(await cursor.fetchall()):
        await write.event(
            'request.withdrawn', {'request_id': str(request_id)}, actor
        )
    status: Status = (
        'held'
        if task['status'] == 'held'
        else 'open'
        if to.assignee_kind == 'person'
        else 'queued'
    )
    await write.event(
        'handed_off',
        {
            'from': _assignee_of(task),
            'to': _assignee_of(dataclasses.asdict(to)),
            'note': to.note,
        },
        actor,
    )
    if status != task['status']:
        await write.event(
            'state.changed',
            {'from': task['status'], 'to': status, 'reason': 'handed_off'},
            actor,
        )
    # One write, so the checks of the assignee kind hold on the row.
    changes: Row = {
        'status': status,
        'control': 'run',
        'period_started_at': datetime.datetime.now(datetime.UTC),
        **await _assignee_columns(write.conn, task, to),
    }
    if to.assignee_kind == 'agent':
        await _queue_done_chain(write.conn, task['chain_id'] or task['id'])
    await write.update(changes)


async def _close_sessions(write: _Write, reason: str, actor: Actor) -> None:
    """Close every open session of the task, each with ``session.closed``."""
    cursor = await write.conn.execute(
        'UPDATE tickets.sessions SET closed_at = NOW(), close_reason = %s'
        ' WHERE ticket_id = %s AND closed_at IS NULL RETURNING id',
        (reason, write.task['id']),
    )
    for (session_id,) in await cursor.fetchall():
        await write.event(
            'session.closed',
            {'session_id': str(session_id), 'reason': reason},
            actor,
            session_id=session_id,
        )


async def _session(
    conn: Conn, task_id: uuid.UUID, session_id: uuid.UUID
) -> Row:
    session = await _fetch_one(
        conn,
        'SELECT * FROM tickets.sessions WHERE id = %s AND ticket_id = %s',
        (session_id, task_id),
    )
    if session is None:
        raise SessionNotFound(str(session_id))
    return session


async def _open_session(
    conn: Conn, task_id: uuid.UUID, session_id: uuid.UUID
) -> Row:
    session = await _session(conn, task_id, session_id)
    if session['closed_at'] is not None:
        raise SessionClosed(str(session_id))
    return session


async def _stale(
    conn: Conn, session_id: uuid.UUID, stale_seconds: int
) -> bool:
    cursor = await conn.execute(
        'SELECT COALESCE(heartbeat_at, opened_at)'
        ' < NOW() - make_interval(secs => %s)'
        ' FROM tickets.sessions WHERE id = %s',
        (stale_seconds, session_id),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def _check_concurrency(
    conn: Conn,
    agent_id: str,
    task_id: uuid.UUID,
    max_concurrent: int,
) -> None:
    """Raise when ``max_concurrent`` other tasks of the agent run.

    A task runs when it has an open session. A new session on a task
    that already runs (for example after a harness restart) does not
    start a new concurrent task, so it always gets a place, even when
    the descendants of the task fill the cap. The count excludes
    ``task_id`` and the ancestors of ``task_id`` (its parent, up to the
    root): a parent that waits for its child keeps its session open, so
    a child of the same agent would otherwise never get a place. The
    siblings of the task and their descendants still count, so one
    chain cannot use more than ``max_concurrent`` places.

    The advisory lock makes concurrent opens for one agent count one at
    a time, so two opens cannot both take the last place.
    """
    await conn.execute(
        'SELECT pg_advisory_xact_lock(hashtext(%s))',
        # The key of the previous release, which opens sessions too
        # during a rolling deploy (ADR 0028).
        (f'agent_runtime.sessions:{agent_id}',),
    )
    cursor = await conn.execute(
        'SELECT EXISTS (SELECT 1 FROM tickets.sessions'
        ' WHERE ticket_id = %s AND closed_at IS NULL)',
        (task_id,),
    )
    row = await cursor.fetchone()
    if row and row[0]:
        return
    cursor = await conn.execute(
        # UNION (not UNION ALL) stops the walk if parent_id makes a loop.
        'WITH RECURSIVE lineage (id) AS ('
        ' SELECT %s::uuid'
        ' UNION SELECT p.parent_id FROM tickets.tickets AS p'
        ' JOIN lineage AS l ON p.id = l.id'
        ' WHERE p.parent_id IS NOT NULL)'
        ' SELECT count(DISTINCT s.ticket_id) FROM tickets.sessions AS s'
        ' JOIN tickets.tickets AS t ON t.id = s.ticket_id'
        ' WHERE t.agent_id = %s AND s.closed_at IS NULL'
        ' AND s.ticket_id NOT IN (SELECT id FROM lineage)',
        (task_id, agent_id),
    )
    row = await cursor.fetchone()
    if row and row[0] >= max_concurrent:
        raise ConcurrencyLimit(agent_id)


async def _ledger_row(conn: Conn, task_id: uuid.UUID, key: str) -> Row | None:
    return await _fetch_one(
        conn,
        'SELECT * FROM tickets.budget_ledger'
        ' WHERE ticket_id = %s AND idempotency_key = %s',
        (task_id, key),
    )


async def _request_open(conn: Conn, task_id: uuid.UUID) -> bool:
    cursor = await conn.execute(
        'SELECT EXISTS (SELECT 1 FROM tickets.requests'
        " WHERE ticket_id = %s AND status = 'open')",
        (task_id,),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


def _jsonb(value: typing.Any) -> pg_json.Jsonb | None:
    return None if value is None else pg_json.Jsonb(value)


async def _fetch_one(
    conn: psycopg.AsyncConnection[typing.Any],
    query: typing.LiteralString,
    params: tuple[typing.Any, ...],
) -> Row | None:
    async with conn.cursor(row_factory=rows.dict_row) as cursor:
        await cursor.execute(query, params)
        return await cursor.fetchone()


async def _fetch_task(
    conn: psycopg.AsyncConnection[typing.Any], task_id: uuid.UUID
) -> Row:
    row = await _fetch_one(
        conn,
        _SELECT_TASKS + ' WHERE id = %s',
        (task_id,),
    )
    if row is None:  # pragma: no cover - read inside the write transaction
        raise TaskNotFound(str(task_id))
    return row


async def _lock_task(
    conn: psycopg.AsyncConnection[typing.Any],
    organization_id: str,
    short_id: str,
    *,
    closed: bool = False,
) -> Row:
    """Lock and return an open task, for a change in this transaction.

    With ``closed``, the task must be closed instead.
    """
    task = await _fetch_one(
        conn,
        _SELECT_TASKS
        + ' WHERE organization_id = %s AND short_id = %s FOR UPDATE',
        (organization_id, short_id),
    )
    if task is None:
        raise TaskNotFound(short_id)
    if closed and task['status'] != 'closed':
        raise TaskOpen(short_id)
    if not closed and task['status'] == 'closed':
        raise TaskClosed(short_id)
    return task


async def _lock_tasks(
    conn: Conn, organization_id: str, short_ids: list[str]
) -> list[Row]:
    """Lock and return tasks in the order of ``short_ids``, closed or
    not."""
    async with conn.cursor(row_factory=rows.dict_row) as cursor:
        await cursor.execute(
            _SELECT_TASKS
            + ' WHERE organization_id = %s AND short_id = ANY(%s)'
            ' ORDER BY array_position(%s, short_id) FOR UPDATE',
            (organization_id, short_ids, short_ids),
        )
        tasks = await cursor.fetchall()
    found = {task['short_id'] for task in tasks}
    for short_id in short_ids:
        if short_id not in found:
            raise TaskNotFound(short_id)
    return tasks


def _json_row(row: Row) -> Row:
    """Return a relation row as event payload: ids and times as text.

    The keys keep the column names of ADR 0020 (``task_id``,
    ``dependent_task_id``), so that the payloads of logged events do not
    change with the rename of ADR 0028.
    """
    return {
        key.replace('ticket', 'task'): value.isoformat()
        if isinstance(value, datetime.datetime)
        else str(value)
        if isinstance(value, uuid.UUID)
        else value
        for key, value in row.items()
    }


def _dependency_payload(relate: _Relate, row: Row) -> abc.Callable[[Row], Row]:
    """Return the payload of a dependency event on each task: the row,
    the short ids of both tasks, and the side of the task."""
    short_ids = {task['id']: task['short_id'] for task in relate.tasks}
    common: Row = {
        **_json_row(row),
        'dependent_short_id': short_ids[row['dependent_ticket_id']],
        'prerequisite_short_id': short_ids[row['prerequisite_ticket_id']],
    }
    return lambda task: {
        **common,
        'side': (
            'dependent'
            if task['id'] == row['dependent_ticket_id']
            else 'prerequisite'
        ),
    }


async def _write_outbox(conn: Conn, task: Row, from_state: str | None) -> bool:
    """Write the ``trigger_outbox`` row of a creation (``from_state`` is
    ``None``) or a status change of ``task``, in its transaction, so its
    ``ticket_state_changed`` runs start even when the change hook fails.

    Most changes start no run, so the row is written only when the
    outbox filter says the org can start one. Return whether it was.
    """
    if _outbox_filter is None or not await _outbox_filter(
        conn, task['organization_id']
    ):
        return False
    # clock_timestamp(), not the NOW() default: a binding that the
    # filter sees can be activated after this transaction started, and
    # the trigger skips a change older than the binding.
    await conn.execute(
        'INSERT INTO tickets.trigger_outbox'
        ' (ticket_id, from_state, to_state, outcome, agent_id, created_at)'
        ' VALUES (%s, %s, %s, %s, %s, clock_timestamp())',
        (
            task['id'],
            from_state,
            task['status'],
            task['outcome'] if task['status'] == 'closed' else None,
            task['agent_id'],
        ),
    )
    return True


async def _update_task(
    conn: psycopg.AsyncConnection[typing.Any],
    task_id: uuid.UUID,
    changes: Row,
) -> Row:
    statement = sql.SQL(
        'UPDATE tickets.tickets AS t SET {sets}, updated_at = NOW()'  # noqa: S608
        ' WHERE id = %s RETURNING t.*, ' + PROJECTS
    ).format(
        sets=sql.SQL(', ').join(
            sql.SQL('{col} = %s').format(col=sql.Identifier(col))
            for col in changes
        )
    )
    async with conn.cursor(row_factory=rows.dict_row) as cursor:
        await cursor.execute(statement, [*changes.values(), task_id])
        row = await cursor.fetchone()
    if row is None:  # pragma: no cover - the row is locked
        raise TaskNotFound(str(task_id))
    return row


async def _session_open(
    conn: psycopg.AsyncConnection[typing.Any], task_id: uuid.UUID
) -> bool:
    cursor = await conn.execute(
        'SELECT EXISTS (SELECT 1 FROM tickets.sessions'
        ' WHERE ticket_id = %s AND closed_at IS NULL)',
        (task_id,),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def _next_short_id(
    conn: psycopg.AsyncConnection[typing.Any], organization_id: str
) -> str:
    """Take the next ``T-<n>`` of the organization.

    The row lock holds until the transaction ends, so a rollback returns
    the number.
    """
    cursor = await conn.execute(
        'INSERT INTO tickets.ticket_id_sequences'
        ' (organization_id, last_value) VALUES (%s, 1)'
        ' ON CONFLICT (organization_id) DO UPDATE'
        ' SET last_value = ticket_id_sequences.last_value + 1'
        ' RETURNING last_value',
        (organization_id,),
    )
    row = await cursor.fetchone()
    if row is None:  # pragma: no cover - RETURNING always yields a row
        raise RuntimeError('task id sequence returned no row')
    return f'T-{row[0]}'


async def _append_event(
    conn: Conn,
    task_id: uuid.UUID,
    event_type: str,
    payload: Row,
    actor: Actor,
    *,
    event_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    schema_version: int = 1,
    at: datetime.datetime | None = None,
) -> Row:
    """Write one event with the next ``seq`` of the task; return it.

    ``event_id`` defaults to a new UUID.

    ``at`` is the time the event happened. The default is the start of
    the transaction.
    """
    cursor = await conn.execute(
        'UPDATE tickets.tickets SET last_seq = last_seq + 1'
        ' WHERE id = %s RETURNING last_seq',
        (task_id,),
    )
    row = await cursor.fetchone()
    if row is None:  # pragma: no cover - callers hold the task
        raise TaskNotFound(str(task_id))
    event = await _fetch_one(
        conn,
        'INSERT INTO tickets.events (ticket_id, seq, event_id, type,'
        ' schema_version, actor_kind, actor_id, channel, session_id, at,'
        ' payload) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,'
        ' COALESCE(%s, NOW()), %s) RETURNING *',
        (
            task_id,
            row[0],
            event_id or uuid.uuid4(),
            event_type,
            schema_version,
            actor.kind,
            actor.id,
            actor.channel,
            session_id,
            at,
            pg_json.Jsonb(payload),
        ),
    )
    if event is None:  # pragma: no cover - RETURNING always yields a row
        raise RuntimeError('event insert returned no row')
    return event


def _event_value(value: typing.Any) -> typing.Any:
    """Return a column value as JSON for an event payload."""
    return value.isoformat() if isinstance(value, datetime.date) else value


#: The backlog tickets of an org other than one, for :func:`_rank_after`.
_BACKLOG = 'organization_id = %s AND status = ANY(%s) AND id <> %s'


async def _rank_after(
    conn: Conn, organization_id: str, task_id: uuid.UUID, after: str | None
) -> float:
    """Return the rank that puts a task right after the backlog task
    ``after``, or first; see :meth:`TicketStore.rank`.

    Raises:
        TaskNotFound: ``after`` is not a backlog task of the org.

    """
    backlog = (organization_id, list(BACKLOG_STATUSES), task_id)

    async def value(
        query: typing.LiteralString, *args: typing.Any
    ) -> typing.Any:
        cursor = await conn.execute(query, (*backlog, *args))
        found = await cursor.fetchone()
        return found[0] if found else None

    if after is None:
        first = await value(
            'SELECT min(backlog_rank) FROM tickets.tickets WHERE ' + _BACKLOG  # noqa: S608
        )
        return 0.0 if first is None else float(first) - 1.0
    anchor = await _fetch_one(
        conn,
        'SELECT id, backlog_rank, created_at FROM tickets.tickets'  # noqa: S608
        ' WHERE ' + _BACKLOG + ' AND short_id = %s',
        (*backlog, after),
    )
    if anchor is None:
        raise TaskNotFound(after)
    lo = anchor['backlog_rank']
    if lo is None:
        # Rank the unranked tickets down to the anchor, in the order
        # the backlog shows them: newest first, after the ranked ones.
        last = await value(
            'SELECT coalesce(max(backlog_rank), 0) FROM tickets.tickets'  # noqa: S608
            ' WHERE ' + _BACKLOG
        )
        cursor = await conn.execute(
            'UPDATE tickets.tickets AS t SET backlog_rank = %s + s.n'  # noqa: S608
            ' FROM (SELECT id, row_number() OVER'
            ' (ORDER BY created_at DESC, id DESC) AS n'
            ' FROM tickets.tickets WHERE '
            + _BACKLOG
            + ' AND backlog_rank IS NULL AND (created_at, id) >= (%s, %s))'
            ' AS s WHERE t.id = s.id',
            (last, *backlog, anchor['created_at'], anchor['id']),
        )
        # The anchor is the oldest of the rows, so it has the last rank.
        lo = float(last) + cursor.rowcount
    hi = await value(
        'SELECT min(backlog_rank) FROM tickets.tickets WHERE '  # noqa: S608
        + _BACKLOG
        + ' AND backlog_rank > %s',
        lo,
    )
    if hi is None:
        return float(lo) + 1.0
    if hi - lo >= _MIN_RANK_GAP:
        return float(lo + hi) / 2
    # ponytail: renumbers every ranked ticket of the org; fine for
    # backlogs of thousands, use a text rank (LexoRank) past that.
    # The moved task is renumbered too, so its stored rank shows its
    # old position in the new numbers.
    await conn.execute(
        'UPDATE tickets.tickets AS t SET backlog_rank = s.n'
        ' FROM (SELECT id, row_number() OVER (ORDER BY backlog_rank,'
        ' created_at DESC, id DESC) AS n FROM tickets.tickets'
        ' WHERE organization_id = %s AND status = ANY(%s)'
        ' AND backlog_rank IS NOT NULL) AS s'
        ' WHERE t.id = s.id',
        backlog[:2],
    )
    return await _rank_after(conn, organization_id, task_id, after)


def _escape_like(value: str) -> str:
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
