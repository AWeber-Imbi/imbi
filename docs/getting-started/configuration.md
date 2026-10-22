# Configuration

Imbi is configured with environment variables. This page lists the minimum
set that starts each service. For every variable, its default, and the
`config.toml` rules, see the [configuration reference](../api/configuration.md).

## Select the service

The container image runs the service that `IMBI_SERVICE` names:

| `IMBI_SERVICE` | Runs |
|---|---|
| `all` (default) | Every service and the Caddy proxy in one container, on port 8080 |
| `api`, `assistant`, `gateway`, `mcp`, `scheduler`, `slackbot`, `workflows` | One service |
| `ui` | Caddy only: the UI and the proxy in front of the other services |

The entrypoint checks some of the variables below before it starts the
service. It stops with a list of the missing ones. The rows marked
"not checked" are not in that check, but the service fails or works wrong
without them.

## Production keys

Set these in every service in production:

| Variable | Value |
|---|---|
| `ENVIRONMENT` | `production` |
| `IMBI_AUTH_JWT_SECRET` | A random string, at least 32 characters |
| `IMBI_AUTH_ENCRYPTION_KEY` | A Fernet key |
| `IMBI_CONFIG_ENCRYPTION_KEY` | A different Fernet key |

When `ENVIRONMENT` is not `development`, a service does not start without the
three keys. In development, a service generates any key that is not set.
A generated key changes at each restart, so tokens and encrypted values stop
working. Use the same values in every service and replica. See
[`ENVIRONMENT` and production](../api/configuration.md#environment-and-production).

`IMBI_ENVIRONMENT` is not read by any code. Use `ENVIRONMENT`.

## Minimum per service

### `all`

| Variable | Example | Checked |
|---|---|---|
| `IMBI_AUTH_JWT_SECRET` | | yes |
| `IMBI_AUTH_ENCRYPTION_KEY` | | yes |
| `POSTGRES_URL` | `postgresql://imbi:secret@postgres:5432/imbi` | yes |
| `CLICKHOUSE_URL` | `clickhouse+http://default:password@clickhouse:8123/imbi` | yes |
| `IGGY_URL` | `iggy+tcp://iggy:iggy@iggy:8090` | yes |
| `IMBI_API_URL` | `https://imbi.example.com/api` | not checked |
| `VITE_API_URL` | The same value as `IMBI_API_URL` | not checked. The UI does not load without it |

The `all` mode makes the credentials of the internal service accounts
(`IMBI_SCHEDULER_SA_*`, `IMBI_WORKFLOWS_SA_*`, `IMBI_GATEWAY_API_TOKEN`) when
they are not set. Run `imbi-api setup` once before the first start.

### `api`

| Variable | Checked |
|---|---|
| `IMBI_AUTH_JWT_SECRET` | yes |
| `IMBI_AUTH_ENCRYPTION_KEY` | yes |
| `CLICKHOUSE_URL` | yes |
| `IGGY_URL` | yes |
| `POSTGRES_URL` | not checked. The default is `localhost:5432` |
| `IMBI_API_URL` | not checked. Without it, routes mount with no path prefix |

### `assistant`

| Variable | Checked |
|---|---|
| `IMBI_AUTH_JWT_SECRET` | yes |
| `POSTGRES_URL` | not checked |
| `IMBI_INTERNAL_API_URL` | not checked. In-cluster origin of imbi-api |
| `ANTHROPIC_API_KEY` | not checked. The assistant is off without it, unless `IMBI_ASSISTANT_ENABLED=true` |

### `gateway`

| Variable | Checked |
|---|---|
| `POSTGRES_URL` | yes |
| `CLICKHOUSE_URL` | not checked. The gateway does not start without ClickHouse |
| `IGGY_URL` | not checked. The gateway does not start without Iggy |
| `IMBI_GATEWAY_API_TOKEN` | not checked. Required: the API key of the `imbi-gateway` service account |
| `IMBI_INTERNAL_API_URL` | not checked |
| `IMBI_API_URL` | not checked. The gateway adds its path to `IMBI_INTERNAL_API_URL` |

### `mcp`

| Variable | Checked |
|---|---|
| `IMBI_INTERNAL_API_URL` | not checked |

To let MCP clients sign in with OAuth, also set `IMBI_MCP_PUBLIC_URL` and
`IMBI_MCP_AUTH_SERVER_URL`.

### `scheduler`

| Variable | Checked |
|---|---|
| `IMBI_AUTH_JWT_SECRET` | yes |
| `POSTGRES_URL` | yes |
| `CLICKHOUSE_URL` | yes |
| `IGGY_URL` | yes |
| `IMBI_SCHEDULER_SA_CLIENT_ID` | yes |
| `IMBI_SCHEDULER_SA_CLIENT_SECRET` | yes |
| `IMBI_API_URL` | yes |
| `IMBI_INTERNAL_API_URL` | yes |

See [Scheduler configuration](../scheduler/configuration.md).

### `workflows`

| Variable | Checked |
|---|---|
| `IMBI_AUTH_JWT_SECRET` | yes |
| `IMBI_AUTH_ENCRYPTION_KEY` | yes |
| `POSTGRES_URL` | yes |
| `IMBI_WORKFLOWS_SA_CLIENT_ID` | yes |
| `IMBI_WORKFLOWS_SA_CLIENT_SECRET` | yes |
| `IMBI_API_URL` | yes |
| `IMBI_INTERNAL_API_URL` | yes |
| `IGGY_URL` | not checked. Without Iggy, imbi-api publishes the run history later |

### `slackbot`

| Variable | Checked |
|---|---|
| `SLACK_APP_TOKEN` | yes |
| `SLACK_BOT_TOKEN` | yes |
| `ANTHROPIC_API_KEY` | yes |
| `POSTGRES_URL` | yes |
| `IMBI_INTERNAL_API_URL` | not checked |

### `ui`

| Variable | Checked |
|---|---|
| `VITE_API_URL` | not checked. The UI does not load without it |
| `IMBI_API_UPSTREAM`, `IMBI_ASSISTANT_UPSTREAM`, `IMBI_GATEWAY_UPSTREAM`, `IMBI_MCP_UPSTREAM`, `IMBI_SCHEDULER_UPSTREAM` | not checked. `host:port` of each service. The defaults are the loopback ports of the `all` mode |

## Service accounts

`imbi-api setup` creates the service accounts of imbi-scheduler,
imbi-gateway, and imbi-workflows. If you set `IMBI_SCHEDULER_SA_*`,
`IMBI_WORKFLOWS_SA_*`, and `IMBI_GATEWAY_API_TOKEN` before you run it, it
stores those values. If not, it generates them and prints them once. Copy
them into the environment of each service.

## Next

- [Configuration reference](../api/configuration.md): every variable.
- [Authentication](../admin/authentication.md): sign-in providers are set in
  the database, not with environment variables.
