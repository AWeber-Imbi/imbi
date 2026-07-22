# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## What This Repo Is

The Imbi platform monorepo — a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)
containing every Imbi service, library, and first-party plugin, plus the
production Docker image, Helm chart, docs site, and the Okteto dev
environment. Imbi is a DevOps Service Management Platform (FastAPI,
PostgreSQL + Apache AGE graph, ClickHouse analytics, React UI).

## Layout

| Path | Distribution | Import path |
|---|---|---|
| `libraries/common/` | `imbi-common` | `imbi.common` |
| `apps/api/` | `imbi-api` (:8000) | `imbi.api` |
| `apps/assistant/` | `imbi-assistant` (:8002) | `imbi.assistant` |
| `apps/gateway/` | `imbi-gateway` (:8003) | `imbi.gateway` |
| `apps/mcp/` | `imbi-mcp` (:8001) | `imbi.mcp` |
| `apps/slackbot/` | `imbi-slackbot` (:8004) | `imbi.slackbot` |
| `apps/ui/` | npm package (Vite :5173) | — |
| `plugins/<name>/` | `imbi-plugin-<name>` | `imbi.plugins.<name>` |
| root `pyproject.toml` | `imbi` meta-package (installs everything) | — |

`imbi` is an implicit namespace package spanning members — there is no
`src/imbi/__init__.py` anywhere. Tests are merged at the root:
`tests/<suite>/` (e.g. `tests/common/`, `tests/api/`,
`tests/plugins/github/`), each a package so duplicate basenames collect
cleanly. Docs are one mkdocs site rooted at `docs/mkdocs.yml`.

All members share one `uv.lock`, one `.venv`, and the root tool config
(ruff, basedpyright, mypy, coverage, pytest). Versions are lockstep:
every member and the meta-package carry the same version, bumped
together in one commit and released with one `v<version>` tag.

## Common Commands

```bash
just setup                 # uv sync --all-groups --all-extras + pre-commit hooks
just test                  # full suite w/ docker backing services (compose.ci.yaml)
just test tests/api/...    # single file/suite (pytest syntax)
just test-suite common 90  # one suite with its own coverage floor
just lint                  # pre-commit run --all-files + basedpyright
just format [FILES]        # ruff + tombi via pre-commit
just docs / docs-serve     # mkdocs build --strict / local serve
just ui-lint / ui-test     # npm lint+format:check / vitest (apps/ui)
just build [tag]           # build the production Docker image
just bootstrap / teardown  # run/destroy the prod image locally (compose.yaml)
just start / stop          # Okteto dev env: deploy + kubefwd + okteto up sessions
just seed                  # imbi-api setup inside the Okteto pod
just sync-prod-to-dev      # refresh dev databases from production backups
```

Test env vars are written to `.env.test` by the docker recipe (never
`.env`, which holds Okteto secrets). Tests that need PostgreSQL are
gated on `POSTGRES_URL` via the root `tests/conftest.py`.

## Conventions

- Line length 79, single quotes, Python 3.14+, strict typing
  (basedpyright + mypy). Rule set is unioned in the root pyproject with
  per-subtree ignores being burned down over time.
- Run `just format` on modified files before returning control, running
  tests, or committing. Never `--no-verify`.
- Cross-member deps are exact lockstep pins (`imbi-common==<version>`)
  resolved from the workspace during development (`[tool.uv.sources]`).
- Console-script names (`imbi-api`, `imbi-gateway`, …) are load-bearing:
  `entrypoint.sh`, the Caddyfile, and the Helm chart dispatch on them.
- Plugins are discovered by scanning `imbi.plugins.*` (first-party) and
  top-level `imbi_plugin_*` modules (third-party) — no entry points.
  `IMBI_PLUGINS_DISABLED` turns individual plugins off by slug.
- Apache AGE does not implement Cypher `FOR EACH` — use `UNWIND` or
  iterate in app code. Cypher params use `{param}`, property maps
  double-escape braces, timestamps are ISO strings.

## Releasing

Bump the version in the root pyproject **and every member pyproject**
(lockstep), `uv lock`, commit, tag `v<version>`, push the tag.
`release.yml` then builds the multi-arch Docker image
(ghcr.io/aweber-imbi/imbi + aweber/imbi) and publishes every member
wheel plus the `imbi` meta-package to PyPI via trusted publishing. The
tag must match the pyproject version or the publish fails fast.

## CI

`test.yml` (python lint+test, ui lint+test), `docs.yml` (Pages deploy of
the merged site), `release.yml` (tag-driven image + PyPI publish).
Reproduce CI failures locally with `just ci` before pushing.
