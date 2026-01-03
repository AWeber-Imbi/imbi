# ADR 0001: Imbi Common Library Extraction

## Status

Accepted

## Context

The Imbi ecosystem consists of multiple services (imbi-api, imbi-webhooks,
imbi-mcp) that share common functionality:

- Database clients (Neo4j, ClickHouse)
- Domain models (Projects, Users, Roles, etc.)
- Authentication primitives (password hashing, JWT, encryption)
- Configuration management
- Logging setup

This shared code was duplicated across services or tightly coupled to
imbi-api, leading to:

- Code duplication and maintenance burden
- Inconsistent behavior across services
- Difficulty adding new services to the ecosystem
- Testing challenges (each service reimplements similar functionality)

We need a shared library to provide core functionality for all Imbi services.

## Decision

### 1. Create imbi-common Library

Create a new Python package `imbi-common` with import path `imbi_common.*`
as a simple package.

**Rationale**:

- Simple package structure is easier to maintain than namespace packages
- Clear, unambiguous import path: `imbi_common`
- PyPI package name `imbi-common` with underscore for imports follows Python
  conventions
- No conflicts with existing `imbi` package (imbi-api)

### 2. Components to Extract

#### Extract to imbi-common:

- **Settings Module** (`imbi_common.settings`): All Pydantic settings
  classes and TOML loading
- **Neo4j Client** (`imbi_common.neo4j`): Singleton client, CRUD
  abstractions, schema constants
- **ClickHouse Client** (`imbi_common.clickhouse`): Singleton client,
  privacy utilities, base schemas
- **Core Models** (`imbi_common.models`): Domain models, auth models, all
  shared data structures
- **Blueprint System** (`imbi_common.blueprints`): Dynamic schema extension
  system
- **Auth Core** (`imbi_common.auth`): Password hashing, JWT primitives,
  token encryption
- **Logging Module** (`imbi_common.logging`): Log configuration loading and
  dictConfig application

**Rationale**:

- These components are fundamental to accessing and managing Imbi data
- All services need identical model definitions for data consistency
- Blueprint system enables dynamic schema extension across all services
- Auth primitives are needed for inter-service authentication
- Centralized logging ensures consistent log format across services

#### Keep in imbi-api:

- FastAPI-specific code (endpoints, dependencies, middleware)
- OAuth flow logic (HTTP-specific)
- Email functionality (API-specific feature)
- API-specific ClickHouse schemas (api_key_usage, rate_limit_events,
  email_audit)

**Rationale**:

- HTTP/web framework concerns don't belong in a data access library
- API-specific features shouldn't bloat the common library
- Separation of concerns: common = data/auth, api = HTTP/business logic

### 3. ClickHouse Schema Strategy: Shared Base + Service Extensions

**Decision**: Common library provides base schemas, each service adds its
own tables.

**Base Schemas** (in imbi-common):

- `session_activity`: User session tracking (used by API and MCP)
- `mfa_events`: MFA event tracking (used by multiple services)

**Service-Specific Schemas** (in each service):

- imbi-api: `api_key_usage`, `rate_limit_events`, `email_audit`
- imbi-webhooks: `webhook_events`, etc.
- imbi-mcp: Service-specific audit tables

**Implementation**:

```python
# Common library loads base schemas automatically
# Services provide additional schema files
await clickhouse.setup_schema([service_schema_path])
```

**Rationale**:

- Standardizes common tables across all services
- Flexibility for service-specific analytics needs
- No tight coupling - services control their own schema evolution
- Clear ownership: base tables documented in common library

### 4. Migration Strategy: Clean Break

**Decision**: No backward compatibility layer, update all imports at once.

**Rationale**:

- Simpler implementation (no temporary wrappers)
- Cleaner codebase (no deprecated import paths)
- Forces complete migration (no lingering old imports)
- Faster timeline (no gradual migration phase)
- All services under our control (can coordinate deployment)

### 5. Testing Framework: unittest (Standard Library)

**Decision**: Use Python's standard `unittest` framework, not pytest.

**Rationale**:

- No external dependencies for basic testing
- Standard library = always available, stable API
- Sufficient for our needs (async support via `IsolatedAsyncioTestCase`)
- Reduces dependency footprint of common library
- Integration tests use `unittest.skipIf()` with
  `SKIP_INTEGRATION_TESTS` env var

### 6. Logging: dictConfig with Shared Configuration

**Decision**: Create `imbi_common.logging` module with
`configure_logging()` function.

**Implementation**:

```python
from imbi_common import logging

# Load bundled log-config.toml and apply with logging.config.dictConfig()
logging.configure_logging(dev=True)
```

**Rationale**:

- Consistent log format across all services
- Easy to override (pass custom config dict)
- Uses Python's standard logging.config.dictConfig (no external deps)
- Development mode support (DEBUG level for imbi loggers)
- Services can extend/override as needed

### 7. Blueprint System Inclusion

**Decision**: Include blueprint system in imbi-common (not API-specific).

**Rationale**:

- Enables all services to work with dynamically-extended models
- MCP server can query projects with custom fields
- Webhooks can validate events against dynamic schemas
- Core data access functionality (not UI/HTTP concern)
- Already well-abstracted from HTTP layer

## Consequences

### Positive

- **Code Reuse**: Single source of truth for models, clients, configuration
- **Consistency**: All services use identical data access patterns
- **Maintainability**: Fix bugs once, benefit all services
- **Testability**: Shared test utilities and fixtures
- **Extensibility**: New services easily integrate with Imbi ecosystem
- **Type Safety**: Shared Pydantic models ensure data consistency
- **Documentation**: Centralized API reference for common functionality

### Negative

- **Dependency Management**: Changes to imbi-common affect all services
- **Coordination Required**: Breaking changes need coordinated releases
- **Initial Migration Effort**: Clean break requires updating all imports
  in imbi-api
- **Version Skew Risk**: Services on different imbi-common versions may be
  incompatible

### Mitigation Strategies

1. **Semantic Versioning**: Use strict SemVer with deprecation warnings
   before breaking changes
2. **Compatibility Matrix**: Document which service versions work with
   which imbi-common versions
3. **CI/CD Integration**: Test all services against imbi-common changes
   before release
4. **Changelog Discipline**: Comprehensive changelog for every release
5. **Deprecation Period**: Give services time to migrate (e.g., 2 minor
   versions before removal)

## Implementation Timeline

1. Create imbi-common repository and extract code
2. Write tests and documentation
3. Set up CI/CD and publish v0.1.0
4. Migrate imbi-api to use imbi-common (separate effort)
5. Update other services (imbi-webhooks, imbi-mcp) as they're developed

## References

- Original discussion: Imbi ecosystem architecture
- Related: Database schema management strategy
- Related: Inter-service authentication approach
