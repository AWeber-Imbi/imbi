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

## Platform Components

Imbi is a set of services that share one container image. The `IMBI_SERVICE`
variable selects the service that a container runs. See
[Services](../architecture/services.md) for ports and URL routing.

| Service | What it does | Documentation |
|---|---|---|
| imbi-api | The REST API. It owns the data and the background workers. | This section |
| imbi-ui | The web interface. | [Initial Setup](../getting-started/setup.md) |
| imbi-gateway | Receives webhooks from integrations and runs their actions. | [Webhook Filter Expressions](../gateway/webhook-filter-expressions.md) |
| imbi-scheduler | Runs scheduled tasks. | [Scheduler](../scheduler/index.md) |
| imbi-workflows | Runs workflows. | [Workflows](../admin/workflows.md) |
| imbi-assistant | The AI assistant in the web interface. | [Prompts](../admin/prompts.md) |
| imbi-mcp | The Model Context Protocol server for AI clients. | [Services](../architecture/services.md) |
| imbi-slackbot | The Slack bot. | [Slack App Manifest](../slackbot/slack-app-manifest.md) |

imbi-harness is not in the shared image. It has its own image and Helm chart.
Its runner pods claim agent tasks from imbi-api. See
[Agent Runners](../deployment/agent-runners.md).

### Data Stores

| Store | Holds |
|---|---|
| PostgreSQL with Apache AGE | The graph of domain entities, and the relational schemas for the scheduler, agent tasks, workflows, the harness, and the secrets broker |
| ClickHouse | Operations log, events, commits and pull requests, score history, agent task and workflow run events, and email and secret audit logs |
| Apache Iggy | The message stream that carries rows to ClickHouse. See [ADR 0019](adr/0019-apache-iggy-message-streaming.md) |
| Valkey | Cache and the background worker queues |
| S3-compatible object storage | Icons, avatars, and document uploads. Development uses ministack |

### Capability Areas

| Area | Documentation |
|---|---|
| Blueprints | [Blueprints](../admin/blueprints.md) |
| Plugins and integrations | [Plugins](../common/plugins/index.md) |
| Deployments and releases | [Deployment plugins](../common/plugins/deployment.md) |
| Project scoring | [ADR 0011](adr/0011-graph-based-project-scoring.md) |
| Agents and agent tasks | [Agents](../admin/agents.md), [Agent Tasks](../admin/agent-tasks.md) |
| Workflows | [Workflows](../admin/workflows.md) |
| Secrets broker | [Secrets](../admin/secrets.md) |
| AI model catalog | [AI Models](../admin/ai-models.md) |
| Prompt management | [Prompts](../admin/prompts.md) |

## API Reference

The API serves its own reference. Use it for the list of routes:

- `/docs` shows the interactive reference.
- `/openapi.json` gives the OpenAPI schema.

Both are at the root of the API host, also when `IMBI_API_URL` has a path
prefix such as `/api`.

## Quick Start

This project uses [moon](https://moonrepo.dev) as its task runner and [uv](https://docs.astral.sh/uv/) for Python package management.

### Development Environment

```bash
# Install dependencies and pre-commit hooks
moon run root:setup

# Start Docker services (Postgres+AGE, ClickHouse, Valkey, Iggy,
# ministack, Mailpit, Jaeger) and write .env.test with the assigned ports and
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
uv run --env-file .env.test pytest apps/api/tests/auth/test_permissions.py::ResourceLevelPermissionTestCase::test_check_resource_permission_user_access
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
- **API Keys**: Format `ik_<32 hex characters>_<secret>` with scoped permissions and a last-used timestamp
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

## Documentation

- **[Configuration Guide](configuration.md)**: All configuration variables — `config.toml`, environment variables, and `.env`
- **[Architecture Decision Records](adr.md)**: Key architectural decisions and rationale

## Contributing

Contributions are welcome! Please see the [GitHub repository](https://github.com/AWeber-Imbi/imbi) for:

- Issue tracking and feature requests
- Pull request process
- Development setup instructions
- Coding standards and conventions

## License

Imbi is licensed under the BSD-3-Clause License. See the LICENSE file for details.
