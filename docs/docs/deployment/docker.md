# Docker Deployment

The Imbi Docker image packages all services into a single container that
can run everything together or individual services for scaled-out
deployments.

## All-in-One Mode

By default, the container starts all services behind a Caddy reverse proxy:

```bash
docker run -p 8080:8080 \
  -e CLICKHOUSE_URL=http://default:password@clickhouse:8123/imbi \
  -e POSTGRES_URL=postgresql://user:pass@postgres/imbi \
  -e IMBI_AUTH_JWT_SECRET=your-secret \
  -e IMBI_AUTH_ENCRYPTION_KEY=your-key \
  ghcr.io/aweber-imbi/imbi:latest
```

This starts:

| Port | Service |
|------|---------|
| 8080 | Caddy (public, routes to all services) |
| 8000 | imbi-api (internal) |
| 8001 | imbi-mcp (internal) |
| 8002 | imbi-assistant (internal) |
| 8003 | imbi-gateway (internal) |

## Individual Services

For production deployments where you want to scale services independently,
set `IMBI_SERVICE` to run a single service:

```bash
# Run only the API
docker run -p 8000:8000 \
  -e IMBI_SERVICE=api \
  -e CLICKHOUSE_URL=http://default:password@clickhouse:8123/imbi \
  -e IMBI_AUTH_JWT_SECRET=your-secret \
  -e IMBI_AUTH_ENCRYPTION_KEY=your-key \
  ghcr.io/aweber-imbi/imbi:latest
```

When running individual services, Caddy is not started. You are
responsible for providing your own reverse proxy or load balancer.

## Running Setup

The `setup` command initializes the authentication system:

```bash
docker run -it \
  -e CLICKHOUSE_URL=http://default:password@clickhouse:8123/imbi \
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
