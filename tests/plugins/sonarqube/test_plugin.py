import unittest

import imbi_plugin_sonarqube
from imbi_plugin_sonarqube import actions


class SonarqubePluginManifestTests(unittest.TestCase):
    def test_manifest_slug_and_type(self) -> None:
        manifest = imbi_plugin_sonarqube.SonarqubePlugin.manifest
        self.assertEqual('sonarqube', manifest.slug)
        self.assertEqual('webhook', manifest.plugin_type)

    def test_manifest_declares_api_token_credential(self) -> None:
        manifest = imbi_plugin_sonarqube.SonarqubePlugin.manifest
        names = [credential.name for credential in manifest.credentials]
        self.assertIn('api_token', names)


class SonarqubePluginActionsTests(unittest.TestCase):
    def test_actions_catalog_lists_known_action(self) -> None:
        descriptors = imbi_plugin_sonarqube.SonarqubePlugin.actions()
        self.assertEqual(1, len(descriptors))
        descriptor = descriptors[0]
        self.assertEqual('update_project_from_webhook', descriptor.name)
        self.assertIsNotNone(descriptor.label)
        self.assertIs(descriptor.callable, actions.update_project_from_webhook)
        self.assertIs(descriptor.config_model, actions.MetricMappings)

    def test_actions_returns_fresh_list_each_call(self) -> None:
        first = imbi_plugin_sonarqube.SonarqubePlugin.actions()
        second = imbi_plugin_sonarqube.SonarqubePlugin.actions()
        self.assertIsNot(first, second)
