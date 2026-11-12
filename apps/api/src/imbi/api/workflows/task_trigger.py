"""Start the ``task_completed`` triggers of a task that closes.

An agent task close hook (:func:`imbi.api.agent_tasks.store.
register_close_hook`). It reads the enabled bindings of the active
workflows of the task's org, and starts a run for each trigger whose
agent and outcomes match. The task id and the trigger node id are the
idempotency key, so a repeat starts no second run.

A run that a closed task starts can give an agent a task, which can
close (or delegate a child task that closes) and start a run again.
:data:`MAX_DEPTH` stops such a chain: the run origin records its depth,
an agent step copies the run origin into its task, and the depth is
read from the root task of the closed task's chain, which every
delegated child shares.
"""

import logging
import typing

from imbi.api.agent_tasks import store as task_store
from imbi.api.workflows import runs as runs_module
from imbi.api.workflows import store
from imbi.common.workflows import graph, validation

LOGGER = logging.getLogger(__name__)

KIND = 'task_completed'

#: The most runs in one chain of task -> run -> task -> run.
MAX_DEPTH = 5


def _matches(params: dict[str, typing.Any], task: store.Row) -> bool:
    agent_id = params.get('agent_id')
    outcomes: list[str] = params.get('outcomes') or []
    return (not agent_id or agent_id == task['agent_id']) and (
        not outcomes or task['outcome'] in outcomes
    )


def _depth(root: store.Row | None) -> int:
    """Return the depth of a run that a task of the chain of ``root``
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
        tasks: task_store.TaskStore,
    ) -> None:
        self._definitions = definitions
        self._runs = runs
        self._tasks = tasks

    async def __call__(self, task: store.Row) -> None:
        """Start a run for each trigger that the closed task matches."""
        depth = _depth(await self._tasks.chain_root(task))
        if depth > MAX_DEPTH:
            LOGGER.warning(
                'Task %s starts no workflow runs: the chain is %d deep',
                task['id'],
                MAX_DEPTH,
            )
            return
        payload = {
            'task_id': task['short_id'],
            'agent_id': task['agent_id'],
            'outcome': task['outcome'],
        }
        org = task['organization_id']
        for binding in await self._definitions.active_bindings(org, KIND):
            if not _matches(binding['params'], task):
                continue
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
                    )
                )
            except Exception:  # one workflow must not stop the rest
                LOGGER.exception(
                    'Task %s did not start workflow %s',
                    task['id'],
                    workflow_id,
                )
