# ADR 0001: Phase 5 Authentication Enhancements

## Status

Accepted

## Context

Imbi v2 completed Phase 4 with basic OAuth2/OIDC authentication, but several critical security and usability features remain unimplemented. These gaps create security vulnerabilities (plaintext OAuth tokens, no token revocation) and limit API usability (no API keys, no MFA).

### Current State
- ✅ JWT-based authentication with access/refresh tokens
- ✅ Password hashing with Argon2id
- ✅ Role-Based Access Control (RBAC)
- ✅ OAuth2/OIDC integration (Google, GitHub, generic OIDC)
- ❌ OAuth provider tokens stored in plaintext
- ❌ Logout endpoint is a no-op (tokens not revoked)
- ❌ Refresh tokens reused indefinitely (no rotation)
- ❌ No rate limiting on auth endpoints
- ❌ No API key authentication
- ❌ Session management settings ignored
- ❌ No MFA/2FA support

### Security Risks
1. **High**: OAuth tokens in plaintext - database breach exposes provider credentials
2. **High**: No token revocation - compromised tokens valid until expiry
3. **Medium**: No rate limiting - vulnerable to brute force attacks
4. **Medium**: No token rotation - refresh token reuse increases exposure window
5. **Medium**: No MFA - single factor authentication insufficient for sensitive operations

## Decision

We will implement seven authentication enhancements in Phase 5:

### 1. Token Revocation (Complete Phase 2 TODO)

**Decision**: Implement actual token revocation in logout endpoint

**Rationale**:
- Security requirement for production systems
- Phase 2 TODO explicitly marked for completion
- Database infrastructure already exists (TokenMetadata.revoked flag)

**Implementation**:
- Update logout endpoint to revoke current access token and associated refresh token
- Support `revoke_all_sessions` parameter for global logout
- Query TokenMetadata by JTI and set `revoked=true, revoked_at=datetime()`

**Trade-offs**:
- Pro: Immediate token invalidation
- Pro: Prevents session hijacking after logout
- Con: Requires database query on every token validation (acceptable with proper indexing)

### 2. OAuth Token Encryption

**Decision**: Encrypt OAuth provider tokens using Fernet symmetric encryption

**Rationale**:
- OAuth tokens grant access to external services (Google, GitHub, OIDC providers)
- Plaintext storage creates unacceptable risk in database breach scenario
- Fernet (symmetric encryption) is appropriate for tokens that must be retrieved
- Python `cryptography` library provides battle-tested implementation

**Implementation**:
- New module: `src/imbi/auth/encryption.py` with `TokenEncryption` singleton
- Encryption key from environment variable `IMBI_AUTH_ENCRYPTION_KEY`
- Auto-generate key on startup if not provided (with warning)
- Update OAuthIdentity model with `set_encrypted_tokens()` and `get_decrypted_tokens()` methods
- Migration script for existing plaintext tokens

**Trade-offs**:
- Pro: Protects sensitive provider credentials
- Pro: Fernet provides authentication (detects tampering)
- Pro: Standard Python library with good docs
- Con: Key management complexity (must secure encryption key)
- Con: Cannot query encrypted tokens directly
- **Why Fernet over AES-GCM**: Fernet includes key derivation and authentication, simpler API, better defaults

**Alternatives Considered**:
- **Asymmetric encryption (RSA)**: Rejected - unnecessary complexity, tokens don't need public/private key separation
- **Database-level encryption**: Rejected - requires database configuration, less portable
- **No encryption**: Rejected - unacceptable security risk

### 3. Rate Limiting

**Decision**: Use slowapi library with memory-based storage

**Rationale**:
- Auth endpoints (login, OAuth, refresh) are prime targets for brute force and DDoS
- slowapi is FastAPI-native rate limiting library
- Memory-based storage avoids Redis dependency for v2 alpha

**Implementation**:
- New middleware: `src/imbi/middleware/rate_limit.py`
- Limits: 5/min login, 10/min refresh, 3/min OAuth, 100/min API keys
- Key function: API key ID > User ID > IP address (prioritized)
- Decorator-based application to specific endpoints

**Trade-offs**:
- Pro: Zero infrastructure dependencies (no Redis)
- Pro: FastAPI-native library with good docs
- Pro: Per-endpoint granular control
- Con: Memory-based limits don't work across multiple server instances
- Con: Limits reset on server restart
- **Why slowapi over custom**: Battle-tested, maintained, follows FastAPI patterns

**Alternatives Considered**:
- **Custom implementation**: Rejected - reinventing the wheel, more bugs
- **fastapi-limiter**: Rejected - requires Redis from day one
- **Middleware-only**: Rejected - less granular control per endpoint

### 4. API Keys with Scoped Permissions

**Decision**: Implement full-featured API keys with CRUD, scopes, expiration, and usage tracking

**Rationale**:
- Service accounts and CI/CD need programmatic access
- JWT tokens designed for interactive sessions, not long-lived automation
- Scoped permissions enable least-privilege access
- Usage tracking via ClickHouse provides observability

