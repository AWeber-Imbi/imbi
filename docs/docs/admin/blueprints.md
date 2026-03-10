# Blueprints

Blueprints are customizable metadata schemas that extend the base project
model with additional fields specific to your organization's needs.

## How Blueprints Work

Each blueprint defines a JSON Schema that describes additional metadata
fields for projects. When a project is created with a blueprint, the
project's metadata is validated against the blueprint's schema.

## Creating a Blueprint

```
POST /api/blueprints
{
  "name": "Microservice",
  "description": "Schema for microservice projects",
  "schema": {
    "type": "object",
    "properties": {
      "language": {
        "type": "string",
        "enum": ["python", "go", "rust", "typescript"]
      },
      "framework": {
        "type": "string"
      },
      "sla_tier": {
        "type": "string",
        "enum": ["tier1", "tier2", "tier3"]
      }
    },
    "required": ["language", "sla_tier"]
  }
}
```

## Using Blueprints

When creating a project, specify the blueprint to apply its schema:

```
POST /api/projects
{
  "name": "my-service",
  "blueprint_id": "blueprint-id",
  "metadata": {
    "language": "python",
    "framework": "FastAPI",
    "sla_tier": "tier1"
  }
}
```

The metadata will be validated against the blueprint's JSON Schema. If
validation fails, the request is rejected with details about which fields
are invalid.

## Updating Blueprints

Blueprint schemas can be updated over time. Existing projects are not
retroactively validated against updated schemas, but new creates and
updates will use the current schema.
