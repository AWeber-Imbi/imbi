# Neo4j Client

The Neo4j client provides async access to the Neo4j graph database with
connection pooling and CRUD operations.

## Overview

The Neo4j client is a singleton that maintains a connection pool to the
Neo4j database. It provides high-level CRUD operations and low-level query
execution capabilities.

## Basic Usage

```python
from imbi_common import neo4j, models

# Initialize the client
await neo4j.initialize()

# Create a node
project = models.Project(
    name="My Service",
    slug="my-service",
    description="A sample service"
)
await neo4j.create_node(project)

# Fetch a node
project = await neo4j.fetch_node(
    models.Project,
    {"slug": "my-service"}
)

# Update a node
project.description = "Updated description"
await neo4j.upsert(project, constraint={"slug": project.slug})

# Delete a node
await neo4j.delete_node(project)

# Cleanup
await neo4j.aclose()
```

## API Reference

### Initialization

::: imbi_common.neo4j.initialize

::: imbi_common.neo4j.aclose

### CRUD Operations

::: imbi_common.neo4j.create_node

::: imbi_common.neo4j.fetch_node

::: imbi_common.neo4j.fetch_nodes

::: imbi_common.neo4j.upsert

::: imbi_common.neo4j.delete_node

### Relationships

::: imbi_common.neo4j.create_relationship

::: imbi_common.neo4j.fetch_relationships

::: imbi_common.neo4j.delete_relationship

### Low-Level Operations

::: imbi_common.neo4j.execute_read

::: imbi_common.neo4j.execute_write

### Client

::: imbi_common.neo4j.client.Neo4jClient

### Constants

::: imbi_common.neo4j.constants