**Implementation**:
- New endpoint module: `src/imbi/endpoints/api_keys.py`
- Key format: `ik_<16chars>_<32chars>` (prefix for identification, URL-safe)
- Secret hashed with Argon2 (same as passwords)
- Scopes filter user permissions (e.g., `['project:read', 'blueprint:read']`)
- Expiration honored (max lifetime from settings)
- Usage events logged to ClickHouse `api_key_usage` table
- Rotation endpoint generates new secret, preserves key_id

**Trade-offs**:
- Pro: Programmatic access for automation
- Pro: Scoped permissions limit blast radius
- Pro: Usage tracking enables audit and cleanup
- Pro: Rotation reduces key exposure window
- Con: Added complexity in authentication flow
- Con: ClickHouse dependency for full feature set
- **Why ClickHouse for usage tracking**: Time-series data, automatic TTL, analytics queries, avoids bloating Neo4j

**Alternatives Considered**:
- **JWT for API keys**: Rejected - JWTs expire, can't be easily revoked, no usage tracking
- **Neo4j for usage tracking**: Rejected - poor fit for high-volume time-series data, no TTL
- **No scopes**: Rejected - violates least privilege principle

### 5. Session Management Enforcement

**Decision**: Enforce `max_concurrent_sessions` setting by tracking sessions in Neo4j

**Rationale**:
- Settings exist but are ignored
- Multiple concurrent sessions increase attack surface
- Session tracking enables security monitoring

**Implementation**:
- New model: `Session` with session_id, IP, user agent, timestamps
- Created on login/OAuth callback
- Enforce limit by deleting oldest sessions when max exceeded
- Store last_activity for session timeout enforcement (future)

**Trade-offs**:
- Pro: Limits session hijacking exposure
- Pro: Enables security monitoring
- Pro: Infrastructure already in place (Neo4j)
- Con: Additional database writes on login
- Con: UX impact if user exceeds limit (old sessions killed)

**Alternatives Considered**:
- **No enforcement**: Rejected - existing setting misleading
- **JWT-only tracking**: Rejected - no way to enumerate user's active sessions

### 6. MFA/2FA with TOTP

**Decision**: TOTP (Time-based One-Time Password) using pyotp library

**Rationale**:
- MFA significantly reduces account compromise risk
- TOTP is industry standard (Google Authenticator, Authy, 1Password)
- No external dependencies (SMS, email) for v2 alpha
- Backup codes handle device loss scenario

**Implementation**:
- New endpoint module: `src/imbi/endpoints/mfa.py`
- New model: `TOTPSecret` with secret, enabled flag, backup codes
- Setup flow: generate secret, QR code, backup codes (not enabled until verified)
- Login flow: check for enabled MFA, require code, fall back to backup codes
- Backup codes: 10 codes, Argon2 hashed, one-time use
- Disable requires password confirmation

**Trade-offs**:
- Pro: Strong security without external dependencies
- Pro: Works offline (time-based)
- Pro: Standard across industry
- Con: Requires user to have authenticator app
- Con: Device loss requires backup codes or admin intervention
- **Why TOTP over SMS**: SMS vulnerable to SIM swapping, requires telco integration
- **Why TOTP over Email**: Email as second factor provides minimal additional security

**Alternatives Considered**:
- **Email OTP**: Rejected - requires email system (Phase 5+ for password reset), weak second factor
- **SMS OTP**: Rejected - expensive, requires telco integration, SIM swapping risk
- **WebAuthn/FIDO2**: Rejected - future enhancement, more complex, requires hardware

### 7. Token Rotation

**Decision**: Rotate refresh tokens on every use (Refresh Token Rotation pattern)

**Rationale**:
- OAuth 2.0 Security Best Practices RFC 8252 recommends rotation
- Limits exposure window if refresh token compromised
- Detects token theft (old token reuse fails)

**Implementation**:
- Update refresh_token endpoint to revoke old refresh token
- Generate new refresh token (new JTI)
- Return new refresh token in response
- Clients must store new refresh token

**Trade-offs**:
- Pro: Reduces exposure window
- Pro: Enables theft detection
- Pro: Industry best practice
- Con: Clients must handle token updates
- Con: Potential for "cascading failures" if client misses update
- **Mitigation for cascading failures**: Clear error messages, logging, retry guidance

**Alternatives Considered**:
- **No rotation**: Rejected - insecure, not industry best practice
- **Rotation on suspicious activity only**: Rejected - requires ML, more complex, less secure baseline

## Consequences

### Positive
1. **Security**: OAuth tokens encrypted, token revocation implemented, MFA available, rate limiting prevents attacks
2. **API Usability**: API keys enable automation and service accounts
3. **Compliance**: Moves toward SOC 2, GDPR compliance (encrypted PII, audit logs)
4. **Observability**: ClickHouse usage tracking enables security monitoring
5. **Best Practices**: Aligns with OAuth 2.0 Security Best Practices RFC 8252

