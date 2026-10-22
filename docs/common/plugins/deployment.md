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
import typing

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
        kind: typing.Literal['default', 'branch', 'tag', 'all'] = 'all',
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
- **`get_environment_state`** — report which deployment is *active* per
  environment, as the provider sees it. The currency counterpart to
  `list_recent_deployments`, which only answers "what happened recently":
  the newest attempt may have failed, still be in flight, or have been
  superseded, leaving an older deployment live. Each returned
  `EnvironmentDeploymentState` carries `active`, `latest` (the newest
  attempt of any status), and an `active_resolution` of `found` / `none` /
  `unknown` / `error`. `unknown` (a bounded scan stopped before
  exhausting the result set) and `error` (the provider call failed) both
  mean "retain the pointer", and neither may be reported as `none` —
  clearing a correct pointer is the failure mode this method exists to
  prevent. Optional even for capabilities that set
  `supports_deployment_sync`; hosts probe by catching
  `NotImplementedError`.
- **`get_release_notes`** — return the remote release's notes body for a
  given tag. The tag-keyed counterpart to `list_recent_deployments`'
  `release_notes` field: it lets the host enrich a `Release` node's notes
  on paths that only know the tag — a webhook that created the release
  from a deployment event (which carries no body), or a resync whose
  deployment `ref` was a raw SHA. Best-effort: capabilities without a
  release concept, or that cannot resolve one for the tag, return `None`
  (the default) so the host never fails a write on a missing or unreadable
  release.
- **`get_release`** — return a `RemoteRelease` for a tag: the notes body
  plus the title, the URL, and who cut the release on the remote
  (`author`, and `author_subject` for identity resolution). The host uses
  it to attribute a release to a person. Return `None` (the default) when
  the remote has no release for the tag. The host then falls back to
  `get_release_notes`.
- **`get_file`** — return the text of the file at `path` on `ref`, or
  `None` when the file does not exist. The default raises
  `NotImplementedError`. The host uses it to read agent plugin
  marketplace files from a repository.

### Release builds

The promote and release-cut flows can build the artifact before they
deploy it. These two methods are optional and work as a pair. The
default implementations raise `NotImplementedError`.

- **`create_deployment_artifact`** — start the remote build that makes
  the deployable artifact for `ref`, under the release identity
  `version`. The remote build cuts the tag and pushes version-bump
  commits, so these do not exist yet when the method returns. Return an
  `ArtifactRun` as soon as the remote accepts the build. `run_id` can be
  `None` when the remote does not report the run it started. That is a
  success, not an error.
- **`get_artifact_run_status`** — report the status of a build by the
  `run_id` that `create_deployment_artifact` returned. Resolve it against
  the remote's build endpoint, not its deployment endpoint.

`ArtifactRun` and `DeploymentRun` are separate models on purpose. The
two IDs come from different identifier spaces on the same remote (for
GitHub, a workflow run ID and a Deployment ID).

### Git notes

The host reads drift verdicts from git notes (the `imbi-drift` notes
ref). Three optional methods give it access. Each default raises
`NotImplementedError`, so the host can tell "no note" from "cannot
answer". `namespace` is the notes ref name without the `refs/notes/`
prefix.

- **`get_commit_note`** — return the note body on one commit, or `None`
  when the ref or the note does not exist. The commit can be a short SHA;
  resolve it to the full SHA first.
- **`list_commit_notes`** — return every note in the ref as a
  `NotesListing` (`notes`, keyed by full SHA, and `complete`). Skip
  reading the bodies of the SHAs in `skip_shas`, but still enumerate the
  ref. Set `complete=False` when a note could not be read. A missing ref
  is an empty listing, not an error.
- **`diff_commit_notes`** — return the notes that changed between two
  commits *of the notes ref* (what a push to `refs/notes/<namespace>`
  reports). A `None` value means the push removed that note. An all-zero
  `before` means the ref is new; return every note in `after`.

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

::: imbi.common.plugins.EnvironmentDeploymentState

::: imbi.common.plugins.ArtifactRun

::: imbi.common.plugins.RemoteRelease

::: imbi.common.plugins.base.NotesListing

::: imbi.common.plugins.CheckStatus

::: imbi.common.plugins.DeploymentEventStatus
