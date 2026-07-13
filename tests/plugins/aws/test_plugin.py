"""Tests for the single AWSPlugin manifest and registry discovery."""

import unittest

from imbi_common.plugins.base import (
    ConfigurationCapability,
    IdentityCapability,
    LogsCapability,
    Plugin,
    PluginManifest,
)

import imbi_plugin_aws
from imbi_plugin_aws.cloudwatch import CloudWatchLogs
from imbi_plugin_aws.identity import AWSIdentity
from imbi_plugin_aws.plugin import AWSPlugin
from imbi_plugin_aws.ssm import SSMConfiguration


class PluginExportTestCase(unittest.TestCase):
    def test_module_level_plugin_attr(self) -> None:
        # The registry's convention scan reads the module-level PLUGIN.
        self.assertIs(imbi_plugin_aws.PLUGIN, AWSPlugin)
        self.assertTrue(issubclass(AWSPlugin, Plugin))

    def test_manifest_is_valid_v2(self) -> None:
        self.assertIsInstance(AWSPlugin.manifest, PluginManifest)
        self.assertEqual(AWSPlugin.manifest.api_version, 2)


class ManifestTestCase(unittest.TestCase):
    manifest = AWSPlugin.manifest

    def test_package_level_declaration(self) -> None:
        self.assertEqual(self.manifest.slug, 'aws')
        self.assertEqual(self.manifest.auth_type, 'aws-iam-ic')
        self.assertEqual(
            {o.name for o in self.manifest.options},
            {'region', 'default_role_name'},
        )
        # Credentials are declared once, at the Integration level.
        self.assertEqual(
            {c.name for c in self.manifest.credentials},
            {'client_id', 'client_secret', 'client_scopes'},
        )

    def test_capability_kinds_and_handlers(self) -> None:
        by_kind = {c.kind: c for c in self.manifest.capabilities}
        self.assertEqual(set(by_kind), {'identity', 'logs', 'configuration'})
        self.assertIs(by_kind['identity'].handler, AWSIdentity)
        self.assertIs(by_kind['logs'].handler, CloudWatchLogs)
        self.assertIs(by_kind['configuration'].handler, SSMConfiguration)
        self.assertTrue(issubclass(AWSIdentity, IdentityCapability))
        self.assertTrue(issubclass(CloudWatchLogs, LogsCapability))
        self.assertTrue(issubclass(SSMConfiguration, ConfigurationCapability))

    def test_identity_is_integration_wide_login_provider(self) -> None:
        identity = self.manifest.get_capability('identity')
        assert identity is not None
        self.assertFalse(identity.project_scoped)
        self.assertTrue(identity.default_enabled)
        self.assertTrue(identity.hints['login_capable'])
        self.assertEqual(
            identity.hints['default_scopes'], ['sso:account:access']
        )
        self.assertFalse(identity.hints['cacheable'])

    def test_data_capabilities_require_identity(self) -> None:
        # There are no static AWS keys in the blob; the data capabilities
        # consume STS keys the identity capability materializes.
        for kind in ('logs', 'configuration'):
            capability = self.manifest.get_capability(kind)
            assert capability is not None
            self.assertTrue(
                capability.requires_identity, f'{kind} requires identity'
            )

    def test_logs_supports_histogram(self) -> None:
        logs = self.manifest.get_capability('logs')
        assert logs is not None
        self.assertTrue(logs.hints['supports_histogram'])

    def test_graph_and_ops_log_extensions(self) -> None:
        self.assertEqual(
            {d.name for d in self.manifest.data_types},
            {'string', 'string_list', 'secret'},
        )
        self.assertEqual(
            [v.name for v in self.manifest.vertex_labels], ['AwsAccount']
        )
        self.assertEqual(
            [e.name for e in self.manifest.edge_labels], ['MAPS_TO']
        )
        self.assertEqual(
            set(self.manifest.ops_log_templates),
            {'set_value', 'delete_key'},
        )


class RegistryDiscoveryTestCase(unittest.TestCase):
    def test_convention_scan_loads_aws(self) -> None:
        from imbi_common.plugins import (
            get_capability,
            get_plugin,
            load_plugins,
        )

        result = load_plugins()
        self.assertIn('aws', result.loaded)
        self.assertEqual(result.errors, {})
        self.assertIs(get_plugin('aws').plugin_cls, AWSPlugin)
        self.assertIs(get_capability('aws', 'identity'), AWSIdentity)
        self.assertIs(get_capability('aws', 'logs'), CloudWatchLogs)
        self.assertIs(get_capability('aws', 'configuration'), SSMConfiguration)
