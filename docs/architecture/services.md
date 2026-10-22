# Services

This page gives the ports, routes, health checks, and scaling rules of each
service. For what each service does, see the
[overview](overview.md#services).

## Port assignments

Each service uses the same port in every topology. In `all` mode the
services bind these ports inside one container, and only Caddy is
published.

| Process | Port | Protocol | Notes |
|---|---|---|---|
| Caddy | 8080 | HTTP | The public port |
| Caddy admin API | 2019 | HTTP | Bound to `localhost` only |
| imbi-api | 8000 | HTTP | Also serves `/metrics` |
| imbi-mcp | 8001 | HTTP (streamable HTTP) | |
| imbi-assistant | 8002 | HTTP | |
| imbi-gateway | 8003 | HTTP | Also serves `/metrics` |
| imbi-slackbot | 8004 | HTTP | Health check only |
| imbi-scheduler | 8005 | HTTP | Also serves `/metrics` |
| imbi-workflows | 8006 | HTTP | Health check only |
| Apache Iggy | 8090 | TCP | The services connect here (`IGGY_URL`) |
| Apache Iggy | 3000 | HTTP | The Iggy HTTP API |
| iggy-connect | 8081 | HTTP | The connectors runtime API and its `/metrics` |

Iggy and iggy-connect are separate containers. The Iggy ports are the ones
that `compose.yaml` sets.

## URL routing

Caddy sends each request to a service by its path. It checks the routes
in this order, so a more specific route comes before a general one:

| Path | Goes to | Prefix |
|---|---|---|
| `/api/*` | imbi-api | kept |
| `/status` | imbi-api | kept |
| `/assistant/*` | imbi-assistant | kept |
| `/docs`, `/docs/*` | imbi-api (API reference page) | kept |
| `/gateway/metrics*` | none: 404 | |
| `/scheduler/metrics*` | none: 404 | |
| `/gateway/*` | imbi-gateway | removed |
| `/scheduler/*` | imbi-scheduler | removed |
| `/mcp/.well-known/oauth-authorization-server*` | imbi-api | `/mcp` removed |
| `/mcp`, `/mcp/*` | imbi-mcp | kept |
| `/.well-known/oauth-protected-resource*` | imbi-mcp | kept |
| `/.well-known/oauth-authorization-server*` | imbi-api | kept |
| `/openapi.json` | imbi-api | kept |
| `/uploads/*` | imbi-api | kept |
| `*.map` | UI source maps, only when `SERVE_SOURCE_MAPS` is `true`. Otherwise 404 | |
| everything else | UI static files, with `index.html` as the fallback | |

Caddy does not cache `/index.html` and `/version.json`. It fills in
`index.html` as a template at serve time, which is how `VITE_API_URL`
gets to the UI.

The prefix rule of each service must match how the service mounts its
routes:

- **Kept** for imbi-api, imbi-assistant, and imbi-mcp. imbi-api and
  imbi-assistant mount their routes under the path of their public URL
  (`IMBI_API_URL`, `IMBI_ASSISTANT_URL`), so they expect the prefix. The
  OAuth and MCP discovery documents need their full paths for the same
  reason.
- **Removed** for imbi-gateway, which mounts at the root, and for
  imbi-scheduler, which mounts under its own `IMBI_SCHEDULER_API_PREFIX`
  (default `/api`). Thus a caller gets to the scheduler API at
  `/scheduler/api/tasks`.

MCP clients look for the authorization server metadata under the MCP
resource URL, at `/mcp/.well-known/oauth-authorization-server`. imbi-api
serves that document at the root, so Caddy removes `/mcp` for this one
path.

`/status` has its own route because imbi-api serves its status route under
the path of `IMBI_API_URL`. When `IMBI_API_URL` has no path (the chart
default), the route is `/status`, which `/api/*` does not match. Without
the `/status` route, the request goes to the UI, which returns 200 from
`index.html` when imbi-api is down. The liveness and readiness probes then
pass for a dead API.

imbi-slackbot and imbi-workflows have no route. imbi-slackbot connects
out to Slack in socket mode. imbi-workflows takes runs from Postgres and
calls imbi-api and imbi-scheduler. The port of each exists only for its
health check.

Caddy trusts `X-Forwarded-*` headers from private address ranges. Thus a
load balancer in front of Caddy can pass the original scheme and host to
the services. imbi-api uses them to make the URLs in its OAuth and MCP
discovery documents.

## Health checks

Each service serves `GET /status`:

| Service | Path on the service | Through Caddy |
|---|---|---|
| imbi-api | `/status` under the path of `IMBI_API_URL`, for example `/api/status` | `/api/status`, or `/status` when `IMBI_API_URL` has no path |
| imbi-assistant | `/status` (no prefix) | `/assistant/status` |
| imbi-gateway | `/status` | `/gateway/status` |
| imbi-mcp | `/status` | `/mcp/status` |
| imbi-scheduler | `/status` (no prefix) | `/scheduler/status` |
| imbi-slackbot | `/status` | No route |
| imbi-workflows | `/status` | No route |
| iggy-connect | none | No route. Use a TCP check on port 8081 |

The Helm chart uses these probes for each `service.mode`:

| `service.mode` | Probe |
|---|---|
| `all`, `api`, `ui` | HTTP GET on the imbi-api status path, through the container port |
| `scheduler`, `slackbot`, `workflows` | HTTP GET `/status` |
| `assistant`, `gateway`, `mcp` | TCP connect on the container port |

In `ui` mode the probe goes through Caddy to imbi-api. Thus a `ui` pod is
not ready when imbi-api is down.

## Scaling

In `all` mode, every service runs as a process in one container. For
production, set `IMBI_SERVICE` to run one service in each container.
Then scale each one by itself, behind a Caddy container in `ui` mode.

| Service | How it scales |
|---|---|
| imbi-api | Horizontal. The background workers read Valkey streams in consumer groups, so replicas share the work. The daily scoring tick takes a Valkey lock. The runner lease sweep uses row locks, so two replicas can run it at the same time |
| imbi-assistant | Horizontal. Conversations are in the graph, not in the process |
| imbi-gateway | Horizontal. Each delivery is one request |
| imbi-mcp | Not verified. FastMCP keeps streamable HTTP sessions in process memory unless it runs in stateless mode, and imbi-mcp does not set stateless mode. Use one replica, or session affinity, until this is verified |
| imbi-scheduler | Horizontal. Firings are claimed with `FOR UPDATE SKIP LOCKED`, so replicas take different tasks, and only one replica claims an occurrence |
| imbi-slackbot | Horizontal. Socket mode gives each replica its own connection, and Slack sends an event to one of them |
| imbi-workflows | Horizontal. Runs are claimed with `FOR UPDATE SKIP LOCKED` and a lease, so replicas take different runs |
| Caddy (`ui`) | Horizontal. It holds no state |
| iggy-connect | One replica (the chart default). Each topic has one partition, and in a consumer group one member reads a partition. It reads its configuration only at startup. See [Events and analytics](events.md#restart-rule-for-new-topics) |

## imbi-harness

imbi-harness is the agent runner. It is not in the all-in-one image, and
it has no `IMBI_SERVICE` mode. It has its own image
(`ghcr.io/aweber-imbi/imbi-harness`) and its own Helm chart
(`helm/imbi-harness`). One chart release is one runner pool. The runners
connect out to imbi-api to claim agent tasks, so imbi-api needs no route to
them.

The chart has two pool modes (`pool.mode`):

- `deployment`: a Deployment with a fixed number of pods
  (`pool.replicas`). Each pod runs one chain of tasks, then deletes itself.
  The ReplicaSet then starts a clean pod.
- `scaledJob`: KEDA, which you install separately, starts one Job for each
  chain that the pool can claim. Each Job runs one chain and stops.

See [Agent Runners](../deployment/agent-runners.md).
