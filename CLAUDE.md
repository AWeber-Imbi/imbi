# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

This is the **build and release** repo for Imbi. It does not contain application source code directly — it assembles all Imbi services (via git submodules) into a single Docker image with Caddy as a reverse proxy. The actual service code lives in separate repos:

- `imbi-api/`, `imbi-assistant/`, `imbi-common/`, `imbi-gateway/`, `imbi-mcp/`, `imbi-ui/` (all submodules)

## Build Commands

Requires [just](https://github.com/casey/just) and Docker.

```bash
just build              # Build Docker image tagged :latest
just build v1.0.0       # Build with specific tag
just release v1.0.0     # Build tagged as both :v1.0.0 and :latest
just update-submodules  # Update all submodules to latest on tracking branch
just update-submodules-tag v1.0.0  # Pin all submodules to a tag
just submodule-status   # Show current submodule commits
just docs               # Build MkDocs documentation
just docs-serve         # Serve docs locally on :8088
```

## Running Locally

```bash
docker compose up --build -d                    # Start everything
docker compose exec -it imbi imbi-api setup     # First-time setup (creates admin user)
docker compose logs -f imbi                     # Tail logs
```

Services available after startup:

| Port | Service |
|------|---------|
| 8080 | Imbi (Caddy → all backends + UI) |
| 7474 | Neo4j Browser |
| 8123 | ClickHouse HTTP |
| 8025 | Mailpit (email testing) |
| 4566 | LocalStack (S3) |
| 5432 | PostgreSQL |

## Docker Image Architecture

The Dockerfile is a multi-stage build:
1. **ui-builder** — `npm ci && npm run build` on imbi-ui
2. **python-builder** — builds wheels for all Python services (imbi-common, imbi-api, imbi-assistant, imbi-gateway, imbi-mcp), installs into a venv at `/app`
3. **caddy** — extracts the Caddy binary
4. **runtime** — slim Python image with the venv, Caddy, UI static files, and `entrypoint.sh`

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
