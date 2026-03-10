# Blueprints

Blueprints let you define custom metadata fields for different types of
projects in your service catalog. For example, you might create a
"Microservice" blueprint that requires every microservice to specify its
programming language and SLA tier, while a "Library" blueprint asks for
documentation URL and supported platforms.

## How Blueprints Work

Each blueprint defines a set of additional fields (as a JSON Schema)
that are added to the project creation and edit forms. When someone
creates a project and selects a blueprint, Imbi shows the blueprint's
fields in the UI and validates them before saving.

## Creating a Blueprint

1. Navigate to **Settings > Blueprints** in the admin panel
2. Click **New Blueprint**
3. Fill in the name and description
4. Define the fields using the schema editor:
    - Add fields with types like text, number, select (dropdown), or
      boolean
    - Mark fields as required or optional
    - For select fields, define the allowed values
5. Click **Save**

### Example

A "Microservice" blueprint might define:

| Field | Type | Required | Options |
|-------|------|----------|---------|
| Language | Select | Yes | Python, Go, Rust, TypeScript |
| Framework | Text | No | - |
| SLA Tier | Select | Yes | Tier 1, Tier 2, Tier 3 |

When a user creates a new project with this blueprint, they see these
fields alongside the standard project fields (name, description,
team, etc.).

## Using Blueprints

When creating or editing a project:

1. Select a blueprint from the **Blueprint** dropdown
2. Fill in the blueprint-specific fields that appear
3. Required fields must be completed before the project can be saved

The blueprint selection can be changed later, but metadata from the
previous blueprint is not automatically migrated.

## Updating Blueprints

Blueprint schemas can be updated over time as your organization's
needs change. When you update a blueprint:

- **New projects** use the updated schema immediately
- **Existing projects** are not retroactively validated -- they keep
  their current metadata until the next edit
- When editing an existing project, the current schema is applied

!!! tip
    Start with fewer required fields and add more over time. It is
    easier to make a field required later than to deal with existing
    projects that are missing a newly required field.
