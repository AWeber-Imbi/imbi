# Database Setup Guide

This guide covers setting up PostgreSQL (with Apache AGE) and ClickHouse
for use with imbi-common.

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

The graph schema is initialized from `schema/postgres/` SQL scripts. In
the project Docker setup these are mounted into
`/docker-entrypoint-initdb.d/` and run automatically on first start.

For the graph itself, `graph_lifespan` (or `graph.initialize()`) creates
the AGE graph, vertex labels, indexes, the embeddings table, and supporting
functions on startup.

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

ClickHouse uses HTTP connections created per-request. For
high-throughput scenarios, consider:

- Batch inserts to reduce connection overhead
- Enabling HTTP keep-alive

## Testing Connections

Verify database connectivity:

```python
import asyncio
from imbi.common import graph, clickhouse, logging

async def test_connections() -> None:
    logging.configure_logging(dev=True)

    # Test PostgreSQL + AGE
    db = graph.Graph()
    await db.open()
    rows = await db.execute("SELECT 1 AS test")
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

## Docker Compose Example

For local development, use Docker Compose (or the project's `compose.yaml`):

```yaml
services:
  postgres:
    image: ghcr.io/aweber-imbi/postgres:latest
    ports:
      - "5432:5432"
    environment:
      POSTGRES_PASSWORD: secret
    volumes:
      - postgres-data:/var/lib/postgresql/data

  clickhouse:
    image: clickhouse/clickhouse-server:latest
    ports:
      - "8123:8123"
      - "9000:9000"
    volumes:
      - clickhouse-data:/var/lib/clickhouse

volumes:
  postgres-data:
  clickhouse-data:
```

Start services:

```bash
docker compose up -d
```
