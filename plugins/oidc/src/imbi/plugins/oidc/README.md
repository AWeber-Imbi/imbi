# imbi-plugin-oidc

Generic OIDC identity plugin for Imbi. Implements the OIDC authorization
code + PKCE flow against any provider that publishes a
`.well-known/openid-configuration` discovery document.

## Manifest options

| Option                   | Required | Description                                                            |
| ------------------------ | -------- | ---------------------------------------------------------------------- |
| `issuer_url`             | yes      | OIDC issuer URL (no trailing slash).                                   |
| `authorization_endpoint` | no       | Override the discovered authorization endpoint.                        |
| `token_endpoint`         | no       | Override the discovered token endpoint.                                |
| `userinfo_endpoint`      | no       | Override the discovered userinfo endpoint.                             |
| `jwks_uri`               | no       | Override the discovered JWKS URI.                                      |
| `revocation_endpoint`    | no       | Override the discovered revocation endpoint (optional in OIDC).        |
| `audience`               | no       | Audience parameter sent on `/authorize`.                               |
| `pkce_required`          | no       | Force PKCE for public clients (default: `true`).                       |
| `default_scopes`         | no       | Comma-separated default scopes (default: `openid profile email`).      |

## Credentials

| Field            | Required                       |
| ---------------- | ------------------------------ |
| `client_id`      | yes                            |
| `client_secret`  | only when `pkce_required=false` |

## License

BSD-3-Clause.
