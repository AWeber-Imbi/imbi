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
from imbi.common import settings

# Load full configuration
config = settings.load_config()

# Access individual settings sections
postgres_config = settings.Postgres()
clickhouse_config = settings.Clickhouse()
auth_config = settings.Auth()
```

## PostgreSQL Settings

Environment prefix: `POSTGRES_`

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `url` | PostgresDsn | `postgresql://postgres:secret@localhost:5432/imbi` | PostgreSQL connection URL |
| `graph_name` | str | `imbi` | Apache AGE graph name |
| `min_pool_size` | int | 2 | Minimum connection pool size |
| `max_pool_size` | int | 10 | Maximum connection pool size |

### Example

**TOML:**
```toml
[postgres]
url = "postgresql://imbi_app:secret@db-prod:5432/imbi"
graph_name = "imbi"
max_pool_size = 20
```

**Environment:**
```bash
export POSTGRES_URL="postgresql://imbi_app:secret@db-prod:5432/imbi"
export POSTGRES_GRAPH_NAME="imbi"
```

## ClickHouse Settings

Environment prefix: `CLICKHOUSE_`

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `url` | HttpUrl | `http://localhost:8123` | ClickHouse HTTP interface URL |
| `connect_timeout` | float | 10.0 | Connection timeout (seconds) |
| `max_connect_attempts` | int | 10 | Maximum connection retry attempts |

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

### Encryption

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `encryption_key` | str | auto-generated | Fernet encryption key |

!!! warning
    Auto-generated keys change on each restart. Always set `IMBI_AUTH_JWT_SECRET`
    and `IMBI_AUTH_ENCRYPTION_KEY` explicitly in production for stable keys
    across restarts.

### Example Auth Configuration

**TOML:**
```toml
[auth]
jwt_secret = "your-secret-key-change-in-production"
access_token_expire_seconds = 7200
encryption_key = "your-fernet-key-here"
```

**Environment:**
```bash
export IMBI_AUTH_JWT_SECRET="your-secret-key-here"
export IMBI_AUTH_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
```

## Complete Example

**config.toml:**
```toml
[postgres]
url = "postgresql://imbi_app:secret@db-prod:5432/imbi"
graph_name = "imbi"
max_pool_size = 20

[clickhouse]
url = "clickhouse+http://clickhouse-prod:8123"

[auth]
jwt_secret = "change-this-in-production"
access_token_expire_seconds = 7200
encryption_key = "your-fernet-key-here"
```

## Validation

Settings are validated on load. Invalid configurations raise `pydantic.ValidationError`:

```python
from imbi.common import settings
import pydantic

try:
    config = settings.Postgres(url="invalid-url")
except pydantic.ValidationError as e:
    print(f"Invalid configuration: {e}")
```

## Best Practices

1. **Never commit secrets** - Use environment variables or secure config files
2. **Generate strong keys** - Use `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
3. **Use TOML for defaults** - Store non-sensitive defaults in config.toml
4. **Override with env vars** - Use environment variables for sensitive values and deployment-specific config
5. **Validate early** - Load config at startup to catch errors before runtime
