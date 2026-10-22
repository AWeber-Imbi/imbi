# Configuration

Every Imbi service reads its configuration from environment variables and,
for some settings classes, from a `config.toml` file. This page is the full
reference. For the minimum set that starts each service,
see [Configuration](../getting-started/configuration.md) in Getting Started.

## Sources and precedence

The settings classes use
[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).
Each service reads values from these sources:

1. **Environment variables.**
2. **A `.env` file** in the working directory. An environment variable wins
   over the same name in `.env`.
3. **A `config.toml` file**, for the settings classes in the next section.
   An environment variable or a `.env` entry wins over the same key in
   `config.toml`.
4. **Built-in defaults.** The tables below show them.

The settings classes accept variable names in upper or lower case. Some
variables are read directly from the process environment, for example
`ENVIRONMENT`, `SENTRY_DSN`, and `IMBI_PROMPT_*`. Those must be in upper case,
and the `.env` file does not set them.

### `config.toml`

Each section of `config.toml` sets one settings class. The key is the field
name, which is the variable name without the prefix, in lower case:

| Section | Settings | Services |
|---|---|---|
| `[auth]` | The `IMBI_AUTH_*` fields | All |
| `[clickhouse]` | The `CLICKHOUSE_*` fields | All |
| `[embeddings]` | The `EMBEDDINGS_*` fields | All |
| `[plugins]` | `imbi_plugins`, `imbi_plugins_disabled` (lists) | All |
| `[postgres]` | The `POSTGRES_*` fields | All |
| `[releases]` | The `IMBI_RELEASES_*` fields | All |
| `[ssl]` | `cert_dir` | All |
| `[valkey]` | The `VALKEY_*` fields | All |
| `[server]` | The `IMBI_API_*` fields, `url`, `ui_url` | imbi-api |
| `[email]` | The `IMBI_EMAIL_*` fields | imbi-api |
| `[storage]` | The `S3_*` fields | imbi-api |

Other settings classes, for example `Iggy`, `ConfigSecrets`, and the
Anthropic settings, do not read `config.toml`. Use their environment
variables.

Each service looks for the file in these places, in this order. A key in an
earlier file wins over the same key in a later file:

1. `./config.toml`
2. `~/.config/imbi/config.toml`
3. `/etc/imbi/config.toml`

An environment variable always wins over the same key in `config.toml`.
The file supplies only the keys that the environment does not set.

imbi-api reads `[server]` one time, when the application starts. The route
prefix (the path of `url`), the CORS origins, the forwarded IPs, the OAuth
URLs, and the cookie path all come from that one read.

Example:

```toml
[storage]
bucket = "imbi-uploads-prod"
region = "us-east-1"
create_bucket_on_init = false
```

## `ENVIRONMENT` and production

`ENVIRONMENT` has no prefix. Every service reads it. The default is
`development`. Set it to `production` in production.

| `ENVIRONMENT` | `IMBI_AUTH_JWT_SECRET`, `IMBI_AUTH_ENCRYPTION_KEY`, `IMBI_CONFIG_ENCRYPTION_KEY` | Mailpit auto-configuration |
|---|---|---|
| `development` (or unset) | Generated per process when not set, with a warning | On |
| Any other value | Required. The service does not start without them | Off |

A generated key is different in each process and after each restart. Then:

- every issued token becomes invalid,
- a value encrypted by one process cannot be decrypted by another process
  or after a restart (OAuth tokens, AI provider keys, MCP server
  credentials).

Generate the three values once and store them in your secret store:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"                              # IMBI_AUTH_JWT_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" # IMBI_AUTH_ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" # IMBI_CONFIG_ENCRYPTION_KEY
```

Use a different key for `IMBI_AUTH_ENCRYPTION_KEY` and
`IMBI_CONFIG_ENCRYPTION_KEY`, so that you can rotate them separately.

!!! note "`IMBI_API_ENVIRONMENT` is a different variable"
    imbi-api also reads `IMBI_API_ENVIRONMENT` (`[server] environment`).
    It controls only the `Secure` flag of the auth cookies: the flag is set
    when the value is not `development`. Set `IMBI_API_ENVIRONMENT=production`
    too when the UI is served over HTTPS. The Helm chart sets both from its
    `environment` value, which defaults to `production`.

!!! warning "`IMBI_ENVIRONMENT` is not read"
    No code reads `IMBI_ENVIRONMENT`. Use `ENVIRONMENT`.

### Production checklist

1. Set `ENVIRONMENT=production` and `IMBI_API_ENVIRONMENT=production`.
2. Set `IMBI_AUTH_JWT_SECRET`, `IMBI_AUTH_ENCRYPTION_KEY`, and
   `IMBI_CONFIG_ENCRYPTION_KEY` from your secret store. Use the same values
   in every service and every replica.
3. Set `IMBI_API_URL` to the public API URL with its path, for example
   `https://imbi.example.com/api`, and `IMBI_UI_URL` to the public UI URL.
