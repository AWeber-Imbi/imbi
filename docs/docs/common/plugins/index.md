# Authoring Plugins

Imbi plugins extend the platform with integrations against third-party
services. A plugin is an installable Python distribution that exposes a
handler class through the `imbi.plugins` entry point group. The host
service (`imbi-api`, or `imbi-gateway` for webhook actions) discovers,
validates, and instantiates plugins at runtime; plugins themselves carry
no global state and receive everything they need — context, credentials,
and options — on every call.

This page covers the parts every plugin shares: the manifest, the
request context, credential resolution, the registry, errors, and
templates. Each plugin variation then has its own page documenting the
base class it must implement and the data models it exchanges with the
host.

## Plugin Variations

`PluginManifest.plugin_type` selects the variation. The contract for a
plugin is defined by the abstract base class it inherits from:

| `plugin_type`   | Base class            | Page                              | Purpose                                                                                          |
| --------------- | --------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------ |
| `configuration` | `ConfigurationPlugin` | [Configuration](configuration.md) | List, read, write, and delete typed configuration keys for a project (feature flags, secrets)    |
| `logs`          | `LogsPlugin`          | [Logs](logs.md)                   | Search log entries and describe the available query schema for a project                         |
| `identity`      | `IdentityPlugin`      | [Identity](identity.md)           | Authenticate a user to a third party via OAuth 2.0 / OIDC / device-code, and mint per-user tokens |
| `deployment`    | `DeploymentPlugin`    | [Deployment](deployment.md)       | Enumerate refs/commits, compare them, cut tags/releases, and trigger CI workflow runs            |
| `lifecycle`     | `LifecyclePlugin`     | [Lifecycle](lifecycle.md)         | React to project state transitions (create / update / archive / unarchive / delete / relocate)   |
| `webhook`       | `WebhookActionPlugin` | [Webhook Actions](webhook.md)     | Run named actions in response to inbound webhook payloads routed by a host such as `imbi-gateway` |

The class hierarchy and `plugin_type` must agree — a class that
subclasses `ConfigurationPlugin` but declares `plugin_type='logs'` is
rejected at load time, and vice versa.

## Anatomy of a Plugin Package

A minimum plugin distribution contains:

1. A handler class subclassing one of the six base classes above.
2. A class-level `manifest: PluginManifest` describing slug, name,
   options, credential fields, and any variation-specific declarations
   (data types, vertex/edge labels, lifecycle events, …).
3. An `imbi.plugins` entry point in the package metadata pointing at the
   handler class.

A trimmed `pyproject.toml`:

```toml
[project]
name = "imbi-plugin-vault"
version = "0.1.0"
dependencies = ["imbi-common>=2.7", "httpx"]

[project.entry-points."imbi.plugins"]
vault = "imbi_plugin_vault.plugin:VaultPlugin"
```

The entry-point name is informational — the canonical identifier is
`manifest.slug`. Two plugins with the same slug cannot coexist; the
second is dropped with an error during load.

## The Manifest

Every plugin declares a class-level `manifest`. The host treats it as
immutable once registered; do not mutate it at runtime.

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

### Field notes

