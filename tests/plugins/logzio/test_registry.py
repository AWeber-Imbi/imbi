"""Manifest declaration and convention-based discovery (v3)."""

from imbi_common.plugins import (
    LogsCapability,
    Plugin,
    load_plugins,
)

import imbi_plugin_logzio
from imbi_plugin_logzio.plugin import LogzioLogs, LogzioPlugin


def test_module_exposes_plugin_attr() -> None:
    assert imbi_plugin_logzio.PLUGIN is LogzioPlugin


def test_plugin_is_plugin_subclass() -> None:
    assert issubclass(LogzioPlugin, Plugin)


def test_manifest_slug() -> None:
    assert LogzioPlugin.manifest.slug == 'logzio'


def test_manifest_api_version() -> None:
    assert LogzioPlugin.manifest.api_version == 2


def test_manifest_auth_type() -> None:
    assert LogzioPlugin.manifest.auth_type == 'api_token'


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


def test_manifest_timeout_is_integration_option() -> None:
    names = [o.name for o in LogzioPlugin.manifest.options]
    assert 'timeout_seconds' in names


def test_manifest_single_logs_capability() -> None:
    kinds = [c.kind for c in LogzioPlugin.manifest.capabilities]
    assert kinds == ['logs']


def test_logs_capability_handler() -> None:
    capability = LogzioPlugin.manifest.get_capability('logs')
    assert capability is not None
    assert capability.handler is LogzioLogs
    assert issubclass(capability.handler, LogsCapability)


def test_logs_capability_hints() -> None:
    capability = LogzioPlugin.manifest.get_capability('logs')
    assert capability is not None
    assert capability.hints['supports_histogram'] is True
    assert capability.hints['cacheable'] is False


def test_logs_capability_options() -> None:
    capability = LogzioPlugin.manifest.get_capability('logs')
    assert capability is not None
    names = {o.name for o in capability.options}
    assert {
        'base_query',
        'timestamp_field',
        'message_field',
        'level_field',
        'environment_field',
        'default_environments',
    } <= names


def test_load_via_convention_scan() -> None:
    result = load_plugins()
    assert 'logzio' in result.loaded
    assert 'logzio' not in result.errors