4. Behind a proxy, set `IMBI_API_FORWARDED_ALLOW_IPS` to the proxy addresses.
   Otherwise rate limits and OAuth URLs use the proxy address.
5. Set `IMBI_API_CORS_ALLOWED_ORIGINS` to the exact origins that call the API.
6. Set `VALKEY_URL`. If imbi-api cannot reach Valkey, the background
   workers that need it do not start, and imbi-api logs a warning.

## Environment variables

The tables come from `scripts/docs_env_table.py`. Run it after you add or
change a setting, and paste its output here:

```bash
uv run python scripts/docs_env_table.py
```

The **Shared** table lists the settings in `imbi-common`. Each service reads
the shared settings that it uses: for example, every service that opens
PostgreSQL reads `POSTGRES_*`. The other tables list the settings that only
that service reads. Some variables, for example `IMBI_INTERNAL_API_URL`, show
in more than one table because more than one service reads them.

In the type column, `list[str]` values are a JSON array, except
`IMBI_PLUGINS`, `IMBI_PLUGINS_DISABLED`, and `IMBI_IGGY_CONNECTORS_API_KEYS`,
which are comma-separated. A default of "none" means that the setting is
unset.

<!-- BEGIN GENERATED: scripts/docs_env_table.py -->

### Shared (imbi-common)

| Variable | Type | Default | Description |
|---|---|---|---|
| `IMBI_AUTH_JWT_SECRET` | str | generated | Secret that signs access and refresh tokens. Required when `ENVIRONMENT` is not `development`. |
| `IMBI_AUTH_JWT_ALGORITHM` | str | `HS256` | JWT signing algorithm |
| `IMBI_AUTH_ACCESS_TOKEN_EXPIRE_SECONDS` | int | `3600` | Access token lifetime |
| `IMBI_AUTH_REFRESH_TOKEN_EXPIRE_SECONDS` | int | `2592000` | Refresh token lifetime. Refresh tokens rotate on each use. |
| `IMBI_AUTH_LAST_USED_THROTTLE_SECONDS` | int | `60` | Minimum seconds between two writes of the `last_used` time of an API key. `0` writes on each request. |
| `IMBI_AUTH_ENCRYPTION_KEY` | str | none | Fernet key that encrypts OAuth tokens and client secrets. Required when `ENVIRONMENT` is not `development`; generated per process in development. |
| `IMBI_CONFIG_ENCRYPTION_KEY` | str | none | Fernet key that encrypts configuration secrets, for example AI provider keys and MCP server credentials. Required when `ENVIRONMENT` is not `development`; generated per process in development. |
| `POSTGRES_URL` | PostgresDsn | `postgresql://postgres:secret@localhost:5432/imbi` | PostgreSQL DSN |
| `POSTGRES_GRAPH_NAME` | str | `imbi` | Apache AGE graph name |
| `POSTGRES_MIN_POOL_SIZE` | int | `2` | Minimum connection pool size |
| `POSTGRES_MAX_POOL_SIZE` | int | `10` | Maximum connection pool size |
| `CLICKHOUSE_URL` | ClickHouseDsn | `clickhouse+http://localhost:8123` | ClickHouse DSN. Credentials in the URL are used. |
| `CLICKHOUSE_CONNECT_TIMEOUT` | float | `10.0` | Connection timeout in seconds |
| `CLICKHOUSE_MAX_CONNECT_ATTEMPTS` | int | `10` | Connection attempts at startup |
| `CLICKHOUSE_CLUSTER_NAME` | str | none | Cluster name. When set, `setup-clickhouse` creates the schema `ON CLUSTER <name>` with `Replicated` table engines. Leave unset for one node. |
| `IGGY_URL` | IggyDSN | `iggy+tcp://iggy:iggy@localhost:8090` | Apache Iggy connection string. The scheme selects the transport: `iggy`, `iggy+tcp`, `iggy+quic`, `iggy+http`, `iggy+ws`. |
| `IGGY_CONNECT_TIMEOUT` | float | `10.0` | Connection timeout in seconds |
| `IGGY_MAX_CONNECT_ATTEMPTS` | int | `10` | Connection attempts at startup |
| `VALKEY_URL` | ValkeyDSN | `valkey://localhost:6379/0` | Valkey DSN |
| `IMBI_PLUGINS` | list[str] | `[]` | Comma-separated `package.module:Attr` paths of plugins that do not use the `imbi_plugin_*` package name |
| `IMBI_PLUGINS_DISABLED` | list[str] | `[]` | Comma-separated plugin slugs not to load |
| `IMBI_RELEASES_VERSION_FORMAT` | `semver` or `commitish` | `semver` | Version format that `Release.version` must match |
| `EMBEDDINGS_ENABLED` | bool | `true` | Generate embeddings for vector search |
| `EMBEDDINGS_DEFAULT_MODEL` | str | `text` | Key in `EMBEDDINGS_MODELS` to use |
| `EMBEDDINGS_MODELS` | dict[str, EmbeddingModelConfig] | `{"text": {"fastembed_id": "BAAI/bge-small-en-v1.5", "dimensions": 384}}` | JSON map of model key to `{fastembed_id, dimensions}` |
| `SSL_CERT_DIR` | Path | none | Directory of CA certificates that every TLS context loads, in addition to the defaults |
| `ANTHROPIC_API_KEY` | SecretStr | none | Anthropic API key |
| `IMBI_ANTHROPIC_DEFAULT_MODEL` | str | `claude-haiku-4-5-20251001` | Model for structured completions, for example release-note drafts |
| `IMBI_ANTHROPIC_TIMEOUT` | float | `30.0` | Request timeout in seconds |
| `IMBI_ANTHROPIC_MAX_RETRIES` | int | `2` | Retries for each request |
| `IMBI_CLIENT_API_BASE_URL` | HttpUrl | `http://imbi-api:8000/` | Imbi API URL for the `imbi.common.api` client |
| `IMBI_CLIENT_API_TOKEN` | SecretStr | required | Bearer token for the `imbi.common.api` client |
| `IMBI_CLIENT_USER_AGENT` | str | none | `User-Agent` for the `imbi.common.api` client. Unset: `imbi-common/<version>`. |
| `IMBI_PROMPT_RENDER_INPROCESS` | str | `''` | `true` renders in the service process. For debugging only: it removes the isolation. |
| `IMBI_PROMPT_WORKERS` | int | `2` | Prompt render worker processes per service process |
| `IMBI_PROMPT_WORKER_MAX_RENDERS` | int | `500` | Renders before a worker is replaced |
| `IMBI_PROMPT_WORKER_MEMORY_MB` | int | `256` | Address space in MiB that a worker can add after it starts. Linux only. |
| `SENTRY_TRACES_SAMPLE_RATE` | float | `0.0` | Trace sample rate, `0.0` to `1.0`. `/status` requests are never sampled. |
| `SENTRY_DSN` | str | none | Sentry DSN. Unset: Sentry is off. |
| `SERVICE` | str | `unknown` | Server name sent to Sentry |
| `IMBI_RELOAD_DIRS` | str | `''` | Extra directories to watch with `serve --dev`, separated by the OS path separator |
| `ENVIRONMENT` | str | `development` | Anything other than `development` makes the auth and config encryption keys required and turns off the Mailpit auto-configuration. The status pages show it. |

