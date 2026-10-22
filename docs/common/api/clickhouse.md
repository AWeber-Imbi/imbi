# ClickHouse Client

The ClickHouse client provides async access to the ClickHouse analytics
database with GDPR-compliant privacy utilities.

## Overview

The ClickHouse client manages connections to ClickHouse and provides query
execution and schema management capabilities. It includes utilities for
GDPR-compliant data handling.

The client does not write rows. Every analytics row is published to Apache
Iggy and written to ClickHouse by the sink, as
[ADR 0019](../../api/adr/0019-apache-iggy-message-streaming.md) describes.

## Basic Usage

```python
from imbi.common import clickhouse

# Initialize the client
await clickhouse.initialize()

# Set up database schema from schemata.toml
await clickhouse.setup_schema()

# Query data
results = await clickhouse.query(
    "SELECT project_id, COUNT(*) AS count "
    "FROM commits FINAL "
    "GROUP BY project_id"
)

for row in results:
    print(f"{row['project_id']}: {row['count']}")
```

## Built-in Tables

`schemata.toml` holds the ClickHouse tables and views that every Imbi
service shares. `setup_schema()` applies the DDL. It runs only
`CREATE ... IF NOT EXISTS`, so it adds new tables but does not change
existing ones.

Each table has an Iggy stream with the same name. The topics split the
stream by the feature that makes the rows. The sink writes every stream
to its table. See [Iggy](iggy.md) for `TOPICS` and the publish API.

<!-- BEGIN GENERATED: scripts/docs_clickhouse_tables.py -->

| Name | Kind | Engine | Order key | Iggy topics |
|---|---|---|---|---|
| `events` | table | `ReplacingMergeTree` | `(project_id, id)` | `comments`, `documents`, `gateway`, `lifecycle`, `projects` |
| `operations_log` | table | `ReplacingMergeTree` | `(project_id, id)` | `api`, `configuration`, `deployments`, `maintenance` |
| `pull_requests` | table | `ReplacingMergeTree` | `(project_id, pr_id)` | `github` |
| `score_history` | table | `MergeTree` | `(project_id, timestamp)` | `scoring` |
| `score_latest_data` | materialized view | `AggregatingMergeTree` | `project_id` |  |
| `score_latest` | view |  |  |  |
| `commits` | table | `ReplacingMergeTree` | `(project_id, sha)` | `github`, `maintenance` |
| `commit_drift` | table | `ReplacingMergeTree` | `(project_id, sha)` | `drift` |
| `document_versions` | table | `ReplacingMergeTree` | `(document_id, version)` | `documents` |
| `tags` | table | `ReplacingMergeTree` | `(project_id, name)` | `github` |
| `scheduler_runs` | table | `ReplacingMergeTree` | `(task_id, run_id)` | `scheduler` |
| `document_read_events` | table | `ReplacingMergeTree` | `(org_slug, document_id, session_id, seq)` | `documents` |
| `document_read_sessions` | table | `ReplacingMergeTree` | `(org_slug, document_id, session_id)` | `documents` |
| `release_component_batches` | table | `MergeTree` | `(release_id, recorded_at, batch_id)` | `sbom` |
| `release_components` | table | `MergeTree` | `(component_id, release_id, batch_id, component_release_id)` | `sbom` |
| `maintenance_log` | table | `MergeTree` | `(occurred_at, id)` | `maintenance` |
| `email_audit` | table | `MergeTree` | `(sent_at, to_email_hash)` | `email` |
| `agent_task_events` | table | `ReplacingMergeTree` | `(organization_id, task_id, seq)` | `agent_tasks` |
| `agent_usage` | table | `ReplacingMergeTree` | `(organization_id, task_id, report_id)` | `agent_tasks` |
| `workflow_run_events` | table | `ReplacingMergeTree` | `(organization_id, run_id, seq)` | `workflows` |
| `workflow_runs` | table | `ReplacingMergeTree` | `(organization_id, workflow_id, run_id)` | `workflows` |
| `secret_audit_events` | table | `ReplacingMergeTree` | `(organization_id, at, event_id)` | `secrets` |

<!-- END GENERATED -->

`maintenance_log` is the durable history of what a global maintenance
operation did, written best-effort so a ClickHouse problem can never fail
maintenance work. One table holds three kinds of append-only row, told
apart by `event_type`: `run` (one per finished run, carrying the
authoritative Valkey counters), `attempt` (one per work item per claim,
written by the worker whatever the outcome), and `activity` (whatever the
operation itself recorded while working). Counting them together would
report events rather than outcomes, so readers filter on `event_type`.
`item_id` is the work item; `project_id` is set only when that item is a
project, which is every operation but `search-reindex`.

The `events` row carries a `version UInt8 DEFAULT 0` column. Writers
that update an event after its initial insert (e.g. backfilling webhook
dispatch outcomes into `metadata` once handlers finish) re-insert with the
same `id` and a higher `version`. The `ReplacingMergeTree(version)`
engine, keyed on `(project_id, id)`, collapses those re-inserts to
the highest-`version` row per event on merge. Merges are asynchronous, so
a read can see more than one row for an event until a merge runs. Use
`FINAL` or `argMax(..., version)` when you need one row per event.

