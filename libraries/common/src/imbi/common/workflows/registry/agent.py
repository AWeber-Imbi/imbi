"""Agent: give an agent a task and wait for its outcome.

The task is an ADR 0020 agent task with the root origin of the run
(ADR 0021, Agent tasks from workflows). The step takes ``Succeeded``
when the outcome is in :data:`SUCCEEDED`, else ``Failed``.

A step with ``output_fields`` asks the agent for structured output.
The fields become a JSON Schema in the subset that structured output
supports: every object has ``additionalProperties: false``, and nesting
stops at one object level. Later steps reference the values as
``{{ <key>.result.<field> }}``; :func:`complete_result` sets each
optional field that the agent left out to ``None``, so a reference
never names a missing value.
"""

import decimal
import typing
from collections import abc

import pydantic

from imbi.common.workflows import graph, step_type

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

ScalarType = typing.Literal['string', 'integer', 'number', 'boolean']
FieldType = ScalarType | typing.Literal['array', 'object']
StringFormat = typing.Literal[
    'date-time',
    'time',
    'date',
    'duration',
    'email',
    'hostname',
    'uri',
    'ipv4',
    'ipv6',
    'uuid',
]

MAX_FIELDS = 50
#: The most optional fields of one schema that structured output takes.
MAX_OPTIONAL_FIELDS = 24


def _unique_names(fields: list[typing.Any]) -> None:
    names = [f.name for f in fields]
    if len(names) != len(set(names)):
        raise ValueError('field names must be unique')


class _Field(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='forbid')

    name: str = pydantic.Field(pattern=graph.KEY_PATTERN, max_length=64)
    description: str = pydantic.Field(default='', max_length=500)
    #: An optional field can be left out. Each one makes the grammar
    #: of the schema larger, so there is a limit.
    required: bool = True
    #: The allowed values of a string, or of each string of an array.
    enum: list[str] | None = pydantic.Field(
        default=None, min_length=1, max_length=50
    )
    format: StringFormat | None = None

    def _check_string_options(self, value_type: str | None) -> None:
        if (self.enum or self.format) and value_type != 'string':
            raise ValueError('enum and format apply to strings only')
        if self.enum and self.format:
            raise ValueError('a field has an enum or a format, not both')


class ObjectField(_Field):
    """A field of an object: a scalar, so nesting stops here."""

    type: ScalarType

    @pydantic.model_validator(mode='after')
    def _check(self) -> typing.Self:
        self._check_string_options(self.type)
        return self


class OutputField(_Field):
    type: FieldType
    #: The type of each value of an ``array``.
    items: ScalarType | typing.Literal['object'] | None = None
    #: The fields of an ``object``, or of each object of an ``array``.
    fields: list[ObjectField] | None = pydantic.Field(
        default=None, min_length=1, max_length=MAX_FIELDS
    )

    @pydantic.model_validator(mode='after')
    def _check(self) -> typing.Self:
        if self.type == 'array' and self.items is None:
            raise ValueError('an array needs items')
        if self.type != 'array' and self.items is not None:
            raise ValueError('only an array has items')
        has_objects = self.type == 'object' or self.items == 'object'
        if has_objects != (self.fields is not None):
            raise ValueError(
                'only an object, or an array of objects, has fields'
            )
        if self.fields:
            _unique_names(self.fields)
        self._check_string_options(
            self.items if self.type == 'array' else self.type
        )
        return self


def _scalar_schema(
    value_type: str, enum: list[str] | None, string_format: str | None
) -> dict[str, typing.Any]:
    schema: dict[str, typing.Any] = {'type': value_type}
    if enum:
        schema['enum'] = enum
    if string_format:
        schema['format'] = string_format
    return schema


def _field_schema(field: OutputField | ObjectField) -> dict[str, typing.Any]:
    if isinstance(field, ObjectField):
        schema = _scalar_schema(field.type, field.enum, field.format)
    elif field.type == 'object':
        schema = _object_schema(field.fields or [])
    elif field.type == 'array':
        schema = {
            'type': 'array',
            'items': _object_schema(field.fields or [])
            if field.items == 'object'
            else _scalar_schema(str(field.items), field.enum, field.format),
        }
    else:
        schema = _scalar_schema(field.type, field.enum, field.format)
    if field.description:
        schema['description'] = field.description
    return schema


