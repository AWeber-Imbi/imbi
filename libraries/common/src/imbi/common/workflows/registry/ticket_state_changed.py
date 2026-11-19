"""Ticket state changed trigger: a ticket that is created or changes
state starts a run.

imbi-api starts the run after the change commits, from its change hook
(:mod:`imbi.api.workflows.ticket_trigger`).
"""

import typing

import pydantic

from imbi.common.workflows import step_type
from imbi.common.workflows.registry import agent

#: The step type, and the origin kind of the runs that it starts.
TYPE = 'ticket_state_changed'

#: The ticket statuses that imbi-api writes, and ``created``, which is
#: the creation of a ticket.
State = typing.Literal[
    'created', 'held', 'queued', 'running', 'paused', 'blocked', 'closed'
]


class Params(pydantic.BaseModel):
    agent_id: str | None = pydantic.Field(
        default=None,
        description='Start a run only for tickets of this agent. Empty '
        'means any agent.',
    )
    states: list[State] = pydantic.Field(
        default=[],
        description='Start a run only for a change to one of these '
        'states. "created" is the creation of a ticket. Empty means '
        'every change.',
    )
    outcomes: list[agent.Outcome] = pydantic.Field(
        default=[],
        description='Start a run for a close only when the ticket closes '
        'with one of these outcomes. Changes to other states ignore it. '
        'Empty means any outcome.',
    )


class Output(agent.TicketAttributes):
    #: The short id of the ticket, such as ``T-12``.
    task_id: str
    #: ``None`` on a ticket assigned to a person.
    agent_id: str | None
    #: ``None`` unless the new state is ``closed``.
    outcome: agent.Outcome | None
    #: The previous status. ``None`` when the ticket was created.
    from_state: str | None
    #: The new status. On creation, the first status of the ticket.
    to_state: str


def required_permissions(_params: dict[str, typing.Any]) -> set[str]:
    """The run payload tells which tickets changed and how. The
    activator must be able to read tickets.
    """
    return {'ticket:read'}


STEP = step_type.StepType(
    type=TYPE,
    category='trigger',
    label='Ticket state changed',
    description='A ticket that is created or changes state starts a run.',
    params=Params,
    output=Output,
    sample_output={
        'task_id': 'T-1',
        'agent_id': 'agent-1',
        'outcome': 'done_acted',
        'from_state': 'running',
        'to_state': 'closed',
        **agent.SAMPLE_ATTRIBUTES,
    },
    trigger=True,
    required_permissions=required_permissions,
)
