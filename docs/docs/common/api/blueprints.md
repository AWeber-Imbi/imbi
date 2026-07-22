# Blueprints

The blueprint system enables dynamic schema extension for domain models.

## Overview

Blueprints allow you to define additional fields for models at runtime
based on data stored in the graph database. This enables flexible,
user-defined schemas without code changes.

## How It Works

1. Blueprint definitions are stored in the graph with a JSON Schema payload
2. At runtime, `get_model()` queries matching `Blueprint` nodes from the graph
3. `get_model()` calls `pydantic.create_model` to return a subclass with
   the extra fields added
4. The extended model validates data according to the blueprint schema

## Basic Usage

```python
from imbi.common import blueprints, models, graph

async def example(db: graph.Graph) -> None:
    # Store a blueprint in the graph
    blueprint = models.Blueprint(
        name="Cloud Provider",
        slug="cloud-provider",
        type="Project",
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
    await db.create(blueprint)

    # Get extended model for Project — blueprints whose type == "Project"
    # are fetched and applied
    ProjectModel = await blueprints.get_model(db, models.Project)

    # ProjectModel now has cloud_provider and cloud_region fields
    # and validates according to the blueprint schema
```

## Filtering by Context

Blueprints can be filtered by `project_type` or `environment`:

```python
# Only apply blueprints that match the given project type
ProjectModel = await blueprints.get_model(
    db,
    models.Project,
    context={"project_type": "microservice"},
)
```

## API Reference

::: imbi.common.blueprints.get_model
