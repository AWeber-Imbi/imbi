# Configuration

Imbi is configured through environment variables. Each service reads its
own set of variables from the shared environment.

## Required Variables

These must be set for Imbi to start:

| Variable | Description |
|----------|-------------|
| `NEO4J_URL` | Neo4j Bolt connection URL (e.g. `bolt://neo4j:7687`) |
| `CLICKHOUSE_URL` | ClickHouse HTTP connection URL (e.g. `http://default:password@clickhouse:8123/imbi`) |
| `IMBI_AUTH_JWT_SECRET` | Secret key for signing JWT tokens. Use a random string of at least 32 characters. |
| `IMBI_AUTH_ENCRYPTION_KEY` | Fernet encryption key for encrypting sensitive data at rest. |

## Neo4j

| Variable | Description | Default |
|----------|-------------|---------|
| `NEO4J_URL` | Bolt connection URL. Credentials can be embedded: `bolt://user:pass@host:7687` | - |
| `NEO4J_USER` | Username (overrides URL credentials) | - |
| `NEO4J_PASSWORD` | Password (overrides URL credentials) | - |

## ClickHouse

| Variable | Description | Default |
|----------|-------------|---------|
| `CLICKHOUSE_URL` | HTTP connection URL with database path | - |

## Authentication

| Variable | Description | Default |
|----------|-------------|---------|
| `IMBI_AUTH_JWT_SECRET` | JWT signing secret | - |
| `IMBI_AUTH_ENCRYPTION_KEY` | Fernet encryption key | - |
| `IMBI_AUTH_LOCAL_ENABLED` | Enable local password authentication | `true` |
| `IMBI_AUTH_CALLBACK_BASE_URL` | Base URL for OAuth callbacks | `http://localhost:8000` |
| `IMBI_AUTH_SESSION_TIMEOUT` | Session duration in seconds | `86400` (24h) |

### OAuth Providers

#### Google

| Variable | Description |
|----------|-------------|
| `IMBI_AUTH_GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `IMBI_AUTH_GOOGLE_CLIENT_SECRET` | Google OAuth client secret |

#### GitHub

| Variable | Description |
|----------|-------------|
| `IMBI_AUTH_GITHUB_CLIENT_ID` | GitHub OAuth client ID |
| `IMBI_AUTH_GITHUB_CLIENT_SECRET` | GitHub OAuth client secret |

#### OIDC (Keycloak, etc.)

| Variable | Description |
|----------|-------------|
| `IMBI_AUTH_OIDC_CLIENT_ID` | OIDC client ID |
| `IMBI_AUTH_OIDC_CLIENT_SECRET` | OIDC client secret |
| `IMBI_AUTH_OIDC_DISCOVERY_URL` | OIDC discovery endpoint URL |

## Email

| Variable | Description | Default |
|----------|-------------|---------|
| `IMBI_EMAIL_ENABLED` | Enable email notifications | `false` |
| `IMBI_EMAIL_SMTP_HOST` | SMTP server hostname | - |
| `IMBI_EMAIL_SMTP_PORT` | SMTP server port | `587` |
| `IMBI_EMAIL_SMTP_USE_TLS` | Use TLS for SMTP | `true` |
| `IMBI_EMAIL_FROM_EMAIL` | Sender email address | - |
| `IMBI_EMAIL_FROM_NAME` | Sender display name | - |

## AI Assistant

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude | - |
| `IMBI_ASSISTANT_ENABLED` | Enable the AI assistant | `false` (auto-enabled if API key set) |
| `IMBI_ASSISTANT_MODEL` | Claude model to use | `claude-sonnet-4-6` |
| `IMBI_ASSISTANT_MAX_TOKENS` | Maximum response tokens | `16384` |

## Gateway

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_URL` | PostgreSQL connection URL | - |

## S3 Storage

| Variable | Description | Default |
|----------|-------------|---------|
| `S3_ENDPOINT_URL` | S3-compatible endpoint (for MinIO, LocalStack) | - (AWS) |
| `S3_ACCESS_KEY` | AWS access key | - |
| `S3_SECRET_KEY` | AWS secret key | - |
| `S3_BUCKET` | S3 bucket name | `imbi-uploads` |
| `S3_REGION` | AWS region | `us-east-1` |

## Service Selection

When running the Docker image, you can select which service to run:

| Variable | Description | Default |
|----------|-------------|---------|
| `IMBI_SERVICE` | Service to run: `all`, `api`, `assistant`, `gateway`, `mcp` | `all` |
