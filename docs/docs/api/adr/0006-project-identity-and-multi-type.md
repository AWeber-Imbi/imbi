# ADR 0006: Project Identity and Multi-Type Support

## Status

Accepted

## Context

Imbi v1 and the current v2 alpha model projects with a single project type. In practice, many projects span multiple categories — a service can be both an API and a database owner, a repository can contain both a schema definition and a CLI tool. Forcing a single type leads to arbitrary classification and prevents blueprints from composing naturally.

Additionally, the current API uses `/{project_type_slug}/{slug}` as the project identifier in URL paths. This creates several problems:

1. **Slug collisions across types are hidden** — two projects with the same slug in different types are distinct resources, which is confusing.
2. **Type is baked into URLs** — changing a project's type would break all bookmarks, integrations, and external references.
3. **Single type limits blueprint composition** — blueprints filter by project type, so a project only gets the schema from its one assigned type.

### Current State

- `Project` has a single `TYPE` relationship to one `ProjectType`
- API paths: `GET /projects/{type_slug}/{slug}`, `PUT /projects/{type_slug}/{slug}`
- `slug` serves as both the human-readable identifier and the URL key (scoped within a type)
- Blueprints resolve against one project type only

## Decision

### 1. Nano-ID as primary project identifier

Add an `id` field to `Project` using [Nano ID](https://github.com/puyuan/py-nanoid) (21-character URL-safe string). This becomes the canonical, immutable identifier used in API paths and external references.

- **Format**: 21-character Nano-ID (default alphabet: `A-Za-z0-9_-`)
- **Uniqueness**: enforced via Neo4j unique constraint on `Project.id`
- **Slug retained**: `slug` remains on the model for use in URL templates (e.g., `https://{slug}.{team}.production.aweber.cloud`) and human-readable display, but is not part of the API path

### 2. Multi-type relationships

Change `Project` → `ProjectType` from a single `TYPE` relationship to multiple `TYPE` relationships. A project can have one or more types.

- **Neo4j**: `(p:Project)-[:TYPE]->(pt:ProjectType)` — one or more edges
- **API**: project create/update accepts `project_types: list[str]` (list of type slugs, minimum one)
- **Model**: `project_type` field becomes `project_types: list[ProjectType]`

### 3. Blueprint aggregation

When resolving the dynamic schema for a project, collect all enabled blueprints matching **any** of the project's types (plus unfiltered blueprints). Merge their JSON schemas by combining `properties` objects. If two blueprints define the same property name, the higher-priority blueprint wins.

Resolution order:
1. Fetch all enabled `Project`-type blueprints
2. Filter to those whose `filter.project_type` list intersects with the project's type slugs (or has no filter)
3. Sort by `priority` (ascending — lower number = higher priority for conflict resolution)
4. Merge `json_schema.properties` across all matching blueprints

### 4. API path changes

| Before | After |
|---|---|
| `GET /projects/{type_slug}/{slug}` | `GET /projects/{id}` |
| `PUT /projects/{type_slug}/{slug}` | `PUT /projects/{id}` |
| `DELETE /projects/{type_slug}/{slug}` | `DELETE /projects/{id}` |
| `POST /projects/{type_slug}` | `POST /projects/` |
| `GET /projects/?project_type_slug=X` | `GET /projects/?project_type=X` |
| `GET /projects/{type_slug}/schema` | `GET /projects/schema?project_types=X,Y` |

All project paths are scoped under the organization: `/organizations/{org_slug}/projects/...`

## Consequences

### Positive

- **Natural modeling** — projects that span categories are represented accurately
- **Stable URLs** — `id`-based paths never change when types are added/removed
- **Composable blueprints** — a project with types `[apis, database]` gets the union of both type schemas
- **Simpler routing** — no type prefix in paths eliminates slug-scoping complexity

### Negative

- **Migration required** — existing projects need Nano-IDs generated; single `TYPE` edge preserved, no data loss
- **Breaking API change** — all clients must update to `id`-based paths (acceptable in alpha)
- **Blueprint conflicts** — two blueprints defining the same property name need priority-based resolution (already supported via `priority` field)

### Migration Plan

1. Add `id` field to all existing `Project` nodes (generate Nano-ID for each)
2. Add unique constraint on `Project.id`
3. Existing single `TYPE` relationships are unchanged — they're already valid multi-type (just with one edge)
4. Update API endpoints to new path structure
5. Update UI to use `id`-based routes
6. Update migrator to generate Nano-IDs for v1 imports

## References

- [Nano ID specification](https://github.com/ai/nanoid)
- [py-nanoid](https://github.com/puyuan/py-nanoid) — Python implementation
