# Docker Deployment

The Imbi Docker image packages all services into a single container that
can run everything together or individual services for scaled-out
deployments.

## All-in-One Mode

By default, the container starts all services behind a Caddy reverse proxy:

```bash
docker run -p 8080:8080 \
  -e CLICKHOUSE_URL=clickhouse+http://default:password@clickhouse:8123/imbi \
  -e IGGY_URL=iggy+tcp://iggy:iggy@iggy:8090 \
  -e POSTGRES_URL=postgresql://user:pass@postgres/imbi \
  -e IMBI_AUTH_JWT_SECRET=your-secret \
  -e IMBI_AUTH_ENCRYPTION_KEY=your-key \
  ghcr.io/aweber-imbi/imbi:latest
```

This starts:

| Port | Service                                                                                                                  |
| ---- | ------------------------------------------------------------------------------------------------------------------------ |
| 8080 | Caddy (public, routes to all services)                                                                                   |
| 8000 | imbi-api (internal)                                                                                                      |
| 8001 | imbi-mcp (internal)                                                                                                      |
| 8002 | imbi-assistant (internal)                                                                                                |
| 8003 | imbi-gateway (internal)                                                                                                  |
| 8005 | imbi-scheduler (internal, started only when `IMBI_SCHEDULER_SA_CLIENT_ID` and `IMBI_SCHEDULER_SA_CLIENT_SECRET` are set) |
| 8004 | imbi-slackbot (internal, started only when the Slack tokens and `ANTHROPIC_API_KEY` are set)                             |

Caddy serves imbi-scheduler under `/scheduler`, stripping that prefix before
the request reaches it — so `/scheduler/api/tasks` hits `/api/tasks` on the
service and `/scheduler/status` reaches its unprefixed health endpoint.

## Individual Services

For production deployments where you want to scale services independently,
set `IMBI_SERVICE` to one of `api`, `assistant`, `gateway`, `mcp`,
`scheduler`, or `slackbot`:

```bash
# Run only the API
docker run -p 8000:8000 \
  -e IMBI_SERVICE=api \
  -e CLICKHOUSE_URL=clickhouse+http://default:password@clickhouse:8123/imbi \
  -e IGGY_URL=iggy+tcp://iggy:iggy@iggy:8090 \
  -e IMBI_AUTH_JWT_SECRET=your-secret \
  -e IMBI_AUTH_ENCRYPTION_KEY=your-key \
  ghcr.io/aweber-imbi/imbi:latest
```

When running individual services, Caddy is not started. You are
responsible for providing your own reverse proxy or load balancer.

Running the scheduler on its own needs the service-account credentials and
both API URLs; the entrypoint refuses to start without them:

```bash
docker run -p 8005:8005 \
  -e IMBI_SERVICE=scheduler \
  -e CLICKHOUSE_URL=clickhouse+http://default:password@clickhouse:8123/imbi \
  -e IGGY_URL=iggy+tcp://iggy:iggy@iggy:8090 \
  -e POSTGRES_URL=postgresql://user:pass@postgres/imbi \
  -e IMBI_AUTH_JWT_SECRET=your-secret \
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

The `setup` command initializes the authentication system:

```bash
docker run -it \
  -e CLICKHOUSE_URL=clickhouse+http://default:password@clickhouse:8123/imbi \
  -e IMBI_AUTH_JWT_SECRET=your-secret \
  -e IMBI_AUTH_ENCRYPTION_KEY=your-key \
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
