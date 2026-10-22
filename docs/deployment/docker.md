# Docker Deployment

The Imbi Docker image packages all services into a single container that
can run everything together or individual services for scaled-out
deployments. To try Imbi on one host, use the Compose file in
[Installation](../getting-started/installation.md#docker-compose).

Use image 2.39.1 or later. On a new install, 2.39.0 cannot create its Iggy
topics, and imbi-api exits at startup (see
[issue #469](https://github.com/AWeber-Imbi/imbi/issues/469)).

The examples on this page reach PostgreSQL, ClickHouse, Iggy, and Valkey by
container name. Docker resolves container names only on a user-defined
network, so run the dependencies and the Imbi containers on the same one
(`docker network create <network>`), and replace `<network>` in the
examples with its name. The credentials in the examples are placeholders.
Use the credentials of your own services.

## All-in-One Mode

By default, the container starts all services behind a Caddy reverse proxy:

```bash
docker run -p 8080:8080 --network <network> \
  -e ENVIRONMENT=production \
  -e IMBI_API_URL=https://imbi.example.com/api \
  -e VITE_API_URL=https://imbi.example.com/api \
  -e CLICKHOUSE_URL=clickhouse+http://default:password@clickhouse:8123/imbi \
  -e IGGY_URL=iggy+tcp://iggy:iggy@iggy:8090 \
  -e POSTGRES_URL=postgresql://user:pass@postgres/imbi \
  -e VALKEY_URL=valkey://valkey:6379/0 \
  -e S3_ENDPOINT_URL=https://s3.example.com \
  -e S3_ACCESS_KEY=your-access-key \
  -e S3_SECRET_KEY=your-secret-key \
  -e IMBI_EMAIL_SMTP_HOST=smtp.example.com \
  -e IMBI_IGGY_CONNECTORS_API_KEYS=your-connectors-key \
  -e IMBI_AUTH_JWT_SECRET=your-secret \
  -e IMBI_AUTH_ENCRYPTION_KEY=your-fernet-key \
  -e IMBI_CONFIG_ENCRYPTION_KEY=your-other-fernet-key \
  ghcr.io/aweber-imbi/imbi:latest
```

- `IMBI_API_URL` is the public URL of the API. imbi-api mounts its routes
  under its path. Caddy sends `/api/*` to imbi-api and keeps the prefix, so
  the path must be `/api`. Without it, every API call through Caddy gets a
  404.
- `VITE_API_URL` is the same URL for the UI. Without it, the UI does not
  load.
- `ENVIRONMENT=production` makes Imbi refuse to start without the three
  keys. When `ENVIRONMENT` is unset, each process generates the keys that
  are not set, and the services cannot decrypt each other's values.
- Without `VALKEY_URL`, imbi-api does not start its background workers.
- imbi-api connects to S3-compatible storage (`S3_*`) and to the SMTP
  server (`IMBI_EMAIL_*`) at startup. Leave `S3_ENDPOINT_URL` unset to use
  AWS S3. To turn off email, set `IMBI_EMAIL_ENABLED=false`. See
  [Installation](../getting-started/installation.md#prerequisites).
- `IMBI_IGGY_CONNECTORS_API_KEYS` must have the same value as
  `IGGY_CONNECTORS_API_KEY` on the connectors runtime. See
  [The Iggy connectors runtime](#the-iggy-connectors-runtime).

This starts:

| Port | Service                                                                                                                  |
| ---- | ------------------------------------------------------------------------------------------------------------------------ |
| 8080 | Caddy (public, routes to all services)                                                                                   |
| 8000 | imbi-api (internal)                                                                                                      |
| 8001 | imbi-mcp (internal)                                                                                                      |
| 8002 | imbi-assistant (internal)                                                                                                |
| 8003 | imbi-gateway (internal)                                                                                                  |
| 8005 | imbi-scheduler (internal, started only when the internal service accounts are seeded; the entrypoint makes the credentials when they are unset) |
| 8004 | imbi-slackbot (internal, started only when the Slack tokens and `ANTHROPIC_API_KEY` are set)                             |
| 8006 | imbi-workflows (internal, started with imbi-scheduler, only when the internal service accounts are seeded)                 |

Caddy serves imbi-scheduler under `/scheduler`, stripping that prefix before
the request reaches it — so `/scheduler/api/tasks` hits `/api/tasks` on the
service and `/scheduler/status` reaches its unprefixed health endpoint.

### Routes

Caddy sends each path on port 8080 to a service:

| Path | Service | Notes |
|---|---|---|
| `/api/*` | imbi-api | Caddy keeps the `/api` prefix |
| `/status` | imbi-api | Used only when `IMBI_API_URL` has no path |
| `/docs`, `/openapi.json`, `/uploads/*` | imbi-api | |
| `/.well-known/oauth-authorization-server*` | imbi-api | Also under `/mcp/.well-known/...` |
| `/assistant/status`, `/mcp/status` | imbi-assistant, imbi-mcp | Caddy removes the prefix, so these reach the unprefixed health endpoints |
| `/assistant/*` | imbi-assistant | |
| `/gateway/*` | imbi-gateway | Caddy removes the `/gateway` prefix |
| `/scheduler/*` | imbi-scheduler | Caddy removes the `/scheduler` prefix |
| `/mcp`, `/mcp/*` | imbi-mcp | |
| `/.well-known/oauth-protected-resource*` | imbi-mcp | |
| `/gateway/metrics*`, `/scheduler/metrics*` | none | Caddy answers 404, so the metrics are not public |
| `*.map` | UI files | Caddy answers 404 unless `SERVE_SOURCE_MAPS` is `true` |
| Other paths | UI files | Unknown paths get `index.html` |

Caddy does not route to imbi-slackbot or imbi-workflows. The Caddy admin
API listens on `localhost:2019` in the container only.

## Individual Services

For production deployments where you want to scale services independently,
set `IMBI_SERVICE` to one of `api`, `assistant`, `gateway`, `mcp`,
`scheduler`, `slackbot`, `workflows`, or `ui`:

The entrypoint refuses to start a service when a variable that it needs is
not set:

| `IMBI_SERVICE` | Required variables |
|---|---|
| `all` | `IMBI_AUTH_JWT_SECRET`, `POSTGRES_URL`, `CLICKHOUSE_URL`, `IGGY_URL`, `IMBI_AUTH_ENCRYPTION_KEY` |
| `api` | `IMBI_AUTH_JWT_SECRET`, `IMBI_AUTH_ENCRYPTION_KEY`, `CLICKHOUSE_URL`, `IGGY_URL` |
| `assistant` | `IMBI_AUTH_JWT_SECRET` |
| `gateway` | `POSTGRES_URL`, `CLICKHOUSE_URL`, `IGGY_URL`, `IMBI_AUTH_ENCRYPTION_KEY`, `IMBI_GATEWAY_API_TOKEN` |
| `mcp`, `ui` | none |
| `scheduler` | `IMBI_AUTH_JWT_SECRET`, `POSTGRES_URL`, `CLICKHOUSE_URL`, `IGGY_URL`, `IMBI_SCHEDULER_SA_CLIENT_ID`, `IMBI_SCHEDULER_SA_CLIENT_SECRET`, `IMBI_API_URL`, `IMBI_INTERNAL_API_URL` |
| `workflows` | `IMBI_AUTH_JWT_SECRET`, `IMBI_AUTH_ENCRYPTION_KEY`, `POSTGRES_URL`, `IMBI_WORKFLOWS_SA_CLIENT_ID`, `IMBI_WORKFLOWS_SA_CLIENT_SECRET`, `IMBI_API_URL`, `IMBI_INTERNAL_API_URL` |
| `slackbot` | `IMBI_AUTH_JWT_SECRET`, `SLACK_APP_TOKEN`, `SLACK_BOT_TOKEN`, `ANTHROPIC_API_KEY`, `POSTGRES_URL` |

This check is not complete. For example, imbi-api in `api` mode starts
without `POSTGRES_URL`, and then connects to PostgreSQL on `localhost`. Set
the connection URLs on every service.

The gateway calls imbi-api with `IMBI_GATEWAY_API_TOKEN`. In `all`
mode, the container makes this token and the scheduler and workflows
credentials when they are not set. For each of the two client credential
pairs, set both variables or neither.

```bash
# Run only the API
docker run -p 8000:8000 --network <network> \
  -e IMBI_SERVICE=api \
  -e ENVIRONMENT=production \
  -e IMBI_API_URL=https://imbi.example.com/api \
  -e POSTGRES_URL=postgresql://user:pass@postgres/imbi \
  -e CLICKHOUSE_URL=clickhouse+http://default:password@clickhouse:8123/imbi \
  -e IGGY_URL=iggy+tcp://iggy:iggy@iggy:8090 \
  -e S3_ENDPOINT_URL=https://s3.example.com \
  -e S3_ACCESS_KEY=your-access-key \
  -e S3_SECRET_KEY=your-secret-key \
  -e IMBI_EMAIL_SMTP_HOST=smtp.example.com \
  -e IMBI_AUTH_JWT_SECRET=your-secret \
  -e IMBI_AUTH_ENCRYPTION_KEY=your-fernet-key \
  -e IMBI_CONFIG_ENCRYPTION_KEY=your-other-fernet-key \
  ghcr.io/aweber-imbi/imbi:latest
```

Give every service the same `ENVIRONMENT` and the same keys. A service that
generates its own key cannot decrypt the values that another service
encrypted.

When running individual services, Caddy is not started. Either provide your
own reverse proxy, or run `IMBI_SERVICE=ui`: the bundled Caddy alone, serving
the UI on `:8080` and proxying to the other containers. Each upstream defaults
to the in-pod loopback, so point them at the containers by name:

```bash
docker run -p 8080:8080 --network <network> \
  -e IMBI_SERVICE=ui \
  -e VITE_API_URL=http://localhost:8080/api \
  -e IMBI_API_UPSTREAM=imbi-api:8000 \
  -e IMBI_MCP_UPSTREAM=imbi-mcp:8001 \
  -e IMBI_ASSISTANT_UPSTREAM=imbi-assistant:8002 \
  -e IMBI_GATEWAY_UPSTREAM=imbi-gateway:8003 \
  -e IMBI_SCHEDULER_UPSTREAM=imbi-scheduler:8005 \
  ghcr.io/aweber-imbi/imbi:latest
```

Running the scheduler on its own needs the service-account credentials and
both API URLs; the entrypoint refuses to start without them:

```bash
docker run -p 8005:8005 --network <network> \
  -e IMBI_SERVICE=scheduler \
  -e ENVIRONMENT=production \
  -e CLICKHOUSE_URL=clickhouse+http://default:password@clickhouse:8123/imbi \
  -e IGGY_URL=iggy+tcp://iggy:iggy@iggy:8090 \
  -e POSTGRES_URL=postgresql://user:pass@postgres/imbi \
  -e IMBI_AUTH_JWT_SECRET=your-secret \
  -e IMBI_AUTH_ENCRYPTION_KEY=your-fernet-key \
  -e IMBI_CONFIG_ENCRYPTION_KEY=your-other-fernet-key \
  -e IMBI_SCHEDULER_SA_CLIENT_ID=... \
  -e IMBI_SCHEDULER_SA_CLIENT_SECRET=... \
  -e IMBI_INTERNAL_API_URL=http://imbi-api:8000 \
  -e IMBI_API_URL=https://imbi.example.com/api \
  ghcr.io/aweber-imbi/imbi:latest
```

If the reverse proxy in front of it passes `/scheduler` through instead of
stripping it, set `IMBI_SCHEDULER_API_PREFIX=/scheduler/api`. More than one
replica is safe — see
[Scheduler configuration](../scheduler/configuration.md).

Running the workflow engine on its own needs its service-account
credentials and both API URLs too. The entrypoint refuses to start without
them:

```bash
docker run -p 8006:8006 --network <network> \
  -e IMBI_SERVICE=workflows \
  -e ENVIRONMENT=production \
  -e CLICKHOUSE_URL=clickhouse+http://default:password@clickhouse:8123/imbi \
  -e IGGY_URL=iggy+tcp://iggy:iggy@iggy:8090 \
  -e POSTGRES_URL=postgresql://user:pass@postgres/imbi \
  -e IMBI_AUTH_JWT_SECRET=your-secret \
  -e IMBI_AUTH_ENCRYPTION_KEY=your-fernet-key \
  -e IMBI_CONFIG_ENCRYPTION_KEY=your-other-fernet-key \
  -e IMBI_WORKFLOWS_SA_CLIENT_ID=... \
  -e IMBI_WORKFLOWS_SA_CLIENT_SECRET=... \
  -e IMBI_INTERNAL_API_URL=http://imbi-api:8000 \
  -e IMBI_API_URL=https://imbi.example.com/api \
  -e IMBI_WORKFLOWS_SCHEDULER_URL=http://imbi-scheduler:8005/api \
  ghcr.io/aweber-imbi/imbi:latest
```

`IMBI_WORKFLOWS_SCHEDULER_URL` is imbi-scheduler's task API, with its route
prefix. Its default, `http://localhost:8005/api`, works in all-in-one mode
only. Caddy does not route to imbi-workflows.

To show imbi-workflows in the admin System health card, set
`IMBI_INTERNAL_WORKFLOWS_URL` on imbi-api, for example
`http://imbi-workflows:8006`. It works like the other `IMBI_INTERNAL_*_URL`
settings. Empty shows the service as "not configured".

## The Iggy connectors runtime

The ClickHouse write path runs through Apache Iggy, and it is the connectors
runtime that drains each stream into its table (see ADR 0019, Apache
Iggy message streaming). It runs from
the Iggy image, not the Imbi one, and carries no sink configuration of its
own: it fetches that from imbi-api once at startup and never re-reads it.

Because that response carries the ClickHouse credentials, imbi-api serves it
only to a caller presenting a key from `IMBI_IGGY_CONNECTORS_API_KEYS`
(comma-separated, so a rotation can overlap). Unset, imbi-api answers 503 and
the runtime exits — there is no open default.

```bash
docker run --network <network> \
  --restart on-failure \
  -e IGGY_MODE=connectors \
  -e IGGY_CONNECTORS_CONNECTORS_BASE_URL=http://imbi-api:8000/api/iggy/connectors \
  -e IGGY_CONNECTORS_API_KEY=the-same-key \
  -e IGGY_CONNECTORS_IGGY_ADDRESS=iggy:8090 \
  -e IGGY_CONNECTORS_IGGY_USERNAME=iggy \
  -e IGGY_CONNECTORS_IGGY_PASSWORD=iggy \
  ghcr.io/aweber-imbi/iggy:0.9.0-edge.6-0
```

The base URL carries whatever path imbi-api mounts its routes under, which is
the path component of `IMBI_API_URL`. Point it at imbi-api's own port rather
than at Caddy in all-in-one mode.

Restart the runtime after a release that adds a stream; that fetch is what
picks it up. It also exits when imbi-api is not answering yet or when a stream
it is configured for does not exist, so run it with `--restart on-failure`:
Imbi provisions every stream as it starts, and coming back is the recovery for
both.

## Running Setup

The `setup` command creates the organization and the first admin user, and
seeds permissions, roles, the internal service accounts, the default
prompts, and the ClickHouse schema. It asks for input. See
[Initial Setup](../getting-started/setup.md).

```bash
docker run -it --network <network> \
  -e POSTGRES_URL=postgresql://user:pass@postgres/imbi \
  -e CLICKHOUSE_URL=clickhouse+http://default:password@clickhouse:8123/imbi \
  -e IGGY_URL=iggy+tcp://iggy:iggy@iggy:8090 \
  -e IMBI_AUTH_JWT_SECRET=your-secret \
  -e IMBI_AUTH_ENCRYPTION_KEY=your-fernet-key \
  ghcr.io/aweber-imbi/imbi:latest setup
```

## Custom Caddyfile

To customize the reverse proxy configuration, mount your own Caddyfile:

```bash
docker run -p 8080:8080 \
  -v /path/to/Caddyfile:/etc/caddy/Caddyfile:ro \
  ...
  ghcr.io/aweber-imbi/imbi:latest
```

## UI Static Files

The UI static files are served by Caddy from `/srv/ui`. To use a custom
build of the UI, mount it as a volume:

```bash
docker run -p 8080:8080 \
  -v /path/to/ui/dist:/srv/ui:ro \
  ...
  ghcr.io/aweber-imbi/imbi:latest
```

## Images

The release workflow publishes the image to GitHub Container Registry
(`ghcr.io/aweber-imbi/imbi`) and to Docker Hub (`aweber/imbi`). Each release
has a `<version>` tag. `latest` is the highest release. Use a version tag in
production.

This repository does not build the Iggy image
(`ghcr.io/aweber-imbi/iggy`) or the PostgreSQL image
(`ghcr.io/aweber-imbi/postgres`) that the examples use.

## Sentry

Set `SENTRY_DSN` to send errors to Sentry, and `VITE_SENTRY_DSN` for the
UI. To upload the UI source maps when the container starts, set
`SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, and `SENTRY_PROJECT` in `all` or `ui`
mode. See [Operations: Sentry](operations.md#sentry).

## Upgrading

Change the image tag, then do the steps in [Upgrading](upgrading.md). With
Docker Compose, run the setup commands with
`docker compose exec imbi imbi-api <command>`.
