"""Tests for the workflow-steps capability (ADR 0032)."""

import unittest
import unittest.mock

import pydantic

from imbi.common.plugins import base, registry
from imbi.common.workflows import registry as steps
from libraries.common.tests.test_plugins.fixtures import step_plugin
from libraries.common.tests.test_plugins.test_registry import (
    _discovery,
    _reset_registry,
)

_MODULE = 'imbi_plugin_stepper'


def _load(plugin: object = step_plugin.StepperPlugin) -> registry.LoadResult:
    with (
        _discovery(convention={_MODULE: _MODULE}),
        unittest.mock.patch.object(
            registry, '_load_convention_plugin', return_value=plugin
        ),
    ):
        return registry.load_plugins()


class DescriptorTestCase(unittest.TestCase):
    def test_valid(self) -> None:
        descriptor = step_plugin.query_descriptor()
        self.assertIs(descriptor.params_model, step_plugin.QueryParams)
        self.assertEqual(descriptor.choice_fields, ['datasource'])

    def test_integration_field_is_reserved(self) -> None:
        with self.assertRaisesRegex(pydantic.ValidationError, 'integration'):
            step_plugin.query_descriptor(
                params_model=pydantic.create_model(
                    'P', integration=(str, ...)
                ),
                choices=None,
            )

    def test_project_id_is_reserved(self) -> None:
        params = pydantic.create_model('P', project_id=(str, ...))
        for scoped in (False, True):
            with self.assertRaisesRegex(
                pydantic.ValidationError, 'project_id'
            ):
                step_plugin.query_descriptor(
                    params_model=params, choices=None, project_scoped=scoped
                )

    def test_alias_is_reserved(self) -> None:
        params = pydantic.create_model(
            'P', project=(str, pydantic.Field(alias='project_id'))
        )
        with self.assertRaisesRegex(pydantic.ValidationError, 'project_id'):
            step_plugin.query_descriptor(params_model=params, choices=None)

    def test_choice_fields_use_alias(self) -> None:
        params = pydantic.create_model(
            'P',
            datasource_id=(
                str,
                pydantic.Field(
                    alias='datasourceId',
                    json_schema_extra={'x-imbi-choices': True},
                ),
            ),
        )
        descriptor = step_plugin.query_descriptor(params_model=params)
        self.assertEqual(descriptor.choice_fields, ['datasourceId'])

    def test_side_effect_needs_permissions(self) -> None:
        with self.assertRaisesRegex(pydantic.ValidationError, 'permissions'):
            step_plugin.query_descriptor(side_effect=True)
        step_plugin.query_descriptor(
            side_effect=True, permissions={'project:deploy'}
        )

    def test_choice_fields_need_choices(self) -> None:
        with self.assertRaisesRegex(pydantic.ValidationError, 'choices'):
            step_plugin.query_descriptor(choices=None)

    def test_ports_unique(self) -> None:
        with self.assertRaisesRegex(pydantic.ValidationError, 'ports'):
            step_plugin.threshold_descriptor(ports=('Pass', 'Pass'))
        with self.assertRaisesRegex(pydantic.ValidationError, 'ports'):
            step_plugin.threshold_descriptor(ports=())

    def test_poll_seconds_minimum(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            step_plugin.threshold_descriptor(poll_seconds=5)


class RegistryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_registry()

    def tearDown(self) -> None:
        _reset_registry()

    def test_loads(self) -> None:
        result = _load()
        self.assertEqual(result.loaded, ['stepper'], result.errors)

    def test_duplicate_step_names_rejected(self) -> None:
        class Dup(base.WorkflowStepsCapability):
            @classmethod
            def steps(cls) -> list[base.WorkflowStepDescriptor]:
                return [
                    step_plugin.query_descriptor(),
                    step_plugin.query_descriptor(),
                ]

        class DupPlugin(base.Plugin):
            manifest = step_plugin.StepperPlugin.manifest.model_copy(
                update={
                    'capabilities': [
                        base.Capability(
                            kind='workflow-steps', label='S', handler=Dup
                        )
                    ]
                }
            )

        result = _load(DupPlugin)
        self.assertEqual(result.loaded, [])
        self.assertIn('Duplicate step', result.errors[_MODULE])

    def test_steps_must_be_descriptors(self) -> None:
        class Bad(base.WorkflowStepsCapability):
            @classmethod
            def steps(cls) -> list[base.WorkflowStepDescriptor]:
                return ['nope']  # type: ignore[list-item]

        class BadPlugin(base.Plugin):
            manifest = step_plugin.StepperPlugin.manifest.model_copy(
                update={
                    'capabilities': [
                        base.Capability(
                            kind='workflow-steps', label='S', handler=Bad
                        )
                    ]
                }
            )

        result = _load(BadPlugin)
        self.assertIn('WorkflowStepDescriptor', result.errors[_MODULE])


class StepTypesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _load()

    def tearDown(self) -> None:
        _reset_registry()

    def test_built_in_types_unchanged(self) -> None:
        self.assertIs(steps.get('wait'), steps.STEP_TYPES['wait'])
        for name, step in steps.STEP_TYPES.items():
            self.assertIs(steps.all_types()[name], step)

    def test_plugin_types_added(self) -> None:
        action = steps.require('stepper.gather_metrics')
        self.assertEqual(action.category, 'action')
        self.assertEqual(action.label, 'Stepper · Gather metrics')
        self.assertEqual(action.plugin, 'stepper')
        self.assertEqual(action.icon, 'si-grafana')
        self.assertEqual(action.ports, ('',))
        gate = steps.require('stepper.metric_threshold')
        self.assertEqual(gate.category, 'logic')
        self.assertEqual(gate.ports, ('Pass', 'Failed'))
        self.assertEqual(gate.poll_seconds, 60)
        self.assertEqual(gate.timeout_seconds, 3600)

    def test_params_get_integration(self) -> None:
        action = steps.require('stepper.gather_metrics')
        schema = action.params.model_json_schema()
        self.assertEqual(
            schema['properties']['integration']['x-imbi-source'],
            'integration',
        )
        self.assertEqual(
            schema['properties']['integration']['x-imbi-plugin'], 'stepper'
        )
        self.assertTrue(schema['properties']['datasource']['x-imbi-choices'])
        # Not project-scoped: the project is optional.
        self.assertIn('project_id', schema['properties'])
        self.assertNotIn('project_id', schema['required'])
        params = action.params.model_validate(
            {'integration': 'grafana', 'datasource': 'prom', 'query': 'up'}
        )
        self.assertIsInstance(params, step_plugin.QueryParams)
        with self.assertRaises(pydantic.ValidationError):
            action.params.model_validate({'datasource': 'p', 'query': 'up'})

    def test_project_scoped_params_get_project_id(self) -> None:
        gate = steps.require('stepper.metric_threshold')
        self.assertIn(
            'project_id', gate.params.model_json_schema()['required']
        )

    def test_required_permissions(self) -> None:
        action = steps.require('stepper.gather_metrics')
        self.assertEqual(action.required_permissions({}), {'integration:read'})

    def test_describe(self) -> None:
        described = steps.require('stepper.metric_threshold').describe()
        self.assertEqual(described['plugin'], 'stepper')
        self.assertEqual(described['ports'], ['Pass', 'Failed'])
        self.assertIsNone(steps.require('wait').describe()['plugin'])

    def test_unknown(self) -> None:
        self.assertIsNone(steps.get('stepper.nope'))
        self.assertIsNone(steps.get('other.gather_metrics'))
        with self.assertRaises(KeyError):
            steps.require('stepper.nope')

    def test_removed_plugin(self) -> None:
        _reset_registry()
        self.assertIsNone(steps.get('stepper.gather_metrics'))
