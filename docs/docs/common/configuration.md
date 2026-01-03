# Configuration Reference

imbi-common uses Pydantic Settings for type-safe configuration management.

## Configuration Sources

Configuration is loaded in priority order:

1. **Environment variables** (highest priority)
2. **./config.toml** (project directory)
3. **~/.config/imbi/config.toml** (user directory)
4. **/etc/imbi/config.toml** (system directory)
5. **Built-in defaults** (lowest priority)

## Loading Configuration

```python
from imbi_common import settings

# Load full configuration
config = settings.load_config()

# Access individual settings sections
neo4j_config = settings.Neo4j()
clickhouse_config = settings.Clickhouse()
auth_config = settings.Auth()
```

## Neo4j Settings

Environment prefix: `NEO4J_`

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `url` | AnyUrl | `neo4j://localhost:7687` | Neo4j connection URL |
| `user` | str | None | Username (or from URL) |
| `password` | str | None | Password (or from URL) |
| `database` | str | `neo4j` | Database name |
| `keep_alive` | bool | True | Enable TCP keep-alive |
| `liveness_check_timeout` | int | 60 | Liveness check timeout (seconds) |
| `max_connection_lifetime` | int | 300 | Max connection lifetime (seconds) |

### Example

**TOML:**
```toml
[neo4j]
url = "neo4j://neo4j:password@production-neo4j:7687"
database = "imbi"
keep_alive = true
max_connection_lifetime = 600
```

**Environment:**
```bash
export NEO4J_URL="neo4j://neo4j:password@production-neo4j:7687"
export NEO4J_DATABASE="imbi"
```

### URL Credential Extraction

Credentials in the URL are automatically extracted and URL-decoded:

```python
config = settings.Neo4j(url="neo4j://user%40example:p%40ssw0rd@host:7687")
# config.user == "user@example"
# config.password == "p@ssw0rd"
```

## ClickHouse Settings

Environment prefix: `CLICKHOUSE_`

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `url` | HttpUrl | `http://localhost:8123` | ClickHouse HTTP interface URL |

### Example

**TOML:**
```toml
[clickhouse]
url = "http://clickhouse-prod:8123"
```

**Environment:**
```bash
export CLICKHOUSE_URL="http://clickhouse-prod:8123"
```

## Server Configuration

Environment prefix: `IMBI_`

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `environment` | str | `development` | Environment name |
| `host` | str | `localhost` | Bind address |
| `port` | int | 8000 | Listen port |

### Example

**TOML:**
```toml
[server]
environment = "production"
host = "0.0.0.0"
port = 8080
```

## Auth Settings

Environment prefix: `IMBI_AUTH_`

### JWT Configuration

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `jwt_secret` | str | auto-generated | JWT signing secret |
| `jwt_algorithm` | str | `HS256` | JWT algorithm |
| `access_token_expire_seconds` | int | 3600 | Access token TTL (1 hour) |
| `refresh_token_expire_seconds` | int | 2592000 | Refresh token TTL (30 days) |

### Password Policy

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `password_min_length` | int | 12 | Minimum password length |
| `password_require_uppercase` | bool | True | Require uppercase letter |
| `password_require_lowercase` | bool | True | Require lowercase letter |
| `password_require_digit` | bool | True | Require digit |
| `password_require_special` | bool | True | Require special character |

### Session Configuration

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `session_timeout_seconds` | int | 86400 | Session timeout (24 hours) |
| `max_concurrent_sessions` | int | 5 | Max sessions per user |

### API Keys

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `api_key_max_lifetime_days` | int | 365 | Max API key lifetime |

### Encryption

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `encryption_key` | str | auto-generated | Fernet encryption key |

**⚠️ Warning:** Auto-generated keys are not suitable for production! Always set explicitly.

### MFA Configuration

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `mfa_issuer_name` | str | `Imbi` | TOTP issuer name |
| `mfa_totp_period` | int | 30 | TOTP period (seconds) |
| `mfa_totp_digits` | int | 6 | TOTP digits |
| `mfa_backup_code_count` | int | 10 | Number of backup codes |

