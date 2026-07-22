# Pull Request Sync Capability

`PullRequestSyncCapability` is the contract base for a capability that
ingests a project's pull-request history into ClickHouse. Bind it with a
`Capability(kind='pr-sync', handler=...)` in the plugin's manifest.

The host addresses this capability directly (manual sync endpoints,
availability checks) and permissions it independently
(`project:pull-requests:write`). Incremental sync from inbound webhook
deliveries still flows through the plugin's
[webhook-actions](webhook-actions.md) catalog.

Surfaces: **api, webhook**.

See [Authoring Plugins](index.md) for the manifest, capabilities,
context, credential decryption, and error conventions shared by every
plugin.

```python
from imbi.common.plugins import (
    PluginContext,
    PullRequestSyncCapability,
)


class GitHubPullRequestSync(PullRequestSyncCapability):
    async def sync_all_history(
        self,
        *,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> int:
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

- **`sync_all_history`** *(required)* — record the project's full
  pull-request history. Host-invoked with no webhook payload; both
  arguments are keyword-only. Returns the number of PRs recorded.
  Re-running is safe: the ClickHouse `pull_requests` table is
  `ReplacingMergeTree`.
- **`check_available`** *(optional, default `True`)* — whether an
  on-demand sync can run for `ctx` right now. Override to report `False`
  when the remote / repository cannot be resolved. Both arguments are
  keyword-only.

## Hints

- **`cacheable`** — the host may cache reads from this capability.

## API reference

::: imbi.common.plugins.PullRequestSyncCapability
