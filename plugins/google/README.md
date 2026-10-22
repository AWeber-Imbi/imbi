# imbi-plugin-google

Google identity plugin for Imbi. Implements "Sign in with Google" using the
OAuth 2.0 authorization-code + PKCE flow against Google's fixed endpoints
(no discovery round-trip). When `hosted_domain` is set, the plugin sends it
as the `hd` authorization hint and rejects any account whose `hd` claim does
not match. Personal Google accounts have no `hd` claim, so they are rejected.

## Manifest options

| Option           | Required | Description                                                                     |
| ---------------- | -------- | ------------------------------------------------------------------------------- |
| `hosted_domain`  | no       | Restrict sign-in to a Google Workspace domain (enforced on the `hd` claim, e.g. `example.com`).|
| `pkce_required`  | no       | Use PKCE (default: `true`).                                                      |
| `default_scopes` | no       | Space-separated default scopes (default: `openid profile email`).               |

## Credentials

| Field           | Required | Secret |
| --------------- | -------- | ------ |
| `client_id`     | yes      | no     |
| `client_secret` | yes      | yes    |

## License

BSD-3-Clause.
