"""Tests for shared AWS capability helpers."""

import unittest

from imbi_common.plugins.base import PluginContext

from imbi_plugin_aws._helpers import template_vars


def _ctx(project_type_slugs: list[str] | None = None) -> PluginContext:
    return PluginContext(
        project_id='proj-1',
        project_slug='widget',
        org_slug='acme',
        team_slug='platform',
        environment='prod',
        project_type_slugs=project_type_slugs or [],
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
