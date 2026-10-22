# Configuration

Imbi is configured through environment variables. Each service reads its
own set of variables from the shared environment.

## Required Variables

Which variables are required depends on the service being run
(see `IMBI_SERVICE` below). When running `IMBI_SERVICE=all` (the default),
all service-specific variables are required.

### Core (all services)

| Variable | Description |
|----------|-------------|
| `IMBI_AUTH_JWT_SECRET` | Secret key for signing JWT tokens. Use a random string of at least 32 characters. |
| `IMBI_AUTH_ENCRYPTION_KEY` | Fernet encryption key for encrypting sensitive data at rest. |

### API only

| Variable | Description |
|----------|-------------|
| `CLICKHOUSE_URL` | ClickHouse HTTP connection URL (e.g. `clickhouse+http://default:password@clickhouse:8123/imbi`) |

### Gateway

| Variable | Description |
|----------|-------------|
| `POSTGRES_URL` | PostgreSQL connection URL (e.g. `postgresql://user:pass@host/db`) |

### Scheduler

| Variable | Description |
|----------|-------------|
| `POSTGRES_URL` | Task definitions, trigger state, and run leases |
| `CLICKHOUSE_URL` | Run history (`imbi.scheduler_runs`) |
| `IMBI_SCHEDULER_SA_CLIENT_ID` | The scheduler's own service-account client id |
| `IMBI_SCHEDULER_SA_CLIENT_SECRET` | Its client secret |
| `IMBI_INTERNAL_API_URL` | Bare origin where the scheduler *connects* to imbi-api (e.g. `http://imbi-api:8000`) |
| `IMBI_API_URL` | imbi-api's *public* URL, whose path is the prefix it mounts its routes under |

The service account is not seeded. Create one in the UI, grant it the
`scheduled_task:*` permissions plus whatever the tasks it runs will need, and
issue it a client credential. Without the credentials the scheduler is left out
of `IMBI_SERVICE=all` and refuses to start in `IMBI_SERVICE=scheduler` mode.

See [Scheduler configuration](../scheduler/configuration.md) for the optional
settings (`IMBI_SCHEDULER_API_PREFIX`, `IMBI_SCHEDULER_SCHEMA`,
`IMBI_SCHEDULER_GATEWAY_URL`, concurrency and poll-interval limits) and for why
the internal and public API URLs are two separate variables.

### Workflows

| Variable | Description |
|----------|-------------|
| `POSTGRES_URL` | Workflow definitions and runs |
| `IMBI_AUTH_ENCRYPTION_KEY` | Decrypts AI provider credentials |
| `IMBI_WORKFLOWS_SA_CLIENT_ID` | The workflow engine's service-account client id |
| `IMBI_WORKFLOWS_SA_CLIENT_SECRET` | Its client secret |
| `IMBI_INTERNAL_API_URL` | Bare origin where imbi-workflows *connects* to imbi-api |
| `IMBI_API_URL` | imbi-api's *public* URL, whose path is the prefix it mounts its routes under |

