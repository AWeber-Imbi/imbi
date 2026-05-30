# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

This is the **build and release** repo for Imbi. It does not contain application source code directly — it assembles all Imbi services (via git submodules) into a single Docker image with Caddy as a reverse proxy. The submodules live under `repositories/`:

- Services: `imbi-api`, `imbi-assistant`, `imbi-gateway`, `imbi-mcp`, `imbi-ui`
- Plugins: `imbi-plugin-aws`, `imbi-plugin-github`, `imbi-plugin-logzio`, `imbi-plugin-oidc`, `imbi-plugin-sonarqube`

`imbi-common` is consumed as a published dependency, **not** a submodule. `repositories/imbi-slackbot/` is vendored in-tree (committed here, not a submodule).

## Build Commands

Requires [just](https://github.com/casey/just) and Docker.

```bash
just build              # Build Docker image tagged :latest
just build v1.0.0       # Build with specific tag
just release v1.0.0     # Build tagged as both :v1.0.0 and :latest
just checkout-submodules # Check out submodules at their recorded commits
just update-submodules  # Update all submodules to latest on tracking branch
just update-submodules-tag v1.0.0  # Pin all submodules to a tag
just submodule-status   # Show current submodule commits
just docs               # Build MkDocs documentation
just docs-serve         # Serve docs locally on :8088
```

### Local Development (beta)

```bash
just bootstrap          # Build + start the compose stack, run setup, annotate Caddy routes
just teardown           # Tear down the compose stack and clear runtime/ caches
just start-dev imbi-api # Build + run a single service from local source, route traffic to it
just stop-dev imbi-api  # Scale the dev service down and route traffic back to the all-in-one image
```

The `runtime/` directory backs this workflow: `Dockerfile.python` builds a per-service dev
image (uv-based, mounts local source), `api-entrypoint.sh` is its entrypoint, `manage-caddy`
flips Caddy routes between the all-in-one `imbi` container and a standalone dev container via
the Caddy admin API, and `env-file` holds the local compose env vars.

## Running Locally

```bash
docker compose up --build -d                    # Start everything
docker compose exec -it imbi imbi-api setup     # First-time setup (creates admin user)
docker compose logs -f imbi                     # Tail logs
```

Only `imbi` is published on a fixed host port (`8080`). The backing services use
**ephemeral** host ports — find a mapping with `docker compose port <service> <container-port>`:

| Container port | Service |
|------|---------|
| 8080 | Imbi (Caddy → all backends + UI) — **fixed** host port |
| 5432 | PostgreSQL (Apache AGE graph DB) |
| 8123 | ClickHouse HTTP |
| 8025 | Mailpit (email testing UI) |
| 4566 | LocalStack (S3) |

The local stack uses PostgreSQL with Apache AGE as the graph database (no Neo4j). The
Helm chart, however, still ships a Neo4j subchart (`helm/imbi/values.yaml`) — legacy and
out of step with the compose stack.

## Docker Image Architecture

The Dockerfile is a multi-stage build:
1. **ui-builder** — `npm run build` on `repositories/imbi-ui`
2. **python-builder** — copies all of `repositories/`, builds a wheel for every Python project there (services + plugins), installs them into a venv at `/app`
3. **caddy** — extracts the Caddy binary
4. **sentry-cli** — extracts the Sentry CLI binary (used by `entrypoint.sh` to upload UI source maps)
5. **runtime** — slim Python image with the venv, Caddy, Sentry CLI, UI static files, and `entrypoint.sh`

## Caddy Routing (Caddyfile)

All services run on `:8080` behind Caddy:
- `/api/*` → imbi-api (:8000)
- `/assistant/*` → imbi-assistant (:8002)
- `/gateway/*` → imbi-gateway (:8003)
- `/mcp/*` → imbi-mcp (:8001)
- Everything else → static UI files from `/srv/ui`

## Entrypoint / Service Dispatch

`entrypoint.sh` uses `IMBI_SERVICE` env var (`all` | `api` | `assistant` | `gateway` | `mcp`) to start one or all services. Passing `setup` as argument runs `imbi-api setup` for initial bootstrapping.

## CI/CD

GitHub Actions (`.github/workflows/build-and-deploy.yaml`) triggers on tag pushes only. Builds multi-arch (amd64/arm64) images and pushes to both GHCR (`ghcr.io/aweber-imbi/imbi`) and DockerHub (`aweber/imbi`).

## Helm Chart

`helm/imbi/` contains a Kubernetes deployment chart with optional subchart dependencies for Neo4j, ClickHouse, and PostgreSQL. Set `neo4j.enabled`, `clickhouse.enabled`, `postgresql.enabled` to false and use `externalNeo4j.url` etc. for external databases.

## GitHub CLI

Always prefix `gh` commands with `GH_HOST=github.com` — the user's environment may have `GH_HOST` set to a GitHub Enterprise instance.
