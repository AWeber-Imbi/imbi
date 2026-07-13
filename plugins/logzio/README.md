# imbi-plugin-logzio

Logz.io provider for the Imbi project logs tab, surfacing relevant logs without requiring search knowledge.

## Installation

```bash
pip install imbi-plugin-logzio
```

## Configuration

Create a Logz.io Integration in Imbi and enable its **Logs** capability.
Connection settings and the API token live on the Integration; the
query-shaping settings are scoped to the Logs capability.

### Integration Options

| Name | Label | Default | Description |
|---|---|---|---|
| `region` | Region | `us` | Logz.io account region. One of `us`, `eu`, `uk`, `au`, `ca`. |
| `timeout_seconds` | Request Timeout | `15` | Per-request timeout in seconds. |

### Logs Capability Options

| Name | Label | Default | Description |
|---|---|---|---|
| `base_query` | Base Query Template | — | Elasticsearch `query_string` applied as a must clause. Supports `${project_slug}`, `${org_slug}`, `${environment}`, `${project_id}`. |
| `timestamp_field` | Timestamp Field | `@timestamp` | Source field containing the log timestamp. |
| `message_field` | Message Field | `message` | Source field containing the log message. |
| `level_field` | Level Field | `level` | Source field containing the log severity level. |
| `environment_field` | Environment Field | — | Log field used to filter by environment. Leave blank to disable automatic environment filtering. |
| `default_environments` | Default Environments | — | Comma-separated environments pre-selected in the UI. |

### Region → Hostname

| Region | API Host |
|---|---|
| `us` | `api.logz.io` |
| `eu` | `api-eu.logz.io` |
| `uk` | `api-uk.logz.io` |
| `au` | `api-au.logz.io` |
| `ca` | `api-ca.logz.io` |

### Credentials

| Name | Description |
|---|---|
| `api_token` | Logz.io API token with search privileges (`X-API-TOKEN` header). |

## Base Query Templates

Use `${variable}` placeholders to scope log searches to a project automatically:

```text
kubernetes.namespace_name:${project_slug} AND env:${environment}
```

Variables substituted at search time: `project_slug`, `org_slug`, `environment`, `project_id`. Unknown variables are rejected at configuration time.

## Filter Operators

| Operator | Translation |
|---|---|
| `eq` | Elasticsearch `term` |
| `ne` | Elasticsearch `bool.must_not.term` |
| `contains` | `match_phrase` on the configured `message_field`; non-leading `wildcard` (`value*`) on other fields |
| `starts_with` | Elasticsearch `prefix` |
| `regex` | Elasticsearch `regexp` (patterns starting with `.*`, `*`, or `?` are rejected) |

## Development

```bash
# Clone alongside imbi-common
git clone https://github.com/AWeber-Imbi/imbi-plugin-logzio
git clone https://github.com/AWeber-Imbi/imbi-common

cd imbi-plugin-logzio
UV_CONFIG_FILE=/dev/null uv sync
UV_CONFIG_FILE=/dev/null uv run pytest tests/
UV_CONFIG_FILE=/dev/null uv run coverage run -m pytest tests/ && uv run coverage report
```
