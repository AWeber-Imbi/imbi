# Models

Core domain models for the Imbi ecosystem.

## Overview

The models module provides Pydantic models for all core domain entities
(projects, organizations, teams) and the blueprint system for dynamic
schema extension.

## Model Categories

### Domain Models
- **Organization**: Top-level organizational units
- **Team**: Groups within organizations
- **Environment**: Deployment environments (production, staging, etc.)
- **ProjectType**: Project categorization and templates
- **Project**: Services and applications

### Software-Composition Models
- **Component**: Third-party package identity (purl with version
  stripped, e.g. `pkg:npm/express`)
- **ComponentRelease**: A specific version of a `Component`
  (`Component-[:HAS_RELEASE]->ComponentRelease`); attached to a
  project `Release` via `[:USES_COMPONENT_RELEASE]`
- **ComponentIdentifier**: Globally unique `(kind, value)` pair
  (purl / cpe / bom-ref / swid) linked to a `Component` via
  `[:IDENTIFIED_BY]`

### Collaboration Models
- **CommentThread**: A thread of comments anchored to a project
  `Document` via `[:ON_DOCUMENT]`. `kind` is `page` (whole-document)
  or `inline` (text-anchored); inline anchors are flattened into the
  `anchor_quote` / `anchor_prefix` / `anchor_suffix` / `anchor_start`
  scalar properties.
- **Comment**: A single comment within a `CommentThread`
  (`Comment-[:IN_THREAD]->CommentThread`); carries `mentions` and
  `acknowledged_by` email lists.

### Blueprint Models
- **Blueprint**: Dynamic schema definitions
- **BlueprintAssignment**: Blueprint-to-entity relationships

### Analytics Models
These are not graph nodes — they are typed rows inserted into ClickHouse
via [`clickhouse.insert`](clickhouse.md). They are provider-agnostic so
any version-control plugin (GitHub, GitLab, …) can reuse them.
- **CommitRecord**: A VCS commit, written to the `commits` table
  (`ReplacingMergeTree` keyed by `(project_id, sha)`)
- **TagRecord**: A VCS tag, written to the `tags` table
  (`ReplacingMergeTree` keyed by `(project_id, name)`)

## Basic Usage

```python
from imbi_common import graph, models

# Create an organization
org = models.Organization(
    name="My Company",
    slug="my-company",
    description="Our organization"
)
await db.create(org)

# Create a team linked to an organization
team = models.Team(
    name="Platform Team",
    slug="platform-team",
    description="Infrastructure and platform",
    organization=org
)
await db.create(team)
```

## API Reference

### Base Classes

::: imbi_common.models.GraphModel

::: imbi_common.models.Node

### Domain Models

::: imbi_common.models.Organization

::: imbi_common.models.Team

::: imbi_common.models.Environment

::: imbi_common.models.ProjectType

::: imbi_common.models.Project

::: imbi_common.models.MCPServer

### Software-Composition Models

::: imbi_common.models.Component

::: imbi_common.models.ComponentRelease

::: imbi_common.models.ComponentIdentifier

### Collaboration Models

::: imbi_common.models.CommentThread

::: imbi_common.models.Comment

### Blueprint Models

::: imbi_common.models.Blueprint

::: imbi_common.models.BlueprintAssignment

::: imbi_common.models.BlueprintEdge

### Analytics Models

::: imbi_common.models.CommitRecord

::: imbi_common.models.TagRecord
