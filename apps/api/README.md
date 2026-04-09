# Imbi

> A DevOps Service Management Platform for managing complex service ecosystems

Imbi provides a centralized platform to manage, track, and understand all services and applications across your
organization. It serves as a single source of truth for service metadata, dependencies, ownership, and operational
information.

## What is Imbi?

Imbi helps organizations answer critical questions about their service landscape:

- **What services do we have?** Complete inventory with ownership, type, and namespace organization
- **How are they related?** Graph-based dependency tracking and relationship visualization
- **Who owns what?** Clear ownership and team assignments
- **What's deployed where?** Environment-specific URLs and deployment tracking
- **What needs attention?** Project health scoring based on configurable factors
- **Where's the documentation?** Links to repos, CI/CD, monitoring, and other tools

### Key Benefits

- **Single Source of Truth**: Centralized service catalog with comprehensive metadata
- **Relationship Visualization**: Graph database enables intuitive dependency mapping
- **Automation Ready**: API-first design enables integration with CI/CD, webhooks, and automations
- **AI-Powered**: Built-in vector search and conversational AI support for natural language queries
- **Extensible**: Blueprint system for customizable project metadata schemas
- **Developer Friendly**: Automatic data collection via GitHub webhooks and integrations

## Version 2.0 (Alpha)

**Complete rewrite** using modern Python technologies for improved performance, scalability, and AI integration:

- **FastAPI**: Modern async web framework with automatic OpenAPI documentation
- **Apache AGE**: Graph database (PostgreSQL extension) for modeling service relationships and dependencies
- **ClickHouse**: Analytics and time-series data storage for operations logs and metrics
- **Pydantic v2**: Type-safe data validation and settings management

### What's New in v2

- **Graph Database**: Apache AGE (PostgreSQL) for intuitive relationship modeling and AI-friendly Cypher queries
- **Modern API**: FastAPI provides automatic OpenAPI docs, async performance, and better type safety
- **Simplified Architecture**: Single PostgreSQL instance for relational and graph data
- **Full Authentication**: OAuth2/OIDC (Google, GitHub, Keycloak) and local password authentication with JWT tokens
- **Fine-Grained Authorization**: Permission-based access control with resource-level permissions and role management
- **Analytics Ready**: ClickHouse integration for operations logs and time-series metrics

For developers, see [CLAUDE.md](CLAUDE.md) for development guide and architecture details.

## Quick Start

### Development Environment

```bash
# Set up development environment (install deps, pre-commit hooks)
just setup

# Start Docker services and run the development server with auto-reload
just serve --dev

# Initialize Imbi (first time only — seeds roles/permissions, creates admin user)
uv run imbi-api setup

# Access the API
curl http://localhost:8000/status
```

### Testing

```bash
# Run all tests with coverage
just test

# Run pre-commit checks + type checking
just lint
```

## Core Concepts

### Data Model

Imbi organizes services using a flexible, graph-based data model:

- **Organizations**: Top-level organizational units
    - Unique slug identifier
    - Name, description, and optional icon
    - Foundation for hierarchical team structure

- **Teams**: Groups within organizations
    - Managed by an organization (MANAGED_BY relationship)
    - Own and maintain projects
    - Unique slug identifier within their scope

- **Projects**: Individual services or applications
    - Owned by a team (OWNED_BY relationship)
    - Categorized by project type (TYPE relationship)
    - Deployed in environments (DEPLOYED_IN relationship)
    - Links to external tools (GitHub, Jira, PagerDuty, monitoring, etc.)
    - Environment-specific URLs (staging, production, etc.)
    - Custom identifiers (repo IDs, service IDs, etc.)

- **Project Types**: Service categorization
    - Web Services, APIs, Libraries, Databases, etc.
    - Unique slug identifier
    - Used to classify projects

- **Environments**: Deployment targets
    - Production, Staging, Development, etc.
    - Unique slug identifier
    - Projects can be deployed to multiple environments

- **Blueprints**: JSON Schema-based metadata templates
    - Apply to Organizations, Teams, Environments, Project Types, or Projects
    - Define custom fields with validation rules
    - Enforce required metadata
    - Priority-based application when multiple blueprints match
    - Optional filtering based on entity properties

- **Users, Groups, and Roles**: Authentication and authorization
    - Users with OAuth or local password authentication
    - Groups for organizing users
    - Roles with fine-grained permissions
    - Resource-based access control

### API Access

Once the server is running, explore the API:

```bash
# Health check
curl http://localhost:8000/status

# Get authentication providers
curl http://localhost:8000/auth/providers

# API documentation
open http://localhost:8000/docs  # ReDoc UI
```

## License

BSD 3-Clause License

Copyright (c) 2018 - 2026, AWeber
