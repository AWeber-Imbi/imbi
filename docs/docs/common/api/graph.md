# Graph Database (Apache AGE)

The graph module provides async access to Apache AGE, a PostgreSQL extension
for graph database queries using Cypher.

## Overview

The `Graph` class wraps a psycopg async connection pool and exposes
high-level CRUD operations (`create`, `delete`, `match`, `merge`) that
accept Pydantic models. The `cypher` module generates Cypher query
templates from those models.

## Basic Usage

```python
from imbi_common import graph, models

# Open a graph connection pool
db = graph.Graph()
await db.open()

# Create a node
org = models.Organization(name="My Org", slug="my-org")
await db.create(org)

# Match nodes
orgs = await db.match(models.Organization, {"slug": "my-org"})

# Match all nodes of a type, ordered
teams = await db.match(models.Team, order_by="name")

# Upsert a node
await db.merge(org, match_on=["slug"])

# Delete a node
await db.delete(org)

# Close the connection pool
await db.close()
```

## FastAPI Dependency Injection

```python
from imbi_common import models
from imbi_common.graph import Pool

async def get_org(slug: str, db: Pool) -> models.Organization:
    results = await db.match(models.Organization, {"slug": slug})
    return results[0]
```

## API Reference

### Graph Client

::: imbi_common.graph.Graph

::: imbi_common.graph.graph_lifespan

::: imbi_common.graph.Pool

### Cypher Query Generation

::: imbi_common.graph.cypher.Statement

::: imbi_common.graph.cypher.create

::: imbi_common.graph.cypher.delete

::: imbi_common.graph.cypher.match

::: imbi_common.graph.cypher.merge
