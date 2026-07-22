# 2. Authentication and Authorization Architecture

Date: 2025-12-30

## Status

Accepted

## Context

Imbi v2 requires a comprehensive authentication and authorization system to:
- Secure API endpoints (all except `/status` and `/docs`)
- Support multiple authentication methods for different use cases
- Enable flexible permission management for users and service accounts
- Provide audit logging for compliance and security monitoring
- Support both UI users and inter-service communication

### Requirements

1. **Authentication Methods**:
   - Local username/password for internal users
   - OAuth2 (GitHub, Google Workspace, Generic OIDC) for SSO
   - JWT tokens for stateless API access
   - API keys for service-to-service communication

2. **Authorization Model**:
   - Hybrid permission system combining role-based and resource-level access control
   - Support for permission inheritance through role and group hierarchies
   - Fine-grained permissions (e.g., `project:read`, `blueprint:write`)
   - Resource-specific access grants (e.g., user X can write to project Y)

3. **Audit Requirements**:
   - Log all authentication events (login, logout, token issuance)
   - Log all authorization decisions (permission checks, access grants/denials)
   - Retain logs for 2 years for compliance
   - Support analytics queries on auth patterns

4. **Service Accounts**:
   - Support for imbi-automations, imbi-webhooks, and future services
   - Long-lived authentication credentials
   - Scoped permissions per service

## Decision

### 1. Data Storage Strategy

**Neo4j for User and Permission Data**

We will store users, groups, roles, permissions, API keys, and OAuth links in Neo4j alongside existing service data.

**Rationale**:
- Natural fit for permission inheritance modeling (role hierarchies, group membership)
- Efficient graph traversal for "who can access what" queries
- Single source of truth for all Imbi entities and their relationships
- Existing infrastructure and operational knowledge

**Trade-offs**:
- Neo4j is less mature for authentication than PostgreSQL
- Must implement custom auth logic rather than using off-the-shelf solutions
- Acceptable given the graph-centric nature of Imbi and existing Neo4j investment

**ClickHouse for Audit Logs**

We will store authentication and authorization audit events in ClickHouse.

**Rationale**:
- Already in stack for analytics
- Excellent performance for time-series data
- Built-in TTL for automatic retention management (2 years)
- Efficient compression for large log volumes
- SQL-like interface for audit queries

**Trade-offs**:
- Less flexible than Elasticsearch for full-text search
- Sufficient for structured audit event queries and compliance reporting

### 2. Token Strategy

**JWT Tokens with Revocation List**

We will use JWT (JSON Web Tokens) for authentication with a revocation mechanism.

**Token Types**:
- **Access tokens**: Short-lived (1 hour), used for API requests
- **Refresh tokens**: Long-lived (30 days), used to obtain new access tokens

**Token Storage**:
- JWTs are stateless (not stored server-side for validation)
- Token metadata stored in Neo4j for revocation and tracking
- Each token has a unique JTI (JWT ID) for identification

**Rationale**:
- Stateless validation enables horizontal scaling
- Self-contained tokens reduce database lookups
- Well-suited for inter-service communication
- Revocation list handles logout and security events
- Industry standard with mature libraries

**Trade-offs**:
- Larger token size than opaque tokens
- Permissions are not in the JWT (must be loaded per request)
- Revocation requires database check, but only on explicit logout/revocation
- Acceptable given scaling benefits and inter-service requirements

### 3. Password Hashing

**Argon2id Algorithm**

We will use Argon2id for password hashing via the argon2-cffi library.

**Rationale**:
- Winner of Password Hashing Competition (2015)
- Memory-hard function resistant to GPU/ASIC attacks
- Configurable parameters (memory cost, time cost, parallelism)
- Automatic rehashing when parameters are upgraded
- Industry best practice for new applications

**Trade-offs**:
- Newer than bcrypt (but well-established since 2015)
- Slightly slower than bcrypt (intentional security feature)
- Preferred for modern applications

### 4. OAuth2 Integration

**Authlib Library with Multiple Providers**

We will use Authlib for OAuth2/OIDC integration supporting:
- GitHub OAuth
- Google Workspace OAuth
- Generic OIDC (Okta, Auth0, Keycloak, etc.)

**Rationale**:
- Modern, actively maintained library
- Native Starlette/FastAPI integration
- Full OIDC support out-of-the-box
- Handles OAuth2 security concerns (state parameter, redirect validation)
- Extensible for future providers

