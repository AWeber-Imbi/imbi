# Services

## Port Assignments

When running in all-in-one mode, services bind to the following internal
ports:

| Service | Port | Protocol |
|---------|------|----------|
| Caddy (public) | 8080 | HTTP |
| imbi-api | 8000 | HTTP |
| imbi-mcp | 8001 | HTTP (streamable-http) |
| imbi-assistant | 8002 | HTTP |
| imbi-gateway | 8003 | HTTP |
| imbi-slackbot | 8004 | HTTP |
| imbi-scheduler | 8005 | HTTP |

## URL Routing

Caddy routes requests to backend services based on path prefix:

| Path | Service | Prefix |
|------|---------|--------|
| `/api/*` | imbi-api | preserved |
| `/status` | imbi-api | preserved |
| `/assistant/*` | imbi-assistant | preserved |
| `/mcp/*` | imbi-mcp | preserved |
| `/gateway/*` | imbi-gateway | stripped |
| `/scheduler/*` | imbi-scheduler | stripped |
| `/*` | Static UI files | — |

Whether the prefix survives is per-service, and it has to match how that
service mounts its routes:

- **Preserved** (`handle`) for imbi-api, imbi-assistant, and imbi-mcp. Each
  mounts its routers under the path component of its own public URL
  (`IMBI_API_URL`, `IMBI_ASSISTANT_URL`), so it expects to see the prefix. The
  OAuth and MCP discovery documents need their full paths for the same reason.
- **Stripped** (`handle_path`) for imbi-gateway, which mounts at the root, and
  imbi-scheduler, which mounts under its own `IMBI_SCHEDULER_API_PREFIX`
  (default `/api`) — so a caller reaches `/scheduler/api/tasks`.

`/status` is routed separately from `/api/*` rather than being covered by it,
because imbi-api serves its status route under the path of `IMBI_API_URL`: with
that unset — the chart default — the route *is* `/status`, which `/api/*` would
never match. Without this route it fell through to the static UI, which answers
200 from `index.html` whatever imbi-api is doing, so the chart's liveness and
readiness probes passed against a dead API.

imbi-slackbot has no route: it connects out to Slack over socket mode and its
port exists only for its health check.

## Health Checks

Each service exposes a health check endpoint:

| Service | Endpoint | Reached at |
|---------|----------|------------|
| imbi-api | `GET /status` | Under its prefix, e.g. `/api/status` |
| imbi-assistant | `GET /status` | Under its prefix, e.g. `/assistant/status` |
| imbi-gateway | `GET /status` | `/gateway/status` |
| imbi-scheduler | `GET /status` | `/scheduler/status` |
| imbi-slackbot | `GET /status` | On the pod only |

imbi-api and imbi-assistant prefix their status route along with everything
else, so the path a probe requests depends on their configured public URL.
imbi-scheduler and imbi-slackbot deliberately leave it unprefixed: a health
check should not move when the API is relocated.

## Scaling

In all-in-one mode, all services run as processes within a single
container. For production deployments, set `IMBI_SERVICE` to run services
individually and scale them independently behind a load balancer.

### Scaling Recommendations

| Service | Scaling Strategy |
|---------|-----------------|
| imbi-api | Horizontal - stateless, scale based on request volume |
| imbi-assistant | Horizontal - stateless, scale based on concurrent conversations |
| imbi-gateway | Horizontal - stateless, scale based on webhook volume |
| imbi-mcp | Horizontal - stateless, scale based on agent connections |
| imbi-scheduler | Horizontal - firings are claimed with `FOR UPDATE SKIP LOCKED`, so replicas take disjoint claims and only one claims a given occurrence |
| imbi-slackbot | Horizontal - socket mode gives each replica its own connection, and Slack delivers an event to one of them |
