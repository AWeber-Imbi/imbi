# Scoring Policies

A scoring policy gives each project a score from 0 to 100 for one
property, for example "has a description" or "test coverage". Imbi
combines the policy scores into one project score. The project page and
the dashboards show the score. See
[Operations Log and Scoring](../user-guide/operations-log-and-scoring.md).

To manage policies, open **Admin > &lt;Org&gt; Admin > Scoring Policies**.
The **Admin** item shows only for platform administrators.

Scoring policies are global. The page is in the **&lt;Org&gt; Admin**
group, but a policy has no organization. Each policy applies to the
projects of every organization. To limit a policy, use its target project
types.

## Permissions

<!-- BEGIN GENERATED: scripts/docs_permissions_subset.py scoring_policy: -->

| Permission | Lets you | Roles that have it |
|---|---|---|
| `scoring_policy:read` | View scoring policies | `admin` |
| `scoring_policy:write` | Create/update scoring policies | `admin` |
| `scoring_policy:delete` | Delete scoring policies | `admin` |
| `scoring_policy:rescore` | Trigger rescore for a single project | `admin`, `developer`, `default` |
| `scoring_policy:rescore_all` | Trigger bulk project rescore | `admin` |

<!-- END GENERATED -->

## How Imbi scores a project

1. Imbi finds the policies that apply to the project. A policy applies
   when all of these are true:
    - The policy is enabled.
    - The policy has no target project types, or one of its targets is a
      project type of the project.
    - For the **Attribute**, **Presence**, and **Age** types: the attribute
      exists on the project. A [blueprint](blueprints.md) for the project
      type adds most attributes.
2. Each policy maps the project to a score from 0 to 100. The sections
   below give the rule for each type.
3. Imbi calculates the weighted average of the policy scores:
   `sum(score x weight) / sum(weight)`.

Some edge cases:

- When no policy applies, the project has no score. Imbi removes the
  score that it had.
- When a policy has no value to map (for example, the attribute is empty
  and the map has no entry for it), the policy score is 0. The policy
  still counts in the average.
- When the weights of all the policies that apply are 0, the score is 0.

Example: a project has two policies that apply. **Has description**
(weight 20) gives 100. **Coverage** (weight 80) gives 50. The score is
`(100 x 20 + 50 x 80) / 100 = 60`.

## Create a policy

1. Open **Admin > &lt;Org&gt; Admin > Scoring Policies**.
2. Click **New Policy**.
3. Select the type. You cannot change the type later.
4. Enter the fields in the table below and the fields of the type.
5. Click **Create Policy**.

| Field | What to enter |
|---|---|
| Name | Required |
| Slug | Required. You cannot change it later |
| Description | Optional |
| Weight (0-100) | Required. The weight of the policy in the average |
| Priority | Imbi stores the priority. The score does not depend on it |
| Enabled | A disabled policy does not apply to any project |
| Target Project Types | Leave all clear to apply the policy to every project type |

To copy a policy as JSON, click **Copy Definition** in the policy list.
To make a policy from JSON or YAML, click **Import** and paste the
definition.

## Policy types

The form offers seven types.

| Type | `category` | Scores the project by |
|---|---|---|
| Attribute | `attribute` | The value of an attribute, through a value map or a range map |
| Presence | `presence` | Whether an attribute has a value |
| Link Presence | `link_presence` | Whether the project has a link of one link definition |
| Age | `age` | The age of a date attribute |
| Analysis Result | `analysis_result` | The status of one Project Doctor result |
| Condition | `condition` | Whether a condition on the project and its dependencies is true |
| Deployment Status | `deployment_status` | The latest deployment status in one environment |

### Attribute

Enter the **Attribute Name**. Select a mapping type:

- **Value** maps each value to a score, for example `gold` to `100` and
  `bronze` to `40`. Boolean values use the keys `true` and `false`.
- **Range** maps numeric ranges to scores. A range key has the form
  `<low>..<high>`, for example `80..100`. The ends are included. Ranges
  must not overlap.

A value that is not in the map gives 0.

### Presence

Enter the **Attribute Name**, the **Present score (0-100)**, and the
**Missing score (0-100)**. The defaults are 100 and 0. An attribute is
missing when it is null, an empty string, a string of spaces, or an empty
list.

### Link Presence

