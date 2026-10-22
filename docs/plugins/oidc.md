# OIDC

The `oidc` plugin signs users in to Imbi with any OpenID Connect provider,
for example Keycloak or Okta. It uses the authorization-code flow, with
PKCE by default.

You use it as a login provider. See
[Authentication](../admin/authentication.md#sso-login-providers).

## Capabilities

| Capability | Label | Default | Scope |
|---|---|---|---|
| `identity` | Sign in with OIDC | Off | Organization-wide. Can sign users in. The login button text is **Sign in with SSO** |

## Configuration

### Options

| Option | Label | Required | Meaning |
|---|---|---|---|
| `issuer_url` | Issuer URL | Yes | The issuer URL, with no trailing slash. Imbi reads `<issuer_url>/.well-known/openid-configuration` |
| `authorization_endpoint` | Authorization endpoint | No | Use this URL instead of the discovered one |
| `token_endpoint` | Token endpoint | No | Use this URL instead of the discovered one |
| `userinfo_endpoint` | Userinfo endpoint | No | Use this URL instead of the discovered one |
| `revocation_endpoint` | Revocation endpoint | No | Use this URL instead of the discovered one |
| `audience` | Audience | No | Sent as the `audience` parameter of the authorization request |
| `pkce_required` | Require PKCE | No | Default `true`. Send a PKCE challenge |
| `default_scopes` | Default scopes (space-separated) | No | Default `openid profile email`. Separate scopes with spaces |

### Credentials

| Credential | Required | Secret | Meaning |
|---|---|---|---|
| `client_id` | Yes | Yes | The OAuth client ID |
| `client_secret` | No | Yes | The OAuth client secret. A public client with PKCE needs none |

Register the Imbi callback URL with the provider. See
[Callback URL](../admin/authentication.md#callback-url).

## Behavior

- Imbi reads the discovery document on the first request and keeps it in
  memory for 24 hours in each API process.
- Imbi gets the user profile from the userinfo endpoint. It reads `sub`,
  `email`, `email_verified`, `name`, `picture`, and `groups`.
- Imbi uses `email` and `email_verified` to find or create the user. A
  provider that does not send `email_verified: true` cannot sign in a user
  that already exists. See
  [First sign-in](../admin/authentication.md#first-sign-in).
- When a user disconnects the identity, Imbi sends the token to the
  revocation endpoint, if there is one.

## Doctor checks

None.

## Webhook actions

None.

## Lifecycle

None.

## Known limits

- Imbi does not use the ID token, so it does not validate one. It gets
  the profile from the userinfo endpoint with the access token, over
  TLS.
- The plugin reads `groups`, but Imbi does not map groups to teams or
  roles.
- A change to the discovery document shows only after the 24-hour cache
  expires or the API restarts.
