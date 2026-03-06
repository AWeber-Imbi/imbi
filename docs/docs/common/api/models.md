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

### Blueprint Models
- **Blueprint**: Dynamic schema definitions
- **BlueprintAssignment**: Blueprint-to-entity relationships

## Basic Usage

```python
from imbi_common import models, neo4j

# Create an organization
org = models.Organization(
    name="My Company",
    slug="my-company",
    description="Our organization"
)
await neo4j.create_node(org)

# Create a team linked to an organization
team = models.Team(
    name="Platform Team",
    slug="platform-team",
    description="Infrastructure and platform",
    organization=org
)
await neo4j.create_node(team)
```

## API Reference

### Base Classes

::: imbi_common.models.Node

### Domain Models

::: imbi_common.models.Organization

::: imbi_common.models.Team

::: imbi_common.models.Environment

::: imbi_common.models.ProjectType

::: imbi_common.models.Project

### Blueprint Models

::: imbi_common.models.Blueprint

::: imbi_common.models.BlueprintAssignment

::: imbi_common.models.BlueprintEdge
