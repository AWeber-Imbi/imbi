"""Start the ``ticket_closed`` triggers of a ticket that closes.

``task_completed`` is the earlier name of the trigger (ADR 0028). Both
start runs. A run and a ticket that this trigger starts still record
the old name as their origin kind until release B (R4), and both names
are read. The unique key of a run includes its origin kind. If this
release wrote the new name, a sweep of the previous release that
retries the same outbox row with the old name would start a second
run.

A ticket close hook (:func:`imbi.api.tickets.store.
register_close_hook`). It reads the enabled bindings of the active
workflows of the task's org, and starts a run for each trigger whose
agent and outcomes match. The task id and the trigger node id are the
idempotency key, so a repeat starts no second run.

The transaction that closes a task writes a ``trigger_outbox`` row.
The trigger deletes the row when no run failed to start; else the
workflow sweep calls the trigger again
(:func:`imbi.api.workflows.sweeper.retry_task_triggers`).

A run that a closed task starts can give an agent a task, which can
close (or delegate a child task that closes) and start a run again.
:data:`MAX_DEPTH` stops such a chain: the run origin records its depth,
an agent step copies the run origin into its task, and the depth is
read from the root task of the closed task's chain, which every
delegated child shares.
"""

import logging
import typing
from collections import abc

from imbi.api.tickets import store as task_store
from imbi.api.workflows import runs as runs_module
from imbi.api.workflows import store, tickets
from imbi.common import graph as graph_db
from imbi.common.workflows import graph, validation
from imbi.common.workflows.registry import ticket_closed

LOGGER = logging.getLogger(__name__)

#: The origin kind that this trigger writes. It stays the old name until
#: release B; see the module docstring.
KIND = 'task_completed'

#: The most runs in one chain of task -> run -> task -> run.
MAX_DEPTH = 5


def _matches(binding: store.Row, task: store.Row) -> bool:
    """Return whether the closed task starts a run of ``binding``.

    A workflow activated after the task closed does not match, so the
    sweep that calls the trigger again starts no run that the close
    hook could not have started.
    """
    params: dict[str, typing.Any] = binding['params']
    agent_id = params.get('agent_id')
    outcomes: list[str] = params.get('outcomes') or []
    return (
        binding['activated_at'] <= task['closed_at']
        and (not agent_id or agent_id == task['agent_id'])
        and (not outcomes or task['outcome'] in outcomes)
    )


def _depth(root: store.Row | None) -> int:
    """Return the depth of a run that a task of the chain of ``root``
    starts. A missing root counts as the deepest chain."""
    if root is None:
        return MAX_DEPTH + 1
    if root['origin_kind'] not in ticket_closed.TYPES:
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
        """``db`` returns the graph, for the slugs of the task's org and
        agent (:func:`tickets.attributes`)."""
        self._definitions = definitions
        self._runs = runs
        self._tasks = tasks
        self._db = db

    async def __call__(self, task: store.Row) -> None:
        """Start a run for each trigger that the closed task matches."""
        depth = _depth(await self._tasks.chain_root(task))
        if depth > MAX_DEPTH:
            LOGGER.warning(
                'Task %s starts no workflow runs: the chain is %d deep',
                task['id'],
                MAX_DEPTH,
            )
            await self._tasks.triggers_started(task['id'])
            return
        org = task['organization_id']
        failed = False
        # Built for the first match only: most closed tasks start no run.
        payload: dict[str, typing.Any] | None = None
        bindings = await self._definitions.active_bindings(
            org, ticket_closed.TYPES
        )
        for binding in bindings:
            if not _matches(binding, task):
                continue
            if payload is None:
                payload = {
                    'task_id': task['short_id'],
                    'agent_id': task['agent_id'],
                    'outcome': task['outcome'],
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
                        },
                        idempotency_key=binding['node_id'],
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
                    'Task %s did not start workflow %s',
                    task['id'],
                    workflow_id,
                )
        if not failed:
            await self._tasks.triggers_started(task['id'])