The `events.type` column holds the event *category* (`'webhook'`
for inbound webhook deliveries); the resolved per-source label
(e.g. `'pull_request'`, `'push'`) lives in `metadata.event_type`.
Rows written before this split stored the label directly in
`type`. Filter or join on either form when reading historical data.

`commits` and `tags` are provider-agnostic commit/tag history keyed by
`project_id`. Their `ReplacingMergeTree` engines collapse duplicate rows
(by `recorded_at`) on merge, so re-syncing an overlapping commit range
or re-pushing a tag is idempotent. Reads that must be exact use `FINAL`
or `argMax(..., recorded_at)`. Publish typed rows with the matching
model:

```python
from imbi.common import iggy, models

await iggy.publish(
    "commits",
    "github",
    [
        models.CommitRecord(
            project_id="abc123",
            sha="9f8e7d6c5b4a",
            short_sha="9f8e7d6",
            ref="main",
            message="Fix the thing",
            authored_at=authored_at,
            pushed_at=pushed_at,
        )
    ],
)
```

`release_components` holds one row per component a release depends on,
written from the SBoM it was ingested with, and `release_component_batches`
holds the record that publishes each snapshot. Component and release
identity stay in the graph; only the usage fact joining them lives here,
because that fact is what the component reports aggregate over.

Batch rows are written **after** every fact row of the same `batch_id`.
Readers resolve a release to one batch, then match fact rows on
`(release_id, batch_id)`:

```sql
SELECT release_id,
       argMax(batch_id, (source = 'ingest', recorded_at)) AS batch_id
  FROM imbi.release_component_batches
 WHERE release_id IN {release_ids}
 GROUP BY release_id
```

Publishing separately is what makes three things work:

- **An ingest that found no components is representable**, as a batch with
  `component_count` 0. Keyed on the fact rows alone it would write nothing,
  the previous batch would stay current, and the release would keep
  reporting components it dropped.
- **Two ingests in the same millisecond resolve to one snapshot** rather
  than the union of both, because `argMax` returns a single `batch_id`.
  Which one wins is undefined, as concurrent PUTs for one release already
  are; that they do not merge is the point.
- **A backfill can never outrank an ingest**, because `source = 'ingest'`
  leads the resolver key. Once a release has an ingest batch no backfill can
  displace it, whatever order the two land in, so backfilling alongside live
  writes needs no check-then-publish race.

Fact rows whose batch was never published are inert, so a failed or
interrupted write leaves readers on the previous complete snapshot. This is
not a distributed transaction — the graph write it accompanies has already
happened — but ClickHouse readers never observe a half-written set.

`component_count` is the rows actually written and `parsed_count` the
components the SBoM held. A graph upsert that drops a component stays
non-fatal, so the two differ exactly when a snapshot claims to be complete
without being complete.

Because a batch is immutable once published, both tables are plain
`MergeTree` — there is nothing for a `ReplacingMergeTree` to collapse.
Superseded batches stay readable for debugging.

## Clustered Deployments

For a clustered ClickHouse deployment, set the `CLICKHOUSE_CLUSTER_NAME`
environment variable (exposed as `settings.Clickhouse.cluster_name`). When
set, `setup_schema()` resolves two placeholders in every `schemata.toml` DDL
statement: `{on_cluster}` becomes an `ON CLUSTER <name>` clause and
`{replicated}` (which prefixes each table engine) becomes `Replicated`, so
the schema is created on every node using the `Replicated*` engine variants:

```sql
-- CLICKHOUSE_CLUSTER_NAME unset (single node)
CREATE TABLE IF NOT EXISTS imbi.events (...) ENGINE = ReplacingMergeTree(version)

-- CLICKHOUSE_CLUSTER_NAME=imbi_prod
CREATE TABLE IF NOT EXISTS imbi.events ON CLUSTER imbi_prod (...)
ENGINE = ReplicatedReplacingMergeTree(version)
```

Every DDL statement in `schemata.toml` must carry the `{on_cluster}`
placeholder immediately after the object identifier, and every `ENGINE =`
clause must carry the `{replicated}` placeholder before the engine name;
both are removed when no cluster name is configured. The `Replicated*`
engines rely on the server's `default_replica_path` / `default_replica_name`
macros to supply the Keeper path and replica name — no explicit path is
injected.

## Privacy Utilities

```python
from imbi.common.clickhouse import privacy

# Truncate IP addresses for GDPR compliance
ipv4 = privacy.truncate_ip_to_subnet("192.168.1.100")  # "192.168.1.0"
ipv6 = privacy.truncate_ip_to_subnet("2001:0db8::1")   # "2001:0db8::"

# Hash IP addresses
hashed = privacy.hash_ip_address("192.168.1.100")
```

## API Reference

### Initialization

::: imbi.common.clickhouse.initialize

::: imbi.common.clickhouse.setup_schema

### Query Operations

::: imbi.common.clickhouse.query

### Client

::: imbi.common.clickhouse.client.Clickhouse

### Privacy Utilities

::: imbi.common.clickhouse.privacy.hash_ip_address

::: imbi.common.clickhouse.privacy.truncate_ip_to_subnet

::: imbi.common.clickhouse.privacy.parse_user_agent

::: imbi.common.clickhouse.privacy.sanitize_metadata
