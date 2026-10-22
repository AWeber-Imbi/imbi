# Maintenance, Graph Query, and Overview

This page describes three admin tools for platform operators:

| Tool | Menu path | What it does |
|---|---|---|
| Maintenance | **Admin > Global Admin > Maintenance** | Runs a background operation across every project |
| Graph Query | **Admin > Global Admin > Graph Query** | Runs a Cypher query against the graph database |
| Overview | **Admin > &lt;Org&gt; Admin > Overview** | Shows activity, project health, Iggy topics, and system health |

The **Admin** item shows only for platform administrators. **Overview**
is the first page that the Admin menu opens.

## Permissions

<!-- BEGIN GENERATED: scripts/docs_permissions_subset.py admin:maintenance: admin:dashboard:read -->
| Permission | Lets you | Roles that have it |
|---|---|---|
| `admin:maintenance:read` | View global maintenance operations | `admin` |
| `admin:maintenance:manage` | Run and cancel global maintenance operations | `admin` |
| `admin:dashboard:read` | View the admin system-health dashboard | `admin` |
<!-- END GENERATED -->

**Graph Query** has no permission. Only a platform administrator
(`is_admin`) can use it.

## Maintenance

A maintenance operation does one job for every project, in all
organizations. **Reindex Search** works on every searchable node instead
of every project. For example, **Sync Commits & Tags** backfills the commit
history of each project. Use these operations after an upgrade, after an
incident, or to repair data.

The page has two tabs: **Operations** and **Activity**.

### Operations

<!-- BEGIN GENERATED: scripts/docs_maintenance_operations.py -->
| Operation | Slug | What it does |
|---|---|---|
| **Run Analysis** | `run-analysis` | Run the Project Doctor analysis and persist a fresh report for every project. |
| **Remediate Findings** | `remediate` | Apply every fixable Project Doctor finding for every project, then refresh its report. Projects with no report or no fixable findings are skipped. |
| **Apply Sync Fixes** | `sync-fixes` | Run the Project Doctor analysis for every project, then apply only the fixes a plugin marks safe to sweep -- e.g. repointing a PagerDuty escalation policy or syncing PagerDuty service dependencies. Never creates or deletes a remote resource. Projects with no such findings are skipped. |
| **Recompute Scores** | `rescore` | Enqueue a score recomputation for every project; the scoring workers process the queue. Completion means all projects were enqueued. |
| **Sync Deployments** | `deployment-resync` | Backfill recent remote deployments for every project with a deployment integration; projects without one are skipped. |
| **Close Out Stuck Deployments** | `deployment-sweep` | Ask the remote what happened to every deployment still running after 30 minutes, and record the answer. Deployments nothing can resolve for a week are marked failed; a deployment recorded before its release was known is attached to it. Also backfills release drift verdicts from git notes for releases without an existing verdict. Projects without a deployment integration are skipped. Safe to re-run, and scheduled rather than only operator-triggered. |
| **Repair Deployments Mislabelled Rolled Back** | `deployment-status-repair` | Restore deployments that resync marked rolled back over a success. GitHub writes an inactive status on a deployment when a later one supersedes it, and resync read that as the outcome -- so most of a project's deployment history could end up claiming a rollback that never happened. Reads each node's own recorded history rather than the remote, so it makes no API calls and cannot be rate-limited. A node whose history holds no earlier success is left alone: there is nothing to restore. Does not change deployment timestamps, so it cannot move which release an environment reports. Safe to re-run. |
| **Report Re-stamped Commit Push Times (dry run)** | `commit-pushed-at-check` | Count the commits whose recorded push time a later re-sync overwrote -- the full backfill stamping a whole history with one instant, or a completed workflow run re-syncing its head commit -- without changing anything. Compares each commit against the push delivery that first carried it to its branch. Run this before Repair to see the scope. |
| **Repair Re-stamped Commit Push Times** | `commit-pushed-at-repair` | Restore the push time of every commit a later re-sync overwrote, from the push delivery that first carried it to its branch. Push order is what the recent-commits feed and the release ranges sliced from it sort on, so a re-stamped commit shows up in the wrong release. Commits with no push delivery on record are left alone. Reads only ClickHouse, so it makes no API calls and cannot be rate-limited. Safe to re-run. |
| **Backfill Deployments to Operations Log** | `opslog-backfill` | Ensure the operations log has Deployed entries for every attributed deployment event on each release, so deployer attribution resolves for deployments recorded outside Imbi. Also fills the release committish in on existing entries that predate it, so release trains group across every environment. |
| **Report Orphaned Releases (dry run)** | `orphan-release-check` | Report releases whose tag never came to exist on the remote (leftovers of failed release dispatches) without deleting anything. Only counts a release when the remote positively confirms the tag is absent; projects whose integration cannot answer are skipped and logged. |
| **Delete Orphaned Releases** | `orphan-release-purge` | Delete releases whose tag never came to exist on the remote: tagged, never built, never deployed, and the remote positively confirms the tag is absent. Blockers attached to them are removed too. Run Report Orphaned Releases first and review the logs. Projects whose integration cannot answer are skipped. |
| **Sync Commits & Tags** | `commit-sync` | Backfill full commit and tag history for every project with a commit-sync integration; projects without one are skipped. |
| **Sync Pull Requests** | `pr-sync` | Backfill full pull-request history for every project with a PR-sync integration; projects without one are skipped. |
| **Reindex Search** | `search-reindex` | Rebuild the vector search index for every searchable node -- documents, comments, releases, projects, and the rest -- from its current content. Run this after a bulk import or a change to the embedding model; ordinary saves index themselves. |
<!-- END GENERATED -->

