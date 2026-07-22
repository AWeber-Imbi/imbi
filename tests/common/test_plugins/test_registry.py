"""Tests for imbi.common.plugins.registry (v3 convention + contract)."""

import contextlib
import unittest
import unittest.mock

from imbi.common.plugins import base, registry
from imbi.common.plugins.errors import (
    PluginNotFoundError,
    PluginSchemaCollisionError,
)
from tests.common.test_plugins.fixtures.good_plugin import (
    FixtureConfiguration,
    GoodPlugin,
)

_FIX = 'tests.common.test_plugins.fixtures'


@contextlib.contextmanager
def _discovery(
    convention: dict[str, str] | None = None,
    imbi_plugins: list[str] | None = None,
    first_party: dict[str, str] | None = None,
    disabled: list[str] | None = None,
):
    """Patch the discovery scans + the IMBI_PLUGINS* settings."""
    plugins_settings = unittest.mock.MagicMock()
    plugins_settings.return_value.imbi_plugins = imbi_plugins or []
    plugins_settings.return_value.imbi_plugins_disabled = disabled or []
    with (
        unittest.mock.patch.object(
            registry,
            '_discover_first_party',
            return_value=first_party or {},
        ),
        unittest.mock.patch.object(
            registry,
            '_discover_convention',
            return_value=convention or {},
        ),
        unittest.mock.patch('imbi.common.settings.Plugins', plugins_settings),
    ):
        yield


def _reset_registry() -> None:
    with _discovery():
        registry.load_plugins()


class RegistryTestBase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_registry()

    def tearDown(self) -> None:
        _reset_registry()


class EmptyLoadTestCase(RegistryTestBase):
    def test_load_plugins_empty(self) -> None:
        with _discovery():
            result = registry.load_plugins()
        self.assertEqual(result.loaded, [])
        self.assertEqual(result.errors, {})
        self.assertEqual(result.skipped, [])
        self.assertEqual(registry.list_plugins(), [])


class ConventionDiscoveryTestCase(RegistryTestBase):
    def test_convention_scan_loads_plugin(self) -> None:
        with _discovery(
            convention={f'{_FIX}.good_plugin': 'imbi_plugin_good'}
        ):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, ['good'])
        self.assertEqual(result.errors, {})
        entry = registry.get_plugin('good')
        self.assertIs(entry.plugin_cls, GoodPlugin)
        self.assertEqual(entry.manifest.slug, 'good')

    def test_get_capability_returns_handler(self) -> None:
        with _discovery(
            convention={f'{_FIX}.good_plugin': 'imbi_plugin_good'}
        ):
            registry.load_plugins()
        handler = registry.get_capability('good', 'configuration')
        self.assertIs(handler, FixtureConfiguration)

    def test_get_capability_unknown_kind_raises(self) -> None:
        with _discovery(
            convention={f'{_FIX}.good_plugin': 'imbi_plugin_good'}
        ):
            registry.load_plugins()
        with self.assertRaises(PluginNotFoundError):
            registry.get_capability('good', 'logs')

    def test_missing_plugin_attr_is_error(self) -> None:
        with _discovery(
            convention={f'{_FIX}.no_plugin_attr': 'imbi_plugin_bad'}
        ):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, [])
        self.assertIn('imbi_plugin_bad', result.errors)
        self.assertIn('PLUGIN', result.errors['imbi_plugin_bad'])

    def test_not_a_plugin_subclass_is_error(self) -> None:
        with _discovery(
            convention={f'{_FIX}.not_a_plugin': 'imbi_plugin_notplugin'}
        ):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, [])
        self.assertIn(
            'not a Plugin subclass',
            result.errors['imbi_plugin_notplugin'],
        )

    def test_bad_api_version_skipped(self) -> None:
        with _discovery(
            convention={f'{_FIX}.bad_version': 'imbi_plugin_badver'}
        ):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, [])
        self.assertIn('imbi_plugin_badver', result.skipped)

    def test_import_failure_reported(self) -> None:
        with _discovery(
            convention={f'{_FIX}.does_not_exist': 'imbi_plugin_missing'}
        ):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, [])
        self.assertIn('imbi_plugin_missing', result.errors)


