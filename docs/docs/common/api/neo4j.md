# Neo4j Client

The Neo4j client provides async access to the Neo4j graph database with
connection pooling and CRUD operations.

## Overview

The Neo4j client is a singleton that maintains a connection pool to the
Neo4j database. It provides high-level CRUD operations and low-level query
execution capabilities through cypherantic integration.

## Basic Usage

```python
from imbi_common import neo4j, models

# Initialize the client (creates indexes/constraints)
await neo4j.initialize()

# Create a node
org = models.Organization(name="My Org", slug="my-org")
created = await neo4j.create_node(org)

# Fetch a single node
org = await neo4j.fetch_node(
    models.Organization, {"slug": "my-org"}
)

# Fetch multiple nodes
async for team in neo4j.fetch_nodes(
    models.Team, order_by="name"
):
    print(team.name)

# Upsert a node
await neo4j.upsert(org, constraint={"slug": org.slug})

# Create a relationship
await neo4j.create_relationship(
    from_node=team,
    to_node=org,
    rel_type="BELONGS_TO"
)

# Delete a node
await neo4j.delete_node(
    models.Organization, {"slug": "my-org"}
)

# Close the connection
await neo4j.aclose()
```

## API Reference

### Lifecycle

::: imbi_common.neo4j.initialize

::: imbi_common.neo4j.aclose

::: imbi_common.neo4j.session

### CRUD Operations

::: imbi_common.neo4j.create_node

::: imbi_common.neo4j.fetch_node

::: imbi_common.neo4j.fetch_nodes

::: imbi_common.neo4j.upsert

::: imbi_common.neo4j.delete_node

### Relationships

::: imbi_common.neo4j.create_relationship

::: imbi_common.neo4j.refresh_relationship

::: imbi_common.neo4j.retrieve_relationship_edges

### Low-Level

::: imbi_common.neo4j.run

::: imbi_common.neo4j.convert_neo4j_types
