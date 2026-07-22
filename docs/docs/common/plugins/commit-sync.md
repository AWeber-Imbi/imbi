# Commit Sync Capability

`CommitSyncCapability` is the contract base for a capability that ingests
a project's commit (and tag) history into ClickHouse. Bind it with a
`Capability(kind='commit-sync', handler=...)` in the plugin's manifest.

The host addresses this capability directly (manual sync endpoints,
availability checks) and permissions it independently
(`project:commits:write`). Incremental sync from inbound webhook
deliveries still flows through the plugin's
[webhook-actions](webhook-actions.md) catalog; this kind exists so the
host can resolve, enable, and assign commit-sync on its own.

Surfaces: **api, webhook**.

See [Authoring Plugins](index.md) for the manifest, capabilities,
context, credential decryption, and error conventions shared by every
plugin.

```python
from imbi.common.plugins import (
    CommitSyncCapability,
    PluginContext,
)


class GitHubCommitSync(CommitSyncCapability):
    async def sync_all_history(
        self,
        *,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> tuple[int, int]:
        ...

    async def check_available(
        self,
        *,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> bool:
        ...
```

## Method contracts

- **`sync_all_history`** *(required)* — record the project's full commit
  and tag history. Host-invoked with no webhook payload; both arguments
  are keyword-only. Returns `(commits_recorded, tags_recorded)`.
  Re-running is safe: the ClickHouse `commits` / `tags` tables are
  `ReplacingMergeTree` and dedupe against rows the webhook already
  recorded.
- **`check_available`** *(optional, default `True`)* — whether an
  on-demand sync can run for `ctx` right now. Override to report `False`
  when the remote / repository cannot be resolved so the host can hide
  the affordance. Both arguments are keyword-only.

To attribute commit authors to Imbi users, use
`ctx.resolve_user_by_identity` (see
[Plugin Context](index.md#plugin-context)); cache results, as a
full-history sync would otherwise repeat the lookup for every commit.

## Hints

- **`cacheable`** — the host may cache reads from this capability.

## API reference

::: imbi.common.plugins.CommitSyncCapability
