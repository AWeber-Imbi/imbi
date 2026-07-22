# Configuration

Imbi uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) to load configuration from three sources, merged in priority order:

1. **Environment variables** — always win
2. **`config.toml` files** — discovered in this order, first match wins per key:
    1. `./config.toml` (project root)
    2. `~/.config/imbi/config.toml` (user)
    3. `/etc/imbi/config.toml` (system)
3. **Built-in defaults** — sensible defaults for development

A `.env` file in the working directory is also read for environment variables (pydantic-settings default).

## Quick Start

### Development Setup

`just serve` runs `just docker` first, which boots all services and writes a fresh `.env` with the dynamically-allocated host ports (Postgres, ClickHouse, Valkey, LocalStack, Mailpit, Jaeger) and freshly-generated JWT and Fernet secrets if none are present.

```bash
just setup       # uv sync + pre-commit hooks
just serve --dev # docker + auto-reload server
```

### Production Setup

Put structural configuration in `/etc/imbi/config.toml` and inject secrets via environment variables:

```bash
sudo install -d /etc/imbi
sudo $EDITOR /etc/imbi/config.toml

export POSTGRES_URL='postgresql://imbi:...@db.example.com:5432/imbi'
export IMBI_AUTH_JWT_SECRET="$(secrets-manager get jwt-secret)"
export IMBI_AUTH_ENCRYPTION_KEY="$(secrets-manager get encryption-key)"
```

Generate the JWT secret and Fernet encryption key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

!!! warning "Stable secrets in production"
    If `IMBI_AUTH_JWT_SECRET` or `IMBI_AUTH_ENCRYPTION_KEY` is unset, the application auto-generates a value at startup and logs a warning. This is fine for ephemeral dev runs, but in production it will invalidate every issued token and break every encrypted credential on every restart — always provide both explicitly.

## Application Settings

### Server (`IMBI_API_*`)

