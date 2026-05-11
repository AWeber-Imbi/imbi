# ADR 0013: Deployment Plugin Type

## Status

Accepted

Source design lives in [`imbi/docs/deployments-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/deployments-plan.md).

## Context

The project-detail header surfaces a release train across environments (Testing → Staging → Production) with version SHAs/tags and a dev-only Deploy button. The data is read-only; promoting a build still happens out-of-band — CI dashboards, `gh release create`, ad-hoc workflow dispatches. We want the release train to be the entry point for **every** deploy operation:

- Clicking a downstream environment chip opens a deploy modal pre-selected to the matching promotion.
- The Promote popover next to the train lets operators pick a gap (testing→staging, staging→production).
- The same modal drafts AI-generated release notes for Promote and lists branches/commits for the Testing tab.

Behind the modal we need a real plumbing path: a way for plugins to drive the actual deploy (list refs, trigger workflow, create tag/release), a way to record the deployment back into Imbi, and a server-side LLM call to draft release notes.

This is a new kind of plugin action — it triggers a side effect on the third party, not just a read. And it should run as the human, not a shared bot, because GitHub PR and Release attribution matter.

## Decision

### 1. A fourth plugin type: `deployment`

Add `deployment` to the plugin type discriminator alongside `configuration`, `logs`, and `identity`. The handler protocol covers:

- `list_deployable_refs(project, environment)` → branches/tags/commits valid for the target environment.
- `list_commits(project, ref, limit)` → commits behind a ref, for the Testing tab.
- `trigger_deployment(project, ref, environment, options)` → side-effectful action that starts the deploy.
- `create_tag_and_release(project, ref, tag, notes)` → for the Promote tab.

The protocol is intentionally small. Plugin authors implement the subset that makes sense for their backend.

### 2. Deployment plugins are separate entry points from identity plugins

`imbi-plugin-github` ships **both** a `github` identity plugin and a separate `github-deployment` plugin. They are different entry points so the manifests stay honest about what each plugin can do. A project can pair them, or pair a different identity provider with a `github-deployment` plugin via `identity_plugin_id` (ADR 0010).

### 3. Triggers use `workflow_dispatch` with inputs `{environment, ref}`

The first-party `github-deployment` plugin invokes GitHub workflows via `workflow_dispatch` with two inputs: `environment` and `ref`. The plugin manifest exposes `workflow`, `environment_input`, and `ref_input` options so projects whose workflow files differ can override the names.

`repository_dispatch` is **not** a v1 path. It was considered for finer-grained control but adds setup friction (per-repo PAT scopes, custom event types) without a matching feature gain.

### 4. Deploy operations run as the human via `identity_plugin_id`

A deployment plugin assignment declares `identity_plugin_id`, and the host resolves the acting user's `IdentityConnection` to that identity plugin at request time (ADR 0010). Outbound GitHub calls use the user's token. No shared bot identity is involved in production deploys.

### 5. Deployments are recorded as `DeploymentEvent`s on the existing edge

A `Release -[:DEPLOYED_TO]-> Environment` edge already exists in `imbi-common`. Successful and failed deploys append a `DeploymentEvent` to that edge. Rollbacks are recorded as `DeploymentEvent.status = 'rolled_back'` — same shape, not a separate UI surface.

### 6. AI-drafted release notes via a shared Anthropic client

`imbi-common` stands up an Anthropic client initialized from a FastAPI lifespan in `imbi-api` (and reusable by other services). The Promote tab calls the model to draft release notes and suggest a semver bump from the commit list. The model output is editable in the UI; no auto-publish without operator confirmation.

### 7. UI surfaces

Two new components in `imbi-ui`:

- `<PromoteDialog />` — small anchored popover (360px) under the release train, two radio options for the promotion gap, inline commit preview.
- `<DeploymentModal />` — full modal with Deploy / Promote tabs, env picker, version picker, branch/commit picker for Testing, AI-drafted tag + release notes for Promote.

API endpoints land under `/api/projects/{org}/{slug}/deployments/*`, all routed through the existing `resolve_plugin()` machinery.

## Consequences

### Positive

- Deploys are first-class operations in Imbi, not "click out to CI."
- Release-note drafting cuts a real human friction point in the Promote flow.
- Per-user identity (ADR 0010) gives accurate GitHub audit attribution for every deploy.
- The protocol is small enough that vendors other than GitHub (Argo, Spinnaker, ad-hoc) can implement it.

### Negative

- The plugin contract grows by a new type with side-effectful methods. Test coverage for side effects is harder than for read-only handlers; first-party plugins must include integration tests against test repos.
- The host has to surface fine-grained errors from a side-effectful call (workflow already running, ref invalid, GitHub 5xx). The `DeploymentEvent.status` enum is the primary visibility surface.
- The Anthropic client is a new external dependency for `imbi-api`. It's behind a configuration flag — release-note drafting degrades to "type your own notes" when the client is not configured.

### Risks Accepted

- **Replacing CI/CD**: not a goal. Imbi triggers workflows and records outcomes; the runner is GitHub Actions (or whatever the plugin targets).
- **Multi-region / canary policies**: out of scope. First cut treats one environment = one target. A future `DeploymentPolicy` plugin type can carry approval and soak-window logic without changing this contract.
- **Rollback UI**: recorded as `status = 'rolled_back'`, not a separate UI surface in v1. If rollback needs richer workflows (approvals, ticket linkage), it gets its own ADR.

## References

- [`imbi/docs/deployments-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/deployments-plan.md) — Full design, including UI mocks and click semantics.
- ADR 0008: Plugin System Architecture
- ADR 0010: Identity Plugin Architecture
- ADR 0012: Plugin Manifest Third-Party Service Template