**OAuth User Linking**:
- OAuth identities stored as relationships to User nodes
- Multiple OAuth providers can link to same user
- Email matching for automatic account linking (configurable)

**Trade-offs**:
- Additional dependency with moderate complexity
- Requires provider-specific configuration
- Necessary for enterprise SSO requirements

### 5. Permission Model

**Hybrid: Role-Based + Resource-Level Access Control**

We will implement a hybrid permission model combining RBAC and resource-specific grants.

**Global Permissions (RBAC)**:
- Permissions named as `resource:action` (e.g., `project:read`, `blueprint:write`)
- Roles contain multiple permissions
- Users assigned roles directly or through group membership
- Role inheritance (e.g., admin role inherits from developer role)

**Resource-Level Permissions**:
- `CAN_ACCESS` relationships from users/groups to specific resources
- Relationship properties specify allowed actions (read, write, delete)
- Override model: resource-level grants supplement global permissions

**Permission Resolution**:
1. Check global permission (user → roles → permissions)
2. If not found, check resource-level permission (user → CAN_ACCESS → resource)
3. Permissions collected through group membership and role inheritance
4. Graph traversal in single Cypher query for efficiency

**Rationale**:
- Balances simplicity (RBAC) with flexibility (resource-level)
- Natural fit for graph database
- Supports both broad roles (admin, developer) and specific grants
- Enables delegation (project owner grants access to their projects)

**Trade-offs**:
- More complex than pure RBAC
- Permission checks require graph traversal
- Acceptable given requirement for fine-grained access control

### 6. Authorization Pattern

**FastAPI Dependency Injection (Not Middleware)**

We will use FastAPI's dependency injection for authentication and authorization.

**Pattern**:
```python
@router.get('/resource')
async def get_resource(
    auth: Annotated[AuthContext, Depends(get_current_user)],
    # ... or ...
    auth: Annotated[AuthContext, Depends(require_permission('resource:read'))],
):
    # Endpoint code with authenticated user context
```

