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
- **TagFormat**: A named (`label`) regular-expression (`pattern`) policy
  for release/deploy tags. Both `Organization` and `ProjectType` carry a
  `tag_formats: list[TagFormat]` field (see
  [Release/Deploy Tag Formats](#releasedeploy-tag-formats)).

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
- **Document**: A free-form, taggable markdown document attached to
  exactly one owning vertex via `[:ATTACHED_TO]` — a `Project`, a
  `ProjectType`, or a `User` (the `User` vertex is defined by
  `imbi-api`, so only the project and project-type edges are typed
  on the model).
- **DocumentTemplate**: Reusable starter content for a `Document`.
  `type` declares which attachment contexts may use the template:
  `project`, `user`, `project_type`, or `global` (every context);
  `project_type_slugs` optionally narrows project types further.
- **CommentThread**: A thread of comments anchored to a
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
from imbi.common import graph, models

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

## Release/Deploy Tag Formats

The tags accepted when cutting a release or promoting a deployment are
governed by a list of `TagFormat` policies. A tag is accepted when it
matches **any** configured format (full-string regex match).

Resolution is hierarchical, project-type overriding organization:

1. If the project's type(s) configure `tag_formats`, those apply.
2. Otherwise the organization's `tag_formats` apply.
3. If neither configures any, **no restriction** is imposed (any tag is
   accepted). Seed `models.SEMVER_TAG_FORMAT` to require semver.

```python
from imbi.common import models, versioning

org = models.Organization(
    name="My Company",
    slug="my-company",
    tag_formats=[models.SEMVER_TAG_FORMAT],
)

patterns = [fmt.pattern for fmt in org.tag_formats]
versioning.matches_tag_formats("v1.2.3", patterns)  # True
versioning.matches_tag_formats("nightly", patterns)  # False
```

::: imbi.common.versioning.matches_tag_formats

## API Reference

### Base Classes

::: imbi.common.models.GraphModel

::: imbi.common.models.Node

### Domain Models

::: imbi.common.models.Organization

::: imbi.common.models.Team

::: imbi.common.models.Environment

::: imbi.common.models.ProjectType

::: imbi.common.models.Project

::: imbi.common.models.TagFormat

::: imbi.common.models.MCPServer

### Software-Composition Models

::: imbi.common.models.Component

::: imbi.common.models.ComponentRelease

::: imbi.common.models.ComponentIdentifier

### Collaboration Models

::: imbi.common.models.CommentThread

::: imbi.common.models.Comment

### Blueprint Models

::: imbi.common.models.Blueprint

::: imbi.common.models.BlueprintAssignment

::: imbi.common.models.BlueprintEdge

### Analytics Models

::: imbi.common.models.CommitRecord

::: imbi.common.models.TagRecord
