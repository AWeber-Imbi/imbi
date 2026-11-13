"""Script: run Python in the pydantic-monty sandbox (ADR 0027).

The engine runs the code with :mod:`imbi.common.workflows.script_runner`.
This module declares the step only, so it does not import the sandbox.

Each name of ``inputs`` becomes a global of the script. The value of the
last expression is the result, with the fields of ``output_fields``.
With ``branches``, the result also holds :data:`BRANCH_FIELD`, the name
of the branch that the step takes.
"""

import keyword
import re
import typing

import pydantic

from imbi.common.workflows import graph, step_type
from imbi.common.workflows.registry import agent

MAX_INPUTS = 20
#: The largest ``code``, in bytes of UTF-8.
MAX_CODE_BYTES = 16 * 1024
#: The field of the result that names the branch to take. A script
#: cannot declare an output field with this name.
BRANCH_FIELD = 'branch'


class Params(pydantic.BaseModel):
    inputs: dict[str, typing.Any] = pydantic.Field(
        default_factory=dict[str, typing.Any],
        description='Globals of the script. A value can be a reference, '
        'such as {{ trigger.payload }}.',
    )
    code: str = pydantic.Field(
        min_length=1,
        description='Python. The value of the last expression is the '
        'result. Never rendered as a template.',
    )
    output_fields: list[agent.OutputField] = pydantic.Field(
        min_length=1,
        max_length=agent.MAX_FIELDS,
        description='The fields of the result. Later steps use each '
        'field as {{ <key>.result.<field> }}.',
    )
    branches: list[typing.Annotated[str, pydantic.Field(min_length=1)]] = (
        pydantic.Field(
            default_factory=list[str],
            description='One output port per branch. The result names '
            f'the branch to take in {BRANCH_FIELD!r}.',
        )
    )

    @pydantic.field_validator('inputs')
    @classmethod
    def _check_inputs(
        cls, value: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        if len(value) > MAX_INPUTS:
            raise ValueError(f'at most {MAX_INPUTS} inputs')
        for name in value:
            if not re.match(graph.KEY_PATTERN, name):
                raise ValueError(f'{name!r} is not a valid input name')
            if keyword.iskeyword(name):
                raise ValueError(f'{name!r} is a Python keyword')
        return value

    @pydantic.field_validator('code')
    @classmethod
    def _check_code(cls, value: str) -> str:
        if len(value.encode()) > MAX_CODE_BYTES:
            raise ValueError(f'code is larger than {MAX_CODE_BYTES} bytes')
        return value

    @pydantic.field_validator('output_fields')
    @classmethod
    def _check_output_fields(
        cls, fields: list[agent.OutputField]
    ) -> list[agent.OutputField]:
        if any(f.name == BRANCH_FIELD for f in fields):
            raise ValueError(f'{BRANCH_FIELD!r} is a reserved name')
        return agent.check_output_fields(fields)

    @pydantic.field_validator('branches')
    @classmethod
    def _unique_branches(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError('branch names must be unique')
        return value


class Output(pydantic.BaseModel):
    #: The value of the script, with every field of ``output_fields``.
    result: dict[str, typing.Any]
    #: The branch that the script picked, when the step has branches.
    branch: str | None = None
    #: The text that the script printed, cut short.
    stdout: str | None = None


STEP = step_type.StepType(
    type='script',
    category='logic',
    label='Script',
    description='Runs Python in a sandbox and returns a structured result.',
    params=Params,
    output=Output,
    sample_output={'result': {}, 'branch': None, 'stdout': None},
    ports=None,
    timeout_seconds=30,
    raw_params=frozenset({'code'}),
    structured_output=True,
)
