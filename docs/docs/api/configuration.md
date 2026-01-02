# Configuration

Imbi uses environment variables for configuration, managed through Pydantic Settings. Configuration can be provided via environment variables or a `.env` file in the project root.

## Quick Start

The `./bootstrap` script automatically generates a `.env` file with sensible defaults for development:

```bash
./bootstrap
```

This creates:
- Neo4j connection settings
- ClickHouse connection settings
- OpenTelemetry configuration for Jaeger tracing
- JWT secret for authentication

## Core Settings

### Application Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `IMBI_ENVIRONMENT` | `development` | Environment name (development, staging, production) |
| `IMBI_HOST` | `localhost` | Server bind address |
| `IMBI_PORT` | `8000` | Server bind port |
| `IMBI_LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) |
| `IMBI_AUTO_SEED_AUTH` | `true` | Auto-seed default roles and permissions on startup |

### Neo4j Configuration

Neo4j is used for the graph database storing service relationships, dependencies, and user/permission models.

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_URL` | `neo4j://localhost:7687` | Neo4j Bolt connection URL (supports credential extraction) |
| `NEO4J_USER` | *(from URL or none)* | Neo4j username (overrides URL credentials) |
| `NEO4J_PASSWORD` | *(from URL or none)* | Neo4j password (overrides URL credentials) |
| `NEO4J_DATABASE` | `neo4j` | Neo4j database name |
| `NEO4J_MAX_POOL_SIZE` | `50` | Maximum connection pool size |
| `NEO4J_KEEP_ALIVE` | `true` | Enable keep-alive for connections |

!!! note "URL Credential Extraction"
    The settings model automatically extracts and URL-decodes credentials from connection URLs like:
    ```
    neo4j://user:pass@localhost:7687
    ```
    Explicit `NEO4J_USER`/`NEO4J_PASSWORD` environment variables take precedence over URL credentials.

### ClickHouse Configuration

ClickHouse is used for analytics, operations logs, and time-series metrics.

| Variable | Default | Description |
|----------|---------|-------------|
| `CLICKHOUSE_URL` | `http://localhost:8123` | ClickHouse HTTP connection URL |
| `CLICKHOUSE_USER` | `default` | ClickHouse username |
| `CLICKHOUSE_PASSWORD` | `password` | ClickHouse password |
| `CLICKHOUSE_DATABASE` | `imbi` | ClickHouse database name |

### Authentication & Authorization

#### JWT Token Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `IMBI_AUTH_JWT_SECRET` | *(required)* | Secret key for JWT token signing |
| `IMBI_AUTH_JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `IMBI_AUTH_JWT_ACCESS_TOKEN_EXPIRY` | `900` | Access token lifetime in seconds (15 min) |
| `IMBI_AUTH_JWT_REFRESH_TOKEN_EXPIRY` | `604800` | Refresh token lifetime in seconds (7 days) |

!!! warning "Production Security"
    Generate a strong random secret for `IMBI_AUTH_JWT_SECRET` in production:
    ```bash
    python -c "import secrets; print(secrets.token_urlsafe(32))"
    ```

#### OAuth2/OIDC Provider Settings

Imbi supports multiple OAuth providers. Each provider requires client credentials from the respective platform.

**Google OAuth**

| Variable | Required | Description |
|----------|----------|-------------|
| `IMBI_AUTH_OAUTH_GOOGLE_CLIENT_ID` | Yes | Google OAuth2 client ID |
| `IMBI_AUTH_OAUTH_GOOGLE_CLIENT_SECRET` | Yes | Google OAuth2 client secret |
| `IMBI_AUTH_OAUTH_GOOGLE_REDIRECT_URI` | No | OAuth callback URL (default: auto-generated) |

**GitHub OAuth**

| Variable | Required | Description |
|----------|----------|-------------|
| `IMBI_AUTH_OAUTH_GITHUB_CLIENT_ID` | Yes | GitHub OAuth app client ID |
| `IMBI_AUTH_OAUTH_GITHUB_CLIENT_SECRET` | Yes | GitHub OAuth app client secret |
| `IMBI_AUTH_OAUTH_GITHUB_REDIRECT_URI` | No | OAuth callback URL (default: auto-generated) |

**Generic OIDC (Keycloak, Okta, Auth0, etc.)**

| Variable | Required | Description |
|----------|----------|-------------|
| `IMBI_AUTH_OAUTH_OIDC_CLIENT_ID` | Yes | OIDC client ID |
| `IMBI_AUTH_OAUTH_OIDC_CLIENT_SECRET` | Yes | OIDC client secret |
| `IMBI_AUTH_OAUTH_OIDC_DISCOVERY_URL` | Yes | OIDC discovery endpoint URL |
| `IMBI_AUTH_OAUTH_OIDC_REDIRECT_URI` | No | OAuth callback URL (default: auto-generated) |

#### Session Management

| Variable | Default | Description |
|----------|---------|-------------|
| `IMBI_AUTH_SESSION_TIMEOUT_SECONDS` | `86400` | Session timeout in seconds (24 hours) |
| `IMBI_AUTH_MAX_CONCURRENT_SESSIONS` | `5` | Maximum concurrent sessions per user |

### OpenTelemetry Configuration

Imbi supports distributed tracing via OpenTelemetry (Jaeger, etc.).

| Variable | Default | Description |
|----------|---------|-------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP gRPC endpoint |
| `OTEL_SERVICE_NAME` | `imbi` | Service name in traces |
| `OTEL_TRACES_EXPORTER` | `otlp` | Trace exporter type |

## Docker Compose Services

The development environment includes Docker services for all dependencies:

```yaml
services:
  neo4j:
    ports:
      - "7474:7474"  # HTTP browser interface
      - "7687:7687"  # Bolt protocol
    environment:
      - NEO4J_AUTH=none  # No authentication in development

  clickhouse:
    ports:
      - "8123:8123"  # HTTP interface
      - "9000:9000"  # Native protocol
    environment:
      - CLICKHOUSE_USER=default
      - CLICKHOUSE_PASSWORD=password

  jaeger:
    ports:
      - "4317:4317"   # OTLP gRPC
      - "16686:16686" # Jaeger UI