The descriptions come from the code. The description of **Close Out
Stuck Deployments** says that it is scheduled, but Imbi does not create a
schedule for it. See [Run an operation](#run-an-operation).

The **Report ... (dry run)** operations change nothing. Run them before
the operation that they report on, and read the activity log.

### Run an operation

1. Open **Admin > Global Admin > Maintenance**.
2. On the **Operations** tab, click **Run** in the row of the operation.
3. Read the dialog. The operation runs across everything that it covers,
   in all organizations. It can put a large load on Imbi and on the
   remote systems.
4. Click **Run**.

The row shows the progress while the run continues. To stop a run, click
**Cancel**. Imbi starts no more projects. The projects in progress
finish. Imbi does not undo the projects that are done.

How a run works:

- Imbi puts the ids of all projects in a Valkey set. Each imbi-api
  instance takes ids from the set and does the work. Without Valkey, Imbi
  refuses the run with `503`.
- One run of an operation can be active at a time. A second **Run** gets
  `409`.
- When a remote system rate-limits **Sync Commits & Tags** or **Sync Pull
  Requests**, Imbi puts the project back in the set and pauses the
  operation until the limit resets. The activity log shows these
  projects as `deferred`.
- If all the instances stop during a run, the run shows as `abandoned`
  after 12 hours.
- The row shows the result of the last run for 7 days.

A run has one of these states: `idle`, `running`, `completed`,
`cancelled`, or `abandoned`.

Imbi does not run an operation on a schedule by itself. You can start an
operation from a scheduled task with
`POST /maintenance/operations/{slug}/run`. The caller needs
`admin:maintenance:manage`. The `imbi-scheduler` role does not have it.
See [Scheduler tasks](../scheduler/tasks.md).

### Activity log

The **Activity** tab shows what each run did. Imbi keeps one row for
each project attempt, with the outcome:

| Outcome | Meaning |
|---|---|
| `succeeded` | The operation did its work for the project |
| `skipped` | The operation does not apply, for example the project has no integration with the capability. The row says why |
| `failed` | The operation failed for the project. The row has the error |
| `deferred` | A rate limit stopped the attempt. Imbi tries the project again later |

Use the outcome filter and the operation filter to narrow the list. Open a
row to see the details that the operation recorded for that attempt.

The log is in the ClickHouse table `maintenance_log`. Imbi deletes rows
after 90 days. The rows go through Iggy, so a new run can take some
seconds to show.

## Graph Query

Graph Query runs a Cypher query against the Apache AGE graph and shows the
result.

!!! warning
    Graph Query does not limit the query to reads. A `CREATE`, `SET`,
    `DELETE`, or `DETACH DELETE` query changes the data at once. Imbi
    keeps no undo. Test a write query on a copy of the data first.

1. Open **Admin > Global Admin > Graph Query**.
2. Type a query in the editor. The query must have a `RETURN` clause.
   Imbi uses the names in the last `RETURN` as the columns.
3. Press **Ctrl+Enter** (**⌘ Enter** on macOS) to run it.

Example:

```cypher
MATCH (p:Project)-[:OWNED_BY]->(t:Team)
RETURN p.name AS project, t.name AS team
LIMIT 25
```

The result has three views: **Graph**, **Table**, and **RAW**. Click a
node or a relationship in the graph to see its properties.

The side panel has two parts:

- **Schema** lists the node labels, the relationship types, and the
  property keys, with counts.
- **History** lists your earlier queries. Click one to load it into the
  editor.

When a query fails, Imbi shows the database error, with the line and the
column when the database gives them.

AGE does not support every Cypher feature. See the
[Apache AGE documentation](https://age.apache.org/).

## Overview

**Admin > &lt;Org&gt; Admin > Overview** shows the state of the platform.
It needs `admin:dashboard:read`.

| Card | What it shows | Scope |
|---|---|---|
| Releases, Events, OpsLog Entries, Pull Requests | Counts for the last 7 days, with a daily trend | All the projects that are not archived, in all organizations |
| Releases by Environment | Releases for each environment | The selected organization |
| Project health | The average score, and the number of projects in each band | The selected organization |
| Iggy topics | Each Iggy topic and its sink consumer group | The platform |
| System health | Each datastore and each service | The platform |
| Resources | Links to the API docs, the REST API, the MCP server, and the webhook gateway | The platform |

The **Project health** bands are:

| Band | Score |
|---|---|
| Healthy | 85 to 100 |
| Fair | 75 to 84 |
| At risk | 50 to 74 |
| Unhealthy | Less than 50 |

### System health

Imbi checks these datastores: PostgreSQL, ClickHouse, Valkey, and Iggy.

Imbi checks the services with a request to the `/status` endpoint of
each. The URL of each service comes from an environment variable of
imbi-api:

| Service | Variable |
|---|---|
| Assistant | `IMBI_INTERNAL_ASSISTANT_URL` |
| Gateway | `IMBI_INTERNAL_GATEWAY_URL` |
| MCP | `IMBI_INTERNAL_MCP_URL` |
| Scheduler | `IMBI_INTERNAL_SCHEDULER_URL` |
| Slackbot | `IMBI_INTERNAL_SLACKBOT_URL` |
| Workflows | `IMBI_INTERNAL_WORKFLOWS_URL` |

When a variable is empty, the service shows as down with the detail `not
configured`. The API row is the imbi-api instance that answers the
request.

### Iggy topics

The **Iggy topics** card has one row for each Iggy topic. Each topic has a
sink consumer group, which writes the messages to ClickHouse. See
[Events](../architecture/events.md).

| Column | Meaning |
|---|---|
| Stream / Topic | The Iggy stream and topic |
| Messages | The messages in the topic |
| Offset | The current offset of the topic |
| Stored | The offset that the consumer group stored |
| Lag | The messages that the group did not consume yet |
| Members | The members of the consumer group |
| Owning | The members that own a partition |

The dot of each row shows the state:

| State | Condition | What to do |
|---|---|---|
| Unowned | The group has no members while messages wait, or a member owns no partition | Check iggy-connect. A member that holds a partition but does not consume can stop the sink. See [Events](../architecture/events.md) |
| Lagging | The lag is more than 0 | Watch it. A lag that grows means the sink is slow or stopped |
| Empty | The topic has no messages | Nothing |
| Owned | The group consumes the topic | Nothing |

The card refreshes every 30 seconds. Use the interval menu to change it,
from **Off** to **1h**. Click a column name to sort.

## Related pages

- [Scoring Policies](scoring-policies.md)
- [Project Doctor](../user-guide/doctor.md)
- [Events](../architecture/events.md)
- [Operations](../deployment/operations.md)
