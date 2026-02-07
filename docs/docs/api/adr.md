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

- Neo4j for user and permission data (natural fit for permission inheritance)
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
- Neo4j for upload metadata (consistent with all other entities)
- Presigned URL redirects (307) for efficient file serving
- Pillow for thumbnail generation, filetype for magic-byte validation
- WEBP thumbnails at 256x256 max, maintaining aspect ratio

**Upload Features:**

- Content type validation with magic-byte verification
- Configurable size limits (default 50 MB)
- Automatic thumbnail generation for raster images
- Permission-based access control (upload:create, upload:read, upload:delete)

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