Select the **Required Link Type**. The list shows the
[link definitions](catalog-settings.md#link-definitions) of the
organization. Enter the present score and the missing score.

### Age

Enter the **Attribute Name** of a date attribute. Under **Age
Thresholds**, map each threshold to a score.

A threshold is an operator (`<`, `<=`, `==`, `>`, `>=`) and a duration
with a unit: `s`, `m`, `h`, `d`, or `w`. For example, `>90d` means "older
than 90 days".

Imbi tests the thresholds in the order of the list. The first match
wins. Put the most specific threshold first. For example, put `>30d`
before `>7d`.

An age changes when time passes, not only when data changes. The daily
recompute (see [Rescore](#rescore)) keeps age scores current.

### Analysis Result

Enter the **Analysis Result Slug**. A Project Doctor check writes a
result with this slug. Under **Status Scores**, enter the score for
`pass`, `warn`, and `fail`. The defaults are 100, 50, and 0. When the
project has no result with the slug, the score is 0. See
[Project Doctor](../user-guide/doctor.md).

A new Doctor report does not start a recompute. The score changes at the
next recompute of the project.

### Condition

Build a condition tree with the condition builder:

- **Rule** tests one attribute of the project. The operators are `eq`,
  `ne`, `gt`, `ge`, `lt`, `le`, `present`, and `absent`.
- **Group** combines rules with `all`, `any`, or `not`.
- **Dependencies** tests the projects that this project depends on
  (outgoing `DEPENDS_ON`). Select **any**, **all**, or **none** of them.
  A dependency rule cannot contain another dependency rule.

The tree can be at most 6 levels deep. Enter **Score when true** and
**Score when false** (defaults 100 and 0). A condition policy always has
a value, so it always counts in the average. The score breakdown names
the dependencies that matched.

Example: give 0 to a project that depends on a deprecated service.

```json
{
  "relationship": {
    "quantifier": "any",
    "where": {"attribute": "deprecated", "op": "eq", "value": true}
  }
}
```

With **Score when true** 0 and **Score when false** 100.

### Deployment Status

Select the **Environment**. Under **Status Scores**, enter a score for
each deployment status: **Success**, **In progress**, **Pending**,
**Failed**, **Rolled back**, and **Not deployed**. A blank status is not
put in the map.

The API body has the same fields:

```json
{
  "category": "deployment_status",
  "name": "Production is healthy",
  "slug": "production-healthy",
  "weight": 50,
  "environment_slug": "production",
  "status_score_map": {
    "success": 100,
    "in_progress": 100,
    "pending": 100,
    "failed": 0,
    "missing": 100
  }
}
```

Imbi uses the status of the latest deployment of the project in the
environment. The `missing` key scores a project that has not deployed to
the environment. A status that is not in the map uses the `missing`
score. The map above is the default.

## Rescore

Imbi recomputes scores in the background. The workers run in imbi-api and
use a Valkey queue. Without Valkey, Imbi does not recompute scores.

Imbi queues a recompute of a project when:

- a project is created, or an attribute, a link, or a dependency of the
  project changes;
- a deployment status of the project changes;
- a blueprint changes (for the projects that the blueprint applies to);
- a policy is created, changed, or deleted (for the projects that the
  policy applies to);
- the daily recompute runs. Once each day, at 06:00 UTC or later, Imbi
  queues every project.

Imbi waits 5 seconds before it queues the same project again, so a burst
of changes gives one recompute.

To recompute by hand:

| Scope | How | Permission |
|---|---|---|
| One project | Click **Recompute Score** on the **Doctor** tab of the project | `scoring_policy:rescore` |
| All projects | Click **Recompute Scores** on the Scoring Policies page | `scoring_policy:rescore_all` |
| All projects, with progress | Run **Recompute Scores** on the [Maintenance](maintenance.md) page | `admin:maintenance:manage` |

The API (`POST /scoring/rescore`) also accepts a `policy_slug`, a
`blueprint_slug`, or a `project_type_slug`. Each of these needs
`scoring_policy:rescore_all`.

## Related pages

- [Blueprints](blueprints.md)
- [Catalog Settings](catalog-settings.md)
- [Project Doctor](../user-guide/doctor.md)
- [ADR 0011](../api/adr/0011-graph-based-project-scoring.md)
