# Blueprints

Blueprints let you define custom metadata fields for different types of
projects in your service catalog, custom fields for tickets, and facts
about deployments. For example, you might create a
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

When a user creates a project that this blueprint applies to, the
**Create New Project** dialog asks for Language and SLA Tier, below the
standard project fields. The user sets Framework after they create the
project.

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

When you create a project, the dialog shows the required fields that have
no default. Imbi sets the default for a required field that has one. You
must complete the fields in the dialog before you can save the project.
When you edit a project, you can set all the fields that the matching
blueprints add.

## Ticket blueprints

A blueprint of type `Ticket` adds custom fields to tickets. Its filter
has three lists in place of project types and environments:

| Filter | Matches when |
|---|---|
| `ticket_type` | The ticket type (`bug`, `task`, or `feature`) is in the list |
| `priority` | The ticket priority (`low`, `normal`, `high`, or `urgent`) is in the list |
| `label` | One or more labels of the ticket are in the list. Imbi normalizes the labels of the filter as it normalizes ticket labels |

An empty list matches every ticket. The lists combine with AND. A
`Ticket` blueprint cannot have a project type or an environment filter.

Imbi checks the custom fields on every ticket create: from a person, an
agent, the scheduler, a webhook, or a workflow. A required field with a
default gets the default. A required field with no default and no value
makes the create fail with `422`. See
[Custom fields](tickets.md#custom-fields).

!!! warning
    `Ticket` blueprints are global. A new required field with no default
    breaks every automatic ticket create (schedules, webhooks, workflows,
    and child tickets of agents) that does not send it, until you change
    that caller. Give a required field a default when you can.

## Deployment blueprints

A blueprint of type `Deployment` adds properties to deployments. Agents
use them to record facts about a deployment after it starts, for
example error counts or CPU metrics for post-deployment monitoring.
The schema of the blueprint sets the structure of the facts. Imbi does
not add a structure of its own.

The filter matches on the project types of the project and on the
environment of the deployment. Imbi keeps the values apart from the
core properties of a deployment, such as `status`, so a blueprint
property can have any name.

This schema keeps a snapshot for each timestamp:

```json
{
  "type": "object",
  "properties": {
    "monitoring": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "properties": {
          "error_count": {"type": "integer"},
          "errors": {"type": "array", "items": {"type": "string"}},
          "cpu_percent": {"type": "number"}
        },
        "additionalProperties": false
      }
    }
  }
}
```

To read and change the properties, use the deployment ID (the `id` of a
deployment in the release endpoints):

- `GET /organizations/{org}/projects/{project}/deployments/environments/{env}/deployments/{id}`
  returns the values, with the default of each property that has no
  value, and the schemas of the matching blueprints.
- `PATCH` on the same path changes the values. The body is a JSON merge
  patch (RFC 7396): an object merges into the stored object, and `null`
  removes a key. To add one snapshot, send only its key:

```json
{"monitoring": {"2026-11-24T10:05:00Z": {"error_count": 3, "cpu_percent": 71.5}}}
```

A `PATCH` fails with `422` when no matching blueprint declares a
property, or when a value does not agree with its schema. One
exception: for a top-level array property, Imbi checks the type of
each item and, for string items, the item `enum`. It does not check
other item rules, such as a `minimum` or the schema of an object item,
so an agent must not rely on those checks. An array inside an object
property is checked against its full schema.

Imbi does not enforce required top-level properties on deployments,
because deployments are also created with no person or agent present.
A nested object is different: after the patch merges into the stored
object, the result must have the properties that its schema requires,
or the `PATCH` fails with `422`.

Concurrent `PATCH` requests on one deployment occur one at a time, so
no change is lost.

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
