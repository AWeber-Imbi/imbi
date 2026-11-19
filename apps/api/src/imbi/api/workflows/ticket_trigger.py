"""Start the ``ticket_state_changed`` triggers of a ticket that changes.

A ticket change hook (:func:`imbi.api.tickets.store.
register_change_hook`). The transaction that creates a ticket or changes
its status writes a ``trigger_outbox`` row for the change, when the org
has a binding (:func:`has_bindings`, the outbox filter). The hook reads
the rows of the ticket, and for each one reads the enabled bindings of
the active workflows of the ticket's org and starts a run for each
trigger whose params match. The ticket id and the trigger node id with
the outbox row id are the idempotency key, so a repeat starts no second
run.

The trigger deletes a row when no run failed to start; else the
workflow sweep calls the trigger again
(:func:`imbi.api.workflows.sweeper.retry_task_triggers`).

A run that a ticket change starts can give an agent a ticket, which
changes (or delegates a child ticket that changes) and starts a run
again. :data:`MAX_DEPTH` stops such a chain: the run origin records its
depth, an agent step copies the run origin into its ticket, and the
depth is read from the root ticket of the changed ticket's chain, which
every delegated child shares.

Each ticket changes state many times, so each level can start several
runs, and the depth alone does not bound the work. The run origin also
records the lineage: the id of the first ticket, which no run started.
:data:`MAX_LINEAGE_RUNS` caps the runs of one lineage.
"""

import logging
import typing
from collections import abc

from imbi.api.tickets import store as task_store
from imbi.api.workflows import runs as runs_module
from imbi.api.workflows import store, tickets
from imbi.common import graph as graph_db
from imbi.common.workflows import graph, validation
from imbi.common.workflows.registry import ticket_state_changed

LOGGER = logging.getLogger(__name__)

KIND = ticket_state_changed.TYPE

#: The most runs in one chain of ticket -> run -> ticket -> run.
MAX_DEPTH = 5

#: The most runs that the tickets of one lineage start, at all depths.
#: A hook call checks it before it starts runs, so one call can go past
#: it by the runs of that call.
MAX_LINEAGE_RUNS = 25