`imbi-api setup` seeds the `imbi-workflows` service account. Deploy and
rollback steps call imbi-api as this account, so without the credentials every
such step fails. In `IMBI_SERVICE=all` mode the entrypoint provisions the
credentials when you do not set them. See
[API configuration](../api/configuration.md#workflow-engine-imbi_workflows_)
for the optional settings.

## ClickHouse

| Variable | Description | Default |
|----------|-------------|---------|
| `CLICKHOUSE_URL` | HTTP connection URL with database path | - |

## Authentication

Sign-in methods are not environment variables. You configure local
authentication and SSO login providers in the database, at
**Admin > Global Admin > Auth Providers**. See
[Authentication](../admin/authentication.md).

| Variable | Description | Default |
|----------|-------------|---------|
| `IMBI_AUTH_JWT_SECRET` | JWT signing secret | Random value in development |
| `IMBI_AUTH_ENCRYPTION_KEY` | Fernet encryption key | Random value in development |
| `IMBI_AUTH_ACCESS_TOKEN_EXPIRE_SECONDS` | Access token lifetime | `3600` (1 hour) |
| `IMBI_AUTH_REFRESH_TOKEN_EXPIRE_SECONDS` | Refresh token lifetime | `2592000` (30 days) |
| `IMBI_AUTH_OAUTH_AUTO_CREATE_USERS` | Create a user at the first SSO sign-in | `true` |
| `IMBI_AUTH_OAUTH_AUTO_LINK_BY_EMAIL` | Link an SSO sign-in to the user with the same verified email | `true` |
| `IMBI_AUTH_DCR_ENABLED` | Let MCP clients register themselves | `true` |

When `ENVIRONMENT` is not `development`, Imbi does not start unless you set
`IMBI_AUTH_JWT_SECRET`, `IMBI_AUTH_ENCRYPTION_KEY`, and
`IMBI_CONFIG_ENCRYPTION_KEY`.

The OAuth callback URL is `<IMBI_API_URL>/auth/oauth/<provider-slug>/callback`.
There is no separate callback setting.

## Email

| Variable | Description | Default |
|----------|-------------|---------|
| `IMBI_EMAIL_ENABLED` | Send email. Set to `false` to stop all email | `true` |
| `IMBI_EMAIL_DRY_RUN` | Log messages but do not send them | `false` |
| `IMBI_EMAIL_SMTP_HOST` | SMTP server hostname | `localhost` |
| `IMBI_EMAIL_SMTP_PORT` | SMTP server port | `587` |
| `IMBI_EMAIL_SMTP_USE_TLS` | Use STARTTLS | `true` |
| `IMBI_EMAIL_SMTP_USE_SSL` | Use implicit TLS (usually port 465) | `false` |
| `IMBI_EMAIL_SMTP_USERNAME` | SMTP user name | - |
| `IMBI_EMAIL_SMTP_PASSWORD` | SMTP password | - |
| `IMBI_EMAIL_FROM_EMAIL` | Sender email address | `noreply@imbi.example.com` |
| `IMBI_EMAIL_FROM_NAME` | Sender display name | `Imbi` |

See [API configuration](../api/configuration.md) for the retry and timeout
settings.

## AI Assistant

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude | - |
| `IMBI_ASSISTANT_ENABLED` | Enable the AI assistant | `false` (auto-enabled if API key set) |
| `IMBI_ASSISTANT_MODEL` | Claude model to use | `claude-sonnet-4-6` |
| `IMBI_ASSISTANT_MAX_TOKENS` | Maximum response tokens | `16384` |
| `IMBI_ASSISTANT_PROMPT_REF` | Prompt CMS reference for the system prompt | `imbi-assistant/system@stable` |
| `IMBI_SLACKBOT_PROMPT_REF` | Prompt CMS reference for the Slack bot's system prompt | `imbi-slackbot/system@stable` |

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

## Prompt Rendering and Secrets

| Variable | Description | Default |
|----------|-------------|---------|
| `IMBI_PROMPT_WORKERS` | Prompt render worker processes per service process | `2` |
| `IMBI_PROMPT_WORKER_MAX_RENDERS` | Renders before a worker is replaced | `500` |
| `IMBI_PROMPT_WORKER_MEMORY_MB` | Address space a worker can add after start (Linux only) | `256` |
| `IMBI_PROMPT_RENDER_INPROCESS` | Render in the service process (debugging only) | `false` |
| `IMBI_SECRETS_GITHUB_GHES_HOSTS` | Comma-separated GHES hosts that GitHub App secret bindings can use | - |
| `IMBI_SECRETS_AWS_ENDPOINT_URL` | AWS endpoint override (LocalStack) | - (AWS) |
| `IMBI_INTERNAL_WORKFLOWS_URL` | Internal URL of imbi-workflows, for the status dashboard | - |

See [API configuration](../api/configuration.md#agents-workflows-and-secrets)
for the details and the imbi-workflows settings.

## Service Selection

When running the Docker image, you can select which service to run:

| Variable | Description | Default |
|----------|-------------|---------|
| `IMBI_SERVICE` | Service to run: `all`, `api`, `assistant`, `gateway`, `mcp`, `scheduler`, `slackbot`, `ui`, `workflows` | `all` |
