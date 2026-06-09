"""Tests for the PagerDuty webhook plugin (v1 stub)."""

import unittest

from imbi_plugin_pagerduty.webhook import PagerDutyWebhookPlugin


class WebhookPluginTestCase(unittest.TestCase):
    def test_manifest(self) -> None:
        manifest = PagerDutyWebhookPlugin.manifest
        self.assertEqual(manifest.slug, 'pagerduty-webhook')
        self.assertEqual(manifest.plugin_type, 'webhook')

    def test_actions_empty(self) -> None:
        self.assertEqual(PagerDutyWebhookPlugin.actions(), [])

    def test_instantiable(self) -> None:
        self.assertIsInstance(PagerDutyWebhookPlugin(), PagerDutyWebhookPlugin)
