"""Email: send a message to Imbi users and teams of the organization."""

import typing

import pydantic

from imbi.common.workflows import step_type


class Recipient(pydantic.BaseModel):
    kind: typing.Literal['user', 'team']
    id: str = pydantic.Field(min_length=1)


class Params(pydantic.BaseModel):
    to: list[Recipient] = pydantic.Field(min_length=1)
    subject: str = pydantic.Field(min_length=1)
    body: str = pydantic.Field(min_length=1)


class Output(pydantic.BaseModel):
    recipients: list[str]


STEP = step_type.StepType(
    type='email',
    category='action',
    label='Send email',
    description='Sends an email to users and teams in the organization.',
    params=Params,
    output=Output,
    sample_output={'recipients': ['person@example.com']},
    side_effect=True,
    timeout_seconds=120,
)
