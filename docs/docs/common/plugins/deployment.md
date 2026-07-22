# Deployment Capability

`DeploymentCapability` is the contract base for a capability that acts on
a deployable repository: enumerate refs and commits, compare them, cut
tags and releases, and trigger CI workflow runs. Bind it with a
`Capability(kind='deployment', handler=...)` in the plugin's manifest.
Deployment is typically paired with an [identity](identity.md) capability
(set `requires_identity=True`) so deploy actions run as the human user
rather than a shared service principal.

Surfaces: **ui, api**.

See [Authoring Plugins](index.md) for the manifest, capabilities,
context, credential decryption, and error conventions shared by every
plugin.

```python
from imbi.common.plugins import (
    CompareResult,
    Commit,
    DeploymentCapability,
    DeploymentRun,
    PluginContext,
    Ref,
)


class GitHubDeployment(DeploymentCapability):
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

These default to returning `'unknown'` or `None`, or raising
`NotImplementedError`; implement only what the remote supports.

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
  `DEPLOYED_TO` edges when webhook delivery has lapsed. Capabilities that
  set the `supports_deployment_sync` hint **must** implement this; each
  returned `RemoteDeployment` must carry a stable `external_run_id` so
  the host can dedupe. Status values use the host's canonical
  `DeploymentEventStatus` vocabulary (`pending`, `in_progress`,
  `success`, `failed`, `rolled_back`). To attribute the deployer to an
  Imbi user, populate `creator` (the remote login, for display) and
  `creator_subject` (the remote's stable identity subject — e.g. the
  numeric GitHub user id); the host resolves the latter through the
  Integration's identity capability. When the deployment targets a tagged
  release, populate `release_notes` with the release's notes body (e.g. a
  GitHub release's "What's Changed" markdown); the host persists it as the
  `Release` node's notes, distinct from the short `description` deploy
  note.
- **`get_release_notes`** — return the remote release's notes body for a
  given tag. The tag-keyed counterpart to `list_recent_deployments`'
  `release_notes` field: it lets the host enrich a `Release` node's notes
  on paths that only know the tag — a webhook that created the release
  from a deployment event (which carries no body), or a resync whose
  deployment `ref` was a raw SHA. Best-effort: capabilities without a
  release concept, or that cannot resolve one for the tag, return `None`
  (the default) so the host never fails a write on a missing or unreadable
  release.

## Hints

- **`supports_deployment_sync`** — the capability implements
  `list_recent_deployments` for the resync flow.
- **`cacheable`** — the host may cache reads from this capability.

## Link write-back

When a deployment call creates, renames, or discovers the project's
canonical repository URL, set
[`ctx.link_writeback`][imbi.common.plugins.LinkWriteback] so the host
self-heals the stored project link. See
[Plugin Context](index.md#plugin-context).

## API reference

::: imbi.common.plugins.DeploymentCapability

::: imbi.common.plugins.Ref

::: imbi.common.plugins.Commit

::: imbi.common.plugins.CompareResult

::: imbi.common.plugins.RefInfo

::: imbi.common.plugins.ReleaseInfo

::: imbi.common.plugins.WorkflowFile

::: imbi.common.plugins.DeploymentRun

::: imbi.common.plugins.RemoteDeployment
