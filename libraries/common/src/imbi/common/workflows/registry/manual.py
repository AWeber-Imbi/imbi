"""Manual trigger: a person starts a run with typed inputs."""

import typing

import pydantic

from imbi.common.workflows import graph, step_type


class ManualInput(pydantic.BaseModel):
    name: str = pydantic.Field(pattern=graph.KEY_PATTERN)
    #: ``text`` is a ``string`` that the run dialog asks for in a text area.
    type: typing.Literal['string', 'text', 'number', 'boolean'] = 'string'


class Params(pydantic.BaseModel):
    inputs: list[ManualInput] = []
    who: typing.Literal['owner_team', 'admins', 'anyone'] = 'owner_team'


class Output(pydantic.BaseModel):
    """The inputs of the run, by name."""

    model_config = pydantic.ConfigDict(extra='allow')


STEP = step_type.StepType(
    type='manual',
    category='trigger',
    label='Manual run',
    description='A person starts a run, with the inputs it declares.',
    params=Params,
    output=Output,
    sample_output={},
    trigger=True,
)
