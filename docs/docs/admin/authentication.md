# Authentication

Imbi supports multiple authentication methods that can be used
simultaneously. As an administrator, you configure these during
deployment via environment variables.

## Local Authentication

Local authentication allows users to sign in with an email address and
password. It is enabled by default and is the simplest way to get
started.

When creating a user account (or when users set their own password),
the following requirements apply:

- Minimum 12 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one digit
- At least one special character

To disable local authentication (for example, if you only want OAuth):

```
IMBI_AUTH_LOCAL_ENABLED=false
```

## Single Sign-On (OAuth2 / OIDC)

For organizations using a centralized identity provider, Imbi supports
OAuth2 and OpenID Connect. When configured, a "Sign in with ..."
button appears on the login page. Users who sign in via SSO for the
first time are automatically provisioned with a default role.

### Google

Add these environment variables to enable Google sign-in:

```
IMBI_AUTH_GOOGLE_CLIENT_ID=your-client-id
IMBI_AUTH_GOOGLE_CLIENT_SECRET=your-client-secret
```

### GitHub

```
IMBI_AUTH_GITHUB_CLIENT_ID=your-client-id
IMBI_AUTH_GITHUB_CLIENT_SECRET=your-client-secret
```

### Generic OIDC (Keycloak, Okta, etc.)

Any OpenID Connect-compatible provider can be used:

```
IMBI_AUTH_OIDC_CLIENT_ID=your-client-id
IMBI_AUTH_OIDC_CLIENT_SECRET=your-client-secret
IMBI_AUTH_OIDC_DISCOVERY_URL=https://your-idp/.well-known/openid-configuration
```

!!! tip
    Set `IMBI_AUTH_CALLBACK_BASE_URL` to the public URL of your Imbi
    instance (e.g. `https://imbi.example.com`) so that OAuth callbacks
    route correctly.

## Multi-Factor Authentication

Users can enable TOTP-based multi-factor authentication from their
profile settings page. Once enabled, they will be prompted for a
time-based one-time password after entering their credentials.

MFA is optional and user-managed -- administrators cannot force it at
this time, but it is recommended for accounts with elevated privileges.

## Sessions

Imbi manages sessions automatically:

- **Access tokens** expire after 15 minutes and are refreshed transparently
- **Refresh tokens** expire after 7 days
- Maximum 5 concurrent sessions per user
- Session timeout (inactivity): 24 hours (configurable via
  `IMBI_AUTH_SESSION_TIMEOUT`)

Users do not need to manage sessions directly. If a session expires,
they are redirected to the login page.
