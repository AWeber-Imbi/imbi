"""LLM Call: send a saved prompt to its AI model and return the answer.

The prompt is in the Prompt CMS, at
``workflows/<org slug>.<workflow slug>.<node key>``. The step pins one
version of it. The engine renders ``inputs`` only: the values become
the variables of the prompt, which imbi-api renders with Jinja2 and
sends to the model of the version (``POST .../prompts/run``).

With ``output_fields``, the model must return a structured answer, and
later steps reference each value as ``{{ <key>.result.<field> }}``.
Without them, the answer is ``{{ <key>.text }}``.
"""

import re
import typing

import pydantic

from imbi.common.workflows import graph, step_type
from imbi.common.workflows.registry import agent, script

MAX_INPUTS = script.MAX_INPUTS
#: The namespace of the prompts of LLM Call steps.
NAMESPACE = 'workflows'
#: Names that Jinja2 reads as a constant (``true``, ``false``, ``none``),
#: as the ``not`` operator, or as the template itself (``self``). Jinja2
#: does not publish this list. Other keywords, such as ``in`` and ``if``,
#: work as variable names.
RESERVED_NAMES = frozenset({'false', 'none', 'not', 'self', 'true'})


class Params(pydantic.BaseModel):
    prompt_ref: str = pydantic.Field(
        pattern=rf'^{NAMESPACE}/[a-z0-9][a-z0-9._-]*$',
        description=f'{NAMESPACE}/<org>.<workflow>.<node key>, with no '
        'version: prompt_version pins it.',
    )
    prompt_version: int = pydantic.Field(
        gt=0, description='The version of the prompt that the step runs.'
    )
    inputs: dict[str, typing.Any] = pydantic.Field(
        default={},
        description='The variables of the prompt. A value can be a '
        'reference, such as {{ trigger.payload }}.',
    )
    output_fields: list[agent.OutputField] = pydantic.Field(
        default=[],
        max_length=agent.MAX_FIELDS,
        description='The structured answer of the model. Later steps use '
        'each field as {{ <key>.result.<field> }}. The model must '
        'support structured output.',
    )

    @pydantic.field_validator('inputs')
    @classmethod
    def _check_inputs(
        cls, value: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        if len(value) > MAX_INPUTS:
            raise ValueError(f'at most {MAX_INPUTS} inputs')
        for name in value:
            if not re.fullmatch(graph.KEY_PATTERN, name):
                raise ValueError(f'{name!r} is not a valid input name')
            if name in RESERVED_NAMES:
                raise ValueError(f'{name!r} is reserved in Jinja2')
        return value

    @pydantic.field_validator('output_fields')
    @classmethod
    def _check_output_fields(
        cls, fields: list[agent.OutputField]
    ) -> list[agent.OutputField]:
        return agent.check_output_fields(fields)


class Output(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(protected_namespaces=())

    #: The answer. With ``output_fields``, the JSON of ``result``.
    text: str
    #: The structured answer, with every field of ``output_fields``.
    result: dict[str, typing.Any] | None = None
    #: The catalog slug of the model.
    model: str
    #: The id of the model at the provider.
    model_id: str
    prompt_version: int
    content_sha256: str | None = None
    #: ``input_tokens`` and ``output_tokens``.
    usage: dict[str, typing.Any]
    cost_usd: float | None = None
    #: The ``ai_runtime.ai_model_calls`` row of the call.
    call_id: str | None = None


def required_permissions(_params: dict[str, typing.Any]) -> set[str]:
    # A run spends provider credit, as the run endpoint does.
    return {'prompt:run'}


STEP = step_type.StepType(
    type='llm_call',
    category='logic',
    label='LLM Call',
    description='Sends a prompt to an AI model and returns the answer.',
    params=Params,
    output=Output,
    sample_output={
        'text': 'Sample output of a test run.',
        'result': None,
        'model': 'sample-model',
        'model_id': 'sample-model',
        'prompt_version': 1,
        'content_sha256': None,
        'usage': {'input_tokens': None, 'output_tokens': None},
        'cost_usd': None,
        'call_id': None,
    },
    # One call of 120 seconds at most, and the waits while imbi-api
    # still runs the call of an attempt.
    timeout_seconds=300,
    retries=2,
    required_permissions=required_permissions,
    structured_output=True,
)