class FirstPartyDiscoveryTestCase(RegistryTestBase):
    def test_first_party_scan_loads_plugin(self) -> None:
        with _discovery(
            first_party={f'{_FIX}.good_plugin': 'imbi.plugins.good'}
        ):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, ['good'])
        self.assertEqual(result.errors, {})
        entry = registry.get_plugin('good')
        self.assertIs(entry.plugin_cls, GoodPlugin)

    def test_missing_optional_dependency_is_skipped(self) -> None:
        with _discovery(
            first_party={f'{_FIX}.does_not_exist': 'imbi.plugins.missing'}
        ):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, [])
        self.assertEqual(result.errors, {})
        self.assertIn('imbi.plugins.missing', result.skipped)

    def test_missing_plugin_attr_is_error(self) -> None:
        with _discovery(
            first_party={f'{_FIX}.no_plugin_attr': 'imbi.plugins.bad'}
        ):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, [])
        self.assertIn('imbi.plugins.bad', result.errors)
        self.assertIn('PLUGIN', result.errors['imbi.plugins.bad'])

    def test_disabled_slug_is_skipped(self) -> None:
        with _discovery(
            first_party={f'{_FIX}.good_plugin': 'imbi.plugins.good'},
            disabled=['good'],
        ):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, [])
        self.assertEqual(result.errors, {})
        self.assertIn('imbi.plugins.good', result.skipped)
        with self.assertRaises(PluginNotFoundError):
            registry.get_plugin('good')

    def test_disabled_applies_to_convention_scan(self) -> None:
        with _discovery(
            convention={f'{_FIX}.good_plugin': 'imbi_plugin_good'},
            disabled=['good'],
        ):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, [])
        self.assertIn('imbi_plugin_good', result.skipped)

    def test_real_first_party_discovery_finds_shipped_plugins(self) -> None:
        discovered = registry._discover_first_party()
        for name in ('aws', 'github', 'sonarqube'):
            self.assertIn(f'imbi.plugins.{name}', discovered)


class ExplicitDiscoveryTestCase(RegistryTestBase):
    def test_imbi_plugins_setting_loads_plugin(self) -> None:
        with _discovery(imbi_plugins=[f'{_FIX}.good_plugin:ExplicitPlugin']):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, ['good'])
        self.assertIs(registry.get_plugin('good').plugin_cls, GoodPlugin)

    def test_bad_dotted_path_reported(self) -> None:
        with _discovery(imbi_plugins=['no-colon-here']):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, [])
        self.assertIn('no-colon-here', result.errors)

    def test_missing_attr_reported(self) -> None:
        with _discovery(imbi_plugins=[f'{_FIX}.good_plugin:Nope']):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, [])
        self.assertIn(f'{_FIX}.good_plugin:Nope', result.errors)

    def test_union_dedupes_same_class(self) -> None:
        with _discovery(
            convention={f'{_FIX}.good_plugin': 'imbi_plugin_good'},
            imbi_plugins=[f'{_FIX}.good_plugin:ExplicitPlugin'],
        ):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, ['good'])


class DuplicateSlugTestCase(RegistryTestBase):
    def test_duplicate_slug_rejected(self) -> None:
        with _discovery(
            convention={
                f'{_FIX}.good_plugin': 'imbi_plugin_good',
                f'{_FIX}.dup_plugin': 'imbi_plugin_dup',
            }
        ):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, ['good'])
        self.assertIn('imbi_plugin_dup', result.errors)
        self.assertIn(
            'duplicate plugin slug', result.errors['imbi_plugin_dup']
        )


class ContractRecheckTestCase(RegistryTestBase):
    """A hand-built manifest that bypassed the Capability validator (via
    ``model_construct``) is still rejected by the registry re-check."""

    def test_registry_rechecks_handler_contract(self) -> None:
        bad_capability = base.Capability.model_construct(
            kind='logs',
            label='Bad',
            handler=FixtureConfiguration,  # wrong contract for 'logs'
            hints={},
            options=[],
        )
        manifest = base.PluginManifest.model_construct(
            slug='bypass',
            name='Bypass',
            api_version=2,
            capabilities=[bad_capability],
            options=[],
            credentials=[],
            data_types=[],
            vertex_labels=[],
            edge_labels=[],
            ops_log_templates={},
        )

        class BypassPlugin(base.Plugin):
            pass

        BypassPlugin.manifest = manifest

        with _discovery():
            with unittest.mock.patch.object(
                registry,
                '_discover_convention',
                return_value={'m': 'imbi_plugin_bypass'},
            ):
                with unittest.mock.patch.object(
                    registry,
                    '_load_convention_plugin',
                    return_value=BypassPlugin,
                ):
                    result = registry.load_plugins()
        self.assertEqual(result.loaded, [])
        self.assertIn('imbi_plugin_bypass', result.errors)
        self.assertIn('does not subclass', result.errors['imbi_plugin_bypass'])


