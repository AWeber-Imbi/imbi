"""Agent: give an agent a task and wait for its outcome.

The task is an ADR 0020 agent task with the root origin of the run
(ADR 0021, Agent tasks from workflows). The step takes ``Succeeded``
when the outcome is in :data:`SUCCEEDED`, else ``Failed``.
"""

import decimal
import typing

import pydantic

from imbi.common.workflows import step_type

#: The closed F5 set of terminal outcomes of an agent task (ADR 0020).
Outcome = typing.Literal[
    'done_acted',
    'done_nothing_to_act_on',
    'no_reason_to_run',
    'partial_capped',
    'suppressed_duplicate',
    'superseded',
    'cancelled_by_human',
    'interrupted_by_operator',
    'failed_at_gate',
    'failed_external',
    'unmapped_subject',
    'exceeded_ceiling',
    'unhandled_no_actor',
    'request_expired',
    'refused_rate_ceiling',
]

#: The outcomes that take the ``Succeeded`` port. Every other outcome
#: takes ``Failed``.
SUCCEEDED = frozenset(
    {'done_acted', 'done_nothing_to_act_on', 'no_reason_to_run'}
)

#: The one template that ``project_id`` can be: the project that the
#: gateway matched to the webhook delivery. imbi-api reads it from the
#: run's origin, which only the gateway sets, not from run input.
TRIGGER_PROJECT = '{{ trigger.project }}'


class Params(pydantic.BaseModel):
    agent_id: str = pydantic.Field(
        min_length=1, description='An agent of the organization.'
    )
    instruction: str = pydantic.Field(
        min_length=1, description='What the agent must do.'
    )
    project_id: str | None = pydantic.Field(
        default=None,
        description='The primary project of the task, or '
        f'``{TRIGGER_PROJECT}`` for the project that the webhook '
        'delivery matched.',
    )
    #: The same limits as the budget of an ADR 0020 task.
    budget: decimal.Decimal | None = pydantic.Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=6,
        description="USD. Defaults to the agent's task budget. It cannot "
        'be more than that budget.',
    )


class Output(pydantic.BaseModel):
    task_id: str
    outcome: str
    reason: str | None = None
    #: The last message of the agent.
    summary: str | None = None


def required_permissions(_params: dict[str, typing.Any]) -> set[str]:
    return {'agent_task:create'}


STEP = step_type.StepType(
    type='agent',
    category='agent',
    label='Agent task',
    description='Gives an agent a task and waits for its outcome.',
    params=Params,
    output=Output,
    sample_output={
        'task_id': 'T-1',
        'outcome': 'done_acted',
        'reason': None,
        'summary': 'Sample output of a test run.',
    },
    ports=('Succeeded', 'Failed'),
    side_effect=True,
    # An agent can work for hours or wait for a person. The max run
    # time of the workflow limits it.
    timeout_seconds=None,
    retries=2,
    required_permissions=required_permissions,
)
