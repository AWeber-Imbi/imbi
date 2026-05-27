# Plugins

Base classes, registry, errors, and template helpers for the Imbi
plugin system. Plugin authors should pair this reference with the
[Authoring Plugins](../guides/plugins.md) guide, which explains the
plugin variations and the contract each must satisfy.

## Manifest and Context

::: imbi_common.plugins.PluginManifest

::: imbi_common.plugins.PluginOption

::: imbi_common.plugins.CredentialField

::: imbi_common.plugins.DataType

::: imbi_common.plugins.PluginContext

::: imbi_common.plugins.RepositoryRelocation

## Configuration Plugins

The `configuration` variation models a typed key/value store scoped to
a project. Implementations subclass `ConfigurationPlugin` and declare
`plugin_type='configuration'` in their manifest.

::: imbi_common.plugins.ConfigurationPlugin

::: imbi_common.plugins.ConfigKey

::: imbi_common.plugins.ConfigKeyWithValue

::: imbi_common.plugins.ConfigValue

## Logs Plugins

The `logs` variation exposes a search interface against an external log
store. Implementations subclass `LogsPlugin` and declare
`plugin_type='logs'` in their manifest.

::: imbi_common.plugins.LogsPlugin

::: imbi_common.plugins.LogQuery

::: imbi_common.plugins.LogFilter

::: imbi_common.plugins.LogEntry

::: imbi_common.plugins.LogResult

::: imbi_common.plugins.LogHistogramBucket

## Webhook Action Plugins

The `webhook` variation reacts to inbound webhook payloads routed by a
host such as `imbi-gateway`. Implementations subclass
`WebhookActionPlugin` and declare `plugin_type='webhook'` in their
manifest. The host parses the `WebhookRule.handler` field as
`"<plugin_slug>:<action_name>"`, fetches per-instance credentials via
`get_plugin_credentials` (see below),
and dispatches by calling `run_action`.

::: imbi_common.plugins.WebhookActionPlugin

## Credential Resolution

Helpers for hosts that need to fetch decrypted plugin credentials out
of the graph. Routing depends on `manifest.auth_type`: `api_token` and
`aws-iam-ic` read the Fernet-encrypted `Plugin.plugin_configuration`
blob directly, while `oauth2` and `oidc` walk
`Plugin -[:USES_APPLICATION]-> ServiceApplication`.

::: imbi_common.plugins.get_plugin_credentials

::: imbi_common.plugins.get_plugin_configuration_keys

::: imbi_common.plugins.patch_plugin_configuration

## Registry

Plugin discovery is driven by `importlib.metadata` entry points under
the `imbi.plugins` group. The host calls `load_plugins()` at startup
(and `reload_plugins()` on demand) to populate the registry.

::: imbi_common.plugins.load_plugins

::: imbi_common.plugins.reload_plugins

::: imbi_common.plugins.get_plugin

::: imbi_common.plugins.list_plugins

::: imbi_common.plugins.RegistryEntry

::: imbi_common.plugins.LoadResult

## Errors

::: imbi_common.plugins.PluginNotFoundError

::: imbi_common.plugins.PluginUnavailableError

::: imbi_common.plugins.PluginCredentialsMissing

::: imbi_common.plugins.PluginTimeoutError

::: imbi_common.plugins.CursorExpiredError

## Templates

Helpers for plugins that build provider-specific query strings from
project context. Substitution is restricted to a fixed whitelist of
variables (`project_slug`, `org_slug`, `environment`, `project_id`);
unknown variables raise `ValueError`.

::: imbi_common.plugins.validate_template

::: imbi_common.plugins.expand_template
