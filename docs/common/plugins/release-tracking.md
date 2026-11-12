# Release Tracking Capability

`ReleaseTrackingCapability` is the contract base for integrations that
record Imbi releases in a remote platform (e.g. Sentry releases). Bind it
with a `Capability(kind='release-tracking', handler=...)` in the plugin's
manifest. The single required method is `on_release_created`.

Surfaces: **api**.

See [Authoring Plugins](index.md) for the manifest, capabilities,
context, credential decryption, and error conventions shared by every
plugin.

```python
from imbi.common.plugins import (
    LifecycleResult,
    PluginContext,
    ReleaseTrackingCapability,
    TrackedRelease,
)


class SentryReleaseTracking(ReleaseTrackingCapability):
    async def on_release_created(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        release: TrackedRelease,
    ) -> LifecycleResult:
        ...
```

## When the host calls it

The host calls `on_release_created` once for each new `Release` node, for
every Integration bound to the project for `release-tracking`. All paths
that create a release call it: `POST .../releases`, a promote, a
deployment webhook, and a deployment resync. A resync that finds old tags
for the first time creates their releases, so the host calls the
capability for each of them.

The call runs after the release is written and does not block the
request. It is best-effort: an exception or a `failed` result is logged
and recorded as a `plugin.release-tracking.created` event, and the
release stays. The host does not retry.

## Method contract

- **`on_release_created`** — record `release` in the remote. Resolve the
  remote project from the Integration's entry in
  [`ctx.service_connections`][imbi.common.plugins.ServiceConnection]
  (matched on `ctx.integration_slug`). `release.committish` is the short
  commit SHA; `release.tag` is `None` for an untagged release. Return
  `status='skipped'` when the release cannot be recorded (for example, the
  remote version needs a tag and there is none). Make the call
  idempotent: the remote can already have the release.
