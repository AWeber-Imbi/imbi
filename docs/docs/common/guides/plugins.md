# Authoring Plugins

Imbi plugins extend the platform with integrations against third-party
services. A plugin is an installable Python distribution that exposes a
handler class through the `imbi.plugins` entry point group. The host
service (`imbi-api`) discovers, validates, and instantiates plugins at
runtime; plugins themselves carry no global state and receive everything
they need — context, credentials, and options — on every call.

This guide walks through the two plugin variations supported by the v1
API and the contract each must satisfy.

## Plugin Variations

`PluginManifest.plugin_type` selects the variation. Two values are
defined today:

| `plugin_type`   | Base class             | Purpose                                                                                       |
| --------------- | ---------------------- | --------------------------------------------------------------------------------------------- |
| `configuration` | `ConfigurationPlugin`  | List, read, write, and delete typed configuration keys for a project (e.g. feature flags, secrets) |
| `logs`          | `LogsPlugin`           | Search log entries and describe the available query schema for a project                      |

The class hierarchy and `plugin_type` must agree — a class that subclasses
`ConfigurationPlugin` declared with `plugin_type='logs'` is rejected at
load time, and vice versa.

## Anatomy of a Plugin Package

A minimum plugin distribution contains:

1. A handler class subclassing one of the two base classes.
2. A class-level `manifest: PluginManifest` describing slug, name,
   options, credential fields, and (for configuration plugins) the data
   types it understands.
3. An `imbi.plugins` entry point in the package metadata pointing at the
   handler class.

A trimmed `pyproject.toml`:

```toml
[project]
name = "imbi-plugin-vault"
version = "0.1.0"
dependencies = ["imbi-common>=2.0", "httpx"]

[project.entry-points."imbi.plugins"]
vault = "imbi_plugin_vault.plugin:VaultPlugin"
```

The entry-point name is informational — the canonical identifier is
`manifest.slug`. Two plugins with the same slug cannot coexist; the
second is dropped with an error during load.

## The Manifest

```python
from imbi_common.plugins import (
    CredentialField,
    DataType,
    PluginManifest,
    PluginOption,
)

manifest = PluginManifest(
    slug='vault',
    name='HashiCorp Vault',
    description='Read and write project secrets stored in Vault.',
    plugin_type='configuration',
    api_version=1,
    cacheable=False,
    options=[
        PluginOption(
            name='mount_path',
            label='Mount Path',
            type='string',
            required=True,
            default='secret',
        ),
        PluginOption(
            name='kv_version',
            label='KV Engine Version',
            type='string',
            choices=['1', '2'],
            default='2',
        ),
    ],
    credentials=[
        CredentialField(
            name='token',
            label='Vault Token',
            description='Vault token with read/write on the mount.',
        ),
    ],
    data_types=[
        DataType(name='string', label='String'),
        DataType(name='secret', label='Secret', secret=True),
    ],
)
```

Notes:

- **`api_version`** must be an integer the host advertises as supported.
  Today only `1` is accepted; plugins declaring other versions are
  skipped and reported as such, *not* errored.
- **`cacheable`** is a hint to the host — set `False` for plugins whose
  reads must always be live (token-based providers, audit-sensitive
  systems).
- **`options`** are configured at assignment time and are validated
  against the `PluginOption` schema. Choices, defaults, and the four
  scalar types (`string`, `integer`, `boolean`, `secret`) are enforced
  by the host UI; plugin code receives the resolved values via
  `PluginContext.assignment_options`.
- **`credentials`** describe what the host must collect for a service
  application using this plugin. Values are encrypted at rest on
  `ServiceApplication.encrypted_credentials` and are decrypted into the
  `credentials` dict the host passes to each call.
- **`data_types`** apply only to configuration plugins. They tell the
  host which `ConfigValue.data_type` strings are valid, and which
  represent secret material (and therefore should be redacted in UI and
  audit logs).

## Variation 1: Configuration Plugins

`ConfigurationPlugin` is the abstract base for integrations that present
a typed key/value store scoped to a project. All four methods receive a
`PluginContext` (project identity + assignment options) and a
`credentials` dict resolved from the linked `ServiceApplication`.

```python
from imbi_common.plugins import (
    ConfigKey,
    ConfigKeyWithValue,
    ConfigurationPlugin,
    ConfigValue,
    PluginContext,
)


class VaultPlugin(ConfigurationPlugin):
    manifest = manifest  # the PluginManifest defined above

    async def list_keys(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[ConfigKey]:
        ...

    async def get_values(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        keys: list[str] | None = None,
    ) -> list[ConfigKeyWithValue]:
        ...

    async def set_value(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        key: str,
        value: ConfigValue,
    ) -> ConfigKey:
        ...

    async def delete_key(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        key: str,
    ) -> None:
        ...
```

