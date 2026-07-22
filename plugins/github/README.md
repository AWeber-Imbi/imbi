# imbi-plugin-github

GitHub plugins for Imbi. Three flavors (github.com, GitHub Enterprise Cloud,
GitHub Enterprise Server) of each plugin type so the admin UI can wire
projects to the right backend.

## Plugin types

| Type       | Slugs                                                                |
| ---------- | -------------------------------------------------------------------- |
| Identity   | `github`, `github-enterprise-cloud`, `github-enterprise-server`      |
| Deployment | `github-deployment`, `github-deployment-ec`, `github-deployment-es`  |
| Lifecycle  | `github-lifecycle`, `github-lifecycle-ec`, `github-lifecycle-es`     |
| Webhook    | `github-commit-sync`                                                  |

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

### Webhook (commit / tag sync)

A single `github-commit-sync` webhook-action plugin exposes two actions
the gateway dispatches on `push` deliveries:

| Action         | Handler                          | Records into ClickHouse |
| -------------- | -------------------------------- | ----------------------- |
| `sync_commits` | `github-commit-sync#sync_commits`| `commits`               |
| `sync_tags`    | `github-commit-sync#sync_tags`   | `tags`                  |

`sync_commits` fetches the full set of commits in a push via the compare
API (paginated, so it isn't capped by the 20-commit inline payload limit);
`sync_tags` records the pushed tag and, with `reconcile_all`, the repo's
full tag list. Branch/tag gating is the rule's CEL `filter_expression`
(e.g. `ref == "refs/heads/main"`, `ref.startsWith("refs/tags/")`). The API
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

## Manifest options (identity)

| Option           | Required  | Description                                                                |
| ---------------- | --------- | -------------------------------------------------------------------------- |
| `host`           | GHEC/GHES | Tenant or appliance host (e.g. `tenant.ghe.com`, `github.example.com`).    |
| `default_scopes` | no        | Space-separated default OAuth scopes (default: `read:user user:email repo workflow`). |

## Credentials (identity)

| Field            | Required |
| ---------------- | -------- |
| `client_id`      | yes      |
| `client_secret`  | yes      |

## Credentials (commit-sync)

Provide **either** the PAT field **or** the GitHub App fields (all
individually optional; validated per call):

| Field             | Mode | Description                                            |
| ----------------- | ---- | ------------------------------------------------------ |
| `access_token`    | PAT  | Static personal/service token.                         |
| `app_id`          | App  | GitHub App identifier.                                 |
| `private_key`     | App  | App private key — raw PEM or base64-encoded PEM.       |
| `installation_id` | App  | Optional; discovered from the repo when unset.         |

## License

BSD-3-Clause.
