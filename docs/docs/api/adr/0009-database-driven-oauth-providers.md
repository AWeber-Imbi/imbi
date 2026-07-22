# ADR 0009: Database-Driven OAuth Provider Configuration

## Status

Accepted

Implementation in progress. Source design lives in [`imbi/docs/oauth-db-config-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/oauth-db-config-plan.md).

## Context

OAuth provider credentials (Google, GitHub, generic OIDC client IDs and secrets) were initially configured via `IMBI_AUTH_OAUTH_GOOGLE_CLIENT_ID`, `IMBI_AUTH_OAUTH_GITHUB_CLIENT_SECRET`, and similar environment variables. Three properties of that design were problematic:

1. **Operators can't manage providers from the admin UI.** Adding or rotating a credential requires a deploy, an env-var update, and a process restart. Imbi's admin surface already manages users, blueprints, webhooks, and service applications; OAuth providers should not be an exception.
2. **One OIDC slot only.** A single `IMBI_AUTH_OAUTH_OIDC_*` block can't represent two tenant-specific OIDC IdPs (Okta plus Auth0, for example) because the env-var slot is singular.
3. **Tokens for the same providers are already encrypted in the graph.** `OAuthIdentity` rows store per-user provider tokens via `imbi_common.auth.encryption.TokenEncryption` (Fernet, key in `IMBI_AUTH_ENCRYPTION_KEY`). The provider configuration sits awkwardly in env vars while the runtime state already lives in the graph with established encryption tooling.

Imbi v2 is in alpha. There are no production deployments to migrate, so we do not need an env-var fallback path.

## Decision

### 1. OAuth provider configuration moves to the graph

A new `OAuthProvider` node type stores per-provider configuration:

```
OAuthProvider:
  slug: Literal['google','github','oidc']         # primary key, merge key
  type: Literal['google','github','oidc']         # dispatch key for profile normalization
  name: str                                       # display name
  enabled: bool
  client_id: str | None
  client_secret_encrypted: str | None             # Fernet ciphertext
  issuer_url: str | None                          # OIDC only
  allowed_domains: list[str]                      # Google email-domain gate
  icon: str                                       # 'google' | 'github' | 'key'
  created_at: datetime
  updated_at: datetime
```

`slug` is the merge key. Keeping `slug` distinct from `type` reserves headroom for multiple OIDC IdPs (`slug='okta'`, `slug='auth0'`, both with `type='oidc'`) without breaking the existing `OAuthIdentity.provider` literal.

### 2. Client secrets are Fernet-encrypted at rest

The existing `TokenEncryption` singleton (keyed by `IMBI_AUTH_ENCRYPTION_KEY`) encrypts `client_secret_encrypted` on write. Response models redact the secret entirely; admin UI offers a write-only "Replace secret" affordance and an `has_secret: bool` indicator. Plaintext never round-trips through the model.

### 3. Repository layer with a short in-memory cache

A new `imbi_api.auth.providers` module exposes `list_providers`, `get_provider`, `upsert_provider`, `delete_provider`. A 30-second TTL cache keyed by slug keeps the graph off the OAuth hot path; writes invalidate the cache. If multi-replica deployments later need immediate propagation, the cache backend swaps to Valkey pub/sub.

### 4. Admin endpoints gated by new permissions

```
GET    /admin/oauth-providers
GET    /admin/oauth-providers/{slug}
PUT    /admin/oauth-providers/{slug}
DELETE /admin/oauth-providers/{slug}
```

Two new permissions: `oauth-providers:read` and `oauth-providers:write`. `oauth-providers:write` is assigned to the admin role at seed time.

### 5. Per-provider env vars are removed

`IMBI_AUTH_OAUTH_GOOGLE_CLIENT_ID`, `IMBI_AUTH_OAUTH_GOOGLE_CLIENT_SECRET`, `IMBI_AUTH_OAUTH_GITHUB_*`, and `IMBI_AUTH_OAUTH_OIDC_*` are deleted from `Auth`. The following auth settings remain in env vars because they are deployment concerns, not per-provider:

- `IMBI_AUTH_OAUTH_AUTO_LINK_BY_EMAIL`
- `IMBI_AUTH_OAUTH_AUTO_CREATE_USERS`
- (Plus the public callback base URL which is derived from `IMBI_API_URL`.)

### 6. `/auth/providers` becomes a single DB-driven loop

`endpoints/auth.py:get_auth_providers` replaces the hardcoded per-provider blocks with a single `list_providers(db, enabled_only=True)` query. The UI's `LoginPage` and `OAuthManagement` components are already provider-agnostic and consume `/auth/providers` directly.

## Consequences

### Positive

- Operators add and rotate OAuth providers without a deploy.
- The schema accommodates multiple OIDC tenants by slug.
- Encryption tooling already validated for `OAuthIdentity` tokens is reused unchanged.
- `Auth` settings shrink to genuine deployment knobs.

### Negative

- `IMBI_AUTH_ENCRYPTION_KEY` becomes load-bearing for both `OAuthIdentity` tokens **and** provider client secrets. Losing the key wipes both — operations must treat it as a long-lived secret and back it up alongside other tier-1 secrets.
- Bootstrap order matters: an empty install has no providers, so first-login is local-password only until an admin configures a provider through the admin UI.
- Cache TTL means admin edits propagate within 30 seconds across replicas (acceptable given operator-driven, low-churn writes).

### Risks Accepted

- Secret leakage via response models is prevented by a separate read model that has no secret field. We do not call `model_dump()` on the graph node directly in responses; the strict `OAuthProviderRead` schema is the only response shape.
- Cross-replica cache coherence is loose by design. If immediate propagation becomes a hard requirement, switch the cache to Valkey pub/sub.

## References

- [`imbi/docs/oauth-db-config-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/oauth-db-config-plan.md) — Full design and order of work.
- [`imbi/docs/saml-support-plan.md`](https://github.com/AWeber-Imbi/imbi/blob/main/docs/saml-support-plan.md) — Forward-looking SAML SP support, modeled on this design.
- ADR 0002: Authentication and Authorization Architecture
- ADR 0004: Phase 5 Authentication Enhancements (Fernet encryption)