async def has_bindings(conn: task_store.Conn, organization_id: str) -> bool:
    """Return whether the org has an enabled ``ticket_state_changed``
    binding of an active workflow: the outbox filter of the ticket store
    (:func:`imbi.api.tickets.store.register_outbox_filter`). It runs in
    the transaction of each ticket change, so it reads one partial
    index (``trigger_bindings_ticket_state_changed_idx``)."""
    cursor = await conn.execute(
        'SELECT EXISTS (SELECT 1 FROM workflows.trigger_bindings AS b'
        ' JOIN workflows.workflows AS w ON w.id = b.workflow_id'
        # A literal type, so the planner uses the partial index.
        " WHERE b.type = 'ticket_state_changed' AND b.organization_id = %s"
        " AND b.enabled AND NOT b.removed AND w.status = 'active')",
        (organization_id,),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


def _matches(binding: store.Row, task: store.Row, change: store.Row) -> bool:
    """Return whether a change of ``task`` starts a run of ``binding``.

    ``states`` names the new state; ``created`` also names a creation.
    ``outcomes`` applies only to a close. A workflow activated after
    the change does not match, so the sweep that calls the trigger
    again starts no run that the change hook could not have started.
    """
    params: dict[str, typing.Any] = binding['params']
    agent_id = params.get('agent_id')
    states: list[str] = params.get('states') or []
    outcomes: list[str] = params.get('outcomes') or []
    to_state = change['to_state']
    return (
        binding['activated_at'] <= change['created_at']
        and (not agent_id or agent_id == task['agent_id'])
        and (
            not states
            or to_state in states
            or (change['from_state'] is None and 'created' in states)
        )
        and (
            to_state != 'closed' or not outcomes or task['outcome'] in outcomes
        )
    )


def _lineage(root: store.Row) -> str:
    """Return the lineage of the runs that a ticket of the chain of
    ``root`` starts."""
    if root['origin_kind'] == KIND:
        origin: dict[str, typing.Any] = root['origin'] or {}
        return str(origin.get('lineage') or root['id'])
    return str(root['id'])


def _depth(root: store.Row | None) -> int:
    """Return the depth of a run that a ticket of the chain of ``root``
    starts. A missing root counts as the deepest chain."""
    if root is None:
        return MAX_DEPTH + 1
    if root['origin_kind'] != KIND:
        return 1
    origin: dict[str, typing.Any] = root['origin'] or {}
    return int(origin.get('depth', 0)) + 1


class TaskTrigger:
    def __init__(
        self,
        definitions: store.WorkflowStore,
        runs: runs_module.RunStore,
        tasks: task_store.TicketStore,
        db: abc.Callable[[], graph_db.Graph | None],
    ) -> None:
        """``db`` returns the graph, for the slugs of the ticket's org
        and agent (:func:`tickets.attributes`)."""
        self._definitions = definitions
        self._runs = runs
        self._tasks = tasks
        self._db = db

    async def __call__(self, task: store.Row, outbox: bool = True) -> None:
        """Start the runs of each pending change of ``task``. Without an
        ``outbox`` row from the change, there is nothing to start."""
        if not outbox:
            return
        changes = await self._tasks.state_changes(task['id'])
        if not changes:
            return
        root = await self._tasks.chain_root(task)
        depth = _depth(root)
        lineage = '' if root is None else _lineage(root)
        if (
            depth > MAX_DEPTH
            or await self._runs.lineage_runs(task['organization_id'], lineage)
            >= MAX_LINEAGE_RUNS
        ):
            LOGGER.warning(
                'Ticket %s starts no workflow runs: its chain is past %d'
                ' deep or its lineage %s started %d runs',
                task['id'],
                MAX_DEPTH,
                lineage,
                MAX_LINEAGE_RUNS,
            )
            await self._tasks.triggers_started([c['id'] for c in changes])
            return
        bindings = await self._definitions.active_bindings(
            task['organization_id'], [KIND]
        )
        await self._tasks.triggers_started(
            [
                change['id']
                for change in changes
                if await self._start(task, change, bindings, depth, lineage)
            ]
        )

    async def _start(
        self,
        task: store.Row,
        change: store.Row,
        bindings: list[store.Row],
        depth: int,
        lineage: str,
    ) -> bool:
        """Start a run for each binding that ``change`` matches. Return
        ``False`` when a run failed to start."""
        org = task['organization_id']
        failed = False
        # Built for the first match only: most changes start no run.
        payload: dict[str, typing.Any] | None = None
        for binding in bindings:
            if not _matches(binding, task, change):
                continue
            if payload is None:
                closed = change['to_state'] == 'closed'
                payload = {
                    'task_id': task['short_id'],
                    'agent_id': task['agent_id'],
                    'outcome': task['outcome'] if closed else None,
                    'from_state': change['from_state'],
                    'to_state': change['to_state'],
                    **await tickets.attributes(self._db(), task),
                }
            workflow_id = binding['workflow_id']
            try:
                settings = graph.Settings.model_validate(binding['settings'])
                await self._runs.create(
                    runs_module.NewRun(
                        organization_id=org,
                        workflow_id=workflow_id,
                        version=binding['active_version'],
                        trigger_node_id=binding['node_id'],
                        origin_kind=KIND,
                        origin_id=str(task['id']),
                        origin={
                            'kind': KIND,
                            'task_id': task['short_id'],
                            'depth': depth,
                            'lineage': lineage,
                        },
                        # One run per binding and change.
                        idempotency_key=f'{binding["node_id"]}:{change["id"]}',
                        payload=payload,
                        concurrency_key=validation.concurrency_key(
                            settings, str(workflow_id), payload
                        ),
                        activated_by=binding['activated_by'],
                        dedupe_key=validation.dedupe_key(settings, payload),
                        dedupe_window_seconds=settings.dedupe_window_seconds,
                        skip_duplicate=True,
                    )
                )
            except Exception as error:  # one workflow must not stop the rest
                # A workflow that is no longer active has no run to start.
                failed = failed or not isinstance(error, runs_module.NotActive)
                LOGGER.exception(
                    'Ticket %s did not start workflow %s',
                    task['id'],
                    workflow_id,
                )
        return not failed
