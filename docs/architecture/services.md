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

## URL Routing

Caddy routes requests to backend services based on path prefix:

| Path | Service |
|------|---------|
| `/api/*` | imbi-api |
| `/assistant/*` | imbi-assistant |
| `/gateway/*` | imbi-gateway |
| `/mcp/*` | imbi-mcp |
| `/*` | Static UI files |

The path prefix is stripped before forwarding to the backend service.

## Health Checks

Each service exposes a health check endpoint:

| Service | Endpoint |
|---------|----------|
| imbi-api | `GET /status` |
| imbi-assistant | `GET /status` |
| imbi-gateway | `GET /status` |

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