class WebhookCatalogTestCase(RegistryTestBase):
    def _load_webhook(self, handler: type) -> registry.LoadResult:
        class HookConfig(base.Plugin):
            manifest = base.PluginManifest(
                slug='hook',
                name='Hook',
                capabilities=[
                    base.Capability(
                        kind='webhook-actions',
                        label='Webhook Actions',
                        handler=handler,
                    )
                ],
            )

        with _discovery():
            with unittest.mock.patch.object(
                registry,
                '_discover_convention',
                return_value={'m': 'imbi_plugin_hook'},
            ):
                with unittest.mock.patch.object(
                    registry,
                    '_load_convention_plugin',
                    return_value=HookConfig,
                ):
                    return registry.load_plugins()

    def test_duplicate_action_names_rejected(self) -> None:
        from tests.common.test_plugins.fixtures.good_plugin import (
            SampleActionConfig,
            sample_action,
        )

        def _descriptor(name: str) -> base.ActionDescriptor:
            return base.ActionDescriptor(
                name=name,
                label=name,
                callable=sample_action,  # type: ignore[arg-type]
                config_model=SampleActionConfig,  # type: ignore[arg-type]
            )

        class DupActions(base.WebhookActionsCapability):
            @classmethod
            def actions(cls):
                return [_descriptor('do_thing'), _descriptor('do_thing')]

        result = self._load_webhook(DupActions)
        self.assertEqual(result.loaded, [])
        self.assertIn('imbi_plugin_hook', result.errors)
        self.assertIn('Duplicate action', result.errors['imbi_plugin_hook'])

    def test_empty_catalog_warns_but_loads(self) -> None:
        class EmptyActions(base.WebhookActionsCapability):
            @classmethod
            def actions(cls):
                return []

        with self.assertLogs('imbi.common.plugins.registry', 'WARNING'):
            result = self._load_webhook(EmptyActions)
        self.assertEqual(result.loaded, ['hook'])

    def test_actions_raises_reported(self) -> None:
        class BoomActions(base.WebhookActionsCapability):
            @classmethod
            def actions(cls):
                raise RuntimeError('boom')

        result = self._load_webhook(BoomActions)
        self.assertEqual(result.loaded, [])
        self.assertIn('actions() raised', result.errors['imbi_plugin_hook'])


class ToolsCatalogTestCase(RegistryTestBase):
    def test_duplicate_tool_names_rejected(self) -> None:
        from tests.common.test_plugins.fixtures.good_plugin import (
            sample_action,
        )

        def _tool(name: str) -> base.ToolDescriptor:
            return base.ToolDescriptor(
                name=name,
                description=name,
                callable=sample_action,  # type: ignore[arg-type]
            )

        class DupTools(base.ToolsCapability):
            @classmethod
            def tools(cls):
                return [_tool('do_thing'), _tool('do_thing')]

        class ToolsPlugin(base.Plugin):
            manifest = base.PluginManifest(
                slug='tools',
                name='Tools',
                capabilities=[
                    base.Capability(
                        kind='tools', label='Tools', handler=DupTools
                    )
                ],
            )

        with _discovery():
            with unittest.mock.patch.object(
                registry,
                '_discover_convention',
                return_value={'m': 'imbi_plugin_tools'},
            ):
                with unittest.mock.patch.object(
                    registry,
                    '_load_convention_plugin',
                    return_value=ToolsPlugin,
                ):
                    result = registry.load_plugins()
        self.assertEqual(result.loaded, [])
        self.assertIn('Duplicate tool', result.errors['imbi_plugin_tools'])


class CollisionTestCase(RegistryTestBase):
    def test_vlabel_collision_across_plugins_raises(self) -> None:
        def _make(slug: str) -> type[base.Plugin]:
            class _P(base.Plugin):
                manifest = base.PluginManifest(
                    slug=slug,
                    name=slug,
                    vertex_labels=[
                        base.PluginVertexLabel(
                            name='Collide', model_ref=f'{slug}:Collide'
                        )
                    ],
                    capabilities=[
                        base.Capability(
                            kind='configuration',
                            label='Config',
                            handler=FixtureConfiguration,
                        )
                    ],
                )

            return _P

        plugins = {'a': _make('a'), 'b': _make('b')}

        def _loader(module_name: str) -> type[base.Plugin]:
            return plugins[module_name]

        with _discovery():
            with unittest.mock.patch.object(
                registry,
                '_discover_convention',
                return_value={'a': 'imbi_plugin_a', 'b': 'imbi_plugin_b'},
            ):
                with unittest.mock.patch.object(
                    registry, '_load_convention_plugin', side_effect=_loader
                ):
                    with self.assertRaises(PluginSchemaCollisionError):
                        registry.load_plugins()


class ReloadTestCase(RegistryTestBase):
    def test_reload_delegates_to_load(self) -> None:
        with _discovery(
            convention={f'{_FIX}.good_plugin': 'imbi_plugin_good'}
        ):
            result = registry.reload_plugins()
        self.assertEqual(result.loaded, ['good'])


class GetPluginNotFoundTestCase(RegistryTestBase):
    def test_get_plugin_not_found(self) -> None:
        with self.assertRaises(PluginNotFoundError):
            registry.get_plugin('nonexistent')