### imbi-api

| Variable | Type | Default | Description |
|---|---|---|---|
| `IMBI_API_ENVIRONMENT` | str | `development` | Anything other than `development` sets the `Secure` flag on the auth cookies |
| `IMBI_API_HOST` | str | `localhost` | Host of the fallback public URL when `IMBI_API_URL` is unset. It does not set the bind address: use `serve --host`. |
| `IMBI_API_PORT` | int | `8000` | Port of the fallback public URL. A `tcp://ip:port` value from Kubernetes service discovery is read as its port. |
| `IMBI_API_CORS_ALLOWED_ORIGINS` | list[str] | `[]` | JSON array of allowed CORS origins. Also the trusted hosts for per-request OAuth URLs. |
| `IMBI_API_FORWARDED_ALLOW_IPS` | str | `''` | Comma-separated proxy IPs (or `*`) whose `X-Forwarded-*` headers are trusted. Empty: off. |
| `IMBI_API_URL` | str | `''` | Public imbi-api URL with its path prefix, for example `https://imbi.example.com/api`. The path is the API route prefix. |
| `IMBI_UI_URL` | str | `''` | Public UI URL, no path. Used for deep links. |
| `IMBI_AUTH_PASSWORD_MIN_LENGTH` | int | `12` | Minimum password length |
| `IMBI_AUTH_PASSWORD_REQUIRE_UPPERCASE` | bool | `true` | Require an uppercase letter |
| `IMBI_AUTH_PASSWORD_REQUIRE_LOWERCASE` | bool | `true` | Require a lowercase letter |
| `IMBI_AUTH_PASSWORD_REQUIRE_DIGIT` | bool | `true` | Require a digit |
| `IMBI_AUTH_PASSWORD_REQUIRE_SPECIAL` | bool | `true` | Require a special character |
| `IMBI_AUTH_API_KEY_MAX_LIFETIME_DAYS` | int | `365` | Maximum lifetime of an API key or client credential |
| `IMBI_AUTH_MFA_ISSUER_NAME` | str | `Imbi` | Issuer name in authenticator apps |
| `IMBI_AUTH_MFA_TOTP_PERIOD` | int | `30` | TOTP time step in seconds |
| `IMBI_AUTH_MFA_TOTP_DIGITS` | int | `6` | TOTP code length |
| `IMBI_AUTH_RATE_LIMIT_LOGIN` | str | `5/minute` | Password login rate |
| `IMBI_AUTH_RATE_LIMIT_TOKEN_REFRESH` | str | `10/minute` | Token refresh rate |
| `IMBI_AUTH_RATE_LIMIT_OAUTH_INIT` | str | `3/minute` | OAuth flow start rate |
| `IMBI_AUTH_OAUTH_AUTO_LINK_BY_EMAIL` | bool | `true` | Link an SSO sign-in to the user with the same email |
| `IMBI_AUTH_OAUTH_AUTO_CREATE_USERS` | bool | `true` | Create a user at the first SSO sign-in |
| `IMBI_AUTH_DCR_ENABLED` | bool | `true` | Let OAuth clients register at `/auth/register` (RFC 7591) |
| `IMBI_EMAIL_ENABLED` | bool | `true` | Send email. `false` stops all email. |
| `IMBI_EMAIL_DRY_RUN` | bool | `false` | Log messages, do not send them |
| `IMBI_EMAIL_SMTP_HOST` | str | `localhost` | SMTP host |
| `IMBI_EMAIL_SMTP_PORT` | int | `587` | SMTP port |
| `IMBI_EMAIL_SMTP_USE_TLS` | bool | `true` | Use STARTTLS |
| `IMBI_EMAIL_SMTP_USE_SSL` | bool | `false` | Use implicit TLS (usually port 465) |
| `IMBI_EMAIL_SMTP_USERNAME` | str | none | SMTP user name |
| `IMBI_EMAIL_SMTP_PASSWORD` | str | none | SMTP password |
| `IMBI_EMAIL_SMTP_TIMEOUT` | int | `30` | SMTP timeout in seconds |
| `IMBI_EMAIL_FROM_EMAIL` | EmailStr | `noreply@imbi.example.com` | Sender address |
| `IMBI_EMAIL_FROM_NAME` | str | `Imbi` | Sender name |
| `IMBI_EMAIL_REPLY_TO` | EmailStr | none | `Reply-To` address |
| `IMBI_EMAIL_MAX_RETRIES` | int | `3` | Send attempts after the first |
| `IMBI_EMAIL_INITIAL_RETRY_DELAY` | float | `1.0` | First retry delay in seconds |
| `IMBI_EMAIL_MAX_RETRY_DELAY` | float | `60.0` | Maximum retry delay in seconds |
| `IMBI_EMAIL_RETRY_BACKOFF_FACTOR` | float | `2.0` | Retry delay multiplier |
| `S3_ENDPOINT_URL` | str | none | S3-compatible endpoint. Unset: AWS S3. |
| `S3_ACCESS_KEY` | str | none | Access key ID. Unset: the default AWS credential chain. |
| `S3_SECRET_KEY` | str | none | Secret access key |
| `S3_BUCKET` | str | `imbi-uploads` | Bucket name |
| `S3_REGION` | str | `us-east-1` | AWS region |
| `S3_CREATE_BUCKET_ON_INIT` | bool | `true` | Create the bucket at startup if it does not exist |
| `S3_MAX_FILE_SIZE` | int | `52428800` | Upload size limit in bytes |
| `S3_ALLOWED_CONTENT_TYPES` | list[str] | `["image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml", "application/pdf"]` | JSON array of MIME types accepted for upload |
| `S3_THUMBNAIL_MAX_SIZE` | int | `256` | Largest thumbnail side in pixels |
| `S3_THUMBNAIL_QUALITY` | int | `85` | WEBP quality of thumbnails, 0 to 100 |
| `IMBI_IGGY_CONNECTORS_API_KEYS` | list[str] | `[]` | Comma-separated bearer keys of the iggy-connect runtime. Empty: the connector config endpoint answers 503. |
| `IMBI_INTERNAL_ASSISTANT_URL` | str | `''` | Internal URL of imbi-assistant, for the status dashboard. Empty: not probed. |
| `IMBI_INTERNAL_GATEWAY_URL` | str | `''` | Internal URL of imbi-gateway, for the status dashboard |
| `IMBI_INTERNAL_MCP_URL` | str | `''` | Internal URL of imbi-mcp, for the status dashboard |
| `IMBI_INTERNAL_SCHEDULER_URL` | str | `''` | Internal URL of imbi-scheduler, for the status dashboard |
| `IMBI_INTERNAL_SLACKBOT_URL` | str | `''` | Internal URL of imbi-slackbot, for the status dashboard |
| `IMBI_INTERNAL_WORKFLOWS_URL` | str | `''` | Internal URL of imbi-workflows, for the status dashboard |
| `IMBI_GATEWAY_API_TOKEN` | str | none | `imbi-api setup` and `setup-service-accounts` store this value as the API key of the `imbi-gateway` service account. Unset, they generate one and print it. |
| `IMBI_SCHEDULER_SA_CLIENT_ID` | str | none | `setup` stores this pair as the client credential of the `imbi-scheduler` service account. Unset, it generates a pair and prints it. |
| `IMBI_SCHEDULER_SA_CLIENT_SECRET` | str | none | See `IMBI_SCHEDULER_SA_CLIENT_ID`. |
| `IMBI_WORKFLOWS_SA_CLIENT_ID` | str | none | The same, for the `imbi-workflows` service account. |
| `IMBI_WORKFLOWS_SA_CLIENT_SECRET` | str | none | See `IMBI_WORKFLOWS_SA_CLIENT_ID`. |
| `IMBI_OAUTH_ALLOW_INSECURE_URLS` | str | `''` | `true` allows `http://localhost` OAuth provider URLs. Development only. |
| `IMBI_PLUGIN_CACHE_TTL` | int | `60` | Seconds that Valkey keeps the configuration key list of a project |
| `IMBI_PLUGIN_TIMEOUT_SECONDS` | int | `10` | Timeout of one plugin call in seconds |
| `IMBI_PLUGINS_INDEX_URL` | str | `https://pypi.org/simple` | Package index for plugin installs |
| `IMBI_PLUGINS_INSTALL_TIMEOUT` | int | `120` | Timeout of one plugin install in seconds |
| `IMBI_PLUGINS_INSTALL_ENABLED` | bool | `true` | `false` turns off plugin install at runtime |
| `IMBI_SECRETS_GITHUB_GHES_HOSTS` | str | `''` | Comma-separated GitHub Enterprise Server hosts that a GitHub App binding can use |
| `IMBI_SECRETS_AWS_ENDPOINT_URL` | str | none | AWS endpoint of the secrets broker, for LocalStack. Unset: AWS. |
| `MAILPIT_SMTP_PORT` | str | none | In development, with the default SMTP host and port, use this port and no TLS (Mailpit) |

