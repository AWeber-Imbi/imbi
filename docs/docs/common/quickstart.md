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

### Create a Project

```python
from imbi_common import models, neo4j

# Create a project
project = models.Project(
    name="My Service",
    slug="my-service",
    description="A sample microservice"
)

# Save to Neo4j
await neo4j.create_node(project)
print(f"Created project: {project.name}")
```

### Query Projects

```python
# Fetch a single project
project = await neo4j.fetch_node(
    models.Project,
    {"slug": "my-service"}
)

# Fetch all projects
async for project in neo4j.fetch_nodes(
    models.Project,
    order_by="name"
):
    print(f"Project: {project.name}")
```

### Update a Project

```python
# Fetch and modify
project = await neo4j.fetch_node(
    models.Project,
    {"slug": "my-service"}
)
project.description = "Updated description"

# Update in database
await neo4j.upsert(
    project,
    constraint={"slug": project.slug}
)
```

## Authentication

### Password Hashing

```python
from imbi_common.auth import core

# Hash a password
password_hash = core.hash_password("secure_password_123")

# Verify a password
is_valid = core.verify_password("secure_password_123", password_hash)
print(f"Password valid: {is_valid}")
```

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

# Insert session activity
activity_data = {
    "timestamp": datetime.now(),
    "session_id": "abc123",
    "user_id": "user@example.com",
    "activity_type": "login",
    "ip_subnet": "192.168.1.0",
    "user_agent_family": "Chrome",
    "user_agent_version": "120.0",
    "metadata": "/api/auth/login"
}

await clickhouse.insert("session_activity", [activity_data])

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
from imbi_common import blueprints, models, neo4j

# Fetch a project with blueprint-extended fields
project = await neo4j.fetch_node(
    models.Project,
    {"slug": "my-service"}
)

# Get the dynamically extended model
ProjectModel = await blueprints.get_model(models.Project)

# Now ProjectModel includes additional fields from blueprints
# defined for this project type
```

## Complete Example

```python
import asyncio
from datetime import datetime
from imbi_common import (
    logging,
    settings,
    models,
    neo4j,
    clickhouse,
    auth,
)

async def main():
    # Setup
    logging.configure_logging(dev=True)
    config = settings.load_config()

    await neo4j.initialize()
    await clickhouse.initialize()

    # Create a user
    password_hash = auth.core.hash_password("secure_password")
    user = models.User(
        email="admin@example.com",
        display_name="Admin User",
        password_hash=password_hash,
        is_active=True,
        is_admin=True
    )
    await neo4j.create_node(user)

    # Create an organization
    org = models.Organization(
        name="My Company",
        slug="my-company",
        description="Our organization"
    )
    await neo4j.create_node(org)

    # Create a team
    team = models.Team(
        name="Platform Team",
        slug="platform-team",
        description="Infrastructure and platform"
    )
    await neo4j.create_node(team)

    # Link team to organization
    await neo4j.create_relationship(
        from_node=team,
        to_node=org,
        rel_type="MANAGED_BY"
    )

    # Create a project
    project = models.Project(
        name="API Gateway",
        slug="api-gateway",
        description="Main API gateway service"
    )
    await neo4j.create_node(project)

    # Link project to team
    await neo4j.create_relationship(
        from_node=project,
        to_node=team,
        rel_type="OWNED_BY"
    )

    print("✓ Setup complete!")

    # Cleanup
    await neo4j.aclose()

if __name__ == "__main__":
    asyncio.run(main())
```

## Next Steps

- [Configuration Reference](configuration.md)
- [API Documentation](api/settings.md)
- [Database Setup Guide](guides/database-setup.md)
- [Authentication Guide](guides/authentication.md)
