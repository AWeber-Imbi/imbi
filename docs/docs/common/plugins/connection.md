# Connection Plugins

`ConnectionPlugin` is the abstract base for plugins that carry no
behavior of their own and exist only to hold the shared connection
settings for a family of sibling plugins attached to the same
`ThirdPartyService`. Declare `plugin_type='connection'` in the manifest.
There are **no methods** — a connection plugin is never dispatched to.

A connection plugin is the single source of two things for its siblings:

- **Host/flavor options** — declared as manifest `options` (e.g. a
  GitHub connection plugin's `flavor` and `host`). Behavioral plugins
  read these off [`PluginContext.service_plugins`][imbi_common.plugins.PluginContext]
  to resolve which host they target, instead of each carrying its own
  host-flavor variant.
- **Credentials** — declared as manifest `credentials`. The host
  resolves a behavioral plugin's credentials from the connection
  plugin's `plugin_configuration` when the behavioral plugin carries
  none of its own.

See [Authoring Plugins](index.md) for the manifest, context, credential
resolution, and error conventions shared by every plugin.

```python
from imbi_common.plugins import (
    ConnectionPlugin,
    CredentialField,
    PluginManifest,
    PluginOption,
)


class GitHubConnectionPlugin(ConnectionPlugin):
    manifest = PluginManifest(
        slug='github-connection',
        name='GitHub Connection',
        plugin_type='connection',
        options=[
            PluginOption(
                name='flavor',
                label='Flavor',
                type='string',
                choices=['github.com', 'ghec', 'ghes'],
                required=True,
            ),
            PluginOption(name='host', label='Host', type='string'),
        ],
        credentials=[
            CredentialField(name='app_id', label='App ID', required=False),
            CredentialField(
                name='private_key', label='Private key', required=False
            ),
            CredentialField(
                name='access_token', label='Token', required=False
            ),
        ],
    )
```

## API reference

::: imbi_common.plugins.ConnectionPlugin
