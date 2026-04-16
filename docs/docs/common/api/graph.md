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

Wire `graph_lifespan` into the application lifespan, then declare `Pool`
as a route parameter to receive the injected `Graph` instance:

```python
import fastapi
from imbi_common import lifespan, models
from imbi_common.graph import Pool, graph_lifespan

app = fastapi.FastAPI(
    lifespan=lifespan.Lifespan(graph_lifespan),
)


@app.get('/orgs/{slug}')
async def get_org(slug: str, db: Pool) -> models.Organization:
    results = await db.match(models.Organization, {"slug": slug})
    return results[0]
```

To run custom initialisation after the pool opens (e.g. schema setup),
register a startup callback before creating the app:

```python
from imbi_common import graph

async def on_graph_ready(db: graph.Graph) -> None:
    await graph.initialize()

graph.set_on_startup(on_graph_ready)
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