Configured by [`ServerConfig`](https://github.com/AWeber-Imbi/imbi-api/blob/main/src/imbi.api/settings.py). The `[server]` section in `config.toml` maps to these.

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `development` | Deployment environment (`development`, `staging`, `production`). Unprefixed — picks up whatever the platform (Vercel, ECS, GHA, etc.) already exports. Currently drives Mailpit dev auto-config. |
| `IMBI_API_HOST` | `localhost` | Server bind address |
| `IMBI_API_PORT` | `8000` | Server bind port. Strings of the form `tcp://ip:port` (injected by Kubernetes service discovery) are parsed and the port extracted, so the `<SERVICE>_PORT=tcp://…` pattern does not collide with this field. |
| `IMBI_API_CORS_ALLOWED_ORIGINS` | `[]` | JSON array of allowed CORS origins. Credentials and the `Authorization` header are allowed for cross-origin requests from these origins. Also the allow-list of trusted hosts for per-request OAuth URL derivation in multi-host deployments (see "OAuth2 Authorization Server"). |
| `IMBI_API_FORWARDED_ALLOW_IPS` | `''` | Comma-separated list (or `*`) of trusted proxy IPs whose `X-Forwarded-*` headers are honored. Required when running behind a reverse proxy so rate limiting keys on the real client IP. Empty disables the middleware. |
| `IMBI_API_URL` | `''` | Public URL where the API is reachable from a browser, including any path prefix it is mounted under (e.g. `https://imbi.example.com/api`). Drives FastAPI route mounting, hypermedia links, and OAuth redirect URIs. Falls back to `http://{host}:{port}` (no prefix) for dev loopback. `/docs` and `/openapi.json` are always served at the root regardless of prefix. |

### PostgreSQL + Apache AGE (`POSTGRES_*`)

PostgreSQL with the Apache AGE extension stores all graph and relational domain data (organizations, teams, projects, users, permissions, blueprints, etc.). The `[postgres]` section in `config.toml` maps to these.

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_URL` | `postgresql://postgres:secret@localhost:5432/imbi` | PostgreSQL DSN |
| `POSTGRES_GRAPH_NAME` | `imbi` | Apache AGE graph name |
| `POSTGRES_MIN_POOL_SIZE` | `2` | Minimum connection pool size |
| `POSTGRES_MAX_POOL_SIZE` | `10` | Maximum connection pool size |

### ClickHouse (`CLICKHOUSE_*`)

ClickHouse stores analytics, operations logs, audit logs, email send logs, and API-key usage metrics. The `[clickhouse]` section in `config.toml` maps to these.

| Variable | Default | Description |
|----------|---------|-------------|
| `CLICKHOUSE_URL` | `clickhouse+http://localhost:8123` | ClickHouse DSN. Credentials in the URL are honored. |
| `CLICKHOUSE_CONNECT_TIMEOUT` | `10.0` | Connection timeout in seconds |
| `CLICKHOUSE_MAX_CONNECT_ATTEMPTS` | `10` | Maximum connection attempts on startup |

### Valkey (`VALKEY_*`)

Valkey (Redis-compatible) is used for ephemeral caching. The `[valkey]` section in `config.toml` maps to these.

| Variable | Default | Description |
|----------|---------|-------------|
| `VALKEY_URL` | `valkey://localhost:6379/0` | Valkey DSN (defaults: host `localhost`, port `6379`, db `0`) |

### Object Storage (`S3_*`)

S3-compatible storage holds icons, avatars, and document uploads. The `[storage]` section in `config.toml` maps to these.

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_ENDPOINT_URL` | *(none — real AWS S3)* | Set to a LocalStack or MinIO endpoint to override |
| `S3_ACCESS_KEY` | *(none)* | Access key ID. Omit to use the default AWS credential chain (instance role, profile, etc.). |
| `S3_SECRET_KEY` | *(none)* | Secret access key |
| `S3_BUCKET` | `imbi-uploads` | Bucket name |
| `S3_REGION` | `us-east-1` | AWS region |
| `S3_CREATE_BUCKET_ON_INIT` | `true` | Auto-create the bucket on startup if it does not exist |
| `S3_MAX_FILE_SIZE` | `52428800` | Upload size limit in bytes (50 MiB default) |
| `S3_ALLOWED_CONTENT_TYPES` | image/jpeg, image/png, image/gif, image/webp, image/svg+xml, application/pdf | JSON array of MIME types accepted for upload |
| `S3_THUMBNAIL_MAX_SIZE` | `256` | Max thumbnail dimension in pixels (aspect ratio preserved) |
| `S3_THUMBNAIL_QUALITY` | `85` | WEBP quality for generated thumbnails (0–100) |

### Email (`IMBI_EMAIL_*`)

SMTP-based transactional email (password reset, welcome, email verification, security alerts). The `[email]` section in `config.toml` maps to these.

| Variable | Default | Description |
|----------|---------|-------------|
| `IMBI_EMAIL_ENABLED` | `true` | Master switch — disable to no-op all sends |
| `IMBI_EMAIL_DRY_RUN` | `false` | Build and log messages without sending |
| `IMBI_EMAIL_SMTP_HOST` | `localhost` | SMTP server host |
| `IMBI_EMAIL_SMTP_PORT` | `587` | SMTP server port |
| `IMBI_EMAIL_SMTP_USE_TLS` | `true` | Use STARTTLS |
| `IMBI_EMAIL_SMTP_USE_SSL` | `false` | Use implicit TLS (SMTPS, typically port 465) |
| `IMBI_EMAIL_SMTP_USERNAME` | *(none)* | SMTP auth username |
| `IMBI_EMAIL_SMTP_PASSWORD` | *(none)* | SMTP auth password |
| `IMBI_EMAIL_SMTP_TIMEOUT` | `30` | SMTP socket timeout in seconds |
| `IMBI_EMAIL_FROM_EMAIL` | `noreply@imbi.example.com` | From address |
| `IMBI_EMAIL_FROM_NAME` | `Imbi` | From display name |
| `IMBI_EMAIL_REPLY_TO` | *(none)* | Optional Reply-To address |
| `IMBI_EMAIL_MAX_RETRIES` | `3` | Send retry attempts |
| `IMBI_EMAIL_INITIAL_RETRY_DELAY` | `1.0` | First retry delay in seconds |
| `IMBI_EMAIL_MAX_RETRY_DELAY` | `60.0` | Maximum backoff delay in seconds |
| `IMBI_EMAIL_RETRY_BACKOFF_FACTOR` | `2.0` | Exponential backoff multiplier |

!!! note "Mailpit auto-config"
    When `ENVIRONMENT=development` (or unset) and `IMBI_EMAIL_SMTP_HOST=localhost` with the default port `587`, the settings model checks for `MAILPIT_SMTP_PORT` (written by `just docker`) and substitutes it, disabling TLS unless `IMBI_EMAIL_SMTP_USE_TLS` is set explicitly. This makes development "just work" against Mailpit without manual SMTP wiring.

## Authentication & Authorization (`IMBI_AUTH_*`)

The `[auth]` section in `config.toml` maps to these. Shared JWT/encryption settings come from `imbi.common`; the API service adds password policy, sessions, API keys, MFA, rate limits, and OAuth behavior.

### JWT and Encryption

| Variable | Default | Description |
|----------|---------|-------------|
| `IMBI_AUTH_JWT_SECRET` | *(auto-generated)* | Secret used to sign JWT access and refresh tokens. **Set explicitly in production** — otherwise every restart invalidates all tokens. |
| `IMBI_AUTH_JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `IMBI_AUTH_ACCESS_TOKEN_EXPIRE_SECONDS` | `3600` | Access token lifetime (1 hour) |
| `IMBI_AUTH_REFRESH_TOKEN_EXPIRE_SECONDS` | `2592000` | Refresh token lifetime (30 days). Refresh tokens rotate on every use. |
| `IMBI_AUTH_ENCRYPTION_KEY` | *(auto-generated)* | Base64-encoded Fernet key used to encrypt OAuth provider tokens and OAuth client secrets at rest. **Set explicitly in production** — otherwise every restart breaks all encrypted secrets. |

### Password Policy

| Variable | Default | Description |
|----------|---------|-------------|
| `IMBI_AUTH_PASSWORD_MIN_LENGTH` | `12` | Minimum password length |
| `IMBI_AUTH_PASSWORD_REQUIRE_UPPERCASE` | `true` | Require an uppercase letter |
| `IMBI_AUTH_PASSWORD_REQUIRE_LOWERCASE` | `true` | Require a lowercase letter |
| `IMBI_AUTH_PASSWORD_REQUIRE_DIGIT` | `true` | Require a digit |
| `IMBI_AUTH_PASSWORD_REQUIRE_SPECIAL` | `true` | Require a special character |

### Sessions and API Keys

| Variable | Default | Description |
|----------|---------|-------------|
| `IMBI_AUTH_SESSION_TIMEOUT_SECONDS` | `86400` | Session timeout (24 hours) |
| `IMBI_AUTH_MAX_CONCURRENT_SESSIONS` | `5` | Max concurrent sessions per user; oldest is evicted past the limit |
| `IMBI_AUTH_API_KEY_MAX_LIFETIME_DAYS` | `365` | Maximum lifetime allowed when creating an API key |

### MFA (TOTP)

| Variable | Default | Description |
|----------|---------|-------------|
| `IMBI_AUTH_MFA_ISSUER_NAME` | `Imbi` | Issuer name shown in authenticator apps |
| `IMBI_AUTH_MFA_TOTP_PERIOD` | `30` | TOTP time step in seconds |
| `IMBI_AUTH_MFA_TOTP_DIGITS` | `6` | TOTP code length |

### Rate Limiting

Values use the [slowapi](https://slowapi.readthedocs.io/) `<n>/<period>` format (e.g. `5/minute`, `100/hour`).

| Variable | Default | Description |
|----------|---------|-------------|
| `IMBI_AUTH_RATE_LIMIT_LOGIN` | `5/minute` | Password login attempts |
| `IMBI_AUTH_RATE_LIMIT_TOKEN_REFRESH` | `10/minute` | Refresh-token exchanges |
| `IMBI_AUTH_RATE_LIMIT_OAUTH_INIT` | `3/minute` | OAuth authorization-flow initiations |
| `IMBI_AUTH_RATE_LIMIT_API_KEY` | `100/minute` | API-key-authenticated requests |

### OAuth Behavior

OAuth **provider credentials** (Google, GitHub, generic OIDC client IDs and secrets) are no longer environment variables — they are managed at runtime through the admin API and stored encrypted in the graph using `IMBI_AUTH_ENCRYPTION_KEY`. The settings below control behavior across all configured providers.

| Variable | Default | Description |
|----------|---------|-------------|
| `IMBI_AUTH_OAUTH_AUTO_LINK_BY_EMAIL` | `true` | Auto-link an incoming OAuth identity to an existing local user when emails match. Safe for verified-email IdPs (Google, most OIDC). Disable when you require an admin to manually approve linking. |
| `IMBI_AUTH_OAUTH_AUTO_CREATE_USERS` | `true` | Auto-create a user record on first successful OAuth login. Disable to require pre-provisioned accounts. |

### OAuth2 Authorization Server (MCP login)

Imbi acts as an OAuth 2.0 Authorization Server so MCP clients (and other
OAuth clients) can log a user in via the browser and obtain an Imbi access
token, instead of pasting a static API key. The flow is authorization-code
with PKCE (`S256` required); clients self-register via :rfc:`7591` Dynamic
Client Registration. Discovery is published at
`/.well-known/oauth-authorization-server` (served at the host root); the
endpoints are `/auth/authorize`, `/auth/token`, and `/auth/register` under
the API prefix. `/authorize` reuses the existing Imbi login (including any
configured upstream IdP), so MCP login inherits MFA and provider rules.

| Variable | Default | Description |
|----------|---------|-------------|
| `IMBI_AUTH_DCR_ENABLED` | `true` | Allow OAuth clients to self-register at `/auth/register` (RFC 7591). Disable to require clients to be provisioned out of band. |

#### Multi-host deployments (separate public login host)

A deployment may be reachable on more than one host — e.g. an internal
host that serves the SPA and a separate internet-facing host that fronts
the MCP OAuth login for a remote client (Claude Desktop and other remote
connectors reach the server from the vendor's cloud, not the user's
machine, so the MCP and OAuth endpoints must be publicly reachable).

The issuer and endpoints in the discovery document, the post-login
`return_to`/login redirect, and the upstream-IdP callback URL are all
derived **per request** from the host the caller actually reached, rather
than from the single `IMBI_API_URL`. To prevent a spoofed `Host` header
from redirecting freshly minted tokens off-origin, a request host is only
honored when it is a **trusted origin**: the origin of `IMBI_API_URL` plus
every entry in `IMBI_API_CORS_ALLOWED_ORIGINS`. Untrusted hosts fall back
to `IMBI_API_URL`. This also requires `IMBI_API_FORWARDED_ALLOW_IPS` to be
set so the request scheme/host are trusted from the proxy.

To enable a separate public login host:

1. Add the public origin to `IMBI_API_CORS_ALLOWED_ORIGINS`
   (e.g. `https://imbi-public.example.com`). `IMBI_API_URL` stays pointed
   at the internal host, so internal SPA traffic is unaffected.
2. Route `/mcp`, `/.well-known/oauth-*`, and `/api/auth/*` to the service
   on that public host. If the public host should support browser-based
   login (not just MCP), also serve the SPA's login UI assets — the SPA
   entry document (`index.html`) served at `/` and `/login`, plus its
   static assets (`*.js`, `*.css`, images) — so the login page renders on
   that host.
3. If login uses an upstream IdP (Google/GitHub/OIDC), register the public
   host's callback — `https://<public-host>/api/auth/oauth/<slug>/callback`
   — with that provider in addition to the internal one, since the
   callback now names whichever host the user logged in from.

!!! note "Known limitation"
    Standard OAuth provider logins (Google/GitHub/OIDC) and MCP OAuth
    client flows are fully per-host aware. The identity-plugin *connect*
    flow (linking an additional identity from the account settings UI) is
    not yet derived per host and continues to use `IMBI_API_URL`, so its
    callback must remain registered against the `IMBI_API_URL` origin.

## Other Settings

### Releases (`IMBI_RELEASES_*`)

The `[releases]` section in `config.toml` maps to these.

| Variable | Default | Description |
|----------|---------|-------------|
| `IMBI_RELEASES_VERSION_FORMAT` | `semver` | Version-string format enforced on `Release.version`. Other values supported by `imbi.common.versioning.VersionFormat`. |

### Embeddings (`EMBEDDINGS_*`)

Controls embedding generation for vector search. The `[embeddings]` section in `config.toml` maps to these.

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDINGS_ENABLED` | `true` | Master enable/disable for embedding generation |
| `EMBEDDINGS_DEFAULT_MODEL` | `text` | Key into `EMBEDDINGS_MODELS` used by default |
| `EMBEDDINGS_MODELS` | `{text: {fastembed_id: BAAI/bge-small-en-v1.5, dimensions: 384}}` | JSON map of model key → `{fastembed_id, dimensions}` |

### Reload Watch Paths

| Variable | Default | Description |
|----------|---------|-------------|
| `IMBI_RELOAD_DIRS` | *(none)* | OS-pathsep-separated list of directories uvicorn should watch when `--dev` is set. Useful when running with an editable `imbi-common` checkout, e.g. `IMBI_RELOAD_DIRS=../imbi-common/src`. |

### Standard OpenTelemetry and uvicorn

The Compose stack and `just docker` populate the standard `OTEL_*` and `UVICORN_*` environment variables. They are read by the OpenTelemetry SDK and uvicorn directly — Imbi does not redefine them. The `.env` written by `just docker` sets sensible development defaults pointing at the bundled Jaeger container:

| Variable | Set by `just docker` to |
|----------|------------------------|
| `OTEL_SERVICE_NAME` | `imbi-api` |
| `OTEL_TRACES_EXPORTER` | `otlp` |
| `OTEL_LOGS_EXPORTER` | `none` |
| `OTEL_METRICS_EXPORTER` | `none` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `<host>:<jaeger-otlp-port>` |
| `OTEL_EXPORTER_OTLP_TRACES_INSECURE` | `true` |
| `OTEL_RESOURCE_ATTRIBUTES` | `service.name=imbi-api,service.environment=development` |

In production, point `OTEL_EXPORTER_OTLP_ENDPOINT` at your collector.

## Docker Compose Services

The development stack defined in `compose.yaml` runs the following with ports mapped to *ephemeral host ports* (resolved by `just docker` and written into `.env`):

| Service | Container Port | Purpose |
|---------|----------------|---------|
| `postgres` (`ghcr.io/aweber-imbi/postgres:latest`) | 5432 | PostgreSQL + Apache AGE + pg_cron + pgvector |
| `clickhouse` | 8123 (HTTP), 9000 (native) | Analytics |
| `valkey` | 6379 | Cache |
| `localstack` | 4566 | S3-compatible storage |
| `mailpit` | 1025 (SMTP), 8025 (web UI) | SMTP capture |
| `jaeger` | 4317 (OTLP), 16686 (UI) | Tracing |

Use `docker compose port <service> <container-port>` to look up the assigned host port, or read it from the generated `.env`.

## Configuration File Format

### `config.toml` Example

```toml
[server]
environment = "production"
host = "0.0.0.0"
port = 8080
cors_allowed_origins = ["https://imbi.example.com"]
forwarded_allow_ips = "10.0.0.0/8"
url = "https://imbi.example.com/api"

[postgres]
url = "postgresql://imbi:secret@db-prod:5432/imbi"
graph_name = "imbi"
min_pool_size = 5
max_pool_size = 50

[clickhouse]
url = "clickhouse+http://clickhouse-prod:8123/imbi"

[valkey]
url = "valkey://valkey-prod:6379/0"

[auth]
# JWT secret and encryption key should come from environment variables:
#   IMBI_AUTH_JWT_SECRET, IMBI_AUTH_ENCRYPTION_KEY
jwt_algorithm = "HS256"
access_token_expire_seconds = 3600
refresh_token_expire_seconds = 2592000
password_min_length = 14
max_concurrent_sessions = 5
oauth_auto_link_by_email = true
oauth_auto_create_users = false

[email]
enabled = true
smtp_host = "smtp.example.com"
smtp_port = 587
smtp_use_tls = true
from_email = "noreply@example.com"
from_name = "Imbi Platform"

[storage]
bucket = "imbi-uploads-prod"
region = "us-east-1"
create_bucket_on_init = false

[releases]
version_format = "semver"
```

### `.env` Example (development)

```bash
# Application
ENVIRONMENT=development
IMBI_API_HOST=localhost
IMBI_API_PORT=8000
IMBI_API_URL=http://localhost:8000
IMBI_API_CORS_ALLOWED_ORIGINS='["http://localhost:5173"]'

# Stores
POSTGRES_URL=postgresql://postgres:secret@localhost:5432/imbi
CLICKHOUSE_URL=clickhouse+http://default:password@localhost:8123/imbi
VALKEY_URL=valkey://localhost:6379/0

# Auth secrets (production: pull from a secrets manager)
IMBI_AUTH_JWT_SECRET=...generate-with-secrets.token_urlsafe(32)...
IMBI_AUTH_ENCRYPTION_KEY=...generate-with-Fernet.generate_key()...

# Object storage (LocalStack in dev)
S3_ENDPOINT_URL=http://localhost:4566
S3_ACCESS_KEY=test
S3_SECRET_KEY=test
S3_BUCKET=imbi-uploads
S3_REGION=us-east-1

# Email (Mailpit auto-configures if these are left at defaults)
IMBI_EMAIL_ENABLED=true
IMBI_EMAIL_FROM_EMAIL=noreply@imbi.example
IMBI_EMAIL_FROM_NAME=Imbi Development

# Tracing
OTEL_SERVICE_NAME=imbi-api
OTEL_TRACES_EXPORTER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=localhost:4317
OTEL_EXPORTER_OTLP_TRACES_INSECURE=true
```

## Production Considerations

### Security

1. **JWT and encryption keys**: Always set `IMBI_AUTH_JWT_SECRET` and `IMBI_AUTH_ENCRYPTION_KEY` explicitly. Auto-generated values change every restart and silently invalidate all tokens and encrypted secrets.
2. **CORS**: Limit `IMBI_API_CORS_ALLOWED_ORIGINS` to the exact origins that need API access. Credentials and the `Authorization` header are allowed for these origins.
3. **Reverse proxy**: Set `IMBI_API_FORWARDED_ALLOW_IPS` to the trusted proxy CIDR(s) — otherwise rate limiting keys on the proxy IP.
4. **TLS**: Terminate HTTPS at the proxy.
5. **Database credentials**: Use strong passwords and rotate regularly; pass via env vars only.
6. **Secrets management**: Store sensitive values in AWS Secrets Manager, HashiCorp Vault, or your platform's secret store.

### Performance

1. **Postgres pool size**: Tune `POSTGRES_MAX_POOL_SIZE` (and `_MIN_`) for your concurrency and DB capacity.
2. **ClickHouse retention**: Configure TTL on analytics tables to match your data-retention policy.
3. **Access token expiry**: `IMBI_AUTH_ACCESS_TOKEN_EXPIRE_SECONDS=900` (15 min) is a common production choice; refresh-token rotation makes shorter lifetimes practical.

### Monitoring

1. **OpenTelemetry**: Point `OTEL_EXPORTER_OTLP_ENDPOINT` at your production collector (Jaeger, Honeycomb, Datadog, etc.).
2. **Health checks**: Use `/status` for load-balancer health probes.

## Advanced

### Loading Configuration Programmatically

```python
from imbi.api import settings

config = settings.load_config()

print(config.server.environment, config.server.host, config.server.port)
print(config.postgres.url)
print(config.auth.jwt_algorithm)
print(config.email.smtp_host)
print(config.storage.bucket)

# Or instantiate a single section directly (env vars and .env apply):
postgres_settings = settings.Postgres()
server_config = settings.ServerConfig()
```

### Environment-Specific Configuration

```bash
# Development — .env written by `just docker`
just serve --dev

# Staging — point at a staging config file
cp /path/to/staging/config.toml ./config.toml
uv run imbi-api serve

# Production — system config + injected secrets
# Config at /etc/imbi/config.toml
export IMBI_AUTH_JWT_SECRET="$(load-from-secrets-manager)"
export IMBI_AUTH_ENCRYPTION_KEY="$(load-from-secrets-manager)"
export POSTGRES_URL="$(load-from-secrets-manager)"
uv run imbi-api serve
```

### Configuration Best Practices

1. **Secrets via environment variables**: Never check in passwords, JWT secrets, or Fernet keys.
2. **`config.toml` for structure**: Put non-sensitive settings in version-controlled config files.
3. **Example configs**: Commit `config.example.toml`, never the real `config.toml`.
4. **Deployment automation**: Render configs via Ansible/Terraform/Helm.

## Troubleshooting

### PostgreSQL / AGE Connection Issues

```bash
docker compose exec postgres psql -U postgres -d imbi -c '\dx'
docker compose logs postgres
```

Verify the AGE and pgvector extensions are loaded.

### ClickHouse Connection Issues

```bash
HOST_PORT=$(docker compose port clickhouse 8123 | cut -d: -f2)
curl http://localhost:${HOST_PORT}/ping
docker compose logs clickhouse
```

### Authentication Issues

```bash
# Confirm secrets are present (do not echo the values in shared output)
env | grep -E '^(IMBI_AUTH_JWT_SECRET|IMBI_AUTH_ENCRYPTION_KEY)=' | wc -l
# Should print 2 in production.

just serve --dev   # watch for JWT-related warnings on startup
```

## See Also

- [Architecture Decision Records](adr.md) — Key architectural decisions
- [GitHub Repository](https://github.com/AWeber-Imbi/imbi-api) — Source code and issues
