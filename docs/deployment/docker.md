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

## Individual Services

For production deployments where you want to scale services independently,
set `IMBI_SERVICE` to one of `api`, `assistant`, `gateway`, `mcp`,
`scheduler`, `slackbot`, `workflows`, or `ui`:

```bash
# Run only the API
docker run -p 8000:8000 --network <network> \
  -e IMBI_SERVICE=api \
  -e ENVIRONMENT=production \
  -e IMBI_API_URL=https://imbi.example.com/api \
  -e POSTGRES_URL=postgresql://user:pass@postgres/imbi \
  -e CLICKHOUSE_URL=clickhouse+http://default:password@clickhouse:8123/imbi \
  -e IGGY_URL=iggy+tcp://iggy:iggy@iggy:8090 \
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
docker run -p 8080:8080 \
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
docker run -p 8005:8005 \
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
docker run -p 8006:8006 \
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
docker run \
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

From 2.39.1, setup creates the PostgreSQL schema itself. With 2.39.0, run
`imbi-api setup-postgres` first on a new database.

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
