# Imbi

Imbi is a DevOps Service Management Platform for managing large environments
containing many services and applications.

## What is Imbi?

Imbi provides a centralized service catalog that tracks:

- **Services and applications** with rich metadata
- **Dependencies** between services via a graph database
- **Ownership** through organizations, teams, and users
- **Operational data** including deployment history and analytics

## Key Features

- **Blueprint System** - Define custom metadata schemas for different project types
- **AI Assistant** - Conversational AI for querying your service catalog
- **Webhook Gateway** - Receive events from GitHub, PagerDuty, and other tools
- **MCP Server** - Expose service data to AI agents via the Model Context Protocol
- **Graph Visualization** - Explore service dependencies visually
- **Scheduled Tasks** - Cron, interval, and one-shot triggers that call the API
  or the gateway on a schedule
- **[Agents](admin/agents.md)** - Define AI agents and give them
  [tasks](admin/agent-tasks.md) to do against your projects
- **[Workflows](admin/workflows.md)** - Chain deploy, rollback, agent, email, and
  wait steps that start manually, on a schedule, or from a webhook
- **[Agent Runners](deployment/agent-runners.md)** - Run agent tasks in runner
  pools that you deploy in your own Kubernetes cluster

## Architecture

Imbi is composed of several services packaged into a single Docker image:

| Service | Purpose |
|---------|---------|
| **imbi-api** | Core REST API for CRUD operations, authentication, and authorization |
| **imbi-assistant** | AI assistant powered by Claude for conversational queries |
| **imbi-gateway** | Inbound webhook gateway for external event processing |
| **imbi-mcp** | MCP server for AI agent integration |
| **imbi-scheduler** | Triggers scheduled tasks against imbi-api and imbi-gateway |
| **imbi-slackbot** | Slack bot for querying and updating the catalog from Slack |
| **imbi-workflows** | Workflow engine that executes workflow runs |
| **imbi-ui** | React-based web interface |

All services run behind [Caddy](https://caddyserver.com/) as a reverse proxy,
except imbi-slackbot, which connects out to Slack over socket mode, and
imbi-workflows, which has no public route.

The agent runner, imbi-harness, is not in this image. It has its own image
and Helm chart. See [Agent Runners](deployment/agent-runners.md).

## Data Stores

| Database | Purpose |
|----------|---------|
| **PostgreSQL + Apache AGE** | Graph and relational database for service relationships, dependencies, users, permissions, and webhook gateway state |
| **ClickHouse** | Analytics database for operations logs and time-series data |