**Rationale**:
- FastAPI's idiomatic approach
- Granular control per endpoint
- Clear intent (explicit permission requirements in function signature)
- Easy to test (mock dependencies)
- Supports optional authentication (public endpoints don't use dependency)
- Composable (can layer multiple dependencies)

**Trade-offs**:
- More boilerplate than global middleware
- Must remember to add dependencies to protected endpoints
- Benefits outweigh drawbacks: clarity, testability, flexibility

### 7. Inter-Service Authentication

**Dual Approach: JWTs and API Keys**

We will support both JWT tokens and API keys for service accounts.

**Service Accounts**:
- Special users with `is_service_account=True`
- Can authenticate with JWTs or API keys
- Assigned roles like regular users

**JWT for Services**:
- Services can login and receive JWTs
- Suitable for temporary credentials
- Supports token refresh

**API Keys for Services**:
- Long-lived credentials (up to 1 year)
- Format: `imbi_key_{id}_{secret}` for easy identification
- Hashed storage (SHA-256)
- Optional scope restrictions
- Tracked usage (last_used timestamp)

**Rationale**:
- JWTs: Better for services that can manage token rotation
- API Keys: Simpler for services needing stable credentials
- Flexibility accommodates different service integration patterns
- Both methods use same permission system

**Trade-offs**:
- Maintaining two authentication methods adds complexity
- Necessary to support diverse service requirements

### 8. Security Measures

**Password Policy**:
- Minimum length: 12 characters (configurable)
- Required character types: uppercase, lowercase, digit, special
- Automatic password hash upgrades
- No password reuse checking in v1 (can add in future)

**Token Security**:
- Short-lived access tokens (1 hour) limit exposure window
- Refresh tokens can be revoked
- JTI tracking enables individual token revocation
- Tokens never logged or exposed in error messages

**API Key Security**:
- Prefix `imbi_key_` enables detection in logs/code (like GitHub tokens)
- Hashed storage prevents exposure if database compromised
- Expiry enforcement
- Full key shown only once at creation
- Per-key scope restrictions

**OAuth2 Security**:
- State parameter prevents CSRF attacks
- Redirect URI validation
- Domain whitelist for email-based access (optional)
- OAuth tokens stored encrypted (future enhancement)

**Audit Logging**:
- All auth events logged with timestamp, IP, user agent
- Failed attempts tracked for security monitoring
- 2-year retention via ClickHouse TTL
- Structured logging enables automated alerting

**Rate Limiting** (Phase 8):
- Login attempts: 5 per minute per IP
- API key creation: 10 per hour per user
- Token refresh: 60 per hour per user
- Prevents brute force and abuse

## Consequences

### Positive

1. **Comprehensive Authentication**: Supports multiple methods (password, OAuth2, JWT, API keys) for different use cases
2. **Flexible Authorization**: Hybrid permission model supports both role-based and fine-grained access control
3. **Scalable Architecture**: Stateless JWTs enable horizontal scaling without session management
4. **Audit Compliance**: All auth events logged to ClickHouse with 2-year retention
5. **Graph-Native**: Leverages Neo4j for natural permission inheritance and relationship modeling
6. **Service-Friendly**: Both JWTs and API keys support inter-service authentication
7. **Security Best Practices**: Argon2id hashing, token revocation, rate limiting, audit logging
8. **Testable Design**: Dependency injection enables easy mocking and testing
9. **Maintainable**: Clear separation of concerns (auth/core, auth/permissions, auth/oauth2, auth/audit)
10. **Extensible**: Can add new OAuth providers, permission types, or auth methods without refactoring

### Negative

1. **Implementation Complexity**: Building custom auth system requires significant development effort
2. **Neo4j for Auth**: Less common than PostgreSQL for user data, fewer reference implementations
3. **Permission Check Overhead**: Graph traversal for permission resolution adds latency
4. **Dual Auth Methods**: Supporting both JWTs and API keys increases maintenance burden
5. **Revocation Overhead**: Token revocation requires database lookup, losing full stateless benefit
6. **Testing Burden**: More test scenarios with multiple auth methods and permission combinations

### Mitigation Strategies

1. **Phased Implementation**: 8 phases spread over 9+ weeks reduces risk and enables early feedback
2. **Comprehensive Testing**: 90% coverage requirement ensures reliability
3. **Permission Caching**: Load permissions once per request, cache in `AuthContext`
4. **Index Optimization**: Neo4j indexes on username, email, API key IDs for fast lookups
5. **Documentation**: ADR, API docs, and developer guides reduce onboarding friction
6. **Reference Patterns**: Following FastAPI best practices makes code familiar to Python developers

### Risks

1. **Performance at Scale**: Permission checks via graph traversal may not scale to millions of users
   - Mitigation: Index optimization, permission caching, consider caching layer if needed
2. **OAuth Provider Changes**: External OAuth APIs may change or deprecate
   - Mitigation: Authlib library abstracts provider specifics, version pinning
3. **Token Compromise**: If JWT secret leaked, all tokens compromised
   - Mitigation: Secret rotation capability, monitor for suspicious activity, short token lifetime
4. **Complexity for Simple Cases**: Hybrid permission model may be overkill for basic use cases
   - Mitigation: Simple roles (admin, viewer) provide easy starting point, complexity is opt-in

### Future Enhancements

Not in scope for initial implementation, but architecturally supported:

1. **Multi-Factor Authentication (MFA)**: Can add TOTP/WebAuthn with minimal changes
2. **Magic Link Authentication**: Passwordless auth via email links
3. **SAML Support**: Enterprise SSO via SAML in addition to OAuth2/OIDC
4. **Passwordless Service Auth**: mTLS or certificate-based authentication
5. **Permission Caching Layer**: Redis cache for permission resolution at scale
6. **Attribute-Based Access Control (ABAC)**: Context-aware permissions (time, location, resource properties)
7. **OAuth Token Encryption**: Encrypt stored OAuth tokens at rest
8. **Password History**: Prevent password reuse
9. **Session Management**: Track and limit concurrent sessions per user
10. **Anomaly Detection**: ML-based detection of unusual auth patterns

## References

- [FastAPI Security Documentation](https://fastapi.tiangolo.com/tutorial/security/)
- [Authlib Documentation](https://docs.authlib.org/)
- [Argon2 Password Hashing](https://github.com/P-H-C/phc-winner-argon2)
- [JWT Best Practices (RFC 8725)](https://datatracker.ietf.org/doc/html/rfc8725)
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [Neo4j Security Best Practices](https://neo4j.com/docs/operations-manual/current/security/)
