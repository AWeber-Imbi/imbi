# ADR 0007: Relationship Blueprints

## Status

Proposed

## Context

The blueprint system dynamically extends Pydantic node models (Project, Environment, Team, etc.) with additional fields defined in JSON Schema. This allows admins to add custom metadata to entities without code changes.

However, relationships between entities also carry data. The `[:DEPLOYED_IN]` edge between Project and Environment currently has a hardcoded `url` property — defined in the Cypher queries, the `EnvironmentRef` Pydantic model, and the API request/response contracts. Adding any new edge property (e.g., `deploy_tag`, `health_check_url`, `version`) requires changes across the API endpoint, Cypher queries, Pydantic models, and UI.

This is the same problem blueprints solved for nodes. Relationship data should be equally data-driven.

### Current State

- Blueprint model has `type: Literal['Team', 'Environment', 'ProjectType', 'Project']` — node types only
- `[:DEPLOYED_IN]` edge properties are hardcoded: `CREATE (p)-[:DEPLOYED_IN {url: entry.url}]->(e)`
- `EnvironmentRef` model has a hardcoded `url: HttpUrl | str | None` field
- API request: `environments: dict[str, str | None]` (slug → URL string)
- No mechanism for admins to extend edge properties without code changes

## Decision

### 1. Extend Blueprint model with `kind` discriminator

Add a `kind` field to the existing `Blueprint` model rather than creating separate models:

```
kind: 'node' | 'relationship'   (default: 'node')
```

- **Node blueprints** (`kind: 'node'`): Use the existing `type` field (e.g., `type: 'Project'`). Unchanged from today.
- **Relationship blueprints** (`kind: 'relationship'`): Use three new fields:
  - `source: str` — Source node type (e.g., `'Project'`)
  - `target: str` — Target node type (e.g., `'Environment'`)
  - `edge: str` — Neo4j relationship type (e.g., `'DEPLOYED_IN'`)

### 2. Structured relationship targeting

Relationship blueprints identify their target by the triple `(source, target, edge)`. This supports any relationship type in the graph:

| source | target | edge | Use case |
|--------|--------|------|----------|
| Project | Environment | DEPLOYED_IN | Deployment URL, deploy tag, version |
| Project | Project | DEPENDS_ON | Dependency version constraints |

### 3. Same filter model

Relationship blueprints reuse the existing `BlueprintFilter` with `project_type` and `environment` lists. A `DEPLOYED_IN` blueprint filtered to `environment: ['production']` would only add those edge properties for production deployments.

### 4. Edge property model

Add a `RelationshipEdge` base model (empty, `extra='ignore'`) analogous to `Node` for nodes. `get_edge_model()` dynamically extends it with blueprint-defined fields using the same `_apply_blueprints()` machinery.

### 5. API contract change

The `environments` field on project create/update changes from a flat mapping to a structured one:

**Before:**
```json
{"environments": {"production": "https://prod.example.com", "staging": null}}
```

**After:**
```json
{
  "environments": {
    "production": {"url": "https://prod.example.com"},
    "staging": {}
  }
}
```

Each environment value is a dict of edge properties validated against the dynamic edge model. This is a breaking change, acceptable in pre-alpha.

### 6. Seed blueprint replaces hardcoded property

The current hardcoded `url` property moves into a seed blueprint:

```yaml
name: Deployment Properties
slug: deployment-properties
kind: relationship
source: Project
target: Environment
edge: DEPLOYED_IN
enabled: true
priority: 0
json_schema:
  type: object
  properties:
    url:
      type: string
      format: uri
      description: The deployment URL for this project in this environment
```

### 7. Dynamic Cypher queries

Project endpoint Cypher queries change from hardcoded edge properties to dynamic ones:

- **Read**: `properties(d)` captures all edge properties
- **Write**: `CREATE (p)-[:DEPLOYED_IN $props]->(e)` passes validated edge property dict

## Consequences

### Positive

- **Extensible edge data** — admins add edge properties via blueprints without code changes
- **Consistent model** — nodes and relationships use the same blueprint machinery
- **Filtered edge schemas** — production environments can have different edge properties than staging
- **Self-documenting** — edge property schemas are discoverable via the blueprint API and OpenAPI spec

### Negative

- **Breaking API change** — `environments` request format changes from `dict[str, str | None]` to `dict[str, dict]` (acceptable in pre-alpha)
- **Increased query complexity** — dynamic edge properties require `properties(d)` instead of named property access
- **Blueprint admin UI** — needs to support the relationship kind with source/target/edge selectors

### Migration

1. Add `kind`, `source`, `target`, `edge` fields to Blueprint model (with defaults for backward compatibility)
2. Load the `deployment-properties` seed blueprint
3. Update project endpoints to use dynamic edge model
4. Update UI to render dynamic edge fields

## References

- ADR 0006: Project Identity and Multi-Type Support (introduced blueprint filtering)
- Neo4j `properties()` function for dynamic property access
