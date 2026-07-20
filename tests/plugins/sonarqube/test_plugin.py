import unittest

import imbi_plugin_sonarqube
from imbi_plugin_sonarqube import actions, plugin


class SonarQubePluginManifestTests(unittest.TestCase):
    def test_module_exposes_plugin_attribute(self) -> None:
        self.assertIs(imbi_plugin_sonarqube.PLUGIN, plugin.SonarQubePlugin)

    def test_manifest_slug_and_auth_type(self) -> None:
        manifest = plugin.SonarQubePlugin.manifest
        self.assertEqual('sonarqube', manifest.slug)
        self.assertEqual('api_token', manifest.auth_type)

    def test_manifest_declares_service_url_option(self) -> None:
        manifest = plugin.SonarQubePlugin.manifest
        names = [option.name for option in manifest.options]
        self.assertIn('service_url', names)

    def test_manifest_declares_api_token_credential(self) -> None:
        manifest = plugin.SonarQubePlugin.manifest
        names = [credential.name for credential in manifest.credentials]
        self.assertIn('api_token', names)

    def test_manifest_declares_webhook_actions_capability(self) -> None:
        manifest = plugin.SonarQubePlugin.manifest
        capability = manifest.get_capability('webhook-actions')
        self.assertIsNotNone(capability)
        assert capability is not None
        self.assertIs(capability.handler, plugin.SonarQubeWebhookActions)

    def test_manifest_declares_analysis_capability(self) -> None:
        manifest = plugin.SonarQubePlugin.manifest
        capability = manifest.get_capability('analysis')
        self.assertIsNotNone(capability)
        assert capability is not None
        self.assertIs(capability.handler, plugin.SonarQubeDoctor)


class SonarQubeWebhookActionsTests(unittest.TestCase):
    def test_actions_catalog_lists_known_action(self) -> None:
        descriptors = plugin.SonarQubeWebhookActions.actions()
        self.assertEqual(1, len(descriptors))
        descriptor = descriptors[0]
        self.assertEqual('update_project_from_webhook', descriptor.name)
        self.assertIsNotNone(descriptor.label)
        self.assertIs(descriptor.callable, actions.update_project_from_webhook)
        self.assertIs(descriptor.config_model, actions.MetricMappings)

    def test_actions_returns_fresh_list_each_call(self) -> None:
        first = plugin.SonarQubeWebhookActions.actions()
        second = plugin.SonarQubeWebhookActions.actions()
        self.assertIsNot(first, second)
