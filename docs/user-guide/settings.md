# Your settings

The **Settings** page holds the settings of your own account. To open it,
click your avatar at the right of the top bar, then click **Settings**.

The page has four tabs. Each tab has its own URL:

| Tab | URL | What it does |
|---|---|---|
| Account | `/settings/account` | Shows your email address, and changes your display name |
| Connections | `/settings/connections` | Connects your account to identity providers |
| API Keys | `/settings/api-keys` | Makes and revokes your personal API keys |
| Security | `/settings/security` | Not in operation in this release |

An unknown tab in the URL opens **Account**.

!!! warning "The Security tab is a placeholder"
    The **Security** tab shows controls that do not save anything. The API
    has no endpoint for them.

## Account

The **Account** tab shows your **Display name** and **Email address**.

- Click your display name to change it. Press Enter or click outside the
  field to save. The name cannot be empty. The API is
  `PATCH /users/me` with a JSON Patch on `/display_name`.
- You cannot change your email address here.

## Connections

A connection links your Imbi account to your account at an identity
provider, for example GitHub or AWS IAM Identity Center. With a
connection, Imbi runs AWS, GitHub, and OIDC operations as you, not as a
shared service principal.

A connection also tells Imbi your GitHub login. The **Mine** filter on the
**Pull Requests** tab and the "my pull requests" dashboard widgets use it.
See [Pull requests and dependencies](pull-requests-and-dependencies.md).

The table has one row for each integration that you can connect to. An
integration shows here when all of these are true:

- An administrator enabled a plugin with the identity capability.
- An administrator configured an integration of that plugin in the
  organization that you selected in the top bar.

Two integrations of one plugin (for example `github.com` and a GitHub
Enterprise host) have two rows. Each row connects separately. When no row
shows, the page says **No identity providers**. Ask your administrator to
configure one. See
[Integrations and plugins](../admin/integrations-and-plugins.md).

| Column | What it shows |
|---|---|
| Provider | The integration name, with the plugin name below it |
| Status | **Connected**, **Expired**, **Revoked**, or **Not connected** |
| Last used | When Imbi last used the connection |
| Actions | The buttons for the row. See below |

### Connect an account

1. Open **Settings > Connections**.
2. On the row of the provider, click **Connect**.
3. Sign in to the provider in the new browser tab, and approve the
   request. Imbi closes the tab when you finish.

If your browser blocks pop-ups, Imbi shows **Popup blocked. Please allow
popups and try again.** Allow pop-ups for Imbi and click **Connect** again.

Some providers, for example AWS IAM Identity Center, use a device code.
For these providers, Imbi opens the **Connect to \<provider\>** dialog:

1. Read the **Verification code** in the dialog.
2. Click **Open \<provider\>** if the provider page did not open.
3. On the provider page, make sure that it shows the same code. Approve
   the request.
4. Wait until the dialog shows **Connected.**, then click **Close**.

If the dialog shows that the code expired, click **Cancel** and start
again.

The dashboard also shows a card for each provider that you did not
connect. Click its connect button to start the same flow. You can dismiss
the card. The dismissal is kept in your browser only.

### Refresh, reconnect, or disconnect

| Status | Buttons |
|---|---|
| Not connected | **Connect** |
| Connected | **Refresh** gets a new token from the provider now. **Disconnect** removes the connection |
| Expired or Revoked | **Reconnect** starts the connect flow again. **Forget** removes the connection |

Imbi refreshes a token before it expires, so you do not usually need
**Refresh**.

**Disconnect** asks you to confirm. Imbi revokes the connection at the
provider when the provider allows it, and then removes it from Imbi.

Connections need the `me:identities:manage` permission. The `admin`,
`developer`, `default`, and `readonly` roles have it.

## API keys

An API key lets a script or tool call the Imbi API as you.

### Make a key

1. Open **Settings > API Keys**.
2. Click **+ Create new key**.
3. Enter a **Key name**, for example `Release script`. If you leave it
   empty, the name is `default`.
4. Click **Create key**.
5. Copy the key from the **API key created** dialog. Imbi shows it one
   time only. Imbi keeps only a hash of the secret.
6. Click **Done**.

The key has the form `ik_<32 hexadecimal characters>_<secret>`. The list
shows only the first part, the key id (`ik_<32 hexadecimal characters>`).
The copy button on a row copies the key id, not the secret.

A key that you make on this page:

- Has all of your permissions. If your roles change, the key changes with
  them.
- Does not expire.

The API can also make a key with an expiry date, a description, and
scopes (a subset of your permissions). The page has no controls for
these. Send `POST /api-keys` with `name`, `description`, `scopes`, and
`expires_in_days`. An expiry cannot be more than
`IMBI_AUTH_API_KEY_MAX_LIFETIME_DAYS` (default 365). The API also has
`POST /api-keys/{key_id}/rotate`, which gives a new secret for the same
key id.

### Use a key

Send the full key as a bearer token. `IMBI_API_URL` is the base URL of
the API in your installation, for example `https://imbi.example.com/api`:

```bash
curl -f -H "Authorization: Bearer ik_..." "$IMBI_API_URL/users/me"
```

Each row shows when you made the key and when a request last used it.

### Revoke a key

1. On the row of the key, click **Revoke**.
2. Click **Revoke key** to confirm.

A revoked key no longer shows in the list. Each API process keeps a
validated key in memory for up to 60 seconds. Thus a revoked key can
still work for up to 60 seconds.

For keys that are not personal, use a service account. See
[Service accounts](../admin/service-accounts.md).

## Security

The **Security** tab shows switches for two-factor authentication and
auto-logout, and buttons for sessions and access logs. None of them do
anything in this release. The **Current authentication method** box
always shows "Google OAuth", for every user.

### Multi-factor authentication

The API supports TOTP multi-factor authentication (MFA) for password
sign-in. The UI has no controls for it:

- Settings has no setup flow. Set up MFA with the API:
    1. `POST /mfa/setup` returns a QR code, the secret, and 10 one-time
       backup codes. Imbi shows the backup codes one time only.
    2. Add the secret to your authenticator app.
    3. `POST /mfa/verify` with a `code` from the app turns MFA on.
- `GET /mfa/status` shows whether MFA is on, and how many backup codes
  remain.
- `DELETE /mfa/disable` turns MFA off. Send `current_password`. A user
  with no password (SSO only) sends `mfa_code`.

!!! danger "Do not turn on MFA for a password account that uses the UI"
    When MFA is on, `POST /auth/login` needs an `mfa_code`. The sign-in
    page of the UI does not ask for a code. Thus a user with MFA on cannot
    sign in to the UI with a password. The **Reset MFA** button on the
    user's page in **Admin** is disabled, and the API has no
    administrator reset. To turn MFA off, call `DELETE /mfa/disable` with
    an access token that you got before you turned MFA on.

SSO sign-in does not use Imbi MFA. For the MFA settings, see
[Authentication](../admin/authentication.md#multi-factor-authentication).
