# Authoring Plugins

Imbi plugins extend the platform with integrations against external
systems. Under **Plugin Architecture v3** (`api_version = 2`) a Python
package ships exactly **one** `Plugin` subclass whose `manifest`
declares — once per package — the integration-level options and
credentials plus a set of **capabilities**. Each capability binds one
enumerated behavior (deployment, logs, identity, …) to an implementation
class. The host services (`imbi-api`, and `imbi-gateway` for webhook
actions) discover, validate, and instantiate plugins at runtime; plugins
carry no global state and receive everything they need — context,
credentials, and options — on every call.

An **Integration** graph node is a *configuration instance* of a plugin:
it stores the resolved integration-level option values and the single
encrypted credential blob. One plugin backs many Integrations. (The
Integration node *is* the connection — there is no separate `connection`
plugin type.)

This page covers the parts every plugin shares: discovery, the manifest,
the `Capability` model, the request context, credential decryption, the
registry, errors, templates, and plugin-declared graph schema. Each
capability kind then has its own page documenting the contract base class
it implements and the data models it exchanges with the host.

## One Plugin per Package

A minimum plugin distribution contains:

1. One `Plugin` subclass whose class-level `manifest: PluginManifest`
   declares the package's slug, name, integration-level options and
   credentials, and its capabilities (each binding a handler class).
2. A module-level **`PLUGIN`** attribute in the package's root
   `__init__`, pointing at that `Plugin` subclass, so the convention scan
   can discover it.

```python
# imbi_plugin_github/__init__.py
from imbi_plugin_github.plugin import GitHubPlugin

PLUGIN = GitHubPlugin
```

## Discovery

`load_plugins()` finds plugins two ways, unions them, and dedupes by
slug:

1. **Convention scan** — every installed top-level module named
   `imbi_plugin_*` is imported and its module-level `PLUGIN` attribute
   (a `Plugin` subclass) is read.
2. **Explicit registration** — the `IMBI_PLUGINS` setting (env var
   `IMBI_PLUGINS`, a comma-separated list — or JSON list — of dotted
   import paths such as `mycorp.imbi.jira:JiraPlugin`) covers packages
   that cannot follow the naming convention. It is read via
   `imbi_common.settings.Plugins().imbi_plugins`.

There is no `imbi.plugins` entry-point group any more: the only source of
truth is the class hierarchy, and discovery is a mechanical scan.
Editable installs and monorepo dev work without re-running metadata
hooks.

## The Manifest

Every plugin declares a class-level `manifest`. Integration-level options
and credentials are declared **once**; capabilities are
enabled/configured per Integration. The host treats the manifest as
immutable once registered.

```python
from imbi_common.plugins import (
    Capability,
    CredentialField,
    Plugin,
    PluginManifest,
    PluginOption,
)

from imbi_plugin_github.capabilities import (
    GitHubDeployment,
    GitHubIdentity,
    GitHubLifecycle,
    GitHubWebhookActions,
    GitHubCommitSync,
    GitHubPullRequestSync,
)


class GitHubPlugin(Plugin):
    manifest = PluginManifest(
        slug='github',
        name='GitHub',
        description='Repositories, deployments, and identity on GitHub.',
        # Brand icon in `library-icon-name` form (Simple Icons, Tabler,
        # Lucide, …). Surfaced to the UI to show the provider's logo.
        icon='si-github',
        api_version=2,
        auth_type='oauth2',
        # Integration-level options — asked ONCE per Integration.
        options=[
            PluginOption(
                name='flavor',
                label='Flavor',
                choices=['github', 'ghec', 'ghes'],
                required=True,
            ),
            PluginOption(name='host', label='Host'),
        ],
        # Integration-level credentials — the ONLY credential declaration.
        credentials=[
            CredentialField(name='app_id', label='App ID', secret=False),
            CredentialField(name='private_key', label='Private key'),
            CredentialField(
                name='installation_id',
                label='Installation ID',
                secret=False,
            ),
            CredentialField(
                name='client_id',
                label='OAuth client ID',
                required=False,
                secret=False,
            ),
            CredentialField(
                name='client_secret',
                label='OAuth client secret',
                required=False,
            ),
        ],
        capabilities=[
            Capability(
                kind='identity',
                label='Sign in with GitHub',
                default_enabled=False,
                project_scoped=False,
                hints={'login_capable': True},
                handler=GitHubIdentity,
            ),
            Capability(
                kind='deployment',
                label='Deployments',
                hints={'supports_deployment_sync': True},
                handler=GitHubDeployment,
            ),
            Capability(
                kind='lifecycle',
                label='Repository lifecycle',
                hints={
                    'supports_lifecycle_sync': True,
                    'lifecycle_events': ['created', 'archived', 'deleted'],
                },
                handler=GitHubLifecycle,
            ),
            Capability(
                kind='webhook-actions',
                label='Webhook actions',
                handler=GitHubWebhookActions,
            ),
            Capability(
                kind='commit-sync',
                label='Commit history sync',
                handler=GitHubCommitSync,
            ),
            Capability(
                kind='pr-sync',
                label='Pull request sync',
                handler=GitHubPullRequestSync,
            ),
        ],
    )
```