### imbi-assistant

| Variable | Type | Default | Description |
|---|---|---|---|
| `IMBI_ASSISTANT_ENABLED` | bool | `false` | Turn the assistant on. `ANTHROPIC_API_KEY` turns it on too. |
| `IMBI_ASSISTANT_MODEL` | str | `claude-sonnet-4-6` | Claude model |
| `IMBI_ASSISTANT_MAX_TOKENS` | int | `16384` | Maximum response tokens |
| `IMBI_ASSISTANT_MAX_CONVERSATION_TURNS` | int | `100` | Maximum turns in one conversation |
| `IMBI_ASSISTANT_MAX_TOOL_ROUNDS` | int | `10` | Maximum tool rounds for one message |
| `IMBI_ASSISTANT_MAX_TOOL_RESULT_CHARS` | int | `120000` | Longer tool results are cut |
| `IMBI_ASSISTANT_SYSTEM_PROMPT` | str | none | Jinja system prompt that replaces the CMS and packaged prompts |
| `IMBI_ASSISTANT_PROMPT_REF` | str | `imbi-assistant/system@stable` | Prompt CMS reference of the system prompt |
| `IMBI_INTERNAL_API_URL` | str | `http://localhost:8000` | In-cluster origin of imbi-api |
| `IMBI_ASSISTANT_URL` | str | `''` | Public assistant URL. Its path is the route prefix. |
| `IMBI_UI_URL` | str | `''` | Public UI URL, no path. Used for deep links. |
| `IMBI_INTERNAL_UI_URL` | str | `''` | In-cluster UI URL for `llms.txt`. Unset: `IMBI_UI_URL`. |

