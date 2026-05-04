"""Plugin system — base classes, registry, and template expansion."""

from imbi_common.plugins.base import (
    ConfigKey,
    ConfigKeyWithValue,
    ConfigurationPlugin,
    ConfigValue,
    CredentialField,
    DataType,
    LogEntry,
    LogFilter,
    LogQuery,
    LogResult,
    LogsPlugin,
    PluginContext,
    PluginManifest,
    PluginOption,
)
from imbi_common.plugins.errors import (
    CursorExpiredError,
    PluginCredentialsMissing,
    PluginNotFoundError,
    PluginTimeoutError,
    PluginUnavailableError,
)
from imbi_common.plugins.registry import (
    LoadResult,
    RegistryEntry,
    get_plugin,
    list_plugins,
    load_plugins,
    reload_plugins,
)
from imbi_common.plugins.templates import expand_template, validate_template

__all__ = [
    'ConfigKey',
    'ConfigKeyWithValue',
    'ConfigValue',
    'ConfigurationPlugin',
    'CredentialField',
    'CursorExpiredError',
    'DataType',
    'LoadResult',
    'LogEntry',
    'LogFilter',
    'LogQuery',
    'LogResult',
    'LogsPlugin',
    'PluginContext',
    'PluginCredentialsMissing',
    'PluginManifest',
    'PluginNotFoundError',
    'PluginOption',
    'PluginTimeoutError',
    'PluginUnavailableError',
    'RegistryEntry',
    'expand_template',
    'get_plugin',
    'list_plugins',
    'load_plugins',
    'reload_plugins',
    'validate_template',
]