### Negative
1. **Complexity**: 7 features add significant code surface area
2. **Testing**: Requires 8 new test modules for 100% coverage
3. **Migration**: Existing OAuth tokens need encryption migration
4. **Client Updates**: Token rotation requires clients to handle new refresh tokens
5. **Key Management**: Encryption key must be secured (vault, secrets manager)

### Neutral
1. **Dependencies**: Adds 3 new libraries (cryptography, pyotp, slowapi)
2. **Database**: Adds 3 models to Neo4j, 4 tables to ClickHouse

## Implementation Plan

### Phase 1: Foundation (Week 1)
- Add dependencies to pyproject.toml
- Implement encryption utility (`src/imbi/auth/encryption.py`)
- Add new models (TOTPSecret, Session, APIKey)
- Create ClickHouse tables
- Update settings

### Phase 2: Token Management (Week 2)
- Implement token revocation (logout)
- Implement token rotation (refresh)
- Implement session management
- Write tests

### Phase 3: Rate Limiting & API Keys (Week 3)
- Implement rate limiting middleware
- Implement API key CRUD endpoints
- Add API key authentication
- Add usage tracking middleware
- Write tests

### Phase 4: MFA & OAuth Encryption (Week 4)
- Implement MFA endpoints
- Integrate MFA into login flow
- Update OAuth flow with encryption
- Create migration script
- Write tests

### Phase 5: Integration & Testing (Week 5)
- Run full test suite (100% coverage)
- End-to-end integration testing
- Performance testing
- Update documentation

## Monitoring & Success Metrics

### Key Metrics
1. **Rate Limiting**: Blocked requests per endpoint per hour
2. **API Keys**: Active keys, usage patterns, revocations
3. **MFA**: Adoption rate (% of users with MFA enabled)
4. **Sessions**: Average concurrent sessions per user
5. **Token Rotation**: Refresh token reuse attempts (security indicator)
6. **OAuth Encryption**: Successful encryption/decryption rate

### ClickHouse Queries
```sql
-- API key usage by endpoint
SELECT endpoint, count() as request_count
FROM api_key_usage
WHERE timestamp >= now() - INTERVAL 1 DAY
GROUP BY endpoint
ORDER BY request_count DESC;

-- MFA adoption
SELECT COUNT(DISTINCT user_id) as mfa_users
FROM mfa_events
WHERE event_type = 'enabled';

-- Rate limit violations
SELECT endpoint, identifier, SUM(blocked_count) as total_blocked
FROM rate_limit_events
WHERE window_start >= now() - INTERVAL 1 HOUR
GROUP BY endpoint, identifier
ORDER BY total_blocked DESC;
```

## Security Considerations

### Critical Security Measures
1. **Encryption Key Storage**: Store `IMBI_AUTH_ENCRYPTION_KEY` in vault (AWS Secrets Manager, HashiCorp Vault)
2. **Token Revocation Checking**: Always check revoked flag before accepting refresh tokens
3. **Rate Limiting Deployment**: Apply at both application and infrastructure layers (nginx, WAF)
4. **API Key Scopes**: Enforce least privilege - grant minimal necessary permissions
5. **MFA Backup Codes**: One-time use only, Argon2 hashed, limit to 10 codes
6. **Session Limits**: Enforce `max_concurrent_sessions` to prevent session hijacking
7. **Audit Logging**: All security events logged to ClickHouse for forensics

### Migration Safety
- OAuth token migration detects encrypted vs plaintext with base64 padding heuristic
- Migration script can be run multiple times (idempotent)
- Existing sessions continue working during rollout
- Rate limits apply gradually (no hard cutoffs during deployment)

## References

- [OAuth 2.0 Security Best Practices (RFC 8252)](https://datatracker.ietf.org/doc/html/rfc8252)
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- [NIST Digital Identity Guidelines (SP 800-63B)](https://pages.nist.gov/800-63-3/sp800-63b.html)
- [cryptography library documentation](https://cryptography.io/)
- [pyotp documentation](https://pyauth.github.io/pyotp/)
- [slowapi documentation](https://github.com/laurents/slowapi)

## Appendix: Environment Variables

```bash
# Required
IMBI_AUTH_ENCRYPTION_KEY=<fernet-key>  # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Optional (with defaults shown)
IMBI_AUTH_MFA_ISSUER_NAME=Imbi
IMBI_AUTH_MFA_TOTP_PERIOD=30
IMBI_AUTH_MFA_TOTP_DIGITS=6
IMBI_AUTH_RATE_LIMIT_LOGIN=5/minute
IMBI_AUTH_RATE_LIMIT_TOKEN_REFRESH=10/minute
IMBI_AUTH_RATE_LIMIT_OAUTH_INIT=3/minute
IMBI_AUTH_RATE_LIMIT_API_KEY=100/minute
IMBI_AUTH_SESSION_TIMEOUT_SECONDS=86400
IMBI_AUTH_MAX_CONCURRENT_SESSIONS=5
IMBI_AUTH_API_KEY_MAX_LIFETIME_DAYS=365
```

## Revision History

- 2026-01-01: Initial version (Phase 5 planning)