### imbi-gateway

| Variable | Type | Default | Description |
|---|---|---|---|
| `IMBI_INTERNAL_API_URL` | HttpUrl | `http://localhost:8000/` | In-cluster origin of imbi-api |
| `IMBI_API_URL` | str | `''` | Public imbi-api URL with its path prefix, for example `https://imbi.example.com/api`. The path is the API route prefix. |
| `IMBI_GATEWAY_API_TOKEN` | str | required | API key of the `imbi-gateway` service account. Required. |

### imbi-mcp

| Variable | Type | Default | Description |
|---|---|---|---|
| `IMBI_INTERNAL_API_URL` | str | `http://localhost:8000` | In-cluster origin of imbi-api (`--api-url`) |
| `IMBI_MCP_PUBLIC_URL` | str | none | Public base URL of the host in front of imbi-mcp, without the `/mcp` path (`--public-url`). OAuth is on only when this and `IMBI_MCP_AUTH_SERVER_URL` are both set. |
| `IMBI_MCP_AUTH_SERVER_URL` | str | none | Imbi OAuth issuer URL, for example `https://imbi.example.com` (`--auth-server-url`) |

### imbi-scheduler

| Variable | Type | Default | Description |
|---|---|---|---|
| `IMBI_SCHEDULER_SCHEMA` | str | `scheduler` | Postgres schema of the task tables |
| `IMBI_SCHEDULER_API_PREFIX` | str | `/api` | Route prefix of the task and run routes |
| `IMBI_INTERNAL_API_URL` | str | `http://localhost:8000` | In-cluster origin of imbi-api |
| `IMBI_API_URL` | str | `''` | Public imbi-api URL with its path prefix, for example `https://imbi.example.com/api`. The path is the API route prefix. |
| `IMBI_SCHEDULER_GATEWAY_URL` | str | `http://localhost:8003` | imbi-gateway URL for gateway targets |
| `IMBI_SCHEDULER_SA_SLUG` | str | `imbi-scheduler` | Slug of the scheduler service account |
| `IMBI_SCHEDULER_SA_CLIENT_ID` | str | none | Client ID of the scheduler service account |
| `IMBI_SCHEDULER_SA_CLIENT_SECRET` | SecretStr | none | Its client secret |
| `IMBI_SCHEDULER_MAX_CONCURRENT_RUNS` | int | `20` | Active runs per process |
| `IMBI_SCHEDULER_CONSECUTIVE_SKIPS_LIMIT` | int | `5` | Skipped runs in a row before a task is disabled |
| `IMBI_SCHEDULER_CONSECUTIVE_NO_EFFECT_LIMIT` | int | `5` | No-effect runs in a row before a warning |
| `IMBI_SCHEDULER_POLL_INTERVAL` | int | `30` | Maximum seconds between polls |

