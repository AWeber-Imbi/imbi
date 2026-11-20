"""Wait: hold the run for a duration."""

import pydantic

from imbi.common.workflows import graph, step_type

DURATION = r'([1-9][0-9]*)([smhd])'


class Params(pydantic.BaseModel):
    duration: str = pydantic.Field(
        pattern=rf'^(?:{DURATION}|{graph.REFERENCE})$',
        description=(
            'A number and a unit: s, m, h, or d. Example: 10m. Or one '
            'reference that renders to one, such as '
            '{{ calc.result.duration }}.'
        ),
    )


class Output(pydantic.BaseModel):
    waited_seconds: int


STEP = step_type.StepType(
    type='wait',
    category='logic',
    label='Wait',
    description='Holds the run for a duration.',
    params=Params,
    output=Output,
    sample_output={'waited_seconds': 600},
    timeout_seconds=None,
)