```

Access the services:

- **Neo4j Browser**: http://localhost:7474
- **ClickHouse**: http://localhost:8123
- **Jaeger UI**: http://localhost:16686

## Example .env File

```bash
# Application
IMBI_ENVIRONMENT=development
IMBI_HOST=localhost
IMBI_PORT=8000
IMBI_LOG_LEVEL=INFO
IMBI_AUTO_SEED_AUTH=true

# Neo4j
NEO4J_URL=neo4j://localhost:7687
NEO4J_DATABASE=neo4j
NEO4J_MAX_POOL_SIZE=50

# ClickHouse
CLICKHOUSE_URL=http://localhost:8123
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=password
CLICKHOUSE_DATABASE=imbi

# JWT Authentication
IMBI_AUTH_JWT_SECRET=your-secret-key-here-generate-with-secrets-module
IMBI_AUTH_JWT_ALGORITHM=HS256
IMBI_AUTH_JWT_ACCESS_TOKEN_EXPIRY=900
IMBI_AUTH_JWT_REFRESH_TOKEN_EXPIRY=604800

# OAuth Providers (optional - configure as needed)
# IMBI_AUTH_OAUTH_GOOGLE_CLIENT_ID=your-google-client-id
# IMBI_AUTH_OAUTH_GOOGLE_CLIENT_SECRET=your-google-client-secret

# OpenTelemetry
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=imbi
OTEL_TRACES_EXPORTER=otlp
```

## Production Considerations

### Security

1. **JWT Secret**: Use a cryptographically secure random string
2. **OAuth Secrets**: Store in a secrets manager (AWS Secrets Manager, HashiCorp Vault)
3. **Database Credentials**: Use strong passwords, rotate regularly
4. **HTTPS**: Always use HTTPS in production (configure via reverse proxy)

### Performance

1. **Neo4j Connection Pool**: Increase `NEO4J_MAX_POOL_SIZE` based on load (50-200)
2. **ClickHouse**: Configure appropriate retention policies for analytics data
3. **Access Token Expiry**: Balance security vs. user experience (5-15 minutes typical)

### Monitoring

1. **OpenTelemetry**: Configure production-grade tracing backend (Jaeger, Honeycomb, Datadog)
2. **Logging**: Set `IMBI_LOG_LEVEL=WARNING` or `ERROR` in production
3. **Health Checks**: Use `/status` endpoint for load balancer health checks

## Advanced Configuration

### Custom Settings Module

For advanced use cases, you can extend the settings system:

```python
from imbi.settings import Settings

# Load settings
settings = Settings()

# Access configuration
print(settings.neo4j.url)
print(settings.auth.jwt_secret)
```

### Environment-Specific Configuration

Use different `.env` files per environment:

```bash
# Development
cp .env.development .env

# Staging
cp .env.staging .env

# Production (load from secrets manager)
```

## Troubleshooting

### Neo4j Connection Issues

```bash
# Test Neo4j connectivity
docker compose exec neo4j cypher-shell

# Check Neo4j logs
docker compose logs neo4j
```

### ClickHouse Connection Issues

```bash
# Test ClickHouse connectivity
curl http://localhost:8123/ping

# Check ClickHouse logs
docker compose logs clickhouse
```

### Authentication Issues

```bash
# Verify JWT secret is set
echo $IMBI_AUTH_JWT_SECRET

# Check authentication logs
uv run imbi run-server --dev
# Look for JWT-related errors in output
```

## See Also

- [Architecture Decision Records](adr.md) - Key architectural decisions
- [GitHub Repository](https://github.com/AWeber-Imbi/imbi-api) - Source code and issues
