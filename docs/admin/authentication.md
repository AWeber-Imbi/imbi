# Authentication

Users sign in to Imbi with an email address and a password, with a single
sign-on (SSO) login provider, or with both. You configure the sign-in
methods in the database, on the **Auth Providers** page. Environment
variables control only the secrets, the token lifetimes, and some SSO
behavior.

To open the page, click **Admin** in the top bar, then
**Global Admin > Auth Providers**. The **Admin** menu shows only for
platform administrators.

## Local authentication

Local authentication is sign-in with an email address and a password that
Imbi stores. It is enabled by default.

The **Local Authentication** card on the **Auth Providers** page has an
**Enabled** switch. When you disable it, the login page does not show the
email and password form. The setting is in the database, so it applies to
all API processes. A change can take up to 30 seconds to show, because each
process caches the value.

!!! warning
    The switch hides the form only. The `POST /auth/login` endpoint
    continues to accept passwords from users that have one. To stop
    password sign-in for a user, disable the user.

| Permission | Lets you |
|---|---|
| `auth_providers:read` | See the setting (`GET /admin/local-auth`) |
| `auth_providers:write` | Change the setting (`PUT /admin/local-auth`) |

Only the `admin` role has these permissions.

### Password rules

Imbi checks these rules when a user changes a password:

- Minimum 12 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one digit
- At least one special character from `!@#$%^&*()_+-=[]{}|;:,.<>?`

The rules are fixed. The `IMBI_AUTH_PASSWORD_*` settings exist, but the
API does not read them. Imbi does not apply the rules to the password that
an administrator sets when they create a user.

## SSO login providers

A login provider is an integration of a plugin that can sign users in.
These plugins can do this:

| Plugin | Sign-in method |
|---|---|
| `google` | Google OAuth 2.0 with PKCE |
| `github` | GitHub OAuth app |
| `oidc` | Any OpenID Connect provider, for example Keycloak or Okta |
| `aws` | AWS IAM Identity Center (device-code flow) |

Login providers are global. Users sign in before they select an
organization, so a login provider does not belong to an organization.
Each plugin can have one login provider. Only one provider at a time can be
used for sign-in.

### Add a login provider

1. Enable the plugin at **Admin > Global Admin > Plugins**.
2. Open **Admin > Global Admin > Auth Providers**.
3. In the **SSO Login Provider** card, click **Add auth provider**.
4. Select the plugin in **Provider**.
5. Enter the credentials and options. The fields come from the plugin.
   For example, `google` and `oidc` ask for **Client ID** and
   **Client secret**, and `oidc` asks for **Issuer URL**.
6. Set **Use for sign-in now** to use the provider immediately.
7. Click **Create**.

Imbi encrypts the credentials with `IMBI_AUTH_ENCRYPTION_KEY` before it
stores them.

To change the provider that users sign in with, use the switch on the
provider row. When you turn on a provider, Imbi turns off the provider that
was in use. You cannot turn on a provider whose status is not `active`.
When a provider is in use, the login page shows a button for it.

| Permission | Lets you |
|---|---|
| `integration:read` | See the login providers |
| `integration:create` | Add a login provider |
| `integration:update` | Change credentials and options, and turn a provider on or off |
| `integration:delete` | Delete a login provider |

