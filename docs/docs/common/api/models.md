# Models

Core domain and authentication models for the Imbi ecosystem.

## Overview

The models module provides Pydantic models for all core domain entities
(projects, organizations, teams) and authentication entities (users, groups,
roles, permissions).

All models inherit from cypherantic's `Node` base class and support
serialization to/from Neo4j.

## Model Categories

### Domain Models
- **Organization**: Top-level organizational units
- **Team**: Groups within organizations
- **Environment**: Deployment environments (production, staging, etc.)
- **ProjectType**: Project categorization and templates
- **Project**: Services and applications

### Auth Models
- **User**: User accounts with authentication
- **Group**: User grouping and organization
- **Role**: Permission grouping with inheritance
- **Permission**: Granular access control
- **Session**: User session tracking
- **APIKey**: Programmatic access tokens
- **OAuthIdentity**: OAuth provider linkage
- **TOTPSecret**: MFA/2FA secrets

### Blueprint Models
- **Blueprint**: Dynamic schema definitions
- **BlueprintAssignment**: Blueprint-to-entity relationships

## Basic Usage

```python
from imbi_common import models, neo4j

# Create a project
project = models.Project(
    name="API Gateway",
    slug="api-gateway",
    description="Main API gateway service"
)
await neo4j.create_node(project)

# Create a user
user = models.User(
    email="admin@example.com",
    display_name="Admin User",
    password_hash="...",  # Use auth.core.hash_password()
    is_active=True,
    is_admin=True
)
await neo4j.create_node(user)

# Create relationships
await neo4j.create_relationship(
    from_node=project,
    to_node=team,
    rel_type="OWNED_BY"
)
```

## API Reference

### Base Classes

::: imbi_common.models.Node

::: imbi_common.models.EmptyRelationship

### Domain Models

::: imbi_common.models.Organization

::: imbi_common.models.Team

::: imbi_common.models.Environment

::: imbi_common.models.ProjectType

::: imbi_common.models.Project

### Auth Models

::: imbi_common.models.User

::: imbi_common.models.UserCreate

::: imbi_common.models.UserResponse

::: imbi_common.models.PasswordChangeRequest

::: imbi_common.models.Group

::: imbi_common.models.Role

::: imbi_common.models.Permission

::: imbi_common.models.ResourcePermission

::: imbi_common.models.Session

::: imbi_common.models.TokenMetadata

::: imbi_common.models.APIKey

::: imbi_common.models.OAuthIdentity

::: imbi_common.models.TOTPSecret

### Blueprint Models

::: imbi_common.models.Blueprint

::: imbi_common.models.BlueprintAssignment

::: imbi_common.models.BlueprintEdge

### Edge Types

::: imbi_common.models.GroupEdge

::: imbi_common.models.RoleEdge
