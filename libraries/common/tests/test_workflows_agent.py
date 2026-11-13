"""Tests for the structured output of the agent step type."""

import typing
import unittest

import pydantic

from imbi.common.workflows import graph, validation
from imbi.common.workflows.registry import agent

FIELDS: list[dict[str, typing.Any]] = [
    {'name': 'subjects', 'type': 'array', 'items': 'string'},
    {'name': 'count', 'type': 'integer', 'description': 'How many.'},
    {
        'name': 'priority',
        'type': 'string',
        'enum': ['High', 'Low'],
        'required': False,
    },
    {
        'name': 'sender',
        'type': 'object',
        'fields': [
            {'name': 'email', 'type': 'string', 'format': 'email'},
            {'name': 'name', 'type': 'string', 'required': False},
        ],
    },
    {
        'name': 'emails',
        'type': 'array',
        'items': 'object',
        'fields': [
            {'name': 'subject', 'type': 'string'},
            {'name': 'urgent', 'type': 'boolean', 'required': False},
        ],
    },
]


def _params(fields: list[dict[str, typing.Any]]) -> agent.Params:
    return agent.Params.model_validate(
        {'agent_id': 'a1', 'instruction': 'Triage.', 'output_fields': fields}
    )


class OutputFieldsTestCase(unittest.TestCase):
    def test_valid(self) -> None:
        self.assertEqual(len(_params(FIELDS).output_fields), 5)

    def test_invalid(self) -> None:
        cases: dict[str, list[dict[str, typing.Any]]] = {
            'array without items': [{'name': 'a', 'type': 'array'}],
            'items on a scalar': [
                {'name': 'a', 'type': 'string', 'items': 'string'}
            ],
            'object without fields': [{'name': 'a', 'type': 'object'}],
            'fields on an array of strings': [
                {
                    'name': 'a',
                    'type': 'array',
                    'items': 'string',
                    'fields': [{'name': 'b', 'type': 'string'}],
                }
            ],
            'nested object': [
                {
                    'name': 'a',
                    'type': 'object',
                    'fields': [{'name': 'b', 'type': 'object'}],
                }
            ],
            'enum on an integer': [
                {'name': 'a', 'type': 'integer', 'enum': ['1']}
            ],
            'enum and format': [
                {
                    'name': 'a',
                    'type': 'string',
                    'enum': ['x'],
                    'format': 'date',
                }
            ],
            'name with a space': [{'name': 'a b', 'type': 'string'}],
            'name of a dict method': [
                {'name': 'items', 'type': 'array', 'items': 'string'}
            ],
            'nested name of a dict method': [
                {
                    'name': 'a',
                    'type': 'object',
                    'fields': [{'name': 'keys', 'type': 'string'}],
                }
            ],
            'empty enum value': [
                {'name': 'a', 'type': 'string', 'enum': ['']}
            ],
            'enum values that differ in case': [
                {'name': 'a', 'type': 'string', 'enum': ['High', 'high']}
            ],
            'duplicate names': [
                {'name': 'a', 'type': 'string'},
                {'name': 'a', 'type': 'integer'},
            ],
            'duplicate nested names': [
                {
                    'name': 'a',
                    'type': 'object',
                    'fields': [
                        {'name': 'b', 'type': 'string'},
                        {'name': 'b', 'type': 'string'},
                    ],
                }
            ],
            'too many optional fields': [
                {'name': f'f{i}', 'type': 'string', 'required': False}
                for i in range(agent.MAX_OPTIONAL_FIELDS + 1)
            ],
        }
        for case, fields in cases.items():
            with (
                self.subTest(case),
                self.assertRaises(pydantic.ValidationError),
            ):
                _params(fields)

    def test_enum_on_array_of_strings(self) -> None:
        fields = [
            {'name': 'a', 'type': 'array', 'items': 'string', 'enum': ['x']}
        ]
        self.assertEqual(_params(fields).output_fields[0].enum, ['x'])


class OutputSchemaTestCase(unittest.TestCase):
    def test_no_fields(self) -> None:
        self.assertIsNone(agent.output_schema([]))

    def test_schema(self) -> None:
        schema = agent.output_schema(_params(FIELDS).output_fields)
        object_of = {
            'type': 'object',
            'additionalProperties': False,
        }
        self.assertEqual(
            schema,
            {
                **object_of,
                'properties': {
                    'subjects': {
                        'type': 'array',
                        'items': {'type': 'string'},
                    },
                    'count': {'type': 'integer', 'description': 'How many.'},
                    'priority': {'type': 'string', 'enum': ['High', 'Low']},
                    'sender': {
                        **object_of,
                        'properties': {
                            'email': {'type': 'string', 'format': 'email'},
                            'name': {'type': 'string'},
                        },
                        'required': ['email'],
                    },
                    'emails': {
                        'type': 'array',
                        'items': {
                            **object_of,
                            'properties': {
                                'subject': {'type': 'string'},
                                'urgent': {'type': 'boolean'},
                            },
                            'required': ['subject'],
                        },
                    },
                },
                'required': ['subjects', 'count', 'sender', 'emails'],
            },
        )