### Field notes

- **`slug`** is the canonical identifier. Two plugins with the same slug
  cannot coexist; the second is rejected at load.
- **`api_version`** must be `2`. Plugins declaring other versions are
  skipped and reported as such, not errored.
- **`auth_type`** declares the credential flow: `'api_token'` (default),
  `'oauth2'`, `'oidc'`, `'aws-iam-ic'`, or `'none'`. OAuth
  `client_id` / `client_secret` are ordinary named fields in
  `credentials`.
- **`options`** are the integration-level option values collected once
  per Integration (e.g. GitHub `flavor` / `host`, AWS `region`). Five
  field types are supported: the four scalars (`string`, `integer`,
  `boolean`, `secret`) plus `mapping` (a key/value editor stored as
  `dict[str, str]`). Resolved values reach a capability via
  `PluginContext.integration_options`.
- **`credentials`** are the **only** credential declaration in the
  package — capabilities cannot declare their own. Values are encrypted
  at rest as the Integration's single blob and decrypted into the
  `credentials` dict passed to every call. Each field is `secret=True`
  by default (masked in the UI, never echoed back); set `secret=False`
  for non-sensitive identifiers such as an OAuth `client_id` or a GitHub
  App id so the UI renders them as plain text. Each field also accepts
  `multiline`, which defaults to `False`; set it to `True` for values
  that span multiple lines (e.g. a PEM private key) so the UI renders a
  textarea instead of a single-line input.
- **`capabilities`** must declare at least one `Capability`, and each
  `kind` must be unique within the manifest.
- **`data_types`** apply to configuration capabilities — see
  [Configuration](configuration.md).
