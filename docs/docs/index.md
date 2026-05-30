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

## Architecture

Imbi is composed of several services packaged into a single Docker image:

| Service | Purpose |
|---------|---------|
| **imbi-api** | Core REST API for CRUD operations, authentication, and authorization |
| **imbi-assistant** | AI assistant powered by Claude for conversational queries |
| **imbi-gateway** | Inbound webhook gateway for external event processing |
| **imbi-mcp** | MCP server for AI agent integration |
| **imbi-ui** | React-based web interface |

All services run behind [Caddy](https://caddyserver.com/) as a reverse proxy.

## Data Stores

| Database | Purpose |
|----------|---------|
| **PostgreSQL + Apache AGE** | Graph and relational database for service relationships, dependencies, users, permissions, and webhook gateway state |
| **ClickHouse** | Analytics database for operations logs and time-series data |