class ResultTestCase(unittest.TestCase):
    def test_complete_result(self) -> None:
        fields = _params(FIELDS).output_fields
        result = agent.complete_result(
            fields,
            {
                'subjects': ['Hi'],
                'count': 1,
                'priority': 'high',
                'sender': {'email': 'a@example.com'},
                'emails': [{'subject': 'Hi'}],
            },
        )
        self.assertEqual(
            result,
            {
                'subjects': ['Hi'],
                'count': 1,
                'priority': 'High',
                'sender': {'email': 'a@example.com', 'name': None},
                'emails': [{'subject': 'Hi', 'urgent': None}],
            },
        )

    def test_complete_result_without_optional_fields(self) -> None:
        fields = _params(FIELDS).output_fields
        result = agent.complete_result(fields, {'count': 0})
        self.assertIsNone(result['priority'])
        self.assertIsNone(result['sender'])

    def test_enum_of_array_of_strings(self) -> None:
        fields = _params(
            [{'name': 'a', 'type': 'array', 'items': 'string', 'enum': ['Hi']}]
        ).output_fields
        self.assertEqual(
            agent.complete_result(fields, {'a': ['hi', 'other']}),
            {'a': ['Hi', 'other']},
        )

    def test_match_enum_case(self) -> None:
        schema = agent.output_schema(_params(FIELDS).output_fields) or {}
        output = {
            'priority': 'HIGH',
            'emails': [{'subject': 'Hi'}],
            'extra': 'kept',
        }
        self.assertEqual(
            agent.match_enum_case(schema, output),
            {
                'priority': 'High',
                'emails': [{'subject': 'Hi'}],
                'extra': 'kept',
            },
        )

    def test_blank_result(self) -> None:
        fields = _params(FIELDS).output_fields
        self.assertEqual(
            agent.blank_result(fields),
            {
                'subjects': '',
                'count': '',
                'priority': '',
                'sender': {'email': '', 'name': ''},
                'emails': '',
            },
        )

    def test_unknown_field(self) -> None:
        fields = _params(FIELDS).output_fields
        cases: dict[tuple[str, ...], str | None] = {
            ('count',): None,
            ('sender', 'email'): None,
            ('sender', 'phone'): 'phone',
            ('sender', 'items'): None,
            ('get',): None,
            ('subjects', 'anything'): None,
            ('nope',): 'nope',
        }
        for path, expected in cases.items():
            with self.subTest(path):
                self.assertEqual(
                    agent.unknown_field(fields, list(path)), expected
                )


def _issues(
    reference: str, fields: list[dict[str, typing.Any]]
) -> list[graph.ValidationIssue]:
    nodes = [
        {'id': 'start', 'type': 'manual', 'params': {}},
        {
            'id': 'triage',
            'type': 'agent',
            'params': {
                'agent_id': 'a1',
                'instruction': 'Triage.',
                'output_fields': fields,
            },
        },
        {
            'id': 'ship',
            'type': 'deploy',
            'params': {
                'project_id': 'p1',
                'environment': 'staging',
                'version': reference,
            },
        },
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
                {'source': 'start', 'port': 0, 'target': 'triage'},
                {'source': 'triage', 'port': 0, 'target': 'ship'},
            ],
        }
    )
    return validation.validate(wf_graph, graph.Settings()).issues


class ResultReferenceTestCase(unittest.TestCase):
    def test_known_fields(self) -> None:
        for reference in (
            '{{ triage.result.count }}',
            '{{ triage.result.sender.email }}',
            '{{ triage.result.priority.upper() }}',
            '{% for s in triage.result.subjects %}{{ s }}{% endfor %}',
            '{{ triage.summary }}',
            "{{ triage.result['sender']['email'] }}",
            '{{ triage.result.subjects[0] }}',
            "{% set f = 'nope' %}{{ triage.result[f] }}",
            '{{ triage.result.sender.items() }}',
            "{{ triage.result.get('count') }}",
        ):
            with self.subTest(reference):
                self.assertEqual(_issues(reference, FIELDS), [])

    def test_unknown_fields(self) -> None:
        for reference, missing in (
            ('{{ triage.result.nope }}', 'nope'),
            ('v{{ triage.result.sender.phone }}', 'phone'),
            ("{{ triage.result['phone'] }}", 'phone'),
            ("{{ triage['result'].sender['phone'] }}", 'phone'),
        ):
            with self.subTest(reference):
                issues = _issues(reference, FIELDS)
                self.assertEqual(
                    [i.code for i in issues], ['unknown_output_field']
                )
                self.assertIn(repr(missing), issues[0].message)

    def test_step_without_output_fields(self) -> None:
        issues = _issues('{{ triage.result.count }}', [])
        self.assertEqual([i.code for i in issues], ['unknown_output_field'])