### Rate Limiting

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `rate_limit_login` | str | `5/minute` | Login endpoint rate limit |
| `rate_limit_api_key` | str | `100/minute` | API key rate limit |
| `rate_limit_default` | str | `60/minute` | Default rate limit |

### OAuth Configuration

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `oauth_google_enabled` | bool | False | Enable Google OAuth |
| `oauth_google_client_id` | str | None | Google client ID |
| `oauth_google_client_secret` | str | None | Google client secret |
| `oauth_google_allowed_domains` | list | [] | Allowed email domains |
| `oauth_github_enabled` | bool | False | Enable GitHub OAuth |
| `oauth_github_client_id` | str | None | GitHub client ID |
| `oauth_github_client_secret` | str | None | GitHub client secret |
| `oauth_oidc_enabled` | bool | False | Enable generic OIDC |
| `oauth_oidc_discovery_url` | str | None | OIDC discovery URL |
| `oauth_oidc_client_id` | str | None | OIDC client ID |
| `oauth_oidc_client_secret` | str | None | OIDC client secret |
| `oauth_auto_create_users` | bool | True | Auto-create users on OAuth login |
| `oauth_auto_link_by_email` | bool | True | Auto-link OAuth by email |
| `oauth_callback_url` | str | None | OAuth callback URL |

### Example Auth Configuration

**TOML:**
```toml
[auth]
jwt_secret = "your-secret-key-change-in-production"
access_token_expire_seconds = 7200
password_min_length = 16
session_timeout_seconds = 43200
mfa_issuer_name = "My Company Imbi"

[auth.oauth]
google_enabled = true
google_client_id = "your-google-client-id"
google_client_secret = "your-google-client-secret"
google_allowed_domains = ["example.com", "company.com"]
```

## Email Settings

Environment prefix: `IMBI_EMAIL_`

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `enabled` | bool | True | Enable email sending |
| `dry_run` | bool | False | Log emails instead of sending |
| `smtp_host` | str | `localhost` | SMTP server hostname |
| `smtp_port` | int | 25 | SMTP server port |
| `smtp_use_tls` | bool | False | Use TLS |
| `smtp_use_ssl` | bool | False | Use SSL |
| `smtp_username` | str | None | SMTP username |
| `smtp_password` | str | None | SMTP password |
| `from_email` | str | `noreply@example.com` | Sender email |
| `from_name` | str | `Imbi` | Sender name |
| `reply_to` | str | None | Reply-to address |
| `max_retries` | int | 3 | Max send retries |

### Mailpit Auto-Configuration

In development mode, if `smtp_host` is `localhost:1025`, Mailpit settings are auto-configured.

## Complete Example

**config.toml:**
```toml
[server]
environment = "production"
host = "0.0.0.0"
port = 8000

[neo4j]
url = "neo4j://neo4j:password@neo4j-prod:7687"
database = "imbi"
keep_alive = true
max_connection_lifetime = 600

[clickhouse]
url = "http://clickhouse-prod:8123"

[auth]
jwt_secret = "change-this-in-production"
access_token_expire_seconds = 7200
password_min_length = 16
encryption_key = "your-fernet-key-here"
mfa_issuer_name = "My Company"

[email]
enabled = true
smtp_host = "smtp.example.com"
smtp_port = 587
smtp_use_tls = true
smtp_username = "noreply@example.com"
smtp_password = "smtp-password"
from_email = "noreply@example.com"
from_name = "Imbi Notifications"
```

## Validation

Settings are validated on load. Invalid configurations raise `pydantic.ValidationError`:

```python
from imbi_common import settings
import pydantic

try:
    config = settings.Neo4j(url="invalid-url")
except pydantic.ValidationError as e:
    print(f"Invalid configuration: {e}")
```

## Best Practices

1. **Never commit secrets** - Use environment variables or secure config files
2. **Generate strong keys** - Use `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
3. **Use TOML for defaults** - Store non-sensitive defaults in config.toml
4. **Override with env vars** - Use environment variables for sensitive values and deployment-specific config
5. **Validate early** - Load config at startup to catch errors before runtime
