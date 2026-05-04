"""Registry integration: verify the plugin loads cleanly via entry points."""

from unittest.mock import MagicMock, patch

from imbi_common.plugins import LogsPlugin, load_plugins

from imbi_plugin_logzio.plugin import LogzioPlugin


def _make_mock_ep(
    name: str = 'logzio',
    cls: type = LogzioPlugin,
    dist_name: str = 'imbi-plugin-logzio',
    dist_version: str = '0.1.0',
) -> MagicMock:
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = cls
    dist = MagicMock()
    dist.name = dist_name
    dist.version = dist_version
    ep.dist = dist
    return ep


def test_plugin_is_logs_plugin_subclass() -> None:
    assert issubclass(LogzioPlugin, LogsPlugin)


def test_manifest_slug() -> None:
    assert LogzioPlugin.manifest.slug == 'logzio'


def test_manifest_plugin_type() -> None:
    assert LogzioPlugin.manifest.plugin_type == 'logs'


def test_manifest_api_version() -> None:
    assert LogzioPlugin.manifest.api_version == 1


def test_manifest_has_api_token_credential() -> None:
    names = [c.name for c in LogzioPlugin.manifest.credentials]
    assert 'api_token' in names


def test_manifest_has_region_option() -> None:
    names = [o.name for o in LogzioPlugin.manifest.options]
    assert 'region' in names


def test_manifest_region_choices() -> None:
    region_opt = next(
        o for o in LogzioPlugin.manifest.options if o.name == 'region'
    )
    assert region_opt.choices == ['us', 'eu', 'uk', 'au', 'ca']
    assert region_opt.default == 'us'


def test_manifest_not_cacheable() -> None:
    assert LogzioPlugin.manifest.cacheable is False


def test_load_via_entry_points() -> None:
    ep = _make_mock_ep()
    with patch('importlib.metadata.entry_points', return_value=[ep]):
        result = load_plugins()
    assert 'logzio' in result.loaded
    assert not result.errors


def test_load_wrong_base_class_rejected() -> None:
    class NotAPlugin:
        manifest = LogzioPlugin.manifest

    ep = _make_mock_ep(cls=NotAPlugin)  # type: ignore[arg-type]
    with patch('importlib.metadata.entry_points', return_value=[ep]):
        result = load_plugins()
    assert 'logzio' not in result.loaded
    assert result.errors


def test_load_unsupported_api_version_skipped() -> None:
    from imbi_common.plugins.base import PluginManifest

    class FuturePlugin(LogsPlugin):
        manifest = PluginManifest(
            slug='logzio',
            name='Logz.io',
            plugin_type='logs',
            api_version=99,
        )

        async def search(self, ctx, credentials, query):  # type: ignore[override]
            ...

        async def schema(self, ctx, credentials):  # type: ignore[override]
            ...

    ep = _make_mock_ep(cls=FuturePlugin)
    with patch('importlib.metadata.entry_points', return_value=[ep]):
        result = load_plugins()
    assert 'logzio' not in result.loaded
    assert 'logzio' in result.skipped