- **`auth_type`** declares the credential flow expected by the plugin:
  `'api_token'` (default), `'oauth2'`, `'oidc'`, or `'aws-iam-ic'`. The
  host uses it both to drive the credentials form and to decide how to
  resolve credentials at call time (see
  [Credential Resolution](#credential-resolution)).
- **`api_version`** must be an integer the host advertises as supported.
  Today only `1` is accepted; plugins declaring other versions are
  skipped and reported as such, *not* errored.
- **`cacheable`** is a hint to the host — set `False` for plugins whose
  reads must always be live (token-based providers, audit-sensitive
  systems).
- **`options`** are configured at assignment time and validated against
  the `PluginOption` schema. Five field types are supported: the four
  scalars (`string`, `integer`, `boolean`, `secret`) plus `mapping`
  (a key/value editor stored as `dict[str, str]`). Plugin code receives
  the resolved values via `PluginContext.assignment_options`.
- **`credentials`** describe what the host must collect for the plugin.
  Values are encrypted at rest and decrypted into the `credentials`
  dict the host passes to every call.
- **`data_types`** apply to configuration plugins — see
  [Configuration Plugins](configuration.md).
- **`supports_histogram`** applies to logs plugins — see
  [Logs Plugins](logs.md).
- **`supports_deployment_sync`**, **`login_capable`**,
  **`requires_identity`**, and **`default_scopes`** govern the
  deployment and identity flows — see the
  [Deployment](deployment.md) and [Identity](identity.md) pages.
- **`vertex_labels`** / **`edge_labels`** let a plugin extend the AGE
  graph with its own reference data (see
  [Plugin-declared Graph Schema](#plugin-declared-graph-schema)).
- **`lifecycle_events`** advertises which project transitions a
  lifecycle plugin handles — see [Lifecycle Plugins](lifecycle.md).
- **`ops_log_templates`** supply Mustache-style templates the UI uses to
  render operations-log entries tagged with the plugin's slug, keyed by
  the `action` value the host wrote into the entry.
- **`widget_text`** is body copy for the dashboard "unconnected
  integration" widget shown for identity plugins.

::: imbi_common.plugins.PluginManifest

::: imbi_common.plugins.PluginOption

::: imbi_common.plugins.CredentialField

::: imbi_common.plugins.DataType

::: imbi_common.plugins.OpsLogTemplate

::: imbi_common.plugins.PluginVertexLabel

::: imbi_common.plugins.PluginEdgeLabel

::: imbi_common.plugins.PluginIndex

## Plugin Context

Every plugin call receives a `PluginContext` carrying the resolved
project's identity plus host-populated fields the plugin can derive
state from (external links, project-type slugs, per-environment config,
the acting user's materialized `identity`, …). A handful of fields are
*write-only* side channels the plugin sets and the host reads back after
the call — most notably `link_writeback`.

::: imbi_common.plugins.PluginContext

::: imbi_common.plugins.LinkWriteback

## Search Templates

For plugins that build provider-specific query strings from project
context, use `expand_template`. It substitutes only the whitelisted
variables — `project_slug`, `org_slug`, `team_slug`, `environment`,
`project_id`, `project_type_slug` — written as `${name}`, and rejects
anything else:

```python
from imbi_common.plugins import expand_template

label_query = expand_template(
    template,  # e.g. '{app="${project_slug}", env="${environment}"}'
    {
        'project_slug': ctx.project_slug,
        'org_slug': ctx.org_slug,
        'team_slug': ctx.team_slug,
        'environment': ctx.environment,
        'project_id': ctx.project_id,
        'project_type_slug': ctx.project_type_slugs[0],
    },
)
```

Validate templates at assignment time with `validate_template` so
configuration errors surface early instead of during a search.

::: imbi_common.plugins.validate_template

::: imbi_common.plugins.expand_template

## Registry and Loading

Plugin discovery is driven by `importlib.metadata` entry points under
the `imbi.plugins` group. The host calls `load_plugins()` at startup
(and `reload_plugins()` on demand) to populate the registry. Each entry
is validated — manifest present and well-formed, class hierarchy
matching `plugin_type`, supported `api_version`, unique slug, and (for
webhook plugins) a valid action catalog — before it is admitted.

::: imbi_common.plugins.load_plugins

::: imbi_common.plugins.reload_plugins

::: imbi_common.plugins.get_plugin

::: imbi_common.plugins.list_plugins

::: imbi_common.plugins.RegistryEntry

::: imbi_common.plugins.LoadResult

## Credential Resolution

Hosts fetch decrypted plugin credentials out of the graph with
`get_plugin_credentials`. Routing depends on `manifest.auth_type`:
`api_token` and `aws-iam-ic` read the Fernet-encrypted
`Plugin.plugin_configuration` blob directly, while `oauth2` and `oidc`
walk `Plugin -[:USES_APPLICATION]-> ServiceApplication` for the
`client_id` / `client_secret`. `patch_plugin_configuration` and
`get_plugin_configuration_keys` manage the configuration blob without
ever surfacing plaintext values.

::: imbi_common.plugins.get_plugin_credentials

::: imbi_common.plugins.get_plugin_configuration_keys

::: imbi_common.plugins.patch_plugin_configuration

## Plugin-declared Graph Schema

Plugins (today, identity plugins) may extend the AGE graph with their
own vertex labels and edges via `PluginManifest.vertex_labels` /
`edge_labels`. The host refuses any declaration that collides with core
schemata or with another plugin's differently-shaped label
(`validate_no_collisions`) and creates the declared vlabels and indexes
idempotently on startup (`apply_plugin_schemas`).

::: imbi_common.plugins.validate_no_collisions

::: imbi_common.plugins.apply_plugin_schemas

## Errors

Plugins should raise exceptions from `imbi_common.plugins.errors` when
the failure mode maps onto one of them; otherwise let the host wrap the
exception. The author-relevant ones:

| Exception                        | When to raise                                                                                  |
| -------------------------------- | ---------------------------------------------------------------------------------------------- |
| `PluginCredentialsMissing`       | A required credential is absent or empty in the `credentials` dict.                            |
| `PluginAuthenticationFailed`     | The upstream rejected the call for an auth reason (HTTP 401, expired token); host may refresh and retry once. |
| `PluginTimeoutError`             | An upstream call exceeded the plugin's internal timeout budget.                                |
| `PluginUnavailableError`         | The upstream service is reachable but cannot serve the request (degraded, locked).             |
| `CursorExpiredError`             | A logs `query.cursor` is no longer valid and the caller must restart paging.                   |
| `IdentityAuthorizationPending`   | An identity device-code flow has not completed yet; the host's poll loop retries.              |
| `IdentityAuthorizationExpired`   | An identity device code expired before the user completed it; the UI must restart the flow.    |
| `PluginSchemaCollisionError`     | Raised by the host when a plugin's declared vlabel collides with core or another plugin.       |

`PluginNotFoundError` and `PluginUnavailableError` (registry lookups)
are host-side — plugin code should not raise `PluginNotFoundError`.

::: imbi_common.plugins.PluginCredentialsMissing

::: imbi_common.plugins.PluginAuthenticationFailed

::: imbi_common.plugins.PluginTimeoutError

::: imbi_common.plugins.PluginUnavailableError

::: imbi_common.plugins.CursorExpiredError

::: imbi_common.plugins.IdentityAuthorizationPending

::: imbi_common.plugins.IdentityAuthorizationExpired

::: imbi_common.plugins.PluginSchemaCollisionError

::: imbi_common.plugins.PluginNotFoundError

## Lifecycle and State

A new handler instance is created **per request**. Do not stash
connection state, cached credentials, or per-project data on `self`. If
you need a connection pool or rate-limited HTTP client, construct it
inside the method, scoped to the call:

```python
async def list_keys(self, ctx, credentials):
    async with httpx.AsyncClient(timeout=10.0) as client:
        ...
```

## Testing

Plugins can be unit-tested in isolation. The host machinery is
straightforward to fake — instantiate the plugin class directly and call
its methods with synthesized `PluginContext` objects and a credentials
dict. For registry-level integration tests, see
`tests/test_plugins/test_registry.py` in this repository for examples of
mocking `importlib.metadata.entry_points` to inject a plugin without
having to install a real distribution.
