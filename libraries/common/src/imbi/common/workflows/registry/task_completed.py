"""Task completed trigger: an agent task that closes starts a run.

imbi-api starts the run when the task closes, from its close hook
(:mod:`imbi.api.workflows.task_trigger`).
"""

import typing

import pydantic

from imbi.common.workflows import step_type
from imbi.common.workflows.registry import agent


class Params(pydantic.BaseModel):
    agent_id: str | None = pydantic.Field(
        default=None,
        description='Start a run only for tasks of this agent. Empty '
        'means any agent.',
    )
    outcomes: list[agent.Outcome] = pydantic.Field(
        default=[],
        description='Start a run only for tasks that close with one of '
        'these outcomes. Empty means any outcome.',
    )


class Output(pydantic.BaseModel):
    #: The short id of the task, such as ``T-12``.
    task_id: str
    agent_id: str
    outcome: agent.Outcome


def required_permissions(_params: dict[str, typing.Any]) -> set[str]:
    """The run payload tells which tasks closed and how. The activator
    must be able to read agent tasks.
    """
    return {'agent_task:read'}


STEP = step_type.StepType(
    type='task_completed',
    category='trigger',
    label='Task completed',
    description='An agent task that closes starts a run.',
    params=Params,
    output=Output,
    sample_output={
        'task_id': 'T-1',
        'agent_id': 'agent-1',
        'outcome': 'done_acted',
    },
    trigger=True,
    required_permissions=required_permissions,
)
