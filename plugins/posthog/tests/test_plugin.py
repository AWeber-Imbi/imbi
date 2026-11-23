"""Tests for the PostHog plugin: manifest and webhook signature."""

import unittest

import imbi.plugins.posthog
from imbi.plugins.posthog import plugin


class ManifestTestCase(unittest.TestCase):
    def test_manifest(self) -> None:
        manifest = imbi.plugins.posthog.PLUGIN.manifest
        self.assertEqual('posthog', manifest.slug)
        self.assertEqual('none', manifest.auth_type)
        self.assertEqual([], manifest.credentials)
        self.assertEqual([], manifest.options)
        capability = manifest.get_capability('webhook-actions')
        self.assertIsNotNone(capability)
        assert capability is not None
        self.assertIs(capability.handler, plugin.PostHogWebhookActions)
        self.assertEqual(
            ['webhook-actions'], [c.kind for c in manifest.capabilities]
        )

    def test_version(self) -> None:
        self.assertTrue(imbi.plugins.posthog.version)


class WebhookActionsTestCase(unittest.TestCase):
    def test_actions_empty(self) -> None:
        self.assertEqual(plugin.PostHogWebhookActions.actions(), [])

    def test_instantiable(self) -> None:
        self.assertIsInstance(
            plugin.PostHogWebhookActions(), plugin.PostHogWebhookActions
        )

    def test_signature_is_standard_webhooks(self) -> None:
        signature = plugin.PostHogWebhookActions.signature()
        self.assertEqual(
            (
                signature.header,
                signature.prefix,
                signature.secret,
                signature.scheme,
            ),
            ('webhook-signature', 'v1,', 'webhook', 'standard-webhooks'),
        )
