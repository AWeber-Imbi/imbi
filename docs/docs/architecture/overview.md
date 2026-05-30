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
                 PostgreSQL + AGE        ClickHouse
                  (graph database)       (analytics)
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

- PostgreSQL + Apache AGE graph client (async)
- ClickHouse client
- Domain models (Pydantic)
- Authentication utilities (JWT, Argon2)
- Settings management

## Data Stores

### PostgreSQL + Apache AGE

PostgreSQL with the Apache AGE extension is the primary datastore, providing
both graph and relational storage:

- Service/project nodes and their relationships
- Dependency graph between services
- User, group, and role hierarchy
- Organization and team structure
- Webhook event storage and processing state (gateway)

### ClickHouse

Column-oriented analytics database storing:

- Operations logs
- Time-series metrics
- Audit trail
