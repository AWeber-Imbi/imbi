# Configuration Plugins

`ConfigurationPlugin` is the abstract base for integrations that present
a typed key/value store scoped to a project (feature flags, secrets,
service settings). Declare `plugin_type='configuration'` in the
manifest. All four methods receive a `PluginContext` (project identity +
assignment options) and a `credentials` dict resolved from the linked
service application.

See [Authoring Plugins](index.md) for the manifest, context, credential
resolution, and error conventions shared by every plugin.

```python
from imbi_common.plugins import (
    ConfigKey,
    ConfigKeyWithValue,
    ConfigurationPlugin,
    ConfigValue,
    PluginContext,
)


class VaultPlugin(ConfigurationPlugin):
    manifest = manifest  # plugin_type='configuration'

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

## Method contracts

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

## Data types and secrets

`manifest.data_types` tells the host which `ConfigValue.data_type`
strings are valid, and which represent secret material (and therefore
should be redacted in UI and audit logs). Mark a
`ConfigKey` / `ConfigKeyWithValue` as `secret=True` when the key's data
type is one of the manifest's secret types; the host uses this to gate
read access and to redact values.

## API reference

::: imbi_common.plugins.ConfigurationPlugin

::: imbi_common.plugins.ConfigKey

::: imbi_common.plugins.ConfigKeyWithValue

::: imbi_common.plugins.ConfigValue
