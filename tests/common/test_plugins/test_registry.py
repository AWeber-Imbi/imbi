import unittest
import unittest.mock

import pydantic

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


class LoadPluginsDeploymentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_registry()

    def test_load_deployment_plugin_round_trip(self) -> None:
        manifest = base.PluginManifest(
            slug='deploy',
            name='Deployment Plugin',
            plugin_type='deployment',
        )

        class _FakeDeploy(base.DeploymentPlugin):
            async def list_refs(  # type: ignore[override]
                self, ctx, credentials, kind='all', query=None
            ):
                return []

            async def list_commits(  # type: ignore[override]
                self, ctx, credentials, ref, limit=25
            ):
                return []

            async def resolve_committish(  # type: ignore[override]
                self, ctx, credentials, committish
            ):
                return base.Commit(sha='x', short_sha='x', message='')

            async def compare(  # type: ignore[override]
                self, ctx, credentials, base_, head
            ):
                return base.CompareResult(
                    base_sha=base_, head_sha=head, ahead=0, behind=0
                )

            async def trigger_deployment(  # type: ignore[override]
                self, ctx, credentials, ref_or_sha, inputs=None
            ):
                return base.DeploymentRun(run_id='1')

            async def get_deployment_status(  # type: ignore[override]
                self, ctx, credentials, run_id
            ):
                return base.DeploymentRun(run_id=run_id)

        _FakeDeploy.manifest = manifest  # type: ignore[attr-defined]

        ep = unittest.mock.MagicMock()
        ep.name = 'deploy'
        ep.load.return_value = _FakeDeploy
        ep.dist.name = 'imbi-plugin-deploy'
        ep.dist.version = '1.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertIn('deploy', result.loaded)
        entry = registry.get_plugin('deploy')
        self.assertIs(entry.handler_cls, _FakeDeploy)
        self.assertEqual(entry.manifest.plugin_type, 'deployment')

    def test_load_deployment_plugin_type_mismatch(self) -> None:
        manifest = base.PluginManifest(
            slug='mis-deploy',
            name='Mismatch',
            plugin_type='deployment',
        )

        class _ConfigImpl(base.ConfigurationPlugin):
            pass

        _ConfigImpl.manifest = manifest  # type: ignore[attr-defined]

        ep = unittest.mock.MagicMock()
        ep.name = 'mis-deploy'
        ep.load.return_value = _ConfigImpl
        ep.dist.name = 'pkg'
        ep.dist.version = '1.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertIn('mis-deploy', result.errors)
        self.assertEqual(result.loaded, [])

    def tearDown(self) -> None:
        _reset_registry()


class LoadPluginsLifecycleTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_registry()

    def test_load_lifecycle_plugin_round_trip(self) -> None:
        manifest = base.PluginManifest(
            slug='lifecycle',
            name='Lifecycle Plugin',
            plugin_type='lifecycle',
        )

        class _FakeLifecycle(base.LifecyclePlugin):
            async def on_project_archived(  # type: ignore[override]
                self, ctx, credentials
            ):
                return base.LifecycleResult(status='ok')

        _FakeLifecycle.manifest = manifest  # type: ignore[attr-defined]

        ep = unittest.mock.MagicMock()
        ep.name = 'lifecycle'
        ep.load.return_value = _FakeLifecycle
        ep.dist.name = 'imbi-plugin-lifecycle'
        ep.dist.version = '1.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertIn('lifecycle', result.loaded)
        entry = registry.get_plugin('lifecycle')
        self.assertIs(entry.handler_cls, _FakeLifecycle)
        self.assertEqual(entry.manifest.plugin_type, 'lifecycle')

    def test_load_lifecycle_plugin_type_mismatch(self) -> None:
        manifest = base.PluginManifest(
            slug='mis-lifecycle',
            name='Mismatch',
            plugin_type='lifecycle',
        )

        class _ConfigImpl(base.ConfigurationPlugin):
            pass

        _ConfigImpl.manifest = manifest  # type: ignore[attr-defined]

        ep = unittest.mock.MagicMock()
        ep.name = 'mis-lifecycle'
        ep.load.return_value = _ConfigImpl
        ep.dist.name = 'pkg'
        ep.dist.version = '1.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertIn('mis-lifecycle', result.errors)
        self.assertEqual(result.loaded, [])

    def tearDown(self) -> None:
        _reset_registry()


async def _sample_webhook_action(
    *, ctx, credentials, external_identifier, action_config, payload
):
    _ = (ctx, credentials, external_identifier, action_config, payload)


class _SampleWebhookConfig(pydantic.BaseModel):
    pass


_WEBHOOK_CALLABLE_PATH = (
    'tests.test_plugins.test_registry:_sample_webhook_action'
)
_WEBHOOK_CONFIG_PATH = 'tests.test_plugins.test_registry:_SampleWebhookConfig'


def _make_webhook_descriptor(name: str = 'do_thing') -> base.ActionDescriptor:
    return base.ActionDescriptor(
        name=name,
        label=name.replace('_', ' ').title(),
        callable=_WEBHOOK_CALLABLE_PATH,  # type: ignore[arg-type]
        config_model=_WEBHOOK_CONFIG_PATH,  # type: ignore[arg-type]
    )


def _make_webhook_plugin_cls(
    slug: str,
    descriptors: list[base.ActionDescriptor],
) -> type[base.WebhookActionPlugin]:
    manifest = base.PluginManifest(
        slug=slug,
        name='Hook Plugin',
        plugin_type='webhook',
        credentials=[
            base.CredentialField(name='api_token', label='API Token')
        ],
    )

    class _FakeWebhook(base.WebhookActionPlugin):
        @classmethod
        def actions(cls) -> list[base.ActionDescriptor]:
            return list(descriptors)

    _FakeWebhook.manifest = manifest  # type: ignore[attr-defined]
    return _FakeWebhook


class LoadPluginsWebhookTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_registry()

    def test_load_webhook_plugin_round_trip(self) -> None:
        cls = _make_webhook_plugin_cls(
            'hook', [_make_webhook_descriptor('do_thing')]
        )

        ep = unittest.mock.MagicMock()
        ep.name = 'hook'
        ep.load.return_value = cls
        ep.dist.name = 'imbi-plugin-hook'
        ep.dist.version = '1.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertIn('hook', result.loaded)
        entry = registry.get_plugin('hook')
        self.assertIs(entry.handler_cls, cls)
        self.assertEqual(entry.manifest.plugin_type, 'webhook')

    def test_load_webhook_plugin_type_mismatch(self) -> None:
        manifest = base.PluginManifest(
            slug='mis-hook',
            name='Mismatch',
            plugin_type='webhook',
        )

        class _ConfigImpl(base.ConfigurationPlugin):
            pass

        _ConfigImpl.manifest = manifest  # type: ignore[attr-defined]

        ep = unittest.mock.MagicMock()
        ep.name = 'mis-hook'
        ep.load.return_value = _ConfigImpl
        ep.dist.name = 'pkg'
        ep.dist.version = '1.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertIn('mis-hook', result.errors)
        self.assertEqual(result.loaded, [])

    def test_load_webhook_plugin_with_empty_catalog_warns_but_loads(
        self,
    ) -> None:
        cls = _make_webhook_plugin_cls('inert', [])

        ep = unittest.mock.MagicMock()
        ep.name = 'inert'
        ep.load.return_value = cls
        ep.dist.name = 'pkg'
        ep.dist.version = '1.0'

        with (
            unittest.mock.patch(
                'importlib.metadata.entry_points', return_value=[ep]
            ),
            self.assertLogs('imbi_common.plugins.registry', 'WARNING') as logs,
        ):
            result = registry.load_plugins()

        self.assertIn('inert', result.loaded)
        self.assertTrue(
            any('inert' in record.getMessage() for record in logs.records)
        )

    def test_load_webhook_plugin_duplicate_action_names_rejected(
        self,
    ) -> None:
        cls = _make_webhook_plugin_cls(
            'dup-action',
            [
                _make_webhook_descriptor('do_thing'),
                _make_webhook_descriptor('do_thing'),
            ],
        )

        ep = unittest.mock.MagicMock()
        ep.name = 'dup-action'
        ep.load.return_value = cls
        ep.dist.name = 'pkg'
        ep.dist.version = '1.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertEqual(result.loaded, [])
        self.assertIn('dup-action', result.errors)
        self.assertIn('Duplicate action', result.errors['dup-action'])

    def test_load_webhook_plugin_actions_raises_is_reported(self) -> None:
        manifest = base.PluginManifest(
            slug='broken',
            name='Broken',
            plugin_type='webhook',
        )

        class _BrokenWebhook(base.WebhookActionPlugin):
            @classmethod
            def actions(cls) -> list[base.ActionDescriptor]:
                raise RuntimeError('boom')

        _BrokenWebhook.manifest = manifest  # type: ignore[attr-defined]

        ep = unittest.mock.MagicMock()
        ep.name = 'broken'
        ep.load.return_value = _BrokenWebhook
        ep.dist.name = 'pkg'
        ep.dist.version = '1.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertEqual(result.loaded, [])
        self.assertIn('broken', result.errors)
        self.assertIn('actions() raised', result.errors['broken'])

    def test_load_webhook_plugin_actions_returns_non_list_rejected(
        self,
    ) -> None:
        manifest = base.PluginManifest(
            slug='not-list',
            name='Not List',
            plugin_type='webhook',
        )

        class _NotListWebhook(base.WebhookActionPlugin):
            @classmethod
            def actions(cls) -> list[base.ActionDescriptor]:
                return None  # type: ignore[return-value]

        _NotListWebhook.manifest = manifest  # type: ignore[attr-defined]

        ep = unittest.mock.MagicMock()
        ep.name = 'not-list'
        ep.load.return_value = _NotListWebhook
        ep.dist.name = 'pkg'
        ep.dist.version = '1.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertEqual(result.loaded, [])
        self.assertIn('not-list', result.errors)
        self.assertIn('list[ActionDescriptor]', result.errors['not-list'])

    def test_load_webhook_plugin_actions_returns_wrong_items_rejected(
        self,
    ) -> None:
        manifest = base.PluginManifest(
            slug='bad-items',
            name='Bad Items',
            plugin_type='webhook',
        )

        class _BadItemsWebhook(base.WebhookActionPlugin):
            @classmethod
            def actions(cls) -> list[base.ActionDescriptor]:
                return ['not a descriptor']  # type: ignore[list-item]

        _BadItemsWebhook.manifest = manifest  # type: ignore[attr-defined]

        ep = unittest.mock.MagicMock()
        ep.name = 'bad-items'
        ep.load.return_value = _BadItemsWebhook
        ep.dist.name = 'pkg'
        ep.dist.version = '1.0'

        with unittest.mock.patch(
            'importlib.metadata.entry_points', return_value=[ep]
        ):
            result = registry.load_plugins()

        self.assertEqual(result.loaded, [])
        self.assertIn('bad-items', result.errors)
        self.assertIn('list[ActionDescriptor]', result.errors['bad-items'])

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
