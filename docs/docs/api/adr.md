# Architecture Decision Records

This page documents the key architectural decisions made during the development of Imbi v2. We use Architecture Decision
Records (ADRs)
as [described by Michael Nygard](http://thinkrelevance.com/blog/2011/11/15/documenting-architecture-decisions) to
capture important architectural choices and their rationale.

## What is an ADR?

An Architecture Decision Record (ADR) is a document that captures an important architectural decision made along with
its context and consequences. Each ADR describes:

- **Context**: The issue or requirement that prompted the decision
- **Decision**: The change or approach being proposed or adopted
- **Status**: Whether the decision is proposed, accepted, deprecated, or superseded
- **Consequences**: The positive and negative outcomes of the decision

## ADR Index

### Core Architecture

#### [ADR 0001: Record Architecture Decisions](adr/0001-record-architecture-decisions.md)

*Date: 2025-12-30 | Status: Accepted*

Establishes the practice of using Architecture Decision Records to document architectural decisions on this project,
following Michael Nygard's format.

**Key Points:**

- Lightweight ADR process adopted
- ADRs stored in version control alongside code
- Provides historical context for architectural choices

---

#### [ADR 0002: Authentication and Authorization Architecture](adr/0002-authentication-and-authorization-architecture.md)

*Date: 2025-12-30 | Status: Accepted*

Comprehensive design for Imbi's authentication and authorization system, including OAuth2/OIDC integration, JWT tokens,
API keys, and permission management.

**Key Decisions:**

- Graph database (originally Neo4j, since migrated to Apache AGE on PostgreSQL — see ADR 0006/0007) for user and permission data (natural fit for permission inheritance)
- ClickHouse for audit logs (time-series optimized with automatic TTL)
- JWT tokens with revocation list (stateless with security)
- Argon2id for password hashing (modern, memory-hard algorithm)
- Hybrid RBAC + resource-level permissions (flexible and powerful)
- FastAPI dependency injection for authorization (not middleware)
- Dual authentication for services (JWTs and API keys)

**Authentication Methods:**

- Local username/password
- OAuth2 (GitHub, Google, Generic OIDC)
- JWT tokens for API access
- API keys for service-to-service communication

---

#### [ADR 0003: Email Sending Architecture](adr/0003-email-sending-architecture.md)

*Date: 2026-01-01 | Status: Accepted*

Design for transactional email system supporting password reset, welcome emails, email verification, and security
alerts.

**Key Decisions:**

- Direct SMTP using Python's `smtplib` (no vendor lock-in)
- Templates stored in source code (version control, code review)
- FastAPI BackgroundTasks for async delivery (simple, no infrastructure)
- Exponential backoff retry with dead letter queue
- Mailpit for development testing (web UI, SMTP server in Docker)
- ClickHouse for email audit logs (1-year retention)
- Jinja2 with dual HTML/text templates (accessibility)
- Table-based layout with inline CSS (email client compatibility)

**Email Types:**

- Password reset
- Welcome messages
- Email verification
- Security notifications

#### [ADR 0004: Phase 5 Authentication Enhancements](adr/0004-phase-5-authentication-enhancements.md)

*Date: 2026-01-01 | Status: Accepted*

Seven security and usability enhancements to the authentication system, addressing gaps identified after Phase 4
completion.

**Key Enhancements:**

1. **Token Revocation**: Implement actual logout (complete Phase 2 TODO)
2. **OAuth Token Encryption**: Encrypt provider tokens using Fernet
3. **Rate Limiting**: Using slowapi library to prevent brute force
4. **API Keys**: Full-featured API keys with scopes and usage tracking
5. **Session Management**: Enforce max concurrent sessions setting
6. **MFA/2FA**: TOTP-based multi-factor authentication with backup codes
7. **Token Rotation**: Rotate refresh tokens on every use (security best practice)

**Security Improvements:**

- OAuth tokens encrypted at rest (Fernet symmetric encryption)
- Token revocation on logout (immediate invalidation)
- Rate limiting on auth endpoints (5/min login, 10/min refresh, etc.)
- MFA support with TOTP and backup codes
- Refresh token rotation (detects token theft)
- Session limits (prevent session hijacking)

**API Keys:**

- Format: `ik_<16chars>_<32chars>` for easy identification
- Scoped permissions (least privilege)
- Usage tracking in ClickHouse
- Rotation support
- Expiration enforcement

---

#### [ADR 0005: File Upload Storage Architecture](adr/0005-file-upload-storage-architecture.md)

*Date: 2026-02-06 | Status: Accepted*

Design for general-purpose file upload system backed by S3-compatible storage, supporting icons, avatars, and documents
for all Node-based entities.

**Key Decisions:**

- S3-compatible object storage with aioboto3 for async operations
- LocalStack for development (full AWS API emulation)
- Apache AGE (PostgreSQL) for upload metadata (consistent with all other entities)
- Presigned URL redirects (307) for efficient file serving
- Pillow for thumbnail generation, filetype for magic-byte validation
- WEBP thumbnails at 256x256 max, maintaining aspect ratio

**Upload Features:**

- Content type validation with magic-byte verification
- Configurable size limits (default 50 MB)
- Automatic thumbnail generation for raster images
- Permission-based access control (upload:create, upload:read, upload:delete)

---

#### [ADR 0006: Project Identity and Multi-Type Support](adr/0006-project-identity-and-multi-type.md)

*Date: 2026-02-13 | Status: Accepted*

Replaces single-type, slug-keyed project identity with a Nano-ID primary key and many-to-many project type relationships, enabling stable URLs and natural blueprint composition.

**Key Decisions:**

- Nano-ID (21-char URL-safe) as the canonical project identifier
- Many `Project -[:TYPE]-> ProjectType` relationships (was: single)
- Blueprint aggregation across all of a project's types, merged by priority
- API paths shift from `/projects/{type_slug}/{slug}` to `/projects/{id}`

---

#### [ADR 0007: Relationship Blueprints](adr/0007-relationship-blueprints.md)

*Date: 2026-02-20 | Status: Proposed*

Extends the blueprint system to relationships (edges), so admins can add custom properties to `[:DEPLOYED_IN]` and other edges without code changes.

**Key Decisions:**

- `kind: 'node' | 'relationship'` discriminator on `Blueprint`
- Relationship blueprints declare `(source, edge, target)` triple
- Edge properties become data-driven, mirroring the node-blueprint model

---

### Plugin Platform

#### [ADR 0008: Plugin System Architecture](adr/0008-plugin-system-architecture.md)

*Date: 2026-04-27 | Status: Accepted*

Establishes Imbi as a SaaS IDP with a stable, versioned plugin model. Plugins are standalone Python packages discovered via entry points; capabilities are stored as `Plugin` graph nodes linked to a shared `ThirdPartyService`.

**Key Decisions:**

- `imbi.plugins` entry-point group; manifests are `ClassVar`s on handler classes
- `ThirdPartyService` + `ServiceApplication` + `Plugin` triplet in the graph
- One service record can back multiple capabilities (`aws-ssm`, `aws-cloudwatch-logs`, `aws-iam-ic`)
- Project-type and per-project `USES_PLUGIN` edges with explicit overrides
- Plugin types grow incrementally (`configuration`, `logs`, then `identity`, `deployment`)

---

#### [ADR 0009: Database-Driven OAuth Provider Configuration](adr/0009-database-driven-oauth-providers.md)

*Date: 2026-04-30 | Status: Accepted*

Moves OAuth provider configuration (Google, GitHub, OIDC) from `IMBI_AUTH_OAUTH_*` environment variables into the graph database, manageable via the admin UI.

**Key Decisions:**

- New `OAuthProvider` node with Fernet-encrypted `client_secret_encrypted`
- 30-second TTL cache keyed by slug, invalidated on writes
- New admin endpoints gated by `oauth-providers:read|write` permissions
- Per-provider env vars deleted; `oauth_auto_link_by_email` / `oauth_auto_create_users` remain

---

#### [ADR 0010: Identity Plugin Architecture](adr/0010-identity-plugin-architecture.md)

*Date: 2026-05-05 | Status: Accepted*

Adds a third plugin type — `identity` — for backends where caller identity matters (AWS IAM IC, GitHub, generic OIDC). Other plugin types declare `identity_plugin_id`; the API materializes per-user credentials at call time.

**Key Decisions:**

- `identity` plugin type alongside `configuration` and `logs`
- Per-user `IdentityConnection` node with Fernet-encrypted tokens, scoped to `(User, Plugin)`
- Identity plugins can double as login providers (`used_as_login: bool`)
- First-party identity entry points in `imbi-plugin-aws`, `imbi-plugin-github`, `imbi-plugin-oidc`

---

#### [ADR 0011: Graph-Based Project Scoring](adr/0011-graph-based-project-scoring.md)

*Date: 2026-04-15 | Status: Accepted*

Replaces v1's fact-based scoring with a blueprint-aware, graph-driven scoring policy model. Attribute policies ship first; event policies are deferred until the integration ingestion path is settled.

**Key Decisions:**

- `ScoringPolicy` node with `value_score_map` or `range_score_map`
- Effective-attribute-set + optional `TARGETS → ProjectType` for policy selection
- Materialized `Project.score`, history in ClickHouse (`score_history` + `score_latest` MV)
- Valkey Streams queue with per-project debounce for async recomputation
- CH-before-AGE write ordering for durable history

---

#### [ADR 0012: Plugin Manifest Third-Party Service Template](adr/0012-plugin-manifest-service-template.md)

*Date: 2026-05-05 | Status: Accepted*

Plugin manifests declare a `third_party_service` template and an embedded icon asset; install-time auto-provisions the `ThirdPartyService`, dedupes capabilities from the same package, and stops re-entering vendor boilerplate.

**Key Decisions:**

- `PluginManifest.third_party_service` and `PluginIcon` (via `importlib.resources`)
- One service record per template ID; multi-entry-point packages dedup
- Manifests carry no secrets; `ServiceApplication` is still operator-supplied
- Re-install preserves operator edits; opt-in "managed by manifest" mode

---

#### [ADR 0013: Deployment Plugin Type](adr/0013-deployment-plugin-type.md)

*Date: 2026-05-08 | Status: Accepted*

Adds a fourth plugin type — `deployment` — so the release-train UI can trigger workflows, draft AI release notes, and record deployments end-to-end against any plugin-supported backend.

**Key Decisions:**

- `deployment` plugin type with a small protocol (list refs/commits, trigger, tag/release)
- Separate `github-deployment` entry point alongside the `github` identity plugin
- `workflow_dispatch` with `{environment, ref}` inputs as the v1 trigger
- Deploys run as the human via `identity_plugin_id`
- Anthropic client in `imbi-common` for server-side release-note drafting

---

#### [ADR 0014: Generic Plugin-Entity CRUD Abstraction](adr/0014-generic-plugin-entity-abstraction.md)

*Date: 2026-05-06 | Status: Accepted*

Replaces hand-coded per-plugin entity routers (e.g., `aws_accounts.py`) with a generic CRUD surface driven by `vertex_labels` / `edge_labels` declared in plugin manifests.

**Key Decisions:**

- Generic `/admin/plugins/{slug}/entities/{label}` routes mounted once
- Edge endpoints for plugin-declared `(source, edge, target)` triples
- Manifest-driven admin UI consuming JSON Schemas
- Existing AWS-specific code is migrated, not preserved in parallel (alpha, no URL compatibility owed)

---

## ADR Format

Our ADRs follow this structure:

```markdown
# [Number]. [Title]

Date: YYYY-MM-DD

## Status

[Proposed | Accepted | Deprecated | Superseded]

## Context

[Description of the issue or requirement]

## Decision

[The change or approach being adopted]

## Consequences

[Positive and negative outcomes]

## References

[Links to relevant documentation]
```

## Creating New ADRs

When making significant architectural decisions:

1. **Create a new ADR file** in `docs/adr/`
2. **Use sequential numbering**: Check existing ADRs and use the next number
3. **Follow the format**: Use the template structure above
4. **Be thorough**: Include context, alternatives considered, and trade-offs
5. **Update this index**: Add a summary entry linking to your new ADR
6. **Submit for review**: ADRs should go through the same PR process as code

## ADR Guidelines

- **Be specific**: Vague ADRs aren't helpful. Include concrete examples.
- **Explain trade-offs**: Every decision has pros and cons. Document both.
- **Consider alternatives**: Show what other options were considered and why they were rejected.
- **Update status**: If a decision is superseded, update the status and link to the new ADR.
- **Link to code**: Reference the files or modules that implement the decision.
- **Keep context**: Future developers need to understand why decisions were made.

## Related Documentation

- **[Configuration Guide](configuration.md)**: Environment variables and settings
- **[GitHub Repository](https://github.com/AWeber-Imbi/imbi-api)**: Source code and issues

## References

- [Documenting Architecture Decisions](http://thinkrelevance.com/blog/2011/11/15/documenting-architecture-decisions) -
  Michael Nygard
- [ADR Tools](https://github.com/npryce/adr-tools) - Lightweight ADR toolset by Nat Pryce
- [ADR GitHub Organization](https://adr.github.io/) - Community resources and examples
