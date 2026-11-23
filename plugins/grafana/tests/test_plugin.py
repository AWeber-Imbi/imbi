"""Tests for the Grafana plugin: manifest and webhook signature."""

import unittest

import imbi.plugins.grafana
from imbi.plugins.grafana import plugin


class ManifestTestCase(unittest.TestCase):
    def test_manifest(self) -> None:
        manifest = imbi.plugins.grafana.PLUGIN.manifest
        self.assertEqual('grafana', manifest.slug)
        self.assertEqual('none', manifest.auth_type)
        self.assertEqual([], manifest.credentials)
        self.assertEqual([], manifest.options)
        capability = manifest.get_capability('webhook-actions')
        self.assertIsNotNone(capability)
        assert capability is not None
        self.assertIs(capability.handler, plugin.GrafanaWebhookActions)
        self.assertEqual(
            ['webhook-actions'], [c.kind for c in manifest.capabilities]
        )

    def test_version(self) -> None:
        self.assertTrue(imbi.plugins.grafana.version)


class WebhookActionsTestCase(unittest.TestCase):
    def test_actions_empty(self) -> None:
        self.assertEqual(plugin.GrafanaWebhookActions.actions(), [])

    def test_instantiable(self) -> None:
        self.assertIsInstance(
            plugin.GrafanaWebhookActions(), plugin.GrafanaWebhookActions
        )

    def test_signature_is_hmac_hex_body(self) -> None:
        signature = plugin.GrafanaWebhookActions.signature()
        self.assertEqual(
            (
                signature.header,
                signature.prefix,
                signature.secret,
                signature.scheme,
            ),
            ('x-grafana-alerting-signature', '', 'webhook', 'hmac-hex'),
        )