Method contracts:

- **`list_keys`** — return every key visible to the project. Do not
  inline values; use `get_values` for that. Populate `last_modified`
  when the upstream system exposes it.
- **`get_values`** — when `keys is None`, return values for every
  visible key (mirroring `list_keys`); otherwise return only the
  requested subset. Missing keys should be omitted, not raised.
- **`set_value`** — create or update. The returned `ConfigKey` should
  reflect the persisted state, including `last_modified`.
- **`delete_key`** — idempotent; deleting an absent key should not
  raise.

Mark a `ConfigKey`/`ConfigKeyWithValue` as `secret=True` when the key's
data type is one of the manifest's secret types. The host uses this to
gate read access and to redact values in UI and logs.

## Variation 2: Logs Plugins

`LogsPlugin` is the abstract base for log-search integrations. It has
two methods: a query-time `search` and a one-shot `schema` describing
the queryable fields.

```python
from imbi_common.plugins import (
    LogQuery,
    LogResult,
    LogsPlugin,
    PluginContext,
)


class LokiPlugin(LogsPlugin):
    manifest = manifest  # plugin_type='logs'

    async def search(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        query: LogQuery,
    ) -> LogResult:
        ...

    async def schema(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[dict]:
        ...
```

Method contracts:

- **`search`** — return a `LogResult` with `entries` ordered most-recent
  first. Honor `query.limit` and `query.cursor`. When more results are
  available, populate `next_cursor` with an opaque token the upstream
  system can decode on the next call. If a cursor has expired or become
  invalid, raise
  [`CursorExpiredError`][imbi_common.plugins.errors.CursorExpiredError]
  rather than silently returning empty results.
- **`schema`** — return a list of field descriptors. The shape is
  intentionally loose (`list[dict]`) so plugins can surface vendor-
  specific metadata; at minimum include a `name` and a human-readable
  `label` for each field exposed to filters.

`LogQuery.filters` are `(field, op, value)` triples with five operators
(`eq`, `ne`, `contains`, `starts_with`, `regex`). Translate them into
the upstream provider's query language; raise a domain-appropriate
exception if a filter cannot be satisfied so the host can surface a
clear error.

## Search Templates

For plugins that build provider-specific query strings from project
context, use `expand_template`. It substitutes only the whitelisted
variables `project_slug`, `org_slug`, `environment`, and `project_id`,
and rejects anything else:

```python
from imbi_common.plugins import expand_template

label_query = expand_template(
    template,
    {
        'project_slug': ctx.project_slug,
        'org_slug': ctx.org_slug,
        'environment': ctx.environment,
        'project_id': ctx.project_id,
    },
)
```

Validate templates at assignment time with `validate_template` so
configuration errors surface early instead of during a search.

## Errors

Plugins should raise exceptions from `imbi_common.plugins.errors` when
the failure mode maps onto one of them; otherwise let the host wrap the
exception. The relevant ones for plugin authors are:

| Exception                  | When to raise                                                                  |
| -------------------------- | ------------------------------------------------------------------------------ |
| `PluginCredentialsMissing` | A required credential is absent or empty in the `credentials` dict.            |
| `PluginTimeoutError`       | An upstream call exceeded the plugin's internal timeout budget.                |
| `PluginUnavailableError`   | The upstream service is reachable but cannot serve the request (degraded, locked). |
| `CursorExpiredError`       | A logs `query.cursor` is no longer valid and the caller must restart paging.   |

`PluginNotFoundError` is host-side only — plugin code should not raise it.

## Lifecycle and State

A new handler instance is created **per request**. Do not stash
connection state, cached credentials, or per-project data on
`self`. If you need a connection pool or rate-limited HTTP client,
construct it inside the method, scoped to the call:

```python
async def list_keys(self, ctx, credentials):
    async with httpx.AsyncClient(timeout=10.0) as client:
        ...
```

The host treats `manifest` as immutable once registered; do not mutate
it at runtime.

## Testing

Plugins can be unit-tested in isolation. The host machinery is
straightforward to fake — instantiate the plugin class directly and
call its methods with synthesized `PluginContext` objects and a
credentials dict. For registry-level integration tests, see
`tests/test_plugins/test_registry.py` in this repository for examples
of mocking `importlib.metadata.entry_points` to inject a plugin without
having to install a real distribution.

## Related Reference

- [Plugins API reference](../api/plugins.md) — generated signatures and
  field-level documentation for every public class and function in
  `imbi_common.plugins`.
