"""Condition: compare values of earlier steps and take one of two ports.

A text template always renders to text, and a value that is one
reference renders to its type, so :func:`evaluate` coerces: numbers
compare as numbers, and text as text.
"""

import decimal
import typing
from collections import abc

import pydantic
import re2

from imbi.common.workflows import step_type

Operator = typing.Literal[
    'equals',
    'not_equals',
    'greater_than',
    'greater_or_equal',
    'less_than',
    'less_or_equal',
    'contains',
    'not_contains',
    'starts_with',
    'ends_with',
    'matches',
    'is_empty',
    'is_not_empty',
]
Side = typing.Literal['a', 'b']
Value = (
    str | int | float | bool | list[typing.Any] | dict[str, typing.Any] | None
)

UNARY = frozenset({'is_empty', 'is_not_empty'})

type _Fit = tuple[str, frozenset[str]]

_ANY: _Fit = (
    'any value',
    frozenset({'string', 'integer', 'number', 'boolean', 'array', 'object'}),
)
_SCALAR: _Fit = (
    'a single value',
    frozenset({'string', 'integer', 'number', 'boolean'}),
)
_NUMBER: _Fit = ('a number', frozenset({'integer', 'number'}))
_TEXT: _Fit = ('text', frozenset({'string'}))
_TEXT_OR_LIST: _Fit = ('text or a list', frozenset({'string', 'array'}))

FITS: dict[Operator, tuple[_Fit, _Fit]] = {
    'equals': (_SCALAR, _SCALAR),
    'not_equals': (_SCALAR, _SCALAR),
    'greater_than': (_NUMBER, _NUMBER),
    'greater_or_equal': (_NUMBER, _NUMBER),
    'less_than': (_NUMBER, _NUMBER),
    'less_or_equal': (_NUMBER, _NUMBER),
    'contains': (_TEXT_OR_LIST, _SCALAR),
    'not_contains': (_TEXT_OR_LIST, _SCALAR),
    'starts_with': (_TEXT, _SCALAR),
    'ends_with': (_TEXT, _SCALAR),
    'matches': (_TEXT, _SCALAR),
    'is_empty': (_ANY, _ANY),
    'is_not_empty': (_ANY, _ANY),
}


def mismatch(operator: Operator, side: Side, types: set[str]) -> str | None:
    """Return what ``side`` needs when a value of ``types`` cannot work.

    ``types`` are the JSON Schema types of the value. ``None`` when one
    of them fits, or when they are not known.
    """
    needs, fitting = FITS[operator][0 if side == 'a' else 1]
    return None if not types or types & fitting else needs


