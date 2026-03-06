# Quick Start

This guide will help you get started with imbi-common in just a few minutes.

## Basic Setup

```python
from imbi_common import logging, settings, neo4j, clickhouse

# 1. Configure logging (do this first)
logging.configure_logging(dev=True)

# 2. Load configuration
config = settings.load_config()

# 3. Initialize database connections
async def setup():
    await neo4j.initialize()
    await clickhouse.initialize()

# Run setup
import asyncio
asyncio.run(setup())
```

## Working with Models

### Create an Organization and Team

```python
from imbi_common import models, neo4j

# Create an organization
org = models.Organization(
    name="My Company",
    slug="my-company",
    description="Our organization"
)
await neo4j.create_node(org)

# Create a team linked to the organization
team = models.Team(
    name="Platform Team",
    slug="platform-team",
    description="Infrastructure and platform",
    organization=org
)
await neo4j.create_node(team)
```

### Query Nodes

```python
# Fetch a single node
org = await neo4j.fetch_node(
    models.Organization,
    {"slug": "my-company"}
)

# Fetch all teams
async for team in neo4j.fetch_nodes(
    models.Team,
    order_by="name"
):
    print(f"Team: {team.name}")
```

### Update a Node

```python
# Fetch and modify
org = await neo4j.fetch_node(
    models.Organization,
    {"slug": "my-company"}
)
org.description = "Updated description"

# Update in database
await neo4j.upsert(
    org,
    constraint={"slug": org.slug}
)
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

print(f"Neo4j URL: {config.neo4j.url}")
print(f"ClickHouse URL: {config.clickhouse.url}")
```

### Access Individual Settings

```python
from imbi_common import settings

# Get Neo4j settings
neo4j_config = settings.Neo4j()
print(f"Database: {neo4j_config.database}")

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
from imbi_common import blueprints, models

# Get a dynamically extended model class
# Blueprints defined in Neo4j add extra fields to the model
ProjectModel = await blueprints.get_model(models.Project)

# ProjectModel now includes additional fields from blueprints
# defined for the Project type
```

## Next Steps

- [Configuration Reference](configuration.md)
- [API Documentation](api/settings.md)
- [Database Setup Guide](guides/database-setup.md)
- [Deployment Guide](guides/deployment.md)
