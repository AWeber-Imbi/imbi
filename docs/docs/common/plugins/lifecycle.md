# Lifecycle Capability

`LifecycleCapability` is the contract base for a capability that reacts
to project state changes — create, update, archive, unarchive, delete,
relocate — by mirroring the change to a backing remote (e.g.
provisioning, renaming, transferring, or deleting a GitHub repository).
Bind it with a `Capability(kind='lifecycle', handler=...)` in the
plugin's manifest.

The host invokes each hook *after* the authoritative Imbi state change
has succeeded, so a third-party failure never rolls back the operator's
intent; failures are captured on `LifecycleResult` and surfaced without
aborting the write.

Surfaces: **api**.

See [Authoring Plugins](index.md) for the manifest, capabilities,
context, credential decryption, and error conventions shared by every
plugin.

## Hooks and event advertisement

Only `on_project_archived` is required. The remaining hooks default to
raising `NotImplementedError`, which the host dispatcher maps to
`LifecycleResult(status='skipped')`. A capability advertises the events
it actually handles via the `lifecycle_events` hint so the UI can gate
the matching affordances (e.g. "Also delete the repository").

| Hook | `lifecycle_events` value | Notes |
| --- | --- | --- |
| `on_project_created` | `created` | Provision the remote; set `ctx.link_writeback` with the canonical link. |
| `on_project_updated` | `updated` | Push name / description / homepage; `ctx.previous_project_slug` locates a renamed remote. |
| `on_project_archived` | `archived` | Required. |
| `on_project_unarchived` | `unarchived` | Inverse of archive. |
| `on_project_deleted` | `deleted` | Invoked after the node is removed; `404` from the remote is a skip. |
| `on_project_relocated` | `relocated` | Move the remote to a new target; set `ctx.link_writeback`. For team-driven targets, `ctx.previous_team_slug` is the team before the move and `ctx.team_slug` the team after. |

```python
from imbi_common.plugins import (
    LifecycleCapability,
    LifecycleResult,
    LinkWriteback,
    PluginContext,
)


class GitHubLifecycle(LifecycleCapability):
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

A lifecycle capability whose `on_project_updated` hook is a safe
**upsert** — creating the remote when it is missing and updating it
otherwise — should set the `supports_lifecycle_sync` hint. It tells the
host it is safe to re-run `on_project_updated` on demand to reconcile the
remote with current Imbi state, and the UI uses it to gate the "Sync
lifecycle" affordances. Leave it unset when `on_project_updated` is not
idempotent or the capability has no update hook.

## Relocation preview

When relocation is keyed off something other than the project's types
(e.g. its owning team), compare `ctx.previous_team_slug` against
`ctx.team_slug` in `on_project_relocated` to decide whether the routing
target actually changed, and **no-op when it has not** — the host fires
`relocated` to every lifecycle capability on the Integration, so each
must ignore moves that do not affect its own target.

`resolve_relocation_target` lets the host answer "would changing this
project's types move its repository?" without inlining plugin-specific
resolution into the API layer. It must resolve the target
deterministically from `ctx` (typically `project_type_slugs` + options)
and **must not** call out to the remote — the host may invoke it many
times during a UI preview. Return `None` (the default) when the
capability has no relocate concept.

## Link write-back

Hooks that create, rename, or relocate the remote set
[`ctx.link_writeback`][imbi_common.plugins.LinkWriteback] so the host
persists or self-heals the project's stored link. See
[Plugin Context](index.md#plugin-context).

## Integration edge write-back

Hooks that create, move, or tear down the project's relationship with the
Integration the capability is bound to set
[`ctx.service_writeback`][imbi_common.plugins.ServiceWriteback]. The host
persists it as the `(:Project)-[:EXISTS_IN]->(:Integration)` edge —
storing the `identifier` and the canonical **API** URL — and merges any
`dashboard_links` into `Project.links`. Set `remove=True` to delete the
edge (e.g. on project delete or relocation away from the Integration).

Set `webhook_secret_enc` to store an **already-encrypted** secret on the
same edge — e.g. a per-subscription webhook signing secret a gateway
reads back to verify inbound deliveries. The capability encrypts the
value; the host persists it verbatim and never decrypts it, and `None`
leaves any existing edge secret untouched.

The host owns the capability↔Integration binding: the writeback targets
the Integration surfaced as
[`ctx.integration_slug`][imbi_common.plugins.PluginContext], so it
carries no slug and a capability cannot write an edge to an arbitrary
Integration. Read the current relationship from
[`ctx.service_connections`][imbi_common.plugins.ServiceConnection].

## Hints

- **`supports_lifecycle_sync`** — `on_project_updated` is a safe upsert
  the host may re-run on demand.
- **`lifecycle_events`** — the list of events this capability handles.
- **`cacheable`** — the host may cache reads from this capability.

## API reference

::: imbi_common.plugins.LifecycleCapability

::: imbi_common.plugins.LifecycleResult

::: imbi_common.plugins.RelocationTarget
