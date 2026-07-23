# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## What This Repo Is

The Imbi platform monorepo — a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)
containing every Imbi service, library, and first-party plugin, plus the
production Docker image, Helm chart, and docs site. (Per-developer
remote-dev orchestration, e.g. Okteto, lives outside this repo.) Imbi is a DevOps Service Management Platform (FastAPI,
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
| `ui/` | npm package (Vite :5173) | — |
| `plugins/<name>/` | `imbi-plugin-<name>` | `imbi.plugins.<name>` |
| root `pyproject.toml` | `imbi` meta-package (installs everything) | — |

`imbi` is an implicit namespace package spanning members — there is no
`src/imbi/__init__.py` anywhere. Every member carries its own tests
(`libraries/common/tests/`, `apps/api/tests/`, `plugins/github/tests/`);
pytest runs them all in one session using `--import-mode=importlib` +
namespace packages, and test helpers import rootdir-anchored
(`apps.api.tests.support`). Docs are one Zensical site configured by the
repo-root `mkdocs.yml` (Zensical natively reads the mkdocs.yml config); the
Markdown content is the sibling `docs/` dir and the build output is `site/`.
Docs are a root-project concern (`moon run root:docs-build`), not a separate
moon project.

All members share one `uv.lock`, one `.venv`, and the root tool config
(ruff, basedpyright, mypy, coverage, pytest). Versions are lockstep:
every member and the meta-package carry the same version, bumped
together in one commit and released with one `v<version>` tag.

## Common Commands

[moon](https://moonrepo.dev) (`.moon/`) is the task runner and owns
lint/format/typecheck/test/build/docs plus the docker service + image
tasks. Toolchains (python 3.14, uv, node, npm) are pinned in `.prototools`
and downloaded/managed by moon on first use. Run `moon query tasks` to see
everything.

```bash
moon ci                    # full pipeline (lint/format/typecheck, ui, docs,
                           #   single-session coverage, docker image test build)
moon run <proj>:<task>     # one task, e.g. `moon run api:test`, `moon run ui:build`
moon run :lint             # a task across every project

moon run root:setup        # toolchains, deps, pre-commit
moon run root:services     # boot backing services (compose.ci.yaml + .env.test)
moon run root:teardown     # tear down backing services and volumes
moon run root:coverage     # full suite, single session, aggregate coverage
moon run api:test          # one member's suite in isolation
moon run :lint :typecheck :format   # lint + type-check + format-check everything
uv run pre-commit run --all-files   # ruff + tombi (write mode) — reformat
moon run root:docs-build   # build docs; root:docs-serve to preview locally
moon run root:image        # production image, no push
```

Run the prod image locally with `docker compose up --build` (compose.yaml).

Task granularity: per-member `test` tasks are for targeted local runs and are
`runInCI: false` (the suite shares one database with no per-process isolation);
CI runs the single-session `root:coverage` instead. Coverage is scoped
per-member: each member's `[tool.coverage]` (in its own `pyproject.toml`) sets
its source + `fail_under`, and the shared test task reads it via
`--cov-config=$projectSource/pyproject.toml` — so `moon run <member>:test`
reports/gates on that member alone, while `root:coverage` uses the root
config's repo-wide `source_pkgs = ["imbi"]`. Cross-member edges are explicit
`dependsOn: [common]` in each member's `moon.yml`. Test env vars are written to
`.env.test` by `root:services`.

Running specific tests: `moon run <member>:test` always runs that member's
whole suite — the task hardcodes its `tests/` dir, so passing a file path
(`moon run <member>:test -- apps/foo/tests/test_x.py`) does **not** narrow it
(pytest just re-collects the dir). To filter within a member, forward pytest
flags after `--`: `moon run <member>:test -- -k <expr>` (or `-m <marker>`,
`-x`, …). To run a single file or node in isolation, bypass moon and call
pytest directly after booting services once:

```bash
moon run root:services   # boots DBs, writes .env.test (once per session)
uv run --env-file .env.test pytest apps/slackbot/tests/test_agent.py::TestAgent::test_x
```

## Conventions

- Line length 79, single quotes, Python 3.14+, strict typing
  (basedpyright + mypy). Rule set is unioned in the root pyproject with
  per-subtree ignores being burned down over time.
- Run `uv run pre-commit run --files <paths>` (ruff + tombi, write mode) on
  modified files before returning control, running tests, or committing.
  Never `--no-verify`.
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
Reproduce CI failures locally with `moon ci` before pushing.
