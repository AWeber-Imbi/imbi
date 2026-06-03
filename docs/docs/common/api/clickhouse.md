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
| `events`         | `MergeTree`          | `(project_id, recorded_at)` | `imbi-gateway` raw webhook deliveries        |
| `pull_requests`  | `ReplacingMergeTree` | `(project_id, pr_id)`       | `pull_requests_mv` over `events`             |
| `operations_log` | `ReplacingMergeTree` | `(project_id, id)`          | ops-log writers                              |
| `commits`        | `ReplacingMergeTree` | `(project_id, sha)`         | a VCS plugin via [`CommitRecord`](models.md) |
| `tags`           | `ReplacingMergeTree` | `(project_id, name)`        | a VCS plugin via [`TagRecord`](models.md)    |

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
