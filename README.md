# Imbi

Imbi is a DevOps Service Management Platform for managing large environments
containing many services and applications. It provides a centralized service
catalog with metadata management, dependency tracking, ownership hierarchy,
and AI-powered features.

## Features

- **Service Catalog**: Centralized inventory of all services and applications
- **Dependency Tracking**: Graph-based dependency visualization using PostgreSQL + Apache AGE
- **Blueprint System**: Customizable metadata schemas for extending project fields
- **Ownership Hierarchy**: Organization, team, and user-based ownership model
- **AI Assistant**: Conversational AI powered by Claude for service queries
- **MCP Server**: Model Context Protocol server for AI agent access
- **Webhook Gateway**: Inbound event processing from GitHub, PagerDuty, etc.
- **Analytics**: Operations logs and time-series data via ClickHouse
- **Authentication**: OAuth2/OIDC (Google, GitHub, Keycloak) + local auth

## Architecture

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

All services run behind [Caddy](https://caddyserver.com/), a powerful and
extensible reverse proxy with automatic HTTPS. The Docker image packages
everything into a single deployable unit that can run all services together
or scale out individual components.

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [just](https://github.com/casey/just) (command runner)

### Running with Docker Compose

The included `compose.yaml` starts Imbi and all backing services:

```bash
# Build and start everything
docker compose up --build -d

# Run initial setup (create admin user, seed permissions)
docker compose exec -it imbi imbi-api setup

# View logs
docker compose logs -f imbi
```

Once running, Imbi is available at **http://localhost:8080** — the only
service published on a fixed host port:

| Service | URL | Description |
|---------|-----|-------------|
| Imbi | http://localhost:8080 | Main application (UI + API via Caddy) |

The backing services are exposed on **ephemeral** host ports (assigned by
Docker) to avoid collisions. Find a service's mapped port with
`docker compose port <service> <container-port>`:

| Service | Container port | Description |
|---------|----------------|-------------|
| PostgreSQL | 5432 | Graph database (Apache AGE); user `postgres`, password `secret` |
| ClickHouse | 8123 | Analytics database HTTP interface |
| Mailpit | 8025 | Email testing UI (captures all outbound email) |
| LocalStack | 4566 | S3-compatible object storage |

### UI Development with Docker Compose

You can use Docker Compose to run the full backend stack while developing
the UI locally with hot-reload:

```bash
# 1. Start the backend services
docker compose up --build -d

# 2. Run initial setup (first time only — creates admin user, seeds permissions)
docker compose exec -it imbi imbi-api setup

# 3. In the imbi-ui directory, point the dev proxy at the local backend
cd repositories/imbi-ui
echo 'VITE_PROXY_TARGET=http://localhost:8080' > .env.local
npm install
npm run dev
```

The Vite dev server starts on http://localhost:3000 and proxies `/api`
requests to the Caddy reverse proxy at `:8080`, which routes them to the
appropriate backend service.

If you have an API token (e.g. from `imbi-api setup`), you can pass it
to the proxy so requests are authenticated:

```bash
echo 'VITE_PROXY_TARGET=http://localhost:8080' > .env.local
echo 'VITE_API_TOKEN=your-token-here' >> .env.local
```

Useful services during UI development:

| Service | URL | Use |
|---------|-----|-----|
| UI (dev) | http://localhost:3000 | Vite dev server with hot-reload |
| Imbi (backend) | http://localhost:8080 | Full app via Caddy (API + bundled UI) |

Mailpit (email) and PostgreSQL (graph data) are reachable on the ephemeral
host ports reported by `docker compose port <service> <container-port>`
(see the table above) for inspecting state during development.

### Python Service Development (Beta)

> **Note:** This workflow is in beta. The existing Docker Compose workflow
> above remains the recommended approach for most development.

You can develop individual Python services locally with hot-reload while
the rest of the stack runs in Docker. The `start-dev` and `stop-dev`
commands manage the Caddy reverse proxy to route traffic to a standalone
dev container that mounts your local source code:

```bash
# First-time setup (builds the image and annotates Caddy routes)
just bootstrap

# Start developing a service (builds, starts, and routes traffic)
just start-dev imbi-api

# Stop the dev service (scales down and reroutes traffic to the main container)
just stop-dev imbi-api
```

The dev container mounts the service's source directory and uses
[uv](https://docs.astral.sh/uv/) for fast dependency installation.
Changes to your local source files are reflected immediately.

### Running the Docker Image

```bash
# Run all services (default)
docker run -p 8080:8080 \
  -e CLICKHOUSE_URL=clickhouse+http://default:password@clickhouse:8123/imbi \
  -e IMBI_AUTH_JWT_SECRET=your-secret-here \
  -e IMBI_AUTH_ENCRYPTION_KEY=your-encryption-key \
  ghcr.io/aweber-imbi/imbi:latest

# Run a specific service only
docker run -e IMBI_SERVICE=api ...
docker run -e IMBI_SERVICE=assistant ...
docker run -e IMBI_SERVICE=gateway ...
docker run -e IMBI_SERVICE=mcp ...

# Run initial setup (create admin user, seed permissions)
docker run -it \
  -e CLICKHOUSE_URL=clickhouse+http://default:password@clickhouse:8123/imbi \
  -e IMBI_AUTH_JWT_SECRET=your-secret-here \
  -e IMBI_AUTH_ENCRYPTION_KEY=your-encryption-key \
  ghcr.io/aweber-imbi/imbi:latest setup
```

### Deploying with Helm

```bash
helm install imbi helm/imbi \
  --set auth.jwtSecret=your-secret \
  --set auth.encryptionKey=your-key
```

See [Helm chart documentation](helm/imbi/README.md) for full configuration.

## Building

### Prerequisites

- [just](https://github.com/casey/just)
- [Docker](https://docs.docker.com/get-docker/)

### Build Commands

```bash
# Build the Docker image
just build

# Build with a specific tag
just build v1.0.0

# Check out all submodules at their recorded commits
just checkout-submodules

# Update all submodules to latest main
just update-submodules

# Update all submodules to a specific tag
just update-submodules-tag v1.0.0
```

## Environment Variables

### Required

| Variable | Description | Services |
|----------|-------------|----------|
| `CLICKHOUSE_URL` | ClickHouse connection URL | api |
| `IMBI_AUTH_JWT_SECRET` | JWT signing secret | api, assistant |
| `IMBI_AUTH_ENCRYPTION_KEY` | Fernet encryption key | api |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `IMBI_SERVICE` | Service to run (`all`, `api`, `assistant`, `gateway`, `mcp`) | `all` |
| `POSTGRES_URL` | PostgreSQL URL for gateway | - |
| `ANTHROPIC_API_KEY` | Anthropic API key for assistant | - |
| `IMBI_ASSISTANT_ENABLED` | Enable the AI assistant | `false` |
| `IMBI_EMAIL_ENABLED` | Enable email notifications | `false` |
| `IMBI_EMAIL_SMTP_HOST` | SMTP server host | `localhost` |
| `IMBI_EMAIL_SMTP_PORT` | SMTP server port | `587` |
| `IMBI_EMAIL_SMTP_USE_TLS` | Use TLS for SMTP | `true` |
| `IMBI_ENVIRONMENT` | Runtime environment | `development` |

## Project Structure

```
imbi/
├── repositories/                 # Git submodules for every service and plugin
│   ├── imbi-api/                 # Core REST API
│   ├── imbi-assistant/           # AI assistant service
│   ├── imbi-gateway/             # Webhook gateway
│   ├── imbi-mcp/                 # MCP server
│   ├── imbi-ui/                  # React frontend
│   ├── imbi-plugin-aws/          # AWS plugin
│   ├── imbi-plugin-github/       # GitHub plugin
│   ├── imbi-plugin-google/       # Google identity plugin
│   ├── imbi-plugin-logzio/       # Logz.io plugin
│   ├── imbi-plugin-oidc/         # OIDC authentication plugin
│   ├── imbi-plugin-pagerduty/    # PagerDuty plugin
│   ├── imbi-plugin-sonarqube/    # SonarQube plugin
│   └── imbi-slackbot/            # Slack bot
├── runtime/           # Per-service dev image + Caddy helper for `just start-dev`/`stop-dev`
├── Caddyfile          # Reverse proxy configuration
├── compose.yaml       # Local Docker Compose stack
├── docs/              # Administration and usage documentation
├── helm/imbi/         # Helm chart for Kubernetes deployment
├── Dockerfile         # Multi-stage Docker build
├── entrypoint.sh      # Container entrypoint with service dispatch
└── justfile           # Build and development commands
```

> `imbi-common` is the shared Python library; it is pulled in as a published
> dependency rather than tracked as a submodule here.

## Documentation

Full documentation is available at
[aweber-imbi.github.io/imbi](https://aweber-imbi.github.io/imbi/) and
covers installation, configuration, administration, and usage.

## License

BSD 3-Clause License. See [LICENSE](LICENSE) for details.
