# imbi-plugin-github

GitHub plugin for Imbi. A single plugin — slug **`github`** — backs every
GitHub Integration; the integration-level `flavor` option selects
github.com (`github`), GitHub Enterprise Cloud (`ghec`), or GitHub
Enterprise Server (`ghes`), and `host` names the tenant or appliance.

## Capabilities

| Kind              | Handler                   |
| ----------------- | ------------------------- |
| `identity`        | `GitHubIdentity`          |
| `deployment`      | `GitHubDeployment`        |
| `lifecycle`       | `GitHubLifecycle`         |
| `webhook-actions` | `GitHubWebhookActions`    |
| `commit-sync`     | `GitHubCommitSync`        |
| `pr-sync`         | `GitHubPullRequestSync`   |
| `analysis`        | `GitHubDoctor`            |

### Identity

Implements the OAuth App flow. The access token returned by the OAuth
grant is passed straight to GitHub APIs as a `Bearer` token, so
`materialize()` is a no-op.

### Deployment

Drives the GitHub Deployments API (`POST /repos/{owner}/{repo}/deployments`)
plus tag and release creation. Promote behaviour is inferred from the
ref shape by the host (semver → trigger Deployment, raw SHA → cut tag
+ Release).  Per-env workflow inputs ride on the `USES_PLUGIN` edge as
`env_payloads` and arrive on `PluginContext.environment_config`.

### Lifecycle

Reacts to project archive / unarchive by archiving the matching repo via
`PATCH /repos/{owner}/{repo}` with `{"archived": true|false}`. When the
`archive_target_org` option is set, archive **also** transfers the repo to
that org first via `POST /repos/{owner}/{repo}/transfer` — useful for
moving sunset projects into a dedicated "archive" org so they no longer
crowd primary-org searches.

GitHub refuses to transfer archived repos, so an already-archived source
is briefly unarchived, transferred, and re-archived at the destination.
On unarchive the plugin only flips `archived` back to `false` at the
repo's current location — it does **not** transfer back to the original
org.

Archiving requires admin scope on the repo; transferring additionally
requires admin permission on the target organization.

### Webhook actions (commit / tag / PR sync)

The `webhook-actions` capability exposes the actions the gateway
dispatches from webhook deliveries. A `WebhookRule.handler` is
`"<plugin_slug>#<action_name>"`, and the slug is the **plugin** slug —
`github` — not the capability kind:

| Action                | Handler                      | Records into ClickHouse |
| --------------------- | ---------------------------- | ----------------------- |
| `sync_commits`        | `github#sync_commits`        | `commits`               |
| `sync_tags`           | `github#sync_tags`           | `tags`                  |
| `sync_pull_requests`  | `github#sync_pull_requests`  | `pull_requests`         |

`sync_commits` and `sync_tags` are dispatched from `push` deliveries;
`sync_pull_requests` from `pull_request` deliveries.

`sync_commits` fetches the full set of commits in a push via the compare
API (paginated, so it isn't capped by the 20-commit inline payload limit);
`sync_tags` records the pushed tag and, with `reconcile_all`, the repo's
full tag list. Branch/tag gating is the rule's CEL `filter_expression`,
which evaluates against the recorded event — the webhook body is under
`payload` (e.g. `payload.ref == "refs/heads/main"`,
`payload.ref.startsWith("refs/tags/")`). The API
flavor (github.com / GHEC / GHES) is resolved at runtime — explicit
`api_base_url`, else a connected GitHub plugin on the same service, else
the service endpoint, else the payload's `repository.url`.

Unlike identity/deployment/lifecycle (which act as the OAuth user),
commit-sync runs without an actor and authenticates with a **service**
credential in one of two modes, resolved per call:

- **PAT** — a static `access_token`.
- **GitHub App** — `app_id` + `private_key`; the plugin signs an App JWT
  and mints a short-lived **installation token** (cached process-wide
  until shortly before it expires), so no static, expiring token is
  stored. `installation_id` is optional — when unset it is discovered
  from the pushed repository (`GET /repos/{owner}/{repo}/installation`).
  The App needs **Contents: Read-only**.

## Integration options

Asked once per Integration and delivered to every capability on
`PluginContext.integration_options`:

| Option   | Required  | Description                                                             |
| -------- | --------- | ----------------------------------------------------------------------- |
| `flavor` | yes       | `github`, `ghec`, or `ghes`.                                            |
| `host`   | GHEC/GHES | Tenant or appliance host (e.g. `tenant.ghe.com`, `github.example.com`). |

## Capability options

Scoped to one capability and delivered on
`PluginContext.capability_options`:

| Capability  | Option               | Description                                                                             |
| ----------- | -------------------- | --------------------------------------------------------------------------------------- |
| `identity`  | `default_scopes`     | Space-separated OAuth scopes (default: `read:user user:email repo workflow`).            |
| `lifecycle` | `archive_target_org` | Org to transfer repos to before archiving; blank archives in place.                     |
| `lifecycle` | `create_org`         | Default org for repo creation when no `org_mapping` entry matches.                       |
| `lifecycle` | `org_mapping`        | Per-project-type-slug org overrides; the first match wins over `create_org`.             |

## Credentials

One credential store per Integration — every capability receives the
same decrypted blob. All fields are individually optional and validated
per call, so an identity-only or App-only Integration is valid:

| Field             | Used by            | Description                                       |
| ----------------- | ------------------ | ------------------------------------------------- |
| `access_token`    | service (PAT mode) | Static personal/service token.                    |
| `app_id`          | service (App mode) | GitHub App identifier.                            |
| `private_key`     | service (App mode) | App private key — raw PEM or base64-encoded PEM.  |
| `installation_id` | service (App mode) | Optional; discovered from the repo when unset.    |
| `client_id`       | `identity`         | OAuth App client id.                              |
| `client_secret`   | `identity`         | OAuth App client secret.                          |

For the service capabilities (commit-sync, pr-sync, deployment,
lifecycle) provide **either** `access_token` **or** `app_id` +
`private_key`.

## License

BSD-3-Clause.
