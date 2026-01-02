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
- **AI-Powered**: Built-in vector search and conversational AI support for natural language queries
- **Extensible**: Blueprint system for customizable project metadata schemas
- **Developer Friendly**: Automatic data collection via GitHub webhooks and integrations

## Version 2.0 (Alpha)

**Complete rewrite** using modern Python technologies for improved performance, scalability, and AI integration:

- **FastAPI**: Modern async web framework with automatic OpenAPI documentation
- **Neo4j**: Graph database for modeling service relationships and dependencies with native vector search
- **ClickHouse**: Analytics and time-series data storage for operations logs and metrics
- **Pydantic v2**: Type-safe data validation and settings management
- **Cypherantic**: Type-safe Neo4j integration with automatic Pydantic model mapping

### What's New in v2

- **Graph Database**: Neo4j replaces Postgres for intuitive relationship modeling and AI-friendly Cypher queries
- **Vector Search**: Built-in support for AI-powered semantic search across the service graph
- **Modern API**: FastAPI provides automatic OpenAPI docs, async performance, and better type safety
- **Simplified Architecture**: Dropping OpenSearch dependency in favor of Neo4j's native capabilities
- **AI-Ready**: Foundation for conversational AI, MCP server integration, and natural language queries
- **Full Authentication**: OAuth2/OIDC (Google, GitHub, Keycloak) and local password authentication with JWT tokens
- **Fine-Grained Authorization**: Permission-based access control with resource-level permissions and role management
- **Analytics Ready**: ClickHouse integration for operations logs and time-series metrics

## Quick Start

### Development Environment

```bash
# Bootstrap development environment (installs deps, starts Docker services)
./bootstrap

# Run development server with auto-reload
uv run imbi run-server --dev

# Access the API
curl http://localhost:8000/status
```

### Testing

```bash
# Run all tests with coverage
uv run pytest

# Run pre-commit checks
uv run pre-commit run --all-files
```

## Core Concepts

### Data Model

Imbi organizes services using a flexible, graph-based data model:

- **Organizations**: Top-level organizational units with unique slug identifiers
- **Teams**: Groups within organizations that own and maintain projects
- **Projects**: Individual services or applications with comprehensive metadata
- **Project Types**: Categories like 'Web Service', 'Library', 'Data Pipeline'
- **Environments**: Deployment targets like 'production', 'staging', 'development'
- **Blueprints**: Schema definitions for custom project metadata

### Authentication & Authorization

- **OAuth2/OIDC**: Support for Google, GitHub, and Keycloak providers
- **Local Authentication**: Password-based authentication with Argon2id hashing
- **JWT Tokens**: Access tokens (15 min) and refresh tokens (7 days)
- **Permission-Based Access Control**: Fine-grained permissions at the resource level
- **Role Management**: Flexible role system with group-based assignments

### Integrations

Imbi integrates with your existing DevOps toolchain:

- **Version Control**: GitHub webhooks for automatic project updates
- **CI/CD**: Links to build pipelines and deployment tools
- **Monitoring**: Integration with observability platforms
- **Issue Tracking**: Links to Jira, GitHub Issues, etc.
- **Incident Management**: PagerDuty integration for on-call management

## Architecture

Imbi v2 uses a multi-database architecture optimized for different data patterns:

- **Neo4j**: Graph database for service relationships, dependencies, and user/permission model
- **ClickHouse**: Analytics database for operations logs, metrics, and time-series data
- **FastAPI**: Async Python web framework for the REST API
- **Docker Compose**: Development environment with all required services

For detailed architecture decisions, see the [Architecture Decision Records](adr.md).

## Documentation

- **[Configuration Guide](configuration.md)**: Environment variables and settings
- **[Architecture Decision Records](adr.md)**: Key architectural decisions and rationale

## Contributing

Contributions are welcome! Please see the [GitHub repository](https://github.com/AWeber-Imbi/imbi-api) for:

- Issue tracking and feature requests
- Pull request process
- Development setup instructions
- Coding standards and conventions

## License

Imbi is licensed under the BSD-3-Clause License. See the LICENSE file for details.