class EvaluationError(Exception):
    """A condition cannot be evaluated. ``code`` names the reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Condition(pydantic.BaseModel):
    a: Value = pydantic.Field(description='A value or a template.')
    operator: Operator
    b: Value = pydantic.Field(
        default=None,
        description='A value or a template. For matches, a regular '
        'expression.',
    )

    @pydantic.model_validator(mode='after')
    def _check_b(self) -> typing.Self:
        if 'b' not in self.model_fields_set and self.operator not in UNARY:
            raise ValueError(f'{self.operator} needs b')
        return self


class Params(pydantic.BaseModel):
    conditions: list[Condition] = pydantic.Field(min_length=1, max_length=10)
    match: typing.Literal['all', 'any'] = pydantic.Field(
        default='all',
        description='All: every condition must be true. '
        'Any: at least one must be true.',
    )
    ignore_case: bool = pydantic.Field(
        default=False,
        description='Treat uppercase and lowercase letters as the same '
        'when comparing text.',
    )


class ConditionResult(pydantic.BaseModel):
    a: Value
    operator: Operator
    b: Value
    result: bool


class Output(pydantic.BaseModel):
    result: bool
    conditions: list[ConditionResult]


def _number(value: typing.Any) -> decimal.Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        number = decimal.Decimal(str(value))
    except decimal.InvalidOperation:
        return None
    return number if number.is_finite() else None


def _text(value: typing.Any, ignore_case: bool) -> str:
    text = '' if value is None else str(value)
    return text.casefold() if ignore_case else text


def _require_text(value: typing.Any) -> str:
    if not isinstance(value, str):
        raise EvaluationError('not_text')
    return value


def _compare(a: typing.Any, b: typing.Any) -> int:
    first, second = _number(a), _number(b)
    if first is None or second is None:
        raise EvaluationError('not_a_number')
    return (first > second) - (first < second)


def _equals(a: typing.Any, b: typing.Any, ignore_case: bool) -> bool:
    first, second = _number(a), _number(b)
    if first is not None and second is not None:
        return first == second
    fold = ignore_case or isinstance(a, bool) or isinstance(b, bool)
    return _text(a, fold) == _text(b, fold)


def _contains(a: typing.Any, b: typing.Any, ignore_case: bool) -> bool:
    if isinstance(a, list):
        items = typing.cast('list[typing.Any]', a)  # type: ignore[redundant-cast]
        return any(_equals(item, b, ignore_case) for item in items)
    return _text(b, ignore_case) in _text(_require_text(a), ignore_case)


def _starts_with(a: typing.Any, b: typing.Any, ignore_case: bool) -> bool:
    text = _text(_require_text(a), ignore_case)
    return text.startswith(_text(b, ignore_case))


def _ends_with(a: typing.Any, b: typing.Any, ignore_case: bool) -> bool:
    text = _text(_require_text(a), ignore_case)
    return text.endswith(_text(b, ignore_case))


def _matches(a: typing.Any, b: typing.Any, ignore_case: bool) -> bool:
    text = _require_text(a)
    options = re2.Options()
    options.log_errors = False
    options.case_sensitive = not ignore_case
    try:
        pattern = re2.compile(_text(b, False), options)
    except re2.error as error:
        raise EvaluationError('invalid_pattern') from error
    return pattern.search(text) is not None


def _is_empty(a: typing.Any, _b: typing.Any, _ignore_case: bool) -> bool:
    return a is None or (isinstance(a, str | list | dict) and not a)


_TESTS: dict[Operator, abc.Callable[[typing.Any, typing.Any, bool], bool]] = {
    'equals': _equals,
    'not_equals': lambda a, b, ignore_case: not _equals(a, b, ignore_case),
    'greater_than': lambda a, b, _: _compare(a, b) > 0,
    'greater_or_equal': lambda a, b, _: _compare(a, b) >= 0,
    'less_than': lambda a, b, _: _compare(a, b) < 0,
    'less_or_equal': lambda a, b, _: _compare(a, b) <= 0,
    'contains': _contains,
    'not_contains': lambda a, b, ignore_case: not _contains(a, b, ignore_case),
    'starts_with': _starts_with,
    'ends_with': _ends_with,
    'matches': _matches,
    'is_empty': _is_empty,
    'is_not_empty': lambda a, b, _: not _is_empty(a, b, False),
}


def evaluate(params: Params) -> Output:
    """Return the result of every condition and of the step.

    Raises:
        EvaluationError: A condition cannot be evaluated:
            ``not_a_number``, ``not_text``, or ``invalid_pattern``.

    """
    results = [
        ConditionResult(
            a=row.a,
            operator=row.operator,
            b=row.b,
            result=_TESTS[row.operator](row.a, row.b, params.ignore_case),
        )
        for row in params.conditions
    ]
    held = [row.result for row in results]
    return Output(
        result=all(held) if params.match == 'all' else any(held),
        conditions=results,
    )


STEP = step_type.StepType(
    type='condition',
    category='logic',
    label='Condition',
    description='Compares values and takes the True or the False port.',
    params=Params,
    output=Output,
    sample_output={
        'result': True,
        'conditions': [
            {
                'a': 'production',
                'operator': 'equals',
                'b': 'production',
                'result': True,
            }
        ],
    },
    ports=('True', 'False'),
    timeout_seconds=10,
)
