"""Tests for the aggregate PagerDuty plugin manifest."""

import unittest

from imbi_common.plugins.base import Plugin

import imbi_plugin_pagerduty
from imbi_plugin_pagerduty import PagerDutyPlugin
from imbi_plugin_pagerduty.doctor import PagerDutyDoctor
from imbi_plugin_pagerduty.incidents import PagerDutyIncidents
from imbi_plugin_pagerduty.lifecycle import PagerDutyLifecycle
from imbi_plugin_pagerduty.webhook import PagerDutyWebhookActions


class PluginTestCase(unittest.TestCase):
    def test_module_level_plugin_attr(self) -> None:
        self.assertIs(imbi_plugin_pagerduty.PLUGIN, PagerDutyPlugin)
        self.assertTrue(issubclass(PagerDutyPlugin, Plugin))

    def test_manifest_identity(self) -> None:
        manifest = PagerDutyPlugin.manifest
        self.assertEqual(manifest.slug, 'pagerduty')
        self.assertEqual(manifest.name, 'PagerDuty')
        self.assertEqual(manifest.api_version, 2)
        self.assertEqual(manifest.auth_type, 'api_token')

    def test_credentials_declared_once(self) -> None:
        creds = PagerDutyPlugin.manifest.credentials
        self.assertEqual([c.name for c in creds], ['api_key'])

    def test_integration_options(self) -> None:
        names = {o.name for o in PagerDutyPlugin.manifest.options}
        self.assertEqual(
            names,
            {
                'team_escalation_policy_mapping',
                'default_escalation_policy_id',
                'gateway_webhook_url',
            },
        )

    def test_capability_kinds(self) -> None:
        kinds = [c.kind for c in PagerDutyPlugin.manifest.capabilities]
        self.assertCountEqual(
            kinds, ['lifecycle', 'incidents', 'webhook-actions', 'analysis']
        )

    def test_analysis_capability(self) -> None:
        capability = PagerDutyPlugin.manifest.get_capability('analysis')
        assert capability is not None
        self.assertIs(capability.handler, PagerDutyDoctor)

    def test_lifecycle_capability(self) -> None:
        capability = PagerDutyPlugin.manifest.get_capability('lifecycle')
        assert capability is not None
        self.assertIs(capability.handler, PagerDutyLifecycle)
        self.assertTrue(capability.hints['supports_lifecycle_sync'])
        self.assertEqual(
            capability.hints['lifecycle_events'],
            ['created', 'updated', 'deleted', 'relocated'],
        )

    def test_incidents_capability(self) -> None:
        capability = PagerDutyPlugin.manifest.get_capability('incidents')
        assert capability is not None
        self.assertIs(capability.handler, PagerDutyIncidents)
        self.assertTrue(capability.hints['cacheable'])

    def test_webhook_actions_capability(self) -> None:
        capability = PagerDutyPlugin.manifest.get_capability('webhook-actions')
        assert capability is not None
        self.assertIs(capability.handler, PagerDutyWebhookActions)
