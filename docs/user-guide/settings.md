# Your settings

The **Settings** page holds the settings of your own account. To open it,
click your avatar at the right of the top bar, then click **Settings**.

The page has five tabs. Each tab has its own URL:

| Tab | URL | What it does |
|---|---|---|
| Account | `/settings/account` | Shows your display name and email address |
| Connections | `/settings/connections` | Connects your account to identity providers |
| Notifications | `/settings/notifications` | Not in operation in this release |
| API Keys | `/settings/api-keys` | Makes and revokes your personal API keys |
| Security | `/settings/security` | Not in operation in this release |

An unknown tab in the URL opens **Account**.

!!! warning "Three tabs are placeholders"
    The **Account**, **Notifications**, and **Security** tabs show controls
    that do not save anything. The API has no endpoint for them. A change
    stays in the browser until you leave the page. Use **Connections** and
    **API Keys** only.

## Account

The **Account** tab shows your **Display name** and **Email address**.

- You cannot change your email address here.
- You can type a new display name, but Imbi does not save it. To change
  your display name, ask an administrator. See
  [Users, teams, and organizations](../admin/users-teams-organizations.md).
- The **Email notifications** switch under **Preferences** does nothing.

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

## Notifications

The **Notifications** tab shows switches for deployment, health, and
operations log notifications, and the **Save preferences** and **Reset to
defaults** buttons. None of them do anything in this release. Imbi does
not send these notifications.

## Security

The **Security** tab has the two-factor authentication controls. It also
shows an auto-logout switch and buttons for sessions and access logs. These
do nothing in this release.

### Multi-factor authentication

Multi-factor authentication (MFA) asks for a code from an authenticator app
when you sign in with a password. To turn it on:

1. On the **Security** tab, click **Set up**.
2. Scan the QR code with your authenticator app, or enter the key below it.
3. Save the 10 backup codes. Imbi shows them one time only.
4. Enter the code from the app and click **Turn on**.

The tab then shows **On** and the number of backup codes that remain. When
you sign in, Imbi asks for the code after your password. A backup code also
works there, one time each.

To turn MFA off, click **Turn off** and enter your password. A user with no
password (SSO only) enters a code from the app or a backup code.

If you lose the app and the backup codes, ask an administrator to reset
your MFA
(see [Authentication](../admin/authentication.md#reset-a-users-mfa)).

SSO sign-in does not use Imbi MFA. For the MFA settings, see
[Authentication](../admin/authentication.md#multi-factor-authentication).
