"""Tests for the condition step type."""

import typing
import unittest

import pydantic

from imbi.common.workflows import graph, validation
from imbi.common.workflows.registry import condition


def _evaluate(
    rows: list[tuple[typing.Any, str, typing.Any]],
    match: str = 'all',
    ignore_case: bool = False,
) -> condition.Output:
    return condition.evaluate(
        condition.Params.model_validate(
            {
                'conditions': [
                    {'a': a, 'operator': operator, 'b': b}
                    for a, operator, b in rows
                ],
                'match': match,
                'ignore_case': ignore_case,
            }
        )
    )


def _holds(a: typing.Any, operator: str, b: typing.Any = None) -> bool:
    return _evaluate([(a, operator, b)]).result


def _error(a: typing.Any, operator: str, b: typing.Any = None) -> str | None:
    try:
        _evaluate([(a, operator, b)])
    except condition.EvaluationError as error:
        return error.code
    return None


class ParamsTestCase(unittest.TestCase):
    def test_b_is_needed_except_for_empty_checks(self) -> None:
        for operator in ('is_empty', 'is_not_empty'):
            condition.Params.model_validate(
                {'conditions': [{'a': 'x', 'operator': operator}]}
            )
        with self.assertRaises(pydantic.ValidationError):
            condition.Params.model_validate(
                {'conditions': [{'a': 'x', 'operator': 'equals'}]}
            )

    def test_b_can_render_to_none(self) -> None:
        condition.Params.model_validate(
            {'conditions': [{'a': 'x', 'operator': 'equals', 'b': None}]}
        )

    def test_row_limits(self) -> None:
        row = {'a': 'x', 'operator': 'equals', 'b': 'x'}
        for rows in ([], [row] * 11):
            with self.assertRaises(pydantic.ValidationError):
                condition.Params.model_validate({'conditions': rows})

    def test_rendered_values_keep_their_type(self) -> None:
        for value in ('5', 5, 5.5, True, ['a'], {'k': 'v'}, None):
            params = condition.Params.model_validate(
                {'conditions': [{'a': value, 'operator': 'is_empty'}]}
            )
            self.assertEqual(params.conditions[0].a, value)
            self.assertIs(type(params.conditions[0].a), type(value))


class EvaluateTestCase(unittest.TestCase):
    def test_equals(self) -> None:
        for a, b, expected in (
            ('5', 5.0, True),
            (5, '5.00', True),
            ('0.1', 0.1, True),
            ('abc', 'abc', True),
            ('abc', 'ABC', False),
            (True, 'TRUE', True),
            ('false', False, True),
            (True, 1, False),
            (True, 'yes', False),
            (None, '', True),
            ('nan', 'nan', True),
        ):
            with self.subTest(a=a, b=b):
                self.assertIs(_holds(a, 'equals', b), expected)
                self.assertIs(_holds(a, 'not_equals', b), not expected)

    def test_ignore_case(self) -> None:
        for operator, a, b in (
            ('equals', 'Prod', 'PROD'),
            ('contains', 'Production', 'DUCT'),
            ('contains', ['Prod'], 'prod'),
            ('starts_with', 'Production', 'prod'),
            ('ends_with', 'Production', 'TION'),
            ('matches', 'Production', '^prod'),
        ):
            with self.subTest(operator):
                self.assertFalse(_holds(a, operator, b))
                self.assertTrue(
                    _evaluate([(a, operator, b)], ignore_case=True).result
                )

    def test_numbers(self) -> None:
        for a, operator, b, expected in (
            (10, 'greater_than', '9', True),
            ('10', 'greater_than', '9', True),
            ('1e3', 'greater_or_equal', 1000, True),
            (2.5, 'less_than', 3, True),
            (3, 'less_or_equal', '3.0', True),
            (3, 'less_than', 3, False),
        ):
            with self.subTest(a=a, operator=operator, b=b):
                self.assertIs(_holds(a, operator, b), expected)

    def test_not_a_number(self) -> None:
        for a, b in (
            ('ten', 9),
            (True, 0),
            ('nan', 1),
            ('inf', 1),
            (None, 1),
            ([1], 1),
        ):
            with self.subTest(a=a, b=b):
                self.assertEqual(_error(a, 'greater_than', b), 'not_a_number')

    def test_contains(self) -> None:
        self.assertTrue(_holds('production', 'contains', 'duct'))
        self.assertTrue(_holds(['a', 5], 'contains', '5'))
        self.assertTrue(_holds([True], 'contains', 'true'))
        self.assertFalse(_holds(['a'], 'contains', 'b'))
        self.assertTrue(_holds(['a'], 'not_contains', 'b'))
        self.assertTrue(_holds('5 apples', 'contains', 5))
        for a in (5, None, {'a': 1}):
            with self.subTest(a=a):
                self.assertEqual(_error(a, 'contains', 'x'), 'not_text')

    def test_text_operators(self) -> None:
        self.assertTrue(_holds('release-1.2', 'starts_with', 'release-'))
        self.assertTrue(_holds('release-1.2', 'ends_with', 1.2))
        self.assertTrue(_holds('release-1.2', 'matches', r'^release-\d'))
        self.assertFalse(_holds('hotfix', 'matches', r'^release'))
        for operator in ('starts_with', 'ends_with', 'matches'):
            with self.subTest(operator):
                self.assertEqual(_error(12, operator, '1'), 'not_text')

    def test_invalid_pattern(self) -> None:
        self.assertEqual(_error('x', 'matches', '('), 'invalid_pattern')
        self.assertEqual(_error('x', 'matches', r'(a)\1'), 'invalid_pattern')

    def test_is_empty(self) -> None:
        for value, expected in (
            (None, True),
            ('', True),
            ([], True),
            ({}, True),
            (' ', False),
            (0, False),
            (False, False),
            (['a'], False),
        ):
            with self.subTest(value=value):
                self.assertIs(_holds(value, 'is_empty'), expected)
                self.assertIs(_holds(value, 'is_not_empty'), not expected)

    def test_match(self) -> None:
        rows = [('a', 'equals', 'a'), ('a', 'equals', 'b')]
        self.assertFalse(_evaluate(rows).result)
        self.assertTrue(_evaluate(rows, match='any').result)

    def test_every_row_is_evaluated(self) -> None:
        with self.assertRaises(condition.EvaluationError):
            _evaluate(
                [('a', 'equals', 'a'), ('x', 'greater_than', 1)],
                match='any',
            )

    def test_output(self) -> None:
        output = _evaluate([(5, 'greater_than', '3'), ('', 'is_empty', None)])
        self.assertEqual(
            output.model_dump(),
            {
                'result': True,
                'conditions': [
                    {
                        'a': 5,
                        'operator': 'greater_than',
                        'b': '3',
                        'result': True,
                    },
                    {
                        'a': '',
                        'operator': 'is_empty',
                        'b': None,
                        'result': True,
                    },
                ],
            },
        )


