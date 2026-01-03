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
from datetime import datetime

# Initialize the client
await clickhouse.initialize()

# Insert data
data = [{
    "timestamp": datetime.now(),
    "user_id": "user@example.com",
    "session_id": "abc123",
    "activity_type": "login"
}]
await clickhouse.insert("session_activity", data)

# Query data
results = await clickhouse.query(
    "SELECT user_id, COUNT(*) as count "
    "FROM session_activity "
    "GROUP BY user_id"
)

for row in results:
    print(f"{row['user_id']}: {row['count']}")
```

## Privacy Utilities

```python
from imbi_common.clickhouse import privacy

# Truncate IP addresses for GDPR compliance
ipv4 = privacy.truncate_ip("192.168.1.100")  # "192.168.1.0"
ipv6 = privacy.truncate_ip("2001:0db8::1")   # "2001:0db8::"

# Hash sensitive data
hashed = privacy.hash_pii("user@example.com")
```

## API Reference

### Initialization

::: imbi_common.clickhouse.initialize

::: imbi_common.clickhouse.setup_schema

### Query Operations

::: imbi_common.clickhouse.query

::: imbi_common.clickhouse.insert

### Client

::: imbi_common.clickhouse.client.ClickHouseClient

### Privacy Utilities

::: imbi_common.clickhouse.privacy.truncate_ip

::: imbi_common.clickhouse.privacy.hash_pii
