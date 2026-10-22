# Database Setup Guide

This guide covers setting up PostgreSQL (with Apache AGE), ClickHouse,
Apache Iggy and Valkey for use with imbi-common.

For local development, `moon run root:services` starts all of them from
`compose.ci.yaml` and writes their ports to `.env.test`.

## PostgreSQL + Apache AGE Setup

imbi-common's graph layer runs on PostgreSQL with the
[Apache AGE](https://age.apache.org/) extension for Cypher queries, plus
pgvector for similarity search.

### Using the Project Docker Image

The project ships a pre-built PostgreSQL image with all required extensions
installed (`ghcr.io/aweber-imbi/postgres:latest`). This is the easiest path
for local development:

```bash
# Via project compose setup (recommended)
moon run root:services

# Or run the image directly
docker run -d \
  --name postgres-age \
  -p 5432:5432 \
  -e POSTGRES_PASSWORD=secret \
  ghcr.io/aweber-imbi/postgres:latest
```

The image bundles: Apache AGE, pgvector, pg_cron, and pgtap. AGE is loaded
automatically via `shared_preload_libraries` in `postgresql.conf`.

### Production Setup

For production deployments:

1. Use a managed PostgreSQL service (RDS, Cloud SQL, etc.) with the AGE
   extension available, or self-host with the same custom image.
2. Create a dedicated database user with limited privileges.
3. Configure TLS for all connections.
4. Set `max_pool_size` based on your workload.

Example production configuration:

```toml
[postgres]
url = "postgresql://imbi_app:strong-password@db-prod:5432/imbi"
graph_name = "imbi"
max_pool_size = 20
```

### Schema Initialization

No SQL init scripts are necessary. `graph_lifespan` (or
`graph.initialize()`) creates the AGE graph, vertex labels, indexes, the
embeddings table, and supporting functions on startup. The vertex labels
come from `graph/schemata.toml` in `imbi-common`.

```python
from imbi.common import graph

# Initialize schema and open the pool (use graph_lifespan in FastAPI)
await graph.initialize()
```

## ClickHouse Setup

### Using Docker

Run ClickHouse locally with Docker:

```bash
docker run -d \
  --name clickhouse \
  -p 8123:8123 -p 9000:9000 \
  -v $HOME/clickhouse/data:/var/lib/clickhouse \
  clickhouse/clickhouse-server:latest
```

### Production Setup

For production deployments:

1. **Use ClickHouse cluster** for high availability
2. **Enable authentication** and TLS
3. **Configure replication** for data redundancy
4. **Set up proper TTLs** for GDPR compliance
5. **Monitor disk usage** and query performance

Example production configuration:

```toml
[clickhouse]
url = "clickhouse+https://clickhouse-prod.example.com:8443"
```

### Schema Initialization

Initialize ClickHouse schemas from the bundled `schemata.toml`:

```python
from imbi.common import clickhouse

# Create schemas from schemata.toml (called explicitly during setup)
await clickhouse.setup_schema()
```

`setup_schema()` runs only `CREATE ... IF NOT EXISTS`. Services do not
call it at startup. When a release adds a table, run
`imbi-api setup-clickhouse` (or the full `imbi-api setup`) to create it.

For a ClickHouse cluster, set `CLICKHOUSE_CLUSTER_NAME`. See
[Clustered Deployments](../api/clickhouse.md#clustered-deployments).

## Apache Iggy Setup

Imbi services do not write rows to ClickHouse. They publish the rows to
Apache Iggy, and the Iggy connectors runtime (`iggy-connect`) runs the
ClickHouse sink that writes them. See [Iggy](../api/iggy.md) and
[ADR 0019](../../api/adr/0019-apache-iggy-message-streaming.md).

You need two processes:

| Process | Image | Purpose |
|---|---|---|
| `iggy` | `ghcr.io/aweber-imbi/iggy` | The Iggy server. Clients connect on TCP port 8090 |
| `iggy-connect` | The same image, with `IGGY_MODE=connectors` | The connectors runtime that runs the ClickHouse sink |

Set `IGGY_URL` on every Imbi service, for example
`iggy+tcp://iggy:iggy@iggy:8090`. A service creates the streams and
topics at startup. The connectors runtime stops if a stream does not
exist, so start it after an Imbi service has started. `compose.yaml`
sets `restart: on-failure` on it for this reason.

The connectors runtime gets its sink configuration from `imbi-api` at
`/iggy/connectors` under the API prefix (for example
`http://imbi:8000/api/iggy/connectors`). Set the same key in
`IGGY_CONNECTORS_API_KEY` on the runtime and in
`IMBI_IGGY_CONNECTORS_API_KEYS` on `imbi-api`. Without the key,
`imbi-api` answers `503`. The runtime reads the configuration one time,
at startup, so restart it after an upgrade that adds a stream or a
topic. For a working example, see the `iggy` and `iggy-connect` services
in `compose.yaml`.

In `compose.ci.yaml`, `iggy-connect` is in the `connect` profile, and
`iggy-config-server` serves the sink configuration in place of
`imbi-api`.

## Valkey Setup

Imbi services connect to Valkey through `valkey_lifespan`. Set `VALKEY_URL`
(default `valkey://localhost:6379/0`). The setting accepts only the
`valkey://` scheme. See [Valkey Client](../api/valkey.md).

`compose.ci.yaml` runs `valkey/valkey:8-alpine`. `compose.yaml` has no
`valkey` service.

## Database Credentials

### Environment Variables

The recommended way to provide credentials:

```bash
# PostgreSQL
export POSTGRES_URL="postgresql://imbi_app:password@localhost:5432/imbi"

# ClickHouse
export CLICKHOUSE_URL="clickhouse+http://localhost:8123"
```

### Configuration File

For local development, use a config file:

```toml
# config.toml

[postgres]
url = "postgresql://postgres:secret@localhost:5432/imbi"

[clickhouse]
url = "clickhouse+http://localhost:8123"
```

!!! warning
    Never commit config files with credentials to version control!

### Secrets Management

For production, use a secrets manager:

- **AWS**: AWS Secrets Manager or Parameter Store
- **GCP**: Secret Manager
- **Azure**: Key Vault
- **HashiCorp**: Vault
- **Kubernetes**: Sealed Secrets or External Secrets Operator

Load secrets at runtime and set environment variables before initializing
the database clients.

## Connection Pooling

### PostgreSQL

The graph client maintains a psycopg connection pool configured via settings:

```toml
[postgres]
min_pool_size = 2
max_pool_size = 10
```

- **min_pool_size**: Connections kept open at idle
- **max_pool_size**: Maximum concurrent connections

### ClickHouse

The ClickHouse client is used for queries and schema setup only. The
Iggy sink does all inserts, in batches.

## Testing Connections

Verify database connectivity:

```python
import asyncio
from imbi.common import graph, clickhouse, logging

async def test_connections() -> None:
    logging.configure_logging(dev=True)

    # Test PostgreSQL + AGE. cypher() fails until the graph exists.
    await graph.initialize()
    db = graph.Graph()
    await db.open()
    # execute() wraps the query in AGE cypher(), so use Cypher, not SQL
    rows = await db.execute("RETURN 1", columns=["test"])
    print(f"PostgreSQL connected! Test value: {rows[0]['test']}")
    await db.close()

    # Test ClickHouse
    result = await clickhouse.query("SELECT 1 as test")
    print(f"ClickHouse connected! Test value: {result[0]['test']}")

asyncio.run(test_connections())
```

## Troubleshooting

### PostgreSQL Connection Issues

**Problem**: `OperationalError: could not connect to server`

**Solutions**:
- Verify PostgreSQL is running: `docker ps | grep postgres`
- Check port 5432 is accessible
- Verify credentials in `POSTGRES_URL`
- Check PostgreSQL logs: `docker logs postgres-age`

### AGE Extension Issues

**Problem**: `ERROR: extension "age" does not exist`

**Solutions**:
- Ensure you are using the custom `ghcr.io/aweber-imbi/postgres:latest` image
- Verify `shared_preload_libraries` includes `age` in `postgresql.conf`

### ClickHouse Connection Issues

**Problem**: Connection timeout or refused

**Solutions**:
- Verify ClickHouse is running: `docker ps | grep clickhouse`
- Check port 8123 is accessible
- Verify the URL scheme (`clickhouse+http://` not bare `http://`)
- Check ClickHouse logs: `docker logs clickhouse`

### Schema Creation Failures

**Problem**: Constraint or index creation fails

**Solutions**:
- Check for existing data that violates constraints
- Verify database user has CREATE privileges
- Review database logs for detailed error messages

## Docker Compose

Do not copy a compose file into your project. Use the files in the
repository root:

- `compose.ci.yaml` holds the services for the tests: ClickHouse, Iggy,
  the connectors runtime, Mailpit, Ministack, PostgreSQL, Valkey and
  Jaeger. `moon run root:services` starts it.
- `compose.yaml` runs the all-in-one Imbi image with its databases
  (`docker compose up --build`).