class MismatchTestCase(unittest.TestCase):
    def test_mismatch(self) -> None:
        for operator, side, types, expected in (
            ('greater_than', 'a', {'string'}, 'a number'),
            ('greater_than', 'b', {'integer'}, None),
            ('contains', 'a', {'integer'}, 'text or a list'),
            ('contains', 'a', {'array'}, None),
            ('contains', 'b', {'object'}, 'a single value'),
            ('matches', 'a', {'number'}, 'text'),
            ('equals', 'a', {'array'}, 'a single value'),
            ('equals', 'a', {'string', 'array'}, None),
            ('is_empty', 'a', {'object'}, None),
            ('greater_than', 'a', set(), None),
        ):
            with self.subTest(operator=operator, side=side, types=types):
                self.assertEqual(
                    condition.mismatch(operator, side, types), expected
                )


FIELDS = [
    {'name': 'count', 'type': 'integer'},
    {'name': 'label', 'type': 'string'},
    {
        'name': 'sender',
        'type': 'object',
        'fields': [{'name': 'email', 'type': 'string'}],
    },
]


def _issues(
    rows: list[dict[str, typing.Any]],
) -> list[graph.ValidationIssue]:
    nodes = [
        {'id': 'start', 'type': 'manual', 'params': {}},
        {'id': 'pause', 'type': 'wait', 'params': {'duration': '1m'}},
        {
            'id': 'triage',
            'type': 'agent',
            'params': {
                'agent_id': 'a1',
                'instruction': 'Triage.',
                'output_fields': FIELDS,
            },
        },
        {'id': 'check', 'type': 'condition', 'params': {'conditions': rows}},
    ]
    wf_graph = graph.Graph.model_validate(
        {
            'nodes': [
                {
                    **n,
                    'key': n['id'],
                    'title': n['id'].title(),
                    'position': {'x': 0, 'y': 0},
                }
                for n in nodes
            ],
            'edges': [
                {'source': 'start', 'port': 0, 'target': 'pause'},
                {'source': 'pause', 'port': 0, 'target': 'triage'},
                {'source': 'triage', 'port': 0, 'target': 'check'},
            ],
        }
    )
    return validation.validate(wf_graph, graph.Settings()).issues


class ValidationTestCase(unittest.TestCase):
    def test_type_mismatch_is_a_warning(self) -> None:
        for a, operator, b in (
            ('{{ triage.result.label }}', 'greater_than', 5),
            ('{{ triage.result.count }}', 'contains', '1'),
            ('{{ pause.waited_seconds }}', 'matches', '^1'),
            ('{{ triage.result.sender }}', 'equals', 'x'),
            ('x', 'contains', '{{ triage.result.sender }}'),
            ('{{ triage.outcome }}', 'greater_than', 1),
        ):
            with self.subTest(a=a, operator=operator, b=b):
                issues = _issues([{'a': a, 'operator': operator, 'b': b}])
                self.assertEqual(
                    [(i.severity, i.code) for i in issues],
                    [('warning', 'condition_type_mismatch')],
                )
                self.assertEqual(issues[0].node_id, 'check')

    def test_no_warning(self) -> None:
        for a, operator, b in (
            ('{{ triage.result.count }}', 'greater_than', 5),
            ('{{ pause.waited_seconds }}', 'less_than', '60'),
            ('{{ triage.result.sender.email }}', 'ends_with', '.com'),
            ('{{ triage.result }}', 'is_empty', None),
            ('n{{ triage.result.count }}', 'contains', '1'),
            ('{{ trigger.count }}', 'contains', '1'),
            ('{{ triage.summary }}', 'contains', 'done'),
            ('{{ triage.result.nope }}', 'greater_than', 1),
        ):
            with self.subTest(a=a, operator=operator, b=b):
                issues = _issues([{'a': a, 'operator': operator, 'b': b}])
                self.assertNotIn(
                    'condition_type_mismatch', {i.code for i in issues}
                )

    def test_missing_b_is_an_error(self) -> None:
        issues = _issues([{'a': 'x', 'operator': 'equals'}])
        self.assertEqual(
            [(i.severity, i.code) for i in issues],
            [('error', 'invalid_param')],
        )
