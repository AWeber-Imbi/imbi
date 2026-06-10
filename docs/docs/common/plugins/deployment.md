# Deployment Plugins

`DeploymentPlugin` is the abstract base for integrations that act on a
deployable repository: enumerate refs and commits, compare them, cut
tags and releases, and trigger CI workflow runs. Declare
`plugin_type='deployment'` in the manifest. Deployment plugins are
typically paired with an [identity plugin](identity.md) (set
`requires_identity=True`) so deploy actions run as the human user rather
than a shared service principal.

See [Authoring Plugins](index.md) for the manifest, context, credential
resolution, and error conventions shared by every plugin.

```python
from imbi_common.plugins import (
    CompareResult,
    Commit,
    DeploymentPlugin,
    DeploymentRun,
    PluginContext,
    Ref,
)


class GitHubDeploymentPlugin(DeploymentPlugin):
    manifest = manifest  # plugin_type='deployment'

    async def list_refs(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        kind: str = 'all',
        query: str | None = None,
    ) -> list[Ref]:
        ...

    async def list_commits(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        ref: str,
        limit: int = 25,
    ) -> list[Commit]:
        ...

    async def resolve_committish(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        committish: str,
    ) -> Commit:
        ...

    async def compare(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        base: str,
        head: str,
    ) -> CompareResult:
        ...

    async def trigger_deployment(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        ref_or_sha: str,
        inputs: dict[str, str] | None = None,
    ) -> DeploymentRun:
        ...

    async def get_deployment_status(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        run_id: str,
    ) -> DeploymentRun:
        ...
```

## Required methods

- **`list_refs`** — enumerate branches / tags / the default ref,
  optionally filtered by `kind` and a `query` substring.
- **`list_commits`** — list commits reachable from `ref`, newest first.
- **`resolve_committish`** — hydrate a single branch / tag / SHA into a
  `Commit`.
- **`compare`** — return a `CompareResult` for `base..head` (ahead /
  behind counts, commits, diffstat).
- **`trigger_deployment`** — dispatch a CI workflow / pipeline run for
  `ref_or_sha` with optional `inputs`, returning a `DeploymentRun`.
- **`get_deployment_status`** — poll a previously triggered run by
  `run_id`.

## Optional methods

These default to returning `'unknown'` / raising `NotImplementedError`;
implement only what the remote supports.

- **`get_check_status`** — aggregate CI check-runs into a single
  `CheckStatus` (`pass` / `fail` / `warn` / `unknown`) for a ref. Powers
  the release-train green/red dot.
- **`create_tag`** / **`create_release`** — mint an annotated tag and a
  release on the remote; required only for the Promote flow.
- **`list_workflows`** — list CI workflow files so the UI can populate a
  workflow dropdown when an operator wires up the per-environment
  dispatch edge.
- **`list_recent_deployments`** — return the most recent deployments per
  environment for the resync flow that backfills `Release` nodes and
  `DEPLOYED_TO` edges when webhook delivery has lapsed. Plugins that set
  `manifest.supports_deployment_sync=True` **must** implement this; each
  returned `RemoteDeployment` must carry a stable `external_run_id` so
  the host can dedupe. Status values use the host's canonical
  `DeploymentEventStatus` vocabulary (`pending`, `in_progress`,
  `success`, `failed`, `rolled_back`). To attribute the deployer to an
  Imbi user, populate `creator` (the remote login, for display) and
  `creator_subject` (the remote's stable identity subject — e.g. the
  numeric GitHub user id); the host resolves the latter through the
  service's identity plugins.

## Link write-back

When a deployment call creates, renames, or discovers the project's
canonical repository URL, set
[`ctx.link_writeback`][imbi_common.plugins.LinkWriteback] so the host
self-heals the stored project link. See
[Plugin Context](index.md#plugin-context).

## API reference

::: imbi_common.plugins.DeploymentPlugin

::: imbi_common.plugins.Ref

::: imbi_common.plugins.Commit

::: imbi_common.plugins.CompareResult

::: imbi_common.plugins.RefInfo

::: imbi_common.plugins.ReleaseInfo

::: imbi_common.plugins.WorkflowFile

::: imbi_common.plugins.DeploymentRun

::: imbi_common.plugins.RemoteDeployment
