# ADR 0010: Identity Plugin Architecture

## Status

Accepted

Implementation in progress; AWS IAM Identity Center identity flow is end-to-end working as of 2026-05-06. Source design lives in [`imbi/docs/identity-plugin-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/identity-plugin-plan.md).

## Context

The plugin system landed in ADR 0008 with two plugin types, `configuration` and `logs`. Both consume credentials stored on a `ServiceApplication` shared by every project that uses the plugin's `ThirdPartyService`. That means when a user opens the Logs tab against `aws-cloudwatch-logs`, the API runs `StartQuery` as a service principal — not as the human looking at the screen.

For three backend classes, caller identity matters:

1. **AWS IAM Identity Center / IAM**: least-privilege CloudWatch Logs Insights queries must run with the calling user's permissions, and CloudTrail attribution should record the actual user.
2. **GitHub / GHEC / GHES**: PR creation, workflow dispatches, and repo writes should be authored by the human, not a shared bot identity.
3. **Generic OIDC IdPs**: Okta, Auth0, Keycloak, Entra. The same federation that drives Imbi sign-in should also seed per-user outbound credentials.

There's also an organizational convergence: orgs that already federate AWS via Okta want the same Okta record to handle Imbi sign-in and to seed AWS STS credentials. Today, `ServiceApplication.usage='login'` (sign-in) is forked from credential-bearing service records, so the same vendor is configured twice.

## Decision

### 1. A third plugin type: `identity`

Add `identity` to the plugin type discriminator alongside `configuration` and `logs`. Identity plugins authenticate a **specific user** to a third-party system via OIDC or OIDC-shaped flows (SAML→OIDC bridge, OAuth 2.0 device code, AWS SSO `RegisterClient` + `StartDeviceAuthorization`).

### 2. Identity plugins can also be login providers

An identity plugin declares `used_as_login: bool` on its `Plugin` row. When set, the same record drives Imbi sign-in, and the federated session also seeds per-user credentials for outbound use. This collapses the v1 fork between sign-in records and credential-bearing service records.

ADR 0009's `OAuthProvider` continues to serve the simple "OAuth-for-login" case (GitHub OAuth, Google OAuth). Identity plugins are for federated flows where the same IdP both authenticates the user and provides outbound credentials.

### 3. Other plugin types declare an identity dependency

`configuration`, `logs`, and future plugin types declare `identity_plugin_id` on their `USES_PLUGIN` edge. At call time, the API:

1. Looks up the acting user's `IdentityConnection` to the referenced identity plugin.
2. Materializes ephemeral credentials (refreshing if necessary, exchanging tokens, calling `AssumeRoleWithWebIdentity`, etc.).
3. Passes the result through `PluginContext.identity` to the consuming handler.

`identity_plugin_id` is optional. When unset, the handler falls back to the shared `ServiceApplication` credentials (the pre-existing model). Both coexist; the assignment chooses which to use.

### 4. Per-user credentials live in a dedicated graph node

```
User -[:HAS_IDENTITY]-> IdentityConnection (plugin_id, user_id)
                         ├── subject
                         ├── access_token_encrypted
                         ├── refresh_token_encrypted (nullable)
                         ├── id_token_claims_encrypted (last seen, for audit)
                         ├── expires_at, scopes, status
```

A separate node — not edge properties — because:

- Refresh tokens, expiry, audit data, and revocation state are non-trivial state with their own lifecycle.
- Indexing on `(plugin_id, user_id)` is straightforward.
- The common `User -> Plugin` query stays cheap (no encrypted blob fetched).

All tokens are Fernet-encrypted using `IMBI_AUTH_ENCRYPTION_KEY` (the same key established by ADR 0004 and reused by ADR 0009).

### 5. First-party identity entry points

One package per third-party integration, multiple entry points per package:

- **`imbi-plugin-aws`** adds `aws-iam-ic` (identity) alongside `aws-ssm` (configuration) and `aws-cloudwatch-logs` (logs).
- **`imbi-plugin-github`** ships identity entry points for github.com, GHEC, and GHES. Future GitHub capabilities (PR-fact sync, workflow dispatch, deployments — ADR 0011) land in this package.
- **`imbi-plugin-oidc`** is the only "no specific vendor" package — generic OIDC code flow, replacing today's hardcoded `oauth_app_type='oidc'` path.

### 6. Static-key AWS auth is not a new plugin type

The existing `aws-ssm` / `aws-cloudwatch-logs` static-key model is preserved. The identity type covers federated/per-user flows only. A project assignment chooses which model to use via `identity_plugin_id` presence or absence.

## Consequences

### Positive

- Least-privilege outbound calls: CloudWatch queries, GitHub mutations, and similar actions run as the human.
- CloudTrail / GitHub audit log attribution is accurate.
- Single Okta (or similar) record drives both sign-in and outbound credentials.
- Plugin authors get a uniform shape (`IdentityProfile`, `IdentityCredentials`) for federation flows.

### Negative

- The credential resolution path branches on `identity_plugin_id`. Handlers receive credentials through `PluginContext` from either source; the contract papers over the difference, but the host-side resolver is more complex than the pre-existing `ServiceApplication` lookup.
- Per-user credential storage scales with `users × identity_plugins`. Encrypted blobs are small (KB-scale per row); not a real concern at expected tenant sizes.
- Token refresh failures become a per-user, per-plugin error class. The UI surfaces them on a "Connections" page with explicit reconnect/forget actions.

### Risks Accepted

- **Cross-tenant/cross-org sharing**: out of scope. An `IdentityConnection` is local to `(User, Plugin)`. If an org needs shared identities, the answer is shared accounts on the IdP side, not Imbi-side sharing.
- **Long-lived non-user tokens for automation**: still use `ServiceApplication`. Gateway and `imbi-automations` workflows continue with shared credentials when they aren't user-driven.
- **SAML SP support**: explicitly deferred. We consume SAML via the IdP's OIDC bridge when offered. The forward-looking SAML SP plan (ADR-shaped but not yet implemented) is captured in [`imbi/docs/saml-support-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/saml-support-plan.md).

## References

- [`imbi/docs/identity-plugin-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/identity-plugin-plan.md) — Design plan.
- [`imbi/docs/identity-plugin-implementation-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/identity-plugin-implementation-plan.md) — Implementation mapping.
- [`imbi/docs/identity-plugin-assignment-binding-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/identity-plugin-assignment-binding-plan.md) — End-to-end `identity_plugin_id` plumbing.
- [`imbi/docs/identity-per-environment-credentials-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/identity-per-environment-credentials-plan.md) — Per-environment AWS account mapping.
- ADR 0008: Plugin System Architecture
- ADR 0009: Database-Driven OAuth Provider Configuration
