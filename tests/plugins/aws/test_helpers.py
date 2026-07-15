"""Tests for shared AWS capability helpers."""

import typing
import unittest

from imbi_common.plugins.base import PluginContext

from imbi_plugin_aws._helpers import template_vars


def _ctx(
    project_type_slugs: list[str] | None = None,
    integration_options: dict[str, typing.Any] | None = None,
) -> PluginContext:
    return PluginContext(
        project_id='proj-1',
        project_slug='widget',
        org_slug='acme',
        team_slug='platform',
        environment='prod',
        project_type_slugs=project_type_slugs or [],
        integration_options=integration_options or {},
    )


class TemplateVarsTestCase(unittest.TestCase):
    def test_includes_all_whitelisted_variables(self) -> None:
        variables = template_vars(_ctx(['apis', 'consumers']))
        self.assertEqual(
            variables,
            {
                'project_slug': 'widget',
                'org_slug': 'acme',
                'team_slug': 'platform',
                'environment': 'prod',
                'project_id': 'proj-1',
                'project_type_slug': 'apis',
            },
        )

    def test_project_type_slug_none_when_untyped(self) -> None:
        self.assertIsNone(template_vars(_ctx())['project_type_slug'])


class ProjectTypePathMapTestCase(unittest.TestCase):
    def test_slug_remapped_when_entry_exists(self) -> None:
        ctx = _ctx(
            ['apis'],
            {'project_type_path_map': {'apis': 'api'}},
        )
        self.assertEqual(template_vars(ctx)['project_type_slug'], 'api')

    def test_slug_passes_through_when_absent_from_map(self) -> None:
        ctx = _ctx(
            ['hosted-services'],
            {'project_type_path_map': {'apis': 'api'}},
        )
        self.assertEqual(
            template_vars(ctx)['project_type_slug'], 'hosted-services'
        )

    def test_only_first_slug_considered(self) -> None:
        ctx = _ctx(
            ['apis', 'consumers'],
            {'project_type_path_map': {'apis': 'api', 'consumers': 'worker'}},
        )
        self.assertEqual(template_vars(ctx)['project_type_slug'], 'api')

    def test_no_map_configured_uses_raw_slug(self) -> None:
        self.assertEqual(
            template_vars(_ctx(['apis']))['project_type_slug'], 'apis'
        )

    def test_untyped_project_ignores_map(self) -> None:
        ctx = _ctx([], {'project_type_path_map': {'apis': 'api'}})
        self.assertIsNone(template_vars(ctx)['project_type_slug'])

    def test_blank_mapping_value_falls_back_to_slug(self) -> None:
        ctx = _ctx(['apis'], {'project_type_path_map': {'apis': ''}})
        self.assertEqual(template_vars(ctx)['project_type_slug'], 'apis')

    def test_whitespace_mapping_value_falls_back_to_slug(self) -> None:
        ctx = _ctx(['apis'], {'project_type_path_map': {'apis': '   '}})
        self.assertEqual(template_vars(ctx)['project_type_slug'], 'apis')

    def test_non_dict_map_option_ignored(self) -> None:
        ctx = _ctx(['apis'], {'project_type_path_map': 'nonsense'})
        self.assertEqual(template_vars(ctx)['project_type_slug'], 'apis')
