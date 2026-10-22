# Blueprints

Blueprints let you define custom metadata fields for different types of
projects in your service catalog. For example, you might create a
"Microservice" blueprint that requires every microservice to specify its
programming language and SLA tier, while a "Library" blueprint asks for
documentation URL and supported platforms.

## How Blueprints Work

Each blueprint defines a set of additional fields (as a JSON Schema)
that are added to the project creation and edit forms. Imbi selects the
blueprints that match the project. It shows their fields in the UI and
validates them before saving.

## Creating a Blueprint

1. Navigate to **Admin > <organization> Admin > Blueprints**
2. Click **New Blueprint**
3. Fill in the name and description
4. Define the fields using the schema editor:
    - Add fields with types like text, number, select (dropdown), or
      boolean
    - Mark fields as required or optional
    - For select fields, define the allowed values
5. Click **Create Blueprint**

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

You do not select a blueprint. Imbi applies every enabled blueprint whose
`type` matches the record (for example `Project`) and whose `filter`
matches. A filter lists project types, environments, or both. A blueprint
with no filter applies to every record of its type. Imbi applies the
matching blueprints in `priority` order.

When you create or edit a project, Imbi matches on the project types and
the environments of the project. A `Project` blueprint with an environment
filter applies when the project is in at least one of the filter's
environments.

When you create or edit a project, fill in the fields that the matching
blueprints add. You must complete the required fields before you can save
the project.

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
