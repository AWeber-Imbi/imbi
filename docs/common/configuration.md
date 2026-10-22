# Configuration Reference

`imbi.common.settings` holds the settings classes that every Imbi service
shares. Each class is a pydantic-settings `BaseSettings` class with an
environment prefix. For each variable, its type, and its default, see the
[configuration reference](../api/configuration.md#environment-variables).
The field name is the variable name without the prefix, in lower case. For
example, `POSTGRES_MAX_POOL_SIZE` is `Postgres.max_pool_size`.

## Settings classes

| Class | Environment prefix | `Configuration` field | Notes |
|---|---|---|---|
| `Auth` | `IMBI_AUTH_` | `auth` | JWT and token encryption. imbi-api extends it with password, MFA, and OAuth settings |
| `ConfigSecrets` | `IMBI_CONFIG_` | none | The Fernet key for configuration secrets |
| `Postgres` | `POSTGRES_` | `postgres` | |
| `Clickhouse` | `CLICKHOUSE_` | `clickhouse` | |
| `Iggy` | `IGGY_` | none | |
| `Valkey` | `VALKEY_` | `valkey` | |
| `Plugins` | none | `plugins` | `IMBI_PLUGINS`, `IMBI_PLUGINS_DISABLED` |
| `Releases` | `IMBI_RELEASES_` | `releases` | |
| `Embeddings` | `EMBEDDINGS_` | `embeddings` | |
| `SSL` | `SSL_` | `ssl` | `SSL_CERT_DIR` |

Two more classes are outside `imbi.common.settings`:

| Class | Environment prefix | Notes |
|---|---|---|
| `imbi.common.llm.AnthropicSettings` | `IMBI_ANTHROPIC_` | Also reads `ANTHROPIC_API_KEY` |
| `imbi.common.api.settings.Settings` | `IMBI_CLIENT_` | The `imbi.common.api` client |

## Reading settings

Make an instance of a class. It reads the environment, then the `.env` file
in the working directory, then its `config.toml` section (when the class has
a `Configuration` field), then the defaults:

```python
from imbi.common import settings

postgres = settings.Postgres()
print(postgres.url, postgres.max_pool_size)
```

For `Auth` and `ConfigSecrets`, use the getters. They keep one instance per
process, so a generated development key stays the same in that process:

```python
auth = settings.get_auth_settings()
config_secrets = settings.get_config_settings()
```

The library code (the graph client, the ClickHouse client, the Iggy client,
the Valkey client, the plugin registry) makes its own instances in this way.
So those clients also read `config.toml`, except the Iggy client, because
`Iggy` has no `Configuration` field.

### `load_config()` and `config.toml`

`settings.load_config()` returns a `Configuration` object. It reads
`config.toml` from these places, in this order:

1. `./config.toml`
2. `~/.config/imbi/config.toml`
3. `/etc/imbi/config.toml`

A key in an earlier file wins over the same key in a later file. Each
settings class with a `Configuration` field reads its own section through
the `ConfigFileSettings` base class, so a direct `settings.Postgres()` and
`load_config().postgres` give the same values. **An environment variable
wins over the same key in the file.** The file supplies only the keys that
the environment does not set.

The next example changes the graph client and the ClickHouse client, unless
`POSTGRES_URL`, `POSTGRES_MAX_POOL_SIZE`, or `CLICKHOUSE_URL` is set:

```toml
[postgres]
url = "postgresql://imbi_app:secret@db-prod:5432/imbi"
max_pool_size = 20

[clickhouse]
url = "clickhouse+http://default:secret@clickhouse-prod:8123/imbi"
```

`Configuration` has no `iggy` field, so an `[iggy]` section has no effect.
Use `IGGY_URL`.

!!! note
    imbi-api adds the `[server]`, `[email]`, and `[storage]` sections
    through its own `APIConfiguration` subclass. See
    [`config.toml`](../api/configuration.md#configtoml).

## Production keys

`Auth` and `ConfigSecrets` read the unprefixed `ENVIRONMENT` variable. When
it is not `development` (the default), they raise a validation error unless
these are set:

- `IMBI_AUTH_JWT_SECRET`
- `IMBI_AUTH_ENCRYPTION_KEY`
- `IMBI_CONFIG_ENCRYPTION_KEY`

In development, they generate a missing key and log a warning. A generated
key is different in each process. Generate a Fernet key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Values with a special format

| Setting | Format |
|---|---|
| `CLICKHOUSE_URL` | `clickhouse+http://user:password@host:8123/database`. The default is `clickhouse+http://localhost:8123` |
| `CLICKHOUSE_CLUSTER_NAME` | When set, `setup_schema()` creates the `schemata.toml` schema `ON CLUSTER <name>`, with `Replicated` table engines. The servers must define the `default_replica_path` and `default_replica_name` macros. Leave unset for one node |
| `IGGY_URL` | `iggy+tcp://user:password@host:8090`. The scheme selects the transport: `iggy` and `iggy+tcp` are TCP; `iggy+quic`, `iggy+http`, and `iggy+ws` are the others. No path |
| `VALKEY_URL` | `valkey://host:6379/0` |
| `IMBI_PLUGINS`, `IMBI_PLUGINS_DISABLED` | Comma-separated in the environment; a list in `config.toml` |
| `EMBEDDINGS_MODELS` | JSON map of a model key to `{"fastembed_id": ..., "dimensions": ...}` |
| `SSL_CERT_DIR` | A directory of CA certificates. `serve` calls `SSL().configure()`, so each new TLS context loads them |

## Validation

A class raises `pydantic.ValidationError` when a value is not valid:

```python
import pydantic

from imbi.common import settings

try:
    settings.Postgres(url='invalid-url')
except pydantic.ValidationError as err:
    print(f'Invalid configuration: {err}')
```
