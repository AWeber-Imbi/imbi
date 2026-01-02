# Configuration

Imbi uses a flexible configuration system managed through Pydantic Settings. Configuration can be provided via:
- **`config.toml` files** - Structured TOML configuration (recommended for production)
- **Environment variables** - Direct environment variable overrides
- **`.env` files** - Environment variable files for development

## Configuration Priority

Settings are loaded in the following priority order (highest to lowest):

1. **Environment variables** - Always take precedence
2. **`./config.toml`** - Project root configuration file
3. **`~/.config/imbi/config.toml`** - User-specific configuration
4. **`/etc/imbi/config.toml`** - System-wide configuration
5. **Built-in defaults** - Sensible defaults for development

## Quick Start

### Development Setup

The `./bootstrap` script automatically generates a `.env` file with sensible defaults for development:

```bash
./bootstrap
```

This creates:
- Neo4j connection settings
- ClickHouse connection settings
- OpenTelemetry configuration for Jaeger tracing
- JWT secret for authentication

### Production Setup

For production deployments, use a `config.toml` file with environment variable overrides for secrets:

```bash
# Create system config
sudo mkdir -p /etc/imbi
sudo vim /etc/imbi/config.toml

# Set secrets via environment
export IMBI_AUTH_JWT_SECRET="your-secret-here"
export NEO4J_PASSWORD="your-neo4j-password"
```

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

## Configuration File Format

### config.toml Example

For production deployments, use a structured TOML configuration file:

```toml
[server]
environment = "production"
host = "0.0.0.0"
port = 8080

[neo4j]
url = "neo4j://neo4j-prod:7687"
user = "admin"
# Password should come from environment variable: NEO4J_PASSWORD
database = "neo4j"
keep_alive = true
max_connection_lifetime = 300

[clickhouse]
url = "http://clickhouse-prod:8123"
# Credentials should come from environment variables

[auth]
# JWT secret should come from environment variable: IMBI_AUTH_JWT_SECRET
jwt_algorithm = "HS256"
access_token_expire_seconds = 900
refresh_token_expire_seconds = 604800
min_password_length = 12
max_concurrent_sessions = 5

# OAuth configuration (optional)
oauth_google_enabled = true
oauth_google_client_id = "your-client-id"
# Client secret should come from environment variable

[email]
enabled = true
smtp_host = "smtp.example.com"
smtp_port = 587
smtp_use_tls = true
from_email = "noreply@example.com"
from_name = "Imbi Platform"
```

### .env File Example

For development, use environment variables or a `.env` file:

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

### Loading Configuration Programmatically

The configuration system can be accessed programmatically in your code:

```python
from imbi import settings

# Load configuration from config.toml with environment overrides
config = settings.load_config()

# Access individual settings sections
print(f"Server: {config.server.environment} on {config.server.host}:{config.server.port}")
print(f"Neo4j: {config.neo4j.url}")
print(f"Auth: JWT algorithm {config.auth.jwt_algorithm}")

# Direct access to specific settings classes
neo4j_settings = settings.Neo4j()
server_config = settings.ServerConfig()
```

### Environment-Specific Configuration

Use different configuration files per environment:

```bash
# Development - use .env file
./bootstrap
uv run imbi serve --dev

# Staging - use staging config file
cp /path/to/staging/config.toml ./config.toml
uv run imbi serve

# Production - use system config + environment variables
# Config at /etc/imbi/config.toml
export IMBI_AUTH_JWT_SECRET="$(load-from-secrets-manager)"
export NEO4J_PASSWORD="$(load-from-secrets-manager)"
uv run imbi serve
```

### Configuration Best Practices

1. **Secrets in Environment Variables**: Store sensitive values (passwords, API keys, JWT secrets) in environment variables, not in config files
2. **Config Files for Structure**: Use `config.toml` for structured, non-sensitive configuration
3. **Version Control**: Commit example configs (e.g., `config.example.toml`), never commit actual secrets
4. **Deployment Automation**: Use configuration management tools (Ansible, Terraform) to deploy config files
5. **Secret Management**: Use proper secret managers (AWS Secrets Manager, HashiCorp Vault) in production

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
uv run imbi serve --dev
# Look for JWT-related errors in output
```

## See Also

- [Architecture Decision Records](adr.md) - Key architectural decisions
- [GitHub Repository](https://github.com/AWeber-Imbi/imbi-api) - Source code and issues
