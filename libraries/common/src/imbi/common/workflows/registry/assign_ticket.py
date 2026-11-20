"""Assign ticket: hand a ticket to the person in one of its roles."""

import typing

import pydantic

from imbi.common.workflows import step_type
from imbi.common.workflows.registry import slack


class Params(pydantic.BaseModel):
    ticket: str = pydantic.Field(
        pattern=slack.TICKET,
        description='The ticket: a short id, for example T-12, or a '
        'reference such as {{ trigger.task_id }}.',
    )
    role: str = pydantic.Field(
        min_length=1,
        max_length=50,
        description='The role on the ticket, for example reviewer. The '
        'ticket goes to the person in it.',
    )


class Output(pydantic.BaseModel):
    task_id: str
    role: str
    #: The email of the person in the role. ``None`` when nobody is in
    #: it; the step then takes its second port.
    assignee: str | None


def required_permissions(_params: dict[str, typing.Any]) -> set[str]:
    """The step changes the assignee of a ticket of the org."""
    return {'ticket:manage'}


STEP = step_type.StepType(
    type='assign_ticket',
    category='action',
    label='Assign ticket to role',
    description='Hands a ticket to the person in one of its roles.',
    params=Params,
    output=Output,
    sample_output={
        'task_id': 'T-1',
        'role': 'reviewer',
        'assignee': 'person@example.com',
    },
    ports=('Assigned', 'No one in role'),
    timeout_seconds=60,
    required_permissions=required_permissions,
)