### imbi-slackbot

| Variable | Type | Default | Description |
|---|---|---|---|
| `IMBI_SLACKBOT_ENABLED` | bool | `false` | Turn the bot on. `ANTHROPIC_API_KEY` and both Slack tokens turn it on too. |
| `IMBI_SLACKBOT_MODEL` | str | `claude-sonnet-4-6` | Claude model |
| `IMBI_SLACKBOT_MAX_TOKENS` | int | `16384` | Maximum response tokens |
| `IMBI_SLACKBOT_MAX_TOOL_ROUNDS` | int | `10` | Maximum tool rounds for one message |
| `IMBI_SLACKBOT_MAX_TOOL_RESULT_CHARS` | int | `200000` | Longer tool results are replaced with an error |
| `IMBI_SLACKBOT_MAX_THREAD_MESSAGES` | int | `30` | Thread messages sent to Claude as context |
| `IMBI_SLACKBOT_PROGRESS_UPDATES` | bool | `true` | Post and update a status message while a request runs |
| `IMBI_SLACKBOT_STATUS_EMOJI` | str | `hourglass_flowing_sand` | Reaction emoji while a request runs |
| `IMBI_SLACKBOT_IDENTITY_CACHE_TTL` | int | `900` | Seconds to cache a Slack user to Imbi user match |
| `IMBI_SLACKBOT_SYSTEM_PROMPT` | str | none | Jinja system prompt that replaces the CMS and packaged prompts |
| `IMBI_SLACKBOT_PROMPT_REF` | str | `imbi-slackbot/system@stable` | Prompt CMS reference of the system prompt |
| `SLACK_BOT_TOKEN` | str | `''` | Slack bot token (`xoxb-`) |
| `SLACK_APP_TOKEN` | str | `''` | Slack app-level token for Socket Mode (`xapp-`) |
| `IMBI_INTERNAL_API_URL` | str | `http://localhost:8000` | In-cluster origin of imbi-api |
| `IMBI_UI_URL` | str | `''` | Public UI URL, no path. Used for deep links. |
| `IMBI_INTERNAL_UI_URL` | str | `''` | In-cluster UI URL for `llms.txt`. Unset: `IMBI_UI_URL`. |

### imbi-workflows

| Variable | Type | Default | Description |
|---|---|---|---|
| `IMBI_INTERNAL_API_URL` | str | `http://localhost:8000` | In-cluster origin of imbi-api |
| `IMBI_API_URL` | str | `''` | Public imbi-api URL with its path prefix, for example `https://imbi.example.com/api`. The path is the API route prefix. |
| `IMBI_WORKFLOWS_SA_CLIENT_ID` | str | none | Client ID of the `imbi-workflows` service account. Deploy and rollback steps fail without it. |
| `IMBI_WORKFLOWS_SA_CLIENT_SECRET` | SecretStr | none | Its client secret |
| `IMBI_WORKFLOWS_WORKERS` | int | `10` | Runs worked on at the same time |
| `IMBI_WORKFLOWS_POLL_INTERVAL` | float | `10.0` | Upper bound in seconds on the sleep between polls. A lost NOTIFY costs latency, not a run. |
| `IMBI_WORKFLOWS_LEASE_SECONDS` | int | `300` | How long a claim lasts. One step call must end inside it. |
| `IMBI_WORKFLOWS_DEPLOY_POLL_SECONDS` | int | `15` | Seconds between deployment polls |
| `IMBI_WORKFLOWS_AGENT_POLL_SECONDS` | int | `30` | Seconds between agent task polls |
| `IMBI_WORKFLOWS_SCHEDULER_URL` | str | `http://localhost:8005/api` | imbi-scheduler's task API, with its route prefix |
| `IMBI_WORKFLOWS_RECONCILE_INTERVAL` | float | `300.0` | Seconds between passes of the trigger reconciler. imbi-api also wakes it after each activation and pause. |

