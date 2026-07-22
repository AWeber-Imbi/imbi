# Quick Start

This guide will help you get started with imbi-common in just a few minutes.

## Basic Setup

```python
from imbi_common import logging, settings, graph, clickhouse

# 1. Configure logging (do this first)
logging.configure_logging(dev=True)

# 2. Load configuration
config = settings.load_config()
```

## Working with the Graph Database

The graph module uses Apache AGE (PostgreSQL extension). The recommended
pattern in FastAPI services is via `graph_lifespan` and dependency injection,
but you can also use `Graph` directly:

```python
import asyncio
from imbi_common import graph, models

async def example() -> None:
    db = graph.Graph()
    await db.open()
    try:
        # Create an organization
        org = models.Organization(
            name="My Company",
            slug="my-company",
            description="Our organization",
        )
        await db.create(org)

        # Match nodes
        orgs = await db.match(
            models.Organization,
            {"slug": "my-company"},
        )
        print(orgs[0].name)

        # Upsert a node
        org.description = "Updated description"
        await db.merge(org, match_on=["slug"])
    finally:
        await db.close()

asyncio.run(example())
```

## Authentication

### JWT Tokens

```python
from imbi_common.auth import core

# Create an access token
token = core.create_access_token(
    subject="user@example.com",
    extra_claims={"role": "admin"}
)

# Verify and decode
try:
    payload = core.verify_token(token)
    print(f"Token valid for: {payload['sub']}")
except Exception as e:
    print(f"Token invalid: {e}")
```

### Token Encryption

```python
from imbi_common.auth import encryption

# Encrypt sensitive data
encrypted = encryption.encrypt_token("sensitive_token_value")

# Decrypt
decrypted = encryption.decrypt_token(encrypted)
```

## Configuration

### Load from TOML File

```python
from imbi_common import settings

# Searches for config.toml in:
# 1. ./config.toml (current directory)
# 2. ~/.config/imbi/config.toml
# 3. /etc/imbi/config.toml
config = settings.load_config()

print(f"Postgres URL: {config.postgres.url}")
print(f"ClickHouse URL: {config.clickhouse.url}")
```

### Access Individual Settings

```python
from imbi_common import settings

# Get PostgreSQL settings
postgres_config = settings.Postgres()
print(f"Graph name: {postgres_config.graph_name}")

# Get Auth settings
auth_config = settings.Auth()
print(f"JWT Algorithm: {auth_config.jwt_algorithm}")
```

## Analytics with ClickHouse

```python
from imbi_common import clickhouse

# Query data
results = await clickhouse.query(
    "SELECT user_id, COUNT(*) as login_count "
    "FROM session_activity "
    "WHERE activity_type = 'login' "
    "GROUP BY user_id"
)

for row in results:
    print(f"{row['user_id']}: {row['login_count']} logins")
```

## Blueprint System

The blueprint system allows dynamic schema extension:

```python
from imbi_common import blueprints, models, graph

async def example(db: graph.Graph) -> None:
    # Get a dynamically extended model class
    # Blueprints stored in the graph add extra fields to the model
    ProjectModel = await blueprints.get_model(db, models.Project)

    # ProjectModel now includes additional fields from blueprints
    # defined for the Project type
```

## Next Steps

- [Configuration Reference](configuration.md)
- [API Documentation](api/settings.md)
- [Database Setup Guide](guides/database-setup.md)
- [Deployment Guide](guides/deployment.md)
