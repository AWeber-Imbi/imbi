"""Tests for the ``release`` step type."""

import typing
import unittest

import pydantic

from imbi.common.workflows import registry
from imbi.common.workflows.registry import release

RELEASE: dict[str, typing.Any] = {
    'project_id': 'p1',
    'from_environment': 'testing',
    'environment': 'staging',
    'commit': '0123abc',
}


class ParamsTestCase(unittest.TestCase):
    def test_tag_and_notes_are_drafted_when_empty(self) -> None:
        params = release.Params.model_validate(RELEASE)
        self.assertEqual((params.tag, params.release_notes), ('', ''))

    def test_required(self) -> None:
        for name in RELEASE:
            for params in (
                {k: v for k, v in RELEASE.items() if k != name},
                RELEASE | {name: ''},
            ):
                with (
                    self.subTest(name),
                    self.assertRaises(pydantic.ValidationError),
                ):
                    release.Params.model_validate(params)


class StepTestCase(unittest.TestCase):
    def test_step(self) -> None:
        step = registry.STEP_TYPES['release']
        self.assertEqual(step.ports_for({}), ['Succeeded', 'Failed'])
        self.assertTrue(step.side_effect)
        self.assertEqual(
            step.required_permissions({}), {'project:deployment:write'}
        )
        release.Output.model_validate(step.sample_output)