- **`vertex_labels`** / **`edge_labels`** let a plugin extend the AGE
  graph with its own reference data (see
  [Plugin-declared Graph Schema](#plugin-declared-graph-schema)).
- **`ops_log_templates`** supply Mustache-style templates the UI uses to
  render operations-log entries tagged with the plugin's slug, keyed by
  the `action` value the host wrote into the entry.

::: imbi_common.plugins.Plugin

::: imbi_common.plugins.PluginManifest

::: imbi_common.plugins.PluginOption

::: imbi_common.plugins.CredentialField

::: imbi_common.plugins.DataType

::: imbi_common.plugins.OpsLogTemplate

::: imbi_common.plugins.PluginVertexLabel

::: imbi_common.plugins.PluginEdgeLabel

::: imbi_common.plugins.PluginIndex

## Capabilities

A `Capability` both **declares** operator-facing metadata (label,
options, defaults) and **binds** the implementation via its `handler` —
a class subclassing the contract base for the capability's `kind`. It is
validated at construction: the handler must subclass the correct contract
(`CAPABILITY_CONTRACTS[kind]`) and every `hints` key must be in the
per-kind allowlist (`HINT_ALLOWLIST`).

Key fields:

- **`kind`** — one of the enumerated `CapabilityKind` values below.
- **`label`** / **`description`** — operator-facing text.
- **`options`** — capability-scoped `PluginOption`s, rendered under the
  capability's toggle in the Integration form; values reach a call via
  `PluginContext.capability_options`.
- **`default_enabled`** — initial toggle state when an Integration is
  created.
- **`project_scoped`** — whether the capability participates in
  per-project-type / per-project `USES` assignment. `identity`, for
  example, is Integration-wide, not project-scoped.
- **`requires_identity`** — the capability wants `ctx.identity`
  populated when available.
- **`hints`** — kind-specific hints, validated against `HINT_ALLOWLIST`
  (see table). These are the v1 manifest booleans, moved onto the
  capability.
- **`ui_module`** — RESERVED: package-relative path to a built ESM module
  the UI can load for the capability; `None` uses built-in UI.
- **`handler`** — the implementation class. Excluded from serialization;
  the manifest that reaches the API/UI is pure data.

### Kinds, surfaces, and contracts

Each `kind` maps to exactly one contract ABC (`CAPABILITY_CONTRACTS`) and
a fixed set of surfaces (`CAPABILITY_SURFACES`). Adding a kind is a
deliberate base-model change.

| `kind` | Contract base | Surfaces | Page |
| --- | --- | --- | --- |
| `configuration` | `ConfigurationCapability` | ui, api | [Configuration](configuration.md) |
| `logs` | `LogsCapability` | ui, api | [Logs](logs.md) |
| `identity` | `IdentityCapability` | api | [Identity](identity.md) |
| `deployment` | `DeploymentCapability` | ui, api | [Deployment](deployment.md) |
| `lifecycle` | `LifecycleCapability` | api | [Lifecycle](lifecycle.md) |
| `webhook-actions` | `WebhookActionsCapability` | webhook | [Webhook Actions](webhook-actions.md) |
| `analysis` | `AnalysisCapability` | ui, api | [Analysis](analysis.md) |
| `incidents` | `IncidentsCapability` | ui, api | [Incidents](incidents.md) |
| `commit-sync` | `CommitSyncCapability` | api, webhook | [Commit Sync](commit-sync.md) |
| `pr-sync` | `PullRequestSyncCapability` | api, webhook | [Pull Request Sync](pr-sync.md) |
| `tools` | `ToolsCapability` | tools | [Tools](tools.md) |

### Hint allowlist

`cacheable` is accepted for every kind (a hint the host may consult to
cache a capability's reads). The remaining keys are per-kind:

| `kind` | Additional allowed hints |
| --- | --- |
| `logs` | `supports_histogram` |
| `deployment` | `supports_deployment_sync` |
| `lifecycle` | `supports_lifecycle_sync`, `lifecycle_events` |
| `identity` | `login_capable`, `default_scopes`, `widget_text` |

An unknown hint key fails at manifest construction, so typos surface at
load.

::: imbi_common.plugins.Capability

::: imbi_common.plugins.CapabilityHandler

## Plugin Context

Every capability call receives a `PluginContext` carrying the resolved
project's identity plus host-populated fields the capability can derive
state from. A handful of fields are *write-only* side channels the
capability sets and the host reads back after the call — most notably
`link_writeback` and `service_writeback`.

Resolved configuration reaches a call on three layers:

- **`integration_options`** — the Integration's resolved
  integration-level option values (e.g. GitHub host/flavor, AWS region),
  so a capability can read connection-level config without re-declaring
  it.
- **`capability_options`** — the invoked capability's own option values
  (from `Integration.capabilities[kind].options`, layered with any
  `USES`-edge overrides). Empty when the capability declares none.
- **`assignment_options`** — the per-assignment (`USES`-edge) options.

The host also injects the running capability's bound Integration
(`integration_slug`) and the project's `EXISTS_IN` connections
(`service_connections`, each a `ServiceConnection`) so a capability can
read the canonical project↔Integration relationship without re-querying
the graph. A lifecycle capability maintains that relationship by setting
`service_writeback`; the host persists it as the `EXISTS_IN` edge against
the bound Integration.

`resolve_user_by_identity` is an optional host-injected coroutine that
maps an external identity *subject* (e.g. a provider's numeric user id)
to the matching Imbi user's email, or `None` when no active identity
matches. A capability uses it to attribute external actors — such as the
authors of synced commits — to Imbi users without knowing how the host
reaches the identity store: the gateway wires an HTTP `/users/by-identity`
lookup, the imbi-api worker a direct graph query. It is a live callable
rather than data, so it is excluded from serialization and is `None` on
any deserialized context. Callers should cache results.

::: imbi_common.plugins.PluginContext

::: imbi_common.plugins.LinkWriteback

::: imbi_common.plugins.ServiceWriteback

::: imbi_common.plugins.ServiceConnection

## Credentials

There is exactly one credential store per Integration —
`Integration.encrypted_credentials`, a mapping of field name to a
Fernet-encrypted value. Decrypt it with
`decrypt_integration_credentials`, which accepts either the Integration
node (anything with an `encrypted_credentials` mapping) or the mapping
itself and returns the decrypted dict. There is no sibling lookup and no
fallback ordering: every capability of an Integration receives the same
decrypted blob (the `credentials` argument on every contract method).

```python
from imbi_common.plugins import decrypt_integration_credentials

credentials = decrypt_integration_credentials(integration)
```

::: imbi_common.plugins.decrypt_integration_credentials

## Search Templates

For capabilities that build provider-specific query strings from project
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

The host calls `load_plugins()` at startup (and `reload_plugins()` on
demand) to populate the registry from the convention scan unioned with
`IMBI_PLUGINS`. Every discovered plugin is validated fail-loud at load:
the class must subclass `Plugin`; its `manifest` must be a
`PluginManifest` with a supported `api_version`; every capability's
`handler` must subclass the contract for its kind; `webhook-actions` and
`tools` catalogs must enumerate cleanly with unique names; declared
vertex/edge labels must not collide; and plugin slugs must be unique.

Lookups are by plugin slug — `get_plugin(slug)` returns a
`RegistryEntry` (`plugin_cls`, `manifest`, `package_name`,
`package_version`) — and by `(slug, kind)` —
`get_capability(slug, kind)` returns the handler class for that
capability. `list_plugins()` returns every registered entry.
`load_plugins()` / `reload_plugins()` return a `LoadResult`
(`loaded`, `errors`, `skipped`).

::: imbi_common.plugins.load_plugins

::: imbi_common.plugins.reload_plugins

::: imbi_common.plugins.get_plugin

::: imbi_common.plugins.get_capability

::: imbi_common.plugins.list_plugins

::: imbi_common.plugins.RegistryEntry

::: imbi_common.plugins.LoadResult

## Plugin-declared Graph Schema

A plugin may extend the AGE graph with its own vertex labels and edges
via `PluginManifest.vertex_labels` / `edge_labels`. The host refuses any
declaration that collides with core schemata or with another plugin's
differently-shaped label (`validate_no_collisions`) and creates the
declared vlabels and indexes idempotently on startup
(`apply_plugin_schemas`).

::: imbi_common.plugins.validate_no_collisions

::: imbi_common.plugins.apply_plugin_schemas

## Errors

Capabilities should raise exceptions from `imbi_common.plugins.errors`
when the failure mode maps onto one of them; otherwise let the host wrap
the exception. The author-relevant ones:

| Exception | When to raise |
| --- | --- |
| `PluginCredentialsMissing` | A required credential is absent or empty in the `credentials` dict. |
| `PluginAuthenticationFailed` | The upstream rejected the call for an auth reason (HTTP 401, expired token); host may refresh and retry once. |
| `PluginRateLimited` | The upstream's rate limit is exhausted; carries `retry_at` so the host can pause and keep the job queued. |
| `PluginTimeoutError` | An upstream call exceeded the capability's internal timeout budget. |
| `PluginUnavailableError` | The upstream service is reachable but cannot serve the request (degraded, locked). |
| `CursorExpiredError` | A logs / incidents `cursor` is no longer valid and the caller must restart paging. |
| `IdentityAuthorizationPending` | An identity device-code flow has not completed yet; the host's poll loop retries. |
| `IdentityAuthorizationExpired` | An identity device code expired before the user completed it; the UI must restart the flow. |
| `PluginRemediationNotSupported` | Raised by the default `AnalysisCapability.remediate` when a capability emits no remediations. |
| `PluginSchemaCollisionError` | Raised by the host when a plugin's declared vlabel collides with core or another plugin. |

`PluginNotFoundError` is host-side (registry lookups) — capability code
should not raise it.

::: imbi_common.plugins.PluginCredentialsMissing

::: imbi_common.plugins.PluginAuthenticationFailed

::: imbi_common.plugins.PluginRateLimited

::: imbi_common.plugins.PluginTimeoutError

::: imbi_common.plugins.PluginUnavailableError

::: imbi_common.plugins.CursorExpiredError

::: imbi_common.plugins.IdentityAuthorizationPending

::: imbi_common.plugins.IdentityAuthorizationExpired

::: imbi_common.plugins.PluginRemediationNotSupported

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

Capabilities can be unit-tested in isolation: instantiate the handler
class directly and call its methods with synthesized `PluginContext`
objects and a credentials dict. For registry-level integration tests,
see `tests/test_plugins/test_registry.py` in this repository for examples
of injecting a plugin without installing a real distribution.
