# Imbi Documentation

> A DevOps Service Management Platform for managing complex service ecosystems

## Overview

Imbi provides a centralized platform to manage, track, and understand all services and applications across your organization. It serves as a single source of truth for service metadata, dependencies, ownership, and operational information.

## What is Imbi?

Imbi helps organizations answer critical questions about their service landscape:

- **What services do we have?** Complete inventory with ownership, type, and namespace organization
- **How are they related?** Graph-based dependency tracking and relationship visualization
- **Who owns what?** Clear ownership and team assignments
- **What's deployed where?** Environment-specific URLs and deployment tracking
- **What needs attention?** Project health scoring based on configurable factors
- **Where's the documentation?** Links to repos, CI/CD, monitoring, and other tools

## Key Benefits

- **Single Source of Truth**: Centralized service catalog with comprehensive metadata
- **Relationship Visualization**: Graph database enables intuitive dependency mapping
- **Automation Ready**: API-first design enables integration with CI/CD, webhooks, and automations
- **Extensible**: Blueprint system for customizable metadata schemas applied via JSON Schema
- **Developer Friendly**: Automatic data collection via GitHub webhooks and integrations

## Version 2.0 (Alpha)

**Complete rewrite** using modern Python technologies for improved performance, scalability, and AI integration:

- **FastAPI**: Modern async web framework with automatic OpenAPI documentation
- **PostgreSQL + Apache AGE**: Graph extension on top of PostgreSQL for modeling service relationships and dependencies with Cypher queries
- **ClickHouse**: Analytics and time-series data storage for operations logs and metrics
- **Valkey**: Redis-compatible cache and ephemeral state
- **S3-compatible object storage**: Icons, avatars, and document uploads (LocalStack in development)
- **Pydantic v2**: Type-safe data validation and settings management

### What's New in v2

- **Apache AGE on PostgreSQL**: Replaces both the v1 PostgreSQL relational schema and the alpha Neo4j prototype — graph plus relational data in a single database
- **Modern API**: FastAPI provides automatic OpenAPI docs, async performance, and better type safety
- **Blueprints**: JSON-Schema-driven custom metadata that extends domain models at runtime
- **Full Authentication**: OAuth2/OIDC (Google, GitHub, generic OIDC) and local password authentication with JWT access and refresh tokens
- **Fine-Grained Authorization**: Permission-based access control with resource-level permissions, roles, and groups
- **API Keys**: Scoped, rotatable API keys with usage tracking for service-to-service access
- **MFA/2FA**: TOTP-based multi-factor authentication with backup codes
- **File Uploads**: S3-backed uploads with magic-byte validation and automatic thumbnail generation
- **Analytics Ready**: ClickHouse integration for operations logs, audit logs, and time-series metrics

## Quick Start

This project uses [moon](https://moonrepo.dev) as its task runner and [uv](https://docs.astral.sh/uv/) for Python package management.

### Development Environment

```bash
# Install dependencies and pre-commit hooks
moon run root:setup

# Start Docker services (Postgres+AGE, ClickHouse, Valkey, LocalStack,
# Mailpit, Jaeger) and write .env.test with the assigned ports and
# freshly-generated secrets
moon run root:services

# Run the API with auto-reload against those services
uv run --env-file .env.test imbi-api serve --dev

# First-time only: seed roles/permissions and create the admin user
uv run --env-file .env.test imbi-api setup

# Health check
curl http://localhost:8000/status
```

The server starts on `http://localhost:8000` by default (configurable via `IMBI_API_HOST` and `IMBI_API_PORT`). The interactive OpenAPI docs are at `/docs` and the raw schema is at `/openapi.json`.

### Testing

```bash
moon run api:test                                      # The API member's suite
uv run --env-file .env.test pytest apps/api/tests/auth/test_permissions.py               # Single module
uv run --env-file .env.test pytest apps/api/tests/auth/test_permissions.py::PermissionTests::test_get_permissions
moon run api:lint api:typecheck api:format             # ruff + basedpyright + format check
```

Run `moon run root:coverage` for the full single-session suite with aggregate
coverage, and `moon run root:services` first if you invoke `pytest` directly.

## Core Concepts

### Data Model

Imbi organizes services using a flexible, graph-based data model:

- **Organizations**: Top-level organizational units with unique slug identifiers
- **Teams**: Groups within organizations that own and maintain projects
- **Projects**: Individual services or applications with comprehensive metadata, optionally classified by one or more project types
- **Project Types**: Categories like 'Web Service', 'Library', 'Data Pipeline'
- **Environments**: Deployment targets like 'production', 'staging', 'development'
- **Blueprints**: JSON Schema definitions that extend the metadata of any of the above entities

### Authentication & Authorization

- **OAuth2/OIDC**: Google, GitHub, and generic OIDC providers — configured at runtime through the admin API and stored in the graph, not via environment variables
- **Local Authentication**: Password-based authentication with Argon2id hashing
- **JWT Tokens**: Access tokens (default 1 hour) and refresh tokens (default 30 days) with refresh-token rotation
- **API Keys**: Format `ik_<16chars>_<32chars>` with scoped permissions and ClickHouse-backed usage tracking
- **MFA**: TOTP-based 2FA with backup codes
- **Permission-Based Access Control**: Fine-grained permissions enforced via FastAPI dependencies
- **Rate Limiting**: Per-route limits on login, refresh, OAuth initiation, and API-key authentication

### Integrations

Imbi integrates with your existing DevOps toolchain:

- **Version Control**: GitHub webhooks for automatic project updates
- **CI/CD**: Links to build pipelines and deployment tools
- **Monitoring**: Integration with observability platforms
- **Issue Tracking**: Links to Jira, GitHub Issues, etc.
- **Incident Management**: PagerDuty integration for on-call management

## Architecture

Imbi v2 uses a multi-database architecture optimized for different data patterns:

- **PostgreSQL + Apache AGE**: Graph plus relational data for service relationships, dependencies, users, permissions, blueprints, and all domain entities
- **ClickHouse**: Analytics database for operations logs, audit logs, email logs, API-key usage, and time-series metrics (ReplacingMergeTree for idempotent writes)
- **Valkey**: Redis-compatible cache for ephemeral state
- **S3-compatible object storage**: Uploads (LocalStack in development, real S3 in production)
- **Mailpit**: SMTP capture in development
- **FastAPI**: Async Python web framework for the REST API
- **Docker Compose**: Development environment with all required services

For detailed architecture decisions, see the [Architecture Decision Records](adr.md).

## Documentation

- **[Configuration Guide](configuration.md)**: All configuration variables — `config.toml`, environment variables, and `.env`
- **[Architecture Decision Records](adr.md)**: Key architectural decisions and rationale

## Contributing

Contributions are welcome! Please see the [GitHub repository](https://github.com/AWeber-Imbi/imbi-api) for:

- Issue tracking and feature requests
- Pull request process
- Development setup instructions
- Coding standards and conventions

## License

Imbi is licensed under the BSD-3-Clause License. See the LICENSE file for details.
