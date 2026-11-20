"""Tests for the ``wait`` step type."""

import typing
import unittest

import pydantic

from imbi.common.workflows import graph, validation
from imbi.common.workflows.registry import wait


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
    def test_duration(self) -> None:
        for duration in ('10m', '1d', '{{ calc.result.duration }}'):
            with self.subTest(duration):
                wait.Params.model_validate({'duration': duration})

    def test_invalid_duration(self) -> None:
        for duration in (
            'abc',
            '0m',
            '{{ calc.result.seconds }}s',
            '{{ trigger }}',
        ):
            with (
                self.subTest(duration),
                self.assertRaises(pydantic.ValidationError),
            ):
                wait.Params.model_validate({'duration': duration})


class ValidationTestCase(unittest.TestCase):
    def test_duration_from_an_earlier_step(self) -> None:
        wf_graph = graph.Graph.model_validate(
            {
                'nodes': [
                    _node('start', 'manual', {}),
                    _node(
                        'calc',
                        'script',
                        {
                            'code': "{'duration': '2h'}",
                            'output_fields': [
                                {'name': 'duration', 'type': 'string'}
                            ],
                        },
                    ),
                    _node(
                        'hold',
                        'wait',
                        {'duration': '{{ calc.result.duration }}'},
                    ),
                ],
                'edges': [
                    {'source': 'start', 'port': 0, 'target': 'calc'},
                    {'source': 'calc', 'port': 0, 'target': 'hold'},
                ],
            }
        )
        issues = validation.validate(wf_graph, graph.Settings()).issues
        self.assertEqual([i.code for i in issues if i.severity == 'error'], [])