def _object_schema(
    fields: abc.Sequence[OutputField | ObjectField],
) -> dict[str, typing.Any]:
    return {
        'type': 'object',
        'properties': {f.name: _field_schema(f) for f in fields},
        'required': [f.name for f in fields if f.required],
        'additionalProperties': False,
    }


def output_schema(fields: list[OutputField]) -> dict[str, typing.Any] | None:
    """Return the JSON Schema of the structured output, if any."""
    return _object_schema(fields) if fields else None


def _matching_enum(value: typing.Any, enum: list[str] | None) -> typing.Any:
    """Return the enum value that ``value`` matches in any case.

    Structured output does not keep the case of enum values.
    """
    if not enum or not isinstance(value, str):
        return value
    return next((e for e in enum if e.casefold() == value.casefold()), value)


def _complete_value(
    field: OutputField | ObjectField, value: typing.Any
) -> typing.Any:
    if isinstance(field, ObjectField):
        return _matching_enum(value, field.enum)
    if field.type == 'object' and isinstance(value, dict):
        return complete_result(field.fields or [], value)
    if field.type != 'array' or not isinstance(value, list):
        return _matching_enum(value, field.enum)
    items = typing.cast('list[typing.Any]', value)  # type: ignore[redundant-cast]
    if field.items == 'object':
        return [
            complete_result(field.fields or [], item)
            if isinstance(item, dict)
            else item
            for item in items
        ]
    return [_matching_enum(item, field.enum) for item in items]


def complete_result(
    fields: abc.Sequence[OutputField | ObjectField],
    result: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Return ``result`` with ``None`` for each field that it lacks.

    Each enum value takes the case of the schema.
    """
    return {f.name: _complete_value(f, result.get(f.name)) for f in fields}


def blank_result(
    fields: abc.Sequence[OutputField | ObjectField],
) -> dict[str, typing.Any]:
    """Return empty text for each field, as a skipped step renders."""
    return {
        f.name: blank_result(f.fields)
        if isinstance(f, OutputField) and f.type == 'object' and f.fields
        else ''
        for f in fields
    }


def unknown_field(
    fields: abc.Sequence[OutputField | ObjectField], path: list[str]
) -> str | None:
    """Return the first name in ``path`` that is not a field, if any.

    The check stops at a value that is not an object: a name after it
    can be a method of the value, such as ``upper`` of a string.
    """
    if not path:
        return None
    field = next((f for f in fields if f.name == path[0]), None)
    if field is None:
        return path[0]
    if isinstance(field, OutputField) and field.type == 'object':
        return unknown_field(field.fields or [], path[1:])
    return None


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
    output_fields: list[OutputField] = pydantic.Field(
        default_factory=list[OutputField],
        max_length=MAX_FIELDS,
        description='The structured output that the agent must return. '
        'Later steps use each field as {{ <key>.result.<field> }}.',
    )

    @pydantic.field_validator('output_fields')
    @classmethod
    def _check_output_fields(
        cls, fields: list[OutputField]
    ) -> list[OutputField]:
        _unique_names(fields)
        nested = [n for f in fields for n in f.fields or []]
        optional = sum(not f.required for f in [*fields, *nested])
        if optional > MAX_OPTIONAL_FIELDS:
            raise ValueError(
                f'at most {MAX_OPTIONAL_FIELDS} fields can be optional'
            )
        return fields


class Output(pydantic.BaseModel):
    task_id: str
    outcome: str
    reason: str | None = None
    #: The last message of the agent.
    summary: str | None = None
    #: The structured output, with the ``output_fields`` of the step.
    #: ``None`` when the step has none, or the task did not succeed.
    result: dict[str, typing.Any] | None = None


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
        'result': None,
    },
    ports=('Succeeded', 'Failed'),
    side_effect=True,
    # An agent can work for hours or wait for a person. The max run
    # time of the workflow limits it.
    timeout_seconds=None,
    retries=2,
    required_permissions=required_permissions,
)
