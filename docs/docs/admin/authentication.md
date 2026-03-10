# Authentication

Imbi supports multiple authentication methods that can be used
simultaneously.

## Local Authentication

Local authentication uses email and password credentials stored in Neo4j
with Argon2 password hashing.

Password requirements:

- Minimum 12 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one digit
- At least one special character

Local authentication is enabled by default. Disable it with:

```
IMBI_AUTH_LOCAL_ENABLED=false
```

## OAuth2 / OIDC

Imbi supports OAuth2/OIDC authentication with the following providers:

### Google

Set the following environment variables:

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

```
IMBI_AUTH_OIDC_CLIENT_ID=your-client-id
IMBI_AUTH_OIDC_CLIENT_SECRET=your-client-secret
IMBI_AUTH_OIDC_DISCOVERY_URL=https://your-idp/.well-known/openid-configuration
```

## Multi-Factor Authentication

Imbi supports TOTP-based MFA. Users can enable MFA from their profile
settings. When enabled, users must provide a time-based one-time password
in addition to their primary credentials.

## Sessions

Sessions are managed via JWT tokens:

- **Access tokens** expire after 15 minutes
- **Refresh tokens** expire after 7 days
- Maximum 5 concurrent sessions per user
- Session timeout (inactivity): 24 hours (configurable)