### imbi-harness (agent runner pods)

| Variable | Type | Default | Description |
|---|---|---|---|
| `IMBI_API_URL` | str | none | Public imbi-api URL with its path prefix, for example `https://imbi.example.com/api`. The path is the API route prefix. |
| `POD_NAME` | str | none | Pod name, from the Kubernetes downward API |
| `POD_NAMESPACE` | str | none | Pod namespace, from the Kubernetes downward API |
| `IMBI_HARNESS_END_OF_CHAIN` | str | `''` | `delete_pod` or `exit` at the end of a chain |
| `IMBI_HARNESS_POOL` | str | `general` | Runner pool name |
| `HOSTNAME` | str | `runner` | Runner instance name |
| `IMBI_HARNESS_IDLE_EXIT_SECONDS` | str | none | Exit after this many idle seconds. Empty or `0`: never. |
| `IMBI_HARNESS_MODEL` | str | none | Model override for the runner |
| `IMBI_HARNESS_MCP_URL` | str | none | imbi-mcp URL that agents use |
| `IMBI_HARNESS_EXTRA_CA` | str | none | PEM file of extra CA certificates |

### Container (entrypoint, Caddy, UI)

| Variable | Type | Default | Description |
|---|---|---|---|
| `IMBI_SERVICE` | str | `all` | Service the image runs: `all`, `api`, `assistant`, `gateway`, `mcp`, `scheduler`, `slackbot`, `ui`, `workflows` |
| `SENTRY_AUTH_TOKEN` | str | none | With `SENTRY_ORG` and `SENTRY_PROJECT`, the `all` and `ui` modes upload the UI source maps to Sentry at start |
| `SENTRY_ORG` | str | none | Sentry organization for the upload |
| `SENTRY_PROJECT` | str | none | Sentry project for the upload |
| `SENTRY_RELEASE` | str | none | Sentry release for the upload |
| `SENTRY_URL` | str | none | Sentry server URL for the upload |
| `IMBI_API_UPSTREAM` | str | `127.0.0.1:8000` | Caddy upstream of imbi-api (`ui` mode) |
| `IMBI_ASSISTANT_UPSTREAM` | str | `127.0.0.1:8002` | Caddy upstream of imbi-assistant |
| `IMBI_GATEWAY_UPSTREAM` | str | `127.0.0.1:8003` | Caddy upstream of imbi-gateway |
| `IMBI_SCHEDULER_UPSTREAM` | str | `127.0.0.1:8005` | Caddy upstream of imbi-scheduler |
| `IMBI_MCP_UPSTREAM` | str | `127.0.0.1:8001` | Caddy upstream of imbi-mcp |
| `SERVE_SOURCE_MAPS` | str | none | `true` serves the UI `*.map` files. Otherwise Caddy answers 404. |
| `VITE_API_URL` | str | none | API URL that Caddy writes into `index.html` at request time. The UI does not start without it. |
| `VITE_SENTRY_DSN` | str | none | Sentry DSN of the UI, written into `index.html` |

<!-- END GENERATED -->

## Notes on some settings

### Public and internal URLs

`IMBI_API_URL` is the URL that a browser uses, with the path that the API is
mounted under. imbi-api mounts its routes under that path. When it is unset,
imbi-api uses `http://<IMBI_API_HOST>:<IMBI_API_PORT>` with no path. The
`/docs` and `/openapi.json` pages are always at the root.

The other services call imbi-api at `IMBI_INTERNAL_API_URL`, an in-cluster
origin with no path. imbi-gateway, imbi-scheduler, and imbi-workflows add the
path of `IMBI_API_URL` to it. So set `IMBI_API_URL` in those services too.

The health check of imbi-api follows the path: with
`IMBI_API_URL=https://imbi.example.com/api` it is `/api/status`.

### Mailpit auto-configuration

When `ENVIRONMENT` is `development` (or unset), `IMBI_EMAIL_SMTP_HOST` is
`localhost`, and `IMBI_EMAIL_SMTP_PORT` is `587`, imbi-api uses the port in
`MAILPIT_SMTP_PORT`. It also turns off STARTTLS, unless
`IMBI_EMAIL_SMTP_USE_TLS` is set. `moon run root:services` writes
`MAILPIT_SMTP_PORT` to `.env.test`.

### Sign-in providers

Sign-in providers (Google, GitHub, OIDC, AWS) and local login are not
environment variables. You configure them in the database. See
[Authentication](../admin/authentication.md). The OAuth callback URL is
`<IMBI_API_URL>/auth/oauth/<provider-slug>/callback`.

### OAuth 2.0 authorization server (MCP login)

imbi-api is an OAuth 2.0 authorization server, so that MCP clients can sign
a user in with the browser. The flow is the authorization code flow with
PKCE (`S256`). Clients register themselves with RFC 7591 dynamic client
registration, unless `IMBI_AUTH_DCR_ENABLED=false`. The discovery document
is at `/.well-known/oauth-authorization-server`, at the host root. The
endpoints are `/auth/authorize`, `/auth/token`, and `/auth/register`, under
the API path. `/auth/authorize` uses the usual Imbi sign-in, so MFA and the
provider rules apply.

