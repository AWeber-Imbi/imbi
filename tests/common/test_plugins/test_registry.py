import unittest
import unittest.mock

from imbi_common.plugins import base, registry
from imbi_common.plugins.errors import PluginNotFoundError


def _make_manifest(
    slug: str = 'test-plugin',
    api_version: int = 1,
) -> base.PluginManifest:
    return base.PluginManifest(
        slug=slug,
        name='Test Plugin',
        plugin_type='configuration',
        api_version=api_version,
    )


def _make_plugin_cls(
    slug: str = 'test-plugin',
    api_version: int = 1,
) -> type:
    manifest = _make_manifest(slug=slug, api_version=api_version)

    class _FakePlugin(base.ConfigurationPlugin):
        pass

    _FakePlugin.manifest = manifest  # type: ignore[attr-defined]
    return _FakePlugin


def _reset_registry() -> None:
    with unittest.mock.patch(
        'importlib.metadata.entry_points', return_value=[]
    ):
        registry.load_plugins()


class LoadPluginsEmptyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_registry()

    def test_load_plugins_empty(self) -> None:
        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[]
        ):
            result = registry.load_plugins()
        self.assertEqual(result.loaded, [])
        self.assertEqual(result.errors, {})
        self.assertEqual(result.skipped, [])

    def tearDown(self) -> None:
        _reset_registry()


class LoadPluginsUnsupportedVersionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_registry()

    def test_load_plugins_unsupported_api_version(self) -> None:
        cls = _make_plugin_cls(api_version=999)
        ep = unittest.mock.MagicMock()
        ep.name = 'test-plugin'
        ep.load.return_value = cls
        ep.dist.name = 'test-pkg'
        ep.dist.version = '1.0.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertIn('test-plugin', result.skipped)
        self.assertEqual(result.loaded, [])

    def tearDown(self) -> None:
        _reset_registry()


class LoadPluginsMissingManifestTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_registry()

    def test_load_plugins_missing_manifest(self) -> None:
        class _NoManifest:
            pass

        ep = unittest.mock.MagicMock()
        ep.name = 'bad-plugin'
        ep.load.return_value = _NoManifest

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertIn('bad-plugin', result.errors)
        self.assertEqual(result.loaded, [])

    def tearDown(self) -> None:
        _reset_registry()


class GetPluginNotFoundTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_registry()

    def test_get_plugin_not_found(self) -> None:
        with self.assertRaises(PluginNotFoundError):
            registry.get_plugin('nonexistent-slug')

    def tearDown(self) -> None:
        _reset_registry()


class ListPluginsEmptyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_registry()

    def test_list_plugins_empty(self) -> None:
        result = registry.list_plugins()
        self.assertEqual(result, [])

    def tearDown(self) -> None:
        _reset_registry()


class LoadPluginsBadInterfaceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_registry()

    def test_load_plugins_class_missing_interface(self) -> None:
        manifest = _make_manifest()

        class _NotAPlugin:
            pass

        _NotAPlugin.manifest = manifest  # type: ignore[attr-defined]

        ep = unittest.mock.MagicMock()
        ep.name = 'wrong-base'
        ep.load.return_value = _NotAPlugin
        ep.dist.name = 'pkg'
        ep.dist.version = '1.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertIn('wrong-base', result.errors)
        self.assertEqual(result.loaded, [])

    def test_load_plugins_plugin_type_mismatch(self) -> None:
        manifest = base.PluginManifest(
            slug='mismatch',
            name='Mismatch',
            plugin_type='logs',
            api_version=1,
        )

        class _ConfigOnly(base.ConfigurationPlugin):
            pass

        _ConfigOnly.manifest = manifest  # type: ignore[attr-defined]

        ep = unittest.mock.MagicMock()
        ep.name = 'mismatch'
        ep.load.return_value = _ConfigOnly
        ep.dist.name = 'pkg'
        ep.dist.version = '1.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertIn('mismatch', result.errors)
        self.assertEqual(result.loaded, [])

    def tearDown(self) -> None:
        _reset_registry()


class LoadPluginsIdentityTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_registry()

    def test_load_identity_plugin_round_trip(self) -> None:
        manifest = base.PluginManifest(
            slug='ident',
            name='Identity Plugin',
            plugin_type='identity',
            auth_type='oidc',
            login_capable=True,
        )

        class _FakeIdentity(base.IdentityPlugin):
            async def authorization_request(  # type: ignore[override]
                self, ctx, credentials, redirect_uri, scopes=None
            ):
                raise NotImplementedError

            async def exchange_code(  # type: ignore[override]
                self,
                ctx,
                credentials,
                code,
                redirect_uri,
                code_verifier=None,
            ):
                raise NotImplementedError

            async def refresh(  # type: ignore[override]
                self, ctx, credentials, refresh_token
            ):
                raise NotImplementedError

        _FakeIdentity.manifest = manifest  # type: ignore[attr-defined]

        ep = unittest.mock.MagicMock()
        ep.name = 'ident'
        ep.load.return_value = _FakeIdentity
        ep.dist.name = 'imbi-plugin-ident'
        ep.dist.version = '1.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertIn('ident', result.loaded)
        entry = registry.get_plugin('ident')
        self.assertIs(entry.handler_cls, _FakeIdentity)
        self.assertEqual(entry.manifest.plugin_type, 'identity')
        self.assertEqual(entry.manifest.auth_type, 'oidc')
        self.assertTrue(entry.manifest.login_capable)

    def test_load_identity_plugin_type_mismatch(self) -> None:
        manifest = base.PluginManifest(
            slug='mis',
            name='Mismatch',
            plugin_type='identity',
        )

        class _ConfigImpl(base.ConfigurationPlugin):
            pass

        _ConfigImpl.manifest = manifest  # type: ignore[attr-defined]

        ep = unittest.mock.MagicMock()
        ep.name = 'mis'
        ep.load.return_value = _ConfigImpl
        ep.dist.name = 'pkg'
        ep.dist.version = '1.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertIn('mis', result.errors)
        self.assertEqual(result.loaded, [])

    def tearDown(self) -> None:
        _reset_registry()


class LoadPluginsDuplicateSlugTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_registry()

    def test_load_plugins_duplicate_slug_skipped(self) -> None:
        cls_a = _make_plugin_cls(slug='dup')
        cls_b = _make_plugin_cls(slug='dup')

        ep_a = unittest.mock.MagicMock()
        ep_a.name = 'dup-a'
        ep_a.load.return_value = cls_a
        ep_a.dist.name = 'pkg-a'
        ep_a.dist.version = '1.0'

        ep_b = unittest.mock.MagicMock()
        ep_b.name = 'dup-b'
        ep_b.load.return_value = cls_b
        ep_b.dist.name = 'pkg-b'
        ep_b.dist.version = '1.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points',
            return_value=[ep_a, ep_b],
        ):
            result = registry.load_plugins()

        self.assertEqual(result.loaded, ['dup'])
        self.assertIn('dup-b', result.errors)
        self.assertIn('Duplicate plugin slug', result.errors['dup-b'])

    def tearDown(self) -> None:
        _reset_registry()