The Google plugin has a **Workspace domain** option. Imbi sends it to Google
as the `hd` parameter, and it rejects a sign-in unless the `hd` claim that
Google returns matches the option. Personal Google accounts have no `hd`
claim, so Imbi rejects them. The generic **Allowed domains** option of a login
provider is not enforced yet
([#472](https://github.com/AWeber-Imbi/imbi/issues/472)).

### Callback URL

Register this redirect URL with the identity provider:

```text
<IMBI_API_URL>/auth/oauth/<provider-slug>/callback
```

`IMBI_API_URL` is the public URL of the API, with its path prefix. The
provider slug is the plugin slug. For example, if `IMBI_API_URL` is
`https://imbi.example.com/api`, the Google callback URL is
`https://imbi.example.com/api/auth/oauth/google/callback`.

If `IMBI_API_URL` is not set, Imbi uses
`http://<IMBI_API_HOST>:<IMBI_API_PORT>` with no prefix. That value is
correct only for local development.

If you serve Imbi on more than one host, Imbi builds the callback URL from
the host of the sign-in request. It does this only when that host is in
`IMBI_API_CORS_ALLOWED_ORIGINS` or is the host of `IMBI_API_URL`. For all
other hosts, it uses `IMBI_API_URL`.

### First sign-in

When a user signs in through a login provider, Imbi finds the user by the
email address that the provider returns:

- **No user has that email.** Imbi creates the user when
  `IMBI_AUTH_OAUTH_AUTO_CREATE_USERS` is `true` (the default). If it is
  `false`, sign-in fails.
- **A user has that email.** Imbi links the sign-in to that user when
  `IMBI_AUTH_OAUTH_AUTO_LINK_BY_EMAIL` is `true` (the default) and the
  provider says that the email is verified. If the setting is `false`,
  sign-in through a login provider fails for every user that already
  exists.

Service accounts cannot sign in through a login provider.

### Default organization and role

After each sign-in, Imbi examines the organization memberships of the user.
If the user has none, Imbi adds the user to an organization with the
default role:

- The role is the role marked as the default. The seeded default role is
  `default`.
- The organization is the only organization, if there is only one.
  If not, it is the organization with the slug `default`.
- If Imbi cannot find the role or the organization, it logs a warning and
  adds no membership. Sign-in continues, but the user has no permissions.

## Multi-factor authentication

Imbi supports TOTP multi-factor authentication (MFA). A user turns it on
and off on **Settings > Security**
(see [Settings](../user-guide/settings.md#multi-factor-authentication)).
The API equivalents are `POST /mfa/setup`, `POST /mfa/verify` and
`DELETE /mfa/disable`.

When MFA is on, the sign-in page asks for a code after the password is
correct. The user enters the code from the authenticator app, or one of the
backup codes. Each backup code works one time.

### Reset a user's MFA

If a user loses the authenticator app and the backup codes, reset their MFA:

1. Open **Admin > Users** and open the user.
2. In **Security**, click **Reset MFA** and confirm.

The reset deletes the user's TOTP secret and backup codes. A user with a
password then signs in with the password only and can set up MFA again. A
user without a password continues to sign in with SSO. You cannot reset
your own MFA here; use **Settings > Security**. The API is
`DELETE /users/{email}/mfa`. It needs the `user:update` permission, the same
permission that lets an administrator reset another user's password.

MFA applies to password sign-in only. SSO sign-in does not ask for an Imbi
MFA code. Administrators cannot make MFA mandatory.

| Variable | Default | Description |
|---|---|---|
| `IMBI_AUTH_MFA_ISSUER_NAME` | `Imbi` | Issuer name that authenticator apps show |
| `IMBI_AUTH_MFA_TOTP_PERIOD` | `30` | TOTP time step, in seconds |
| `IMBI_AUTH_MFA_TOTP_DIGITS` | `6` | Number of digits in a code |

## Tokens

Imbi issues an access token and a refresh token at sign-in. The UI uses the
refresh token to get a new access token. When the refresh token expires,
the user must sign in again.

| Variable | Default | Description |
|---|---|---|
| `IMBI_AUTH_ACCESS_TOKEN_EXPIRE_SECONDS` | `3600` (1 hour) | Access token lifetime |
| `IMBI_AUTH_REFRESH_TOKEN_EXPIRE_SECONDS` | `2592000` (30 days) | Refresh token lifetime |
| `IMBI_AUTH_API_KEY_MAX_LIFETIME_DAYS` | `365` | Maximum lifetime of a new API key or client credential |

Users make their own API keys at **Settings > API Keys**.

## Required secrets

Set these two variables in every deployment:

| Variable | Description |
|---|---|
| `IMBI_AUTH_JWT_SECRET` | Secret that signs the tokens |
| `IMBI_AUTH_ENCRYPTION_KEY` | Fernet key that encrypts provider credentials and tokens |

When `ENVIRONMENT` is not `development`, Imbi does not start if one of
these variables is not set. `IMBI_CONFIG_ENCRYPTION_KEY` has the same rule.
In development, Imbi makes random values at start. Then each restart makes
all tokens and all encrypted values unusable.

!!! note
    The variable is `ENVIRONMENT`, with no `IMBI_` prefix. Its default is
    `development`.

## Rate limits

Imbi limits these requests for each client IP address:

| Request | Limit |
|---|---|
| `POST /auth/login` | 5 per minute |
| `POST /auth/token/refresh` | 10 per minute |
| `GET /auth/oauth/{provider}` | 3 per minute |
| `GET /auth/oauth/{provider}/callback` | 10 per minute |
| `POST /auth/logout` | 30 per minute |
| `POST /mfa/verify` | 5 per minute |

The limits are fixed in the code. The `IMBI_AUTH_RATE_LIMIT_*` settings
exist, but the API does not read them. Behind a reverse proxy, set
`IMBI_API_FORWARDED_ALLOW_IPS` to the proxy addresses. If you do not, Imbi
counts all requests against the proxy address.

## MCP clients

Imbi is an OAuth 2.0 authorization server for MCP clients. Clients find it
at `/.well-known/oauth-authorization-server`. A client can register itself
at `POST /auth/register` (dynamic client registration, RFC 7591). To stop
this, set `IMBI_AUTH_DCR_ENABLED` to `false`. Then you must provision each
client out of band.
