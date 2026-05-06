# imbi-plugin-github

GitHub identity plugin for Imbi. Ships three entry points so the admin UI
can distinguish github.com, GitHub Enterprise Cloud, and GitHub Enterprise
Server installations:

| Entry point                | Slug                          | Host                                |
| -------------------------- | ----------------------------- | ----------------------------------- |
| `github`                   | `github`                      | `github.com`                        |
| `github-enterprise-cloud`  | `github-enterprise-cloud`     | `<tenant>.ghe.com`                  |
| `github-enterprise-server` | `github-enterprise-server`    | operator-supplied via the `host` option |

Phase 1 ships the OAuth App flow only; GitHub App installation tokens are
deferred. The access token returned by the OAuth grant is passed straight
to GitHub APIs as a `Bearer` token, so `materialize()` is a no-op.

## Manifest options

| Option           | Required  | Description                                                                |
| ---------------- | --------- | -------------------------------------------------------------------------- |
| `host`           | GHEC/GHES | Tenant or appliance host (e.g. `tenant.ghe.com`, `github.example.com`).    |
| `default_scopes` | no        | Space-separated default OAuth scopes (default: `read:user user:email`).    |

## Credentials

| Field            | Required |
| ---------------- | -------- |
| `client_id`      | yes      |
| `client_secret`  | yes      |

## License

BSD-3-Clause.