imbi-mcp turns on OAuth only when `IMBI_MCP_PUBLIC_URL` and
`IMBI_MCP_AUTH_SERVER_URL` are both set.

#### More than one public host

A deployment can have more than one host. For example, an internal host
serves the UI, and a public host serves the MCP OAuth sign-in for remote
clients. Remote MCP clients connect from the cloud of the vendor, so the MCP
and OAuth endpoints must be public.

imbi-api makes the discovery URLs, the sign-in redirects, and the IdP
callback URL from the host of each request. It uses the request host only
when it is a trusted origin: the origin of `IMBI_API_URL`, or an entry in
`IMBI_API_CORS_ALLOWED_ORIGINS`. For other hosts, it uses `IMBI_API_URL`.
`IMBI_API_FORWARDED_ALLOW_IPS` must be set, so that imbi-api trusts the
scheme and host from the proxy.

To add a public sign-in host:

1. Add the public origin to `IMBI_API_CORS_ALLOWED_ORIGINS`, for example
   `https://imbi-public.example.com`. Keep `IMBI_API_URL` on the internal
   host.
2. Route `/mcp`, `/.well-known/oauth-*`, and `<api-path>/auth/*` on the
   public host to Imbi. `<api-path>` is the path of `IMBI_API_URL`, for
   example `/api`. For browser sign-in on that host, also serve the UI
   (`index.html` at `/` and `/login`, and its static files).
3. If sign-in uses an IdP, register the callback of the public host with
   the IdP: `https://<public-host><api-path>/auth/oauth/<slug>/callback`.

!!! note "Known limit"
    The flow that connects an extra identity from the account settings page
    does not use the request host. It always uses `IMBI_API_URL`, so its
    callback must be registered on that origin.

### System prompts

imbi-assistant and imbi-slackbot read their system prompt from the prompt CMS
at `IMBI_ASSISTANT_PROMPT_REF` and `IMBI_SLACKBOT_PROMPT_REF`. If the CMS does
not supply the prompt, they use the packaged prompt. `imbi-api setup-prompts`
seeds the defaults. `IMBI_ASSISTANT_SYSTEM_PROMPT` and
`IMBI_SLACKBOT_SYSTEM_PROMPT` replace both. See [Prompts](../admin/prompts.md).

### Prompt rendering

imbi-api, imbi-assistant, imbi-slackbot, and imbi-workflows render prompt
templates in worker processes, so that a template cannot stop the service.
`IMBI_PROMPT_*` sets the pool of each service process.

### Other per-service references

- imbi-scheduler: [Scheduler configuration](../scheduler/configuration.md).
- imbi-workflows: [Workflows](../admin/workflows.md).
- Secrets broker (`IMBI_SECRETS_*`): [Secrets](../admin/secrets.md).
- Plugins (`IMBI_PLUGINS*`): [Plugins](../common/plugins/index.md).
- Agent runner pods (`IMBI_HARNESS_*`): [Agent runners](../deployment/agent-runners.md).

### Tracing (`OTEL_*`)

The images install the OpenTelemetry distro, but no service starts the
OpenTelemetry SDK, and the container entrypoint does not run the services
under `opentelemetry-instrument`. So the standard `OTEL_*` variables have no
effect in the published image. To send traces, run the service command under
`opentelemetry-instrument` and set the `OTEL_*` variables.

## Development stack

`moon run root:services` starts the backing services in `compose.ci.yaml`
on random host ports. Then it writes the ports, and a JWT secret and an
encryption key, to `.env.test`. Load that file when you run a service:

```bash
moon run root:setup
moon run root:services
uv run --env-file .env.test imbi-api serve --dev
```

| Service | Container ports | Purpose |
|---|---|---|
| `postgres` | 5432 | PostgreSQL with Apache AGE, pg_cron, and pgvector |
| `clickhouse` | 8123 | Analytics, operations log, audit |
| `valkey` | 6379 | Cache |
| `iggy` | 3000, 8090, 8092 | Apache Iggy message streams (8090 is TCP) |
| `iggy-config-server` | 8080 | Serves the sink configuration to `iggy-connect`, in place of imbi-api |
| `iggy-connect` | 8081 | Iggy connectors runtime with the ClickHouse sink. In the `connect` profile: `moon run root:services` starts it after it creates the topics |
| `ministack` | 4566 | S3-compatible storage |
| `mailpit` | 1025 (SMTP), 8025 (web UI) | SMTP capture |
| `jaeger` | 4317 (OTLP), 16686 (UI) | Tracing |

To find a host port, run
`docker compose -f compose.ci.yaml port <service> <container-port>`, or read
`.env.test`.

`IMBI_RELOAD_DIRS` adds directories that `serve --dev` watches for changes.
