"""Tests for the ``analysis`` step type."""

import typing
import unittest

import pydantic

from imbi.common.workflows import graph, registry, validation
from imbi.common.workflows.registry import analysis

FIELDS: list[dict[str, typing.Any]] = [{'name': 'risk', 'type': 'string'}]


def _params(**overrides: typing.Any) -> analysis.Params:
    return analysis.Params.model_validate(
        {'prompt_ref': 'workflows/acme.wf.sum', 'prompt_version': 1}
        | overrides
    )


def _node(
    key: str, step: str, params: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    return {
        'id': key,
        'key': key,
        'type': step,
        'title': key.title(),
        'position': {'x': 0, 'y': 0},
        'params': params,
    }


class ParamsTestCase(unittest.TestCase):
    def test_valid(self) -> None:
        params = _params(inputs={'diff': '{{ trigger.diff }}', 'lambda': 1})
        self.assertEqual(params.output_fields, [])
        self.assertEqual(set(params.inputs), {'diff', 'lambda'})

    def test_invalid(self) -> None:
        for overrides, message in (
            ({'prompt_ref': 'workflows/acme.wf.sum@2'}, 'pattern'),
            ({'prompt_ref': 'agents/acme.x'}, 'pattern'),
            ({'prompt_ref': 'workflows/{{ x }}'}, 'pattern'),
            ({'prompt_version': 0}, 'greater than 0'),
            ({'inputs': {'Bad': 1}}, 'not a valid input name'),
            ({'inputs': {f'i{n}': n for n in range(21)}}, 'at most 20'),
            ({'output_fields': FIELDS * 2}, 'unique'),
            ({'output_fields': FIELDS * 51}, 'at most 50'),
        ):
            with (
                self.subTest(message),
                self.assertRaisesRegex(pydantic.ValidationError, message),
            ):
                _params(**overrides)

    def test_step(self) -> None:
        step = registry.STEP_TYPES['analysis']
        self.assertEqual(step.category, 'logic')
        self.assertEqual(step.ports_for({}), [''])
        self.assertEqual(step.required_permissions({}), {'prompt:run'})
        self.assertFalse(step.side_effect)
        analysis.Output.model_validate(step.sample_output)

    def test_result_references_are_checked(self) -> None:
        def issues(reference: str) -> list[str]:
            wf_graph = graph.Graph.model_validate(
                {
                    'nodes': [
                        _node('start', 'manual', {}),
                        _node(
                            'sum',
                            'analysis',
                            {
                                'prompt_ref': 'workflows/acme.wf.sum',
                                'prompt_version': 1,
                                'output_fields': FIELDS,
                            },
                        ),
                        _node('wait', 'wait', {'duration': reference}),
                    ],
                    'edges': [
                        {'source': 'start', 'port': 0, 'target': 'sum'},
                        {'source': 'sum', 'port': 0, 'target': 'wait'},
                    ],
                }
            )
            return [
                i.code
                for i in validation.validate(wf_graph, graph.Settings()).issues
            ]

        self.assertNotIn('unknown_output_field', issues('{{ sum.text }}'))
        self.assertNotIn(
            'unknown_output_field', issues('{{ sum.result.risk }}')
        )
        self.assertIn('unknown_output_field', issues('{{ sum.result.nope }}'))
