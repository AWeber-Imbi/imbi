# Logz.io

The `logzio` plugin searches Logz.io logs from the project **Logs** tab.
It uses the Logz.io search API.

## Capabilities

| Capability | Label | Default | Scope |
|---|---|---|---|
| `logs` | Logs | On | Project-scoped. Supports the histogram |

## Configuration

### Options

| Option | Label | Default | Meaning |
|---|---|---|---|
| `region` | Region | `us` | The Logz.io account region: `us`, `eu`, `uk`, `au`, or `ca` |
| `timeout_seconds` | Request Timeout | `15` | The timeout of each request, in seconds |

The region selects the API host:

| Region | API host |
|---|---|
| `us` | `api.logz.io` |
| `eu` | `api-eu.logz.io` |
| `uk` | `api-uk.logz.io` |
| `au` | `api-au.logz.io` |
| `ca` | `api-ca.logz.io` |

### Logs capability options

You can set these on the integration, and override them for a project type
or a project. See
[Assignments](../admin/integrations-and-plugins.md#assignments).

| Option | Label | Default | Meaning |
|---|---|---|---|
| `base_query` | Base Query Template | (empty) | An Elasticsearch `query_string` that every search must match. See [Base query](#base-query) |
| `timestamp_field` | Timestamp Field | `@timestamp` | The field that holds the log time |
| `message_field` | Message Field | `message` | The field that holds the log message |
| `level_field` | Level Field | `level` | The field that holds the log level |
| `environment_field` | Environment Field | (empty) | The field to filter on when the user selects an environment. Leave it empty to turn off environment filtering |
| `default_environments` | Default Environments | (empty) | Comma-separated environments that the **Logs** tab selects first, for example `production,staging` |

### Credentials

| Credential | Required | Secret | Meaning |
|---|---|---|---|
| `api_token` | Yes | Yes | A Logz.io API token with search permission. Imbi sends it in the `X-API-TOKEN` header |

## Base query

The base query limits each search to the logs of one project. It can use
these variables:

- `${project_slug}`
- `${org_slug}`
- `${environment}`
- `${project_id}`

Example:

```text
kubernetes.namespace_name:${project_slug} AND env:${environment}
```

Imbi replaces a variable that has no value with an empty string. A search
fails if the template has an unknown variable. `${team_slug}` and
`${project_type_slug}` are accepted, but the Logz.io plugin always
replaces them with an empty string.

## Filters

The **Logs** tab sends filters. The plugin changes them to Elasticsearch
queries:

| Operator | Query |
|---|---|
| `eq` | `term` |
| `ne` | `term` in `bool.must_not` |
| `contains` | `match_phrase` on the message field. On other fields, a `wildcard` with a trailing `*` |
| `starts_with` | `prefix` |
| `regex` | `regexp` |

## Doctor checks

None.

## Webhook actions

None.

## Lifecycle

None.

## Known limits

- One search returns 1000 entries at most.
- A `contains` filter on a field that is not the message field cannot
  start with `*` or `?`. A `regex` filter cannot start with `.*`, `*`, or
  `?`. Logz.io does not allow leading wildcards.
- The field list that the **Logs** tab offers is fixed: `@timestamp`,
  `message`, `level`, `type`, `host`, `service`, `env`, and `tags`. The
  plugin reads the log types of the account to fill the choices of the
  `type` field. It does not use the `*_field` options for this list.
