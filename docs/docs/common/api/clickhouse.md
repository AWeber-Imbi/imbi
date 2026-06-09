# ClickHouse Client

The ClickHouse client provides async access to the ClickHouse analytics
database with GDPR-compliant privacy utilities.

## Overview

The ClickHouse client manages connections to ClickHouse and provides query
execution, data insertion, and schema management capabilities. It includes
utilities for GDPR-compliant data handling.

## Basic Usage

```python
from imbi_common import clickhouse

# Initialize the client
await clickhouse.initialize()

# Set up database schema from schemata.toml
await clickhouse.setup_schema()

# Insert data (list of Pydantic models)
await clickhouse.insert("table_name", [model_instance])

# Query data
results = await clickhouse.query(
    "SELECT user_id, COUNT(*) as count "
    "FROM session_activity "
    "GROUP BY user_id"
)

for row in results:
    print(f"{row['user_id']}: {row['count']}")
```

## Built-in Tables

`schemata.toml` ships the tables every Imbi service shares. DDL is
applied by `setup_schema()`. Notable tables:

| Table            | Engine               | Order key                   | Written by                                   |
| ---------------- | -------------------- | --------------------------- | -------------------------------------------- |
| `events`         | `ReplacingMergeTree` | `(project_id, id)`          | `imbi-gateway` raw webhook deliveries        |
| `pull_requests`  | `ReplacingMergeTree` | `(project_id, pr_id)`       | `pull_requests_mv` over `events`             |
| `operations_log` | `ReplacingMergeTree` | `(project_id, id)`          | ops-log writers                              |
| `commits`        | `ReplacingMergeTree` | `(project_id, sha)`         | a VCS plugin via [`CommitRecord`](models.md) |
| `tags`           | `ReplacingMergeTree` | `(project_id, name)`        | a VCS plugin via [`TagRecord`](models.md)    |

The `events` row carries a `version UInt8 DEFAULT 0` column and a
sibling `events_latest` view. Writers that update an event after
its initial insert (e.g. backfilling webhook dispatch outcomes
into `metadata` once handlers finish) re-insert with the same
`id` and a higher `version`. The `ReplacingMergeTree(version)`
engine, keyed on `(project_id, id)`, collapses those re-inserts to
the highest-`version` row per event on merge. Because merges are
asynchronous, reads that need the latest state immediately go
through `events_latest`, which uses a window function to return one
row per `id` (highest `version`, breaking ties by `recorded_at`)
even before a merge has run. Inserts always go to `events`.

`commits` and `tags` are provider-agnostic commit/tag history keyed by
`project_id`. Their `ReplacingMergeTree` engines collapse duplicate rows
(by `recorded_at`) on merge, so re-syncing an overlapping commit range
or re-pushing a tag is idempotent. Reads that must be exact use `FINAL`
or `argMax(..., recorded_at)`. Insert typed rows with the matching
model:

```python
from imbi_common import clickhouse, models

await clickhouse.insert(
    "commits",
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
from imbi_common.clickhouse import privacy

# Truncate IP addresses for GDPR compliance
ipv4 = privacy.truncate_ip_to_subnet("192.168.1.100")  # "192.168.1.0"
ipv6 = privacy.truncate_ip_to_subnet("2001:0db8::1")   # "2001:0db8::"

# Hash IP addresses
hashed = privacy.hash_ip_address("192.168.1.100")
```

## API Reference

### Initialization

::: imbi_common.clickhouse.initialize

::: imbi_common.clickhouse.setup_schema

### Query Operations

::: imbi_common.clickhouse.query

::: imbi_common.clickhouse.insert

### Client

::: imbi_common.clickhouse.client.Clickhouse

### Privacy Utilities

::: imbi_common.clickhouse.privacy.hash_ip_address

::: imbi_common.clickhouse.privacy.truncate_ip_to_subnet

::: imbi_common.clickhouse.privacy.parse_user_agent

::: imbi_common.clickhouse.privacy.sanitize_metadata
