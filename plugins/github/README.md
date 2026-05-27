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

## License

BSD-3-Clause.
