"""Webhook trigger: a gateway Webhook delivery starts a run."""

import typing

import pydantic

from imbi.common.workflows import step_type


class Params(pydantic.BaseModel):
    webhook_id: str = pydantic.Field(
        min_length=1, description='The id of an existing gateway Webhook.'
    )
    filter: str | None = pydantic.Field(
        default=None,
        description='A CEL expression. A delivery starts a run only when '
        'it is true.',
    )


class Output(pydantic.BaseModel):
    payload: dict[str, typing.Any]


STEP = step_type.StepType(
    type='webhook',
    category='trigger',
    label='Webhook',
    description='A delivery to a gateway Webhook starts a run.',
    params=Params,
    output=Output,
    sample_output={'payload': {}},
    trigger=True,
)
