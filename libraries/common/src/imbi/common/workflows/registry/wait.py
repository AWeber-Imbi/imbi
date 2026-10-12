"""Wait: hold the run for a fixed duration."""

import pydantic

from imbi.common.workflows import step_type


class Params(pydantic.BaseModel):
    duration: str = pydantic.Field(
        pattern=r'^[1-9][0-9]*[smhd]$',
        description='A number and a unit: s, m, h, or d. Example: 10m.',
    )


class Output(pydantic.BaseModel):
    waited_seconds: int


STEP = step_type.StepType(
    type='wait',
    category='logic',
    label='Wait',
    description='Holds the run for a fixed duration.',
    params=Params,
    output=Output,
    sample_output={'waited_seconds': 600},
    timeout_seconds=None,
)
