# Database Setup Guide

This guide covers setting up Neo4j and ClickHouse for use with imbi-common.

## Neo4j Setup

### Using Docker

The easiest way to run Neo4j locally is with Docker:

```bash
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  -v $HOME/neo4j/data:/data \
  -v $HOME/neo4j/logs:/logs \
  neo4j:5-community
```

Access the Neo4j Browser at: `http://localhost:7474`

### Production Setup

For production deployments:

1. **Use Neo4j Enterprise** for clustering and advanced features
2. **Enable authentication** with strong passwords
3. **Configure backups** with regular snapshots
4. **Set up monitoring** with Neo4j metrics
5. **Tune JVM settings** based on your workload

Example production configuration:

```toml
[neo4j]
url = "neo4j://neo4j-prod:7687"
user = "imbi_app"
password = "strong-password-from-secrets-manager"
database = "imbi"
keep_alive = true
max_connection_lifetime = 600
```

### Schema Initialization

The Neo4j client automatically creates required indexes and constraints:

```python
from imbi_common import neo4j

# Initialize client and create schema
await neo4j.initialize()

# Indexes and constraints are created automatically
# See imbi_common.neo4j.constants for definitions
```

Required indexes and constraints:

- **Blueprint**: Unique constraint on `(name, type)`
- **Team**: Unique constraint on `slug`
- **Conversation**: Unique constraint on `id`, indexes on `user_email` and `updated_at`
- **Message**: Unique constraint on `id`, index on `conversation_id`

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
url = "https://clickhouse-prod.example.com:8443"
```

### Schema Initialization

Initialize ClickHouse schemas from the bundled `schemata.toml`:

```python
from imbi_common import clickhouse

# Initialize client
await clickhouse.initialize()

# Create schemas from schemata.toml
await clickhouse.setup_schema()
```

## Database Credentials

### Environment Variables

The recommended way to provide credentials:

```bash
# Neo4j
export NEO4J_URL="neo4j://neo4j:password@localhost:7687"
export NEO4J_DATABASE="imbi"

# ClickHouse
export CLICKHOUSE_URL="http://localhost:8123"
```

### Configuration File

For local development, use a config file:

```toml
# config.toml

[neo4j]
url = "neo4j://localhost:7687"
user = "neo4j"
password = "password"
database = "imbi"

[clickhouse]
url = "http://localhost:8123"
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

### Neo4j

The Neo4j client maintains a connection pool configured via settings:

```toml
[neo4j]
keep_alive = true
max_connection_lifetime = 600  # 10 minutes
liveness_check_timeout = 60    # 60 seconds
```

Connection pool tuning:
- **keep_alive**: Enable TCP keep-alive to detect dead connections
- **max_connection_lifetime**: Rotate connections to avoid staleness
- **liveness_check_timeout**: How long to wait for connection health checks

### ClickHouse

ClickHouse uses HTTP connections that are created per-request. For
high-throughput scenarios, consider:

- Using a connection pool at the HTTP client level
- Enabling HTTP keep-alive
- Batch inserts to reduce connection overhead

## Testing Connections

Verify database connectivity:

```python
import asyncio
from imbi_common import neo4j, clickhouse, logging

async def test_connections():
    logging.configure_logging(dev=True)

    # Test Neo4j
    await neo4j.initialize()
    async with neo4j.run("RETURN 'Neo4j connected!' as message") as result:
        record = await result.single()
        print(record['message'])
    await neo4j.aclose()

    # Test ClickHouse
    await clickhouse.initialize()
    result = await clickhouse.query("SELECT 1 as test")
    print(f"ClickHouse connected! Test value: {result[0]['test']}")

asyncio.run(test_connections())
```

## Troubleshooting

### Neo4j Connection Issues

**Problem**: `ServiceUnavailable: Unable to connect to localhost:7687`

**Solutions**:
- Verify Neo4j is running: `docker ps | grep neo4j`
- Check firewall rules allow port 7687
- Verify credentials are correct
- Check Neo4j logs: `docker logs neo4j`

### ClickHouse Connection Issues

**Problem**: Connection timeout or refused

**Solutions**:
- Verify ClickHouse is running: `docker ps | grep clickhouse`
- Check firewall rules allow port 8123
- Verify URL uses `http://` (not `https://` unless configured)
- Check ClickHouse logs: `docker logs clickhouse`

### Schema Creation Failures

**Problem**: Constraint or index creation fails

**Solutions**:
- Check for existing data that violates constraints
- Verify database user has CREATE privileges
- Check for naming conflicts with existing objects
- Review database logs for detailed error messages

## Docker Compose Example

For local development, use Docker Compose:

```yaml
# docker-compose.yml

services:
  neo4j:
    image: neo4j:5-community
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/password
    volumes:
      - neo4j-data:/data
      - neo4j-logs:/logs

  clickhouse:
    image: clickhouse/clickhouse-server:latest
    ports:
      - "8123:8123"
      - "9000:9000"
    volumes:
      - clickhouse-data:/var/lib/clickhouse

volumes:
  neo4j-data:
  neo4j-logs:
  clickhouse-data:
```

Start services:

```bash
docker-compose up -d
```
