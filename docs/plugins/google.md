# Google

The `google` plugin signs users in to Imbi with a Google account or a
Google Workspace account. It uses the OAuth 2.0 authorization-code flow
with PKCE against the fixed Google endpoints. It does not use OIDC
discovery.

You use it as a login provider. See
[Authentication](../admin/authentication.md#sso-login-providers).

## Capabilities

| Capability | Label | Default | Scope |
|---|---|---|---|
| `identity` | Sign in with Google | Off | Organization-wide. Can sign users in |

## Configuration

### Options

| Option | Label | Default | Meaning |
|---|---|---|---|
| `hosted_domain` | Workspace domain | (empty) | A Google Workspace domain, for example `example.com`. When set, Imbi accepts only accounts whose `hd` claim is this domain. Leave it empty to accept any Google account |
| `pkce_required` | Require PKCE | `true` | Send a PKCE challenge with the authorization request |
| `default_scopes` | Default scopes (space-separated) | `openid profile email` | The OAuth scopes to request |

### Credentials

| Credential | Required | Secret | Meaning |
|---|---|---|---|
| `client_id` | Yes | No | The OAuth client ID from the Google Cloud console |
| `client_secret` | Yes | Yes | The OAuth client secret |

Make an OAuth client in the Google Cloud console. Add the Imbi callback
URL to it as an authorized redirect URI. See
[Callback URL](../admin/authentication.md#callback-url).

## Workspace domain

When `hosted_domain` is set, Imbi does two things:

1. It sends the domain to Google as the `hd` parameter. Google then shows
   only accounts of that domain on its sign-in page.
2. After the code exchange, it compares the `hd` claim of the user profile
   with the domain. The comparison ignores case. If the claim is different
   or absent, sign-in fails.

The `hd` parameter alone is not a control, because a user can remove it
from the URL. Step 2 is the control. Google sets the `hd` claim only for
Workspace accounts. Thus, when the option is set, personal Google accounts
cannot sign in, even when their email address ends in the domain.

## Behavior

- The plugin asks for offline access and always shows the consent screen,
  so that Google returns a refresh token.
- On refresh, Google does not return a new refresh token. The plugin keeps
  the old one.
- Imbi uses the `email` and `email_verified` claims from the Google
  userinfo endpoint to find or create the user.

## Doctor checks

None.

## Webhook actions

None.

## Lifecycle

None.

## Known limits

- One domain only. You cannot allow two Workspace domains with one
  integration.
- The plugin does not read Google groups.
