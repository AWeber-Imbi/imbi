# Architecture Overview

Imbi is composed of several services that work together to provide a
complete service management platform.

## Service Architecture

```
                          +--------------------+
                          |       Caddy        |
                          |   reverse proxy    |
                          +----+--+--+--+--+---+
                               |  |  |  |  |
        +----------------------+  |  |  |  +---------------------+
        |            +------------+  |  +-----------+            |
        |            |               |              |            |
    imbi-api   imbi-assistant    imbi-ui      imbi-gateway   imbi-mcp
    (FastAPI)    (FastAPI)     (React/Vite)    (FastAPI)      (FastMCP)
        |            |                              |            |
        +------------+--------------+---------------+------------+
                                    |
                              imbi-common
                       (shared Python library)
                                    |
                          +---------+---------+
                          |                   |
                        Neo4j            ClickHouse
```

## Services

### imbi-api

The core REST API service built with FastAPI. Provides:

- CRUD operations for the service catalog
- Authentication (OAuth2/OIDC + local passwords)
- Authorization (role-based permissions)
- Blueprint system for customizable metadata

### imbi-assistant

AI-powered assistant built with FastAPI and the Anthropic SDK. Provides:

- Conversational queries about the service catalog
- Streaming responses via Server-Sent Events
- Conversation management and history

### imbi-gateway

Inbound webhook gateway built with FastAPI. Provides:

- Event ingestion from external systems (GitHub, PagerDuty)
- Event recording and routing

### imbi-mcp

Model Context Protocol server built with FastMCP. Provides:

- AI agent access to service catalog data
- Dependency graph queries
- Service discovery

### imbi-common

Shared Python library used by all backend services. Provides:

- Neo4j client with async support
- ClickHouse client
- Domain models (Pydantic)
- Authentication utilities (JWT, Argon2)
- Settings management

## Data Stores

### Neo4j

Graph database storing:

- Service/project nodes and their relationships
- User, group, and role hierarchy
- Dependency graph between services
- Organization and team structure

### ClickHouse

Column-oriented analytics database storing:

- Operations logs
- Time-series metrics
- Audit trail

### PostgreSQL

Relational database used by the gateway for:

- Webhook event storage
- Event processing state
