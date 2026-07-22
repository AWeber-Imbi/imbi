# imbi-plugin-google

Google identity plugin for Imbi. Implements "Sign in with Google" using the
OAuth 2.0 authorization-code + PKCE flow against Google's fixed endpoints
(no discovery round-trip). A Google Workspace domain can be enforced by
Google itself via the `hd` authorization parameter.

## Manifest options

| Option           | Required | Description                                                                     |
| ---------------- | -------- | ------------------------------------------------------------------------------- |
| `hosted_domain`  | no       | Restrict sign-in to a Google Workspace domain (sent as `hd`, e.g. `example.com`).|
| `pkce_required`  | no       | Use PKCE (default: `true`).                                                      |
| `default_scopes` | no       | Space-separated default scopes (default: `openid profile email`).               |

## Credentials

| Field           | Required | Secret |
| --------------- | -------- | ------ |
| `client_id`     | yes      | no     |
| `client_secret` | yes      | yes    |

## License

BSD-3-Clause.
