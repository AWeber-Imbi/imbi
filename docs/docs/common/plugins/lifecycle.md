# Lifecycle Plugins

`LifecyclePlugin` is the abstract base for plugins that react to project
state changes — create, update, archive, unarchive, delete, relocate —
by mirroring the change to a backing remote (e.g. provisioning,
renaming, transferring, or deleting a GitHub repository). Declare
`plugin_type='lifecycle'` in the manifest.

The host invokes each hook *after* the authoritative Imbi state change
has succeeded, so a third-party failure never rolls back the operator's
intent; failures are captured on `LifecycleResult` and surfaced without
aborting the write.

See [Authoring Plugins](index.md) for the manifest, context, credential
resolution, and error conventions shared by every plugin.

## Hooks and capability advertisement

Only `on_project_archived` is required. The remaining hooks default to
raising `NotImplementedError`, which the host dispatcher maps to
`LifecycleResult(status='skipped')`. A plugin advertises the events it
actually handles via `PluginManifest.lifecycle_events` so the UI can
gate the matching affordances (e.g. "Also delete the repository"); the
default is `['archived', 'unarchived']`.

| Hook                       | `lifecycle_events` value | Notes                                                                   |
| -------------------------- | ------------------------ | ----------------------------------------------------------------------- |
| `on_project_created`       | `created`                | Provision the remote; set `ctx.link_writeback` with the canonical link. |
| `on_project_updated`       | `updated`                | Push name / description / homepage; `ctx.previous_project_slug` locates a renamed remote. |
| `on_project_archived`      | `archived`               | Required.                                                               |
| `on_project_unarchived`    | `unarchived`             | Inverse of archive.                                                     |
| `on_project_deleted`       | `deleted`                | Invoked after the node is removed; `404` from the remote is a skip.     |
| `on_project_relocated`     | `relocated`              | Move the remote to a new target; set `ctx.link_writeback`. For team-driven targets, `ctx.previous_team_slug` is the team before the move and `ctx.team_slug` the team after. |

```python
from imbi_common.plugins import (
    LifecyclePlugin,
    LifecycleResult,
    PluginContext,
)


class GitHubLifecyclePlugin(LifecyclePlugin):
    manifest = manifest  # plugin_type='lifecycle'

    async def on_project_archived(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        ...

    async def on_project_created(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        # provision the remote, then:
        # ctx.link_writeback = LinkWriteback(link_key=..., new_url=...)
        ...
```

## Push-sync

A lifecycle plugin whose `on_project_updated` hook is a safe **upsert**
— creating the remote when it is missing and updating it otherwise —
should set `manifest.supports_lifecycle_sync = True`. The flag tells the
host it is safe to re-run `on_project_updated` on demand to reconcile the
remote with current Imbi state, and the UI uses it to gate the "Sync
lifecycle" affordances on the project and admin service pages. Leave it
`False` (the default) when `on_project_updated` is not idempotent or the
plugin has no update hook.

## Relocation preview

When relocation is keyed off something other than the project's types
(e.g. its owning team), compare `ctx.previous_team_slug` against
`ctx.team_slug` in `on_project_relocated` to decide whether the routing
target actually changed, and **no-op when it has not** — the host fires
`relocated` to every lifecycle plugin on the service, so each must
ignore moves that do not affect its own target.

`resolve_relocation_target` lets the host answer "would changing this
project's types move its repository?" without inlining plugin-specific
resolution into the API layer. It must resolve the target
deterministically from `ctx` (typically `project_type_slugs` + plugin
options) and **must not** call out to the remote — the host may invoke
it many times during a UI preview. Return `None` (the default) when the
plugin has no relocate concept.

## Link write-back

Hooks that create, rename, or relocate the remote set
[`ctx.link_writeback`][imbi_common.plugins.LinkWriteback] so the host
persists or self-heals the project's stored link. See
[Plugin Context](index.md#plugin-context).

## Service edge write-back

Hooks that create, move, or tear down the project's relationship with
the service the plugin is bound to set
[`ctx.service_writeback`][imbi_common.plugins.ServiceWriteback]. The
host persists it as the
`(:Project)-[:EXISTS_IN]->(:ThirdPartyService)` edge — storing the
`identifier` and the canonical **API** URL — and merges any
`dashboard_links` into `Project.links`. Set `remove=True` to delete the
edge (e.g. on project delete or relocation away from the service).

The host owns the plugin↔service binding: the writeback targets the
service surfaced as
[`ctx.third_party_service_slug`][imbi_common.plugins.PluginContext], so
it carries no service slug and a plugin cannot write an edge to an
arbitrary service. Read the current relationship from
[`ctx.service_connections`][imbi_common.plugins.ServiceConnection].

## API reference

::: imbi_common.plugins.LifecyclePlugin

::: imbi_common.plugins.LifecycleResult

::: imbi_common.plugins.RelocationTarget
