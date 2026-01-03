# Blueprints

The blueprint system enables dynamic schema extension for domain models.

## Overview

Blueprints allow you to define additional fields for models at runtime
based on data stored in Neo4j. This enables flexible, user-defined schemas
without code changes.

## How It Works

1. Blueprint definitions are stored in Neo4j with JSON Schema
2. Blueprints are assigned to entities (e.g., a project type)
3. At runtime, `get_model()` creates a new Pydantic model class with
   additional fields from assigned blueprints
4. The extended model validates data according to the blueprint schema

## Basic Usage

```python
from imbi_common import blueprints, models, neo4j

# Create a blueprint for projects
blueprint = models.Blueprint(
    name="Cloud Provider",
    slug="cloud-provider",
    description="Cloud provider details",
    json_schema={
        "type": "object",
        "properties": {
            "cloud_provider": {
                "type": "string",
                "enum": ["AWS", "GCP", "Azure"]
            },
            "cloud_region": {
                "type": "string"
            }
        },
        "required": ["cloud_provider"]
    }
)
await neo4j.create_node(blueprint)

# Assign blueprint to a project type
project_type = await neo4j.fetch_node(
    models.ProjectType,
    {"slug": "microservice"}
)
assignment = models.BlueprintAssignment(
    is_required=True
)
await neo4j.create_relationship(
    from_node=project_type,
    to_node=blueprint,
    rel_type="HAS_BLUEPRINT",
    properties=assignment
)

# Get extended model for a project
project = await neo4j.fetch_node(
    models.Project,
    {"slug": "my-service"}
)
ProjectModel = await blueprints.get_model(project)

# ProjectModel now has cloud_provider and cloud_region fields
# and validates according to the blueprint schema
```

## API Reference

::: imbi_common.blueprints.get_model
