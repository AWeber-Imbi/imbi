# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A set of GitHub plugins for the Imbi platform, distributed as a single
Python package (`imbi_plugin_github`). It ships **three plugin types**
(identity, deployment, lifecycle), each in **three host flavors**
(github.com, GitHub Enterprise Cloud, GitHub Enterprise Server) — nine
plugins total. The Imbi host discovers them through the
`imbi.plugins` entry points declared in `pyproject.toml`; that table is
the registration surface — adding a plugin class means adding an entry
point there.

All plugin base classes (`IdentityPlugin`, `DeploymentPlugin`,
`LifecyclePlugin`, `PluginContext`, `PluginManifest`, the result/dataclass
types) come from `imbi_common.plugins.base`. That module is the contract
this package implements against; read it (in the sibling `imbi-common`
repo) before changing a plugin's method signatures.

## Commands

```bash
just setup              # uv sync --all-groups --all-extras + install pre-commit hooks
just test               # coverage run -m pytest tests + coverage report/xml (fails under 85%)
just test tests/test_lifecycle.py                       # one file
just test tests/test_lifecycle.py::ManifestTestCase     # one class/test (passed straight to pytest)
just lint               # pre-commit run --all-files (ruff, ruff-format, tombi, basedpyright)
just format [FILES]     # ruff-format + tombi-format
```

`just test` with arguments skips the coverage wrapper and runs `pytest`
directly. `.env`, if present, is passed via `--env-file` (not required
for the test suite). Type checking is `basedpyright` in **strict** mode
over `src`. Python is pinned to **3.14**; ruff uses single quotes and a
79-char line length.

## Architecture

### The base/subclass/host-flavor pattern

Every plugin type follows the same shape: one `_*Base` class holds all
behavior, and three thin concrete subclasses differ *only* in their
`_resolve_host(options)` classmethod:

- github.com flavor → returns `'github.com'`.
- GHEC flavor → reads the required `host` option, validates it's a
  `*.ghe.com` tenant via `require_ghec_tenant_host`.
- GHES flavor → reads the required `host` option, normalized only.

`_resolve_host` feeds URL construction, and the three backends route
differently — this mapping is the single most important thing to keep
consistent and is **duplicated** across the three modules
(`identity._endpoints`, `deployment._api_base`, `lifecycle._api_base`):

| Host                | REST API base                  | OAuth base (identity only)        |
| ------------------- | ------------------------------ | --------------------------------- |
| `github.com`        | `https://api.github.com`       | `https://github.com/login/oauth`  |
| `<tenant>.ghe.com`  | `https://api.<tenant>.ghe.com` | `https://<tenant>.ghe.com/login/oauth` |
| GHES `<host>`       | `https://<host>/api/v3`        | `https://<host>/login/oauth`      |

When you change routing for one plugin type, check whether the other two
need the same change.

### Shared helpers (single sources of truth)

- `_hosts.py` — `normalize_host` (strip/validate a bare hostname, reject
  paths/ports/queries) and `require_ghec_tenant_host`. All host-option
  validation lives here.
- `_repos.py` — `resolve_owner_repo(ctx, host, label)` derives the target
  `(owner, repo)` for deployment and lifecycle calls: it scans
  `ctx.project_links` (preferring the `github-repository` key, skipping
  reserved GitHub path prefixes like `/orgs/`), then falls back to
  `<project_type_slug>/<project_slug>`, and raises `ValueError` with an
  operator-facing message when neither works.

### Plugin invocation contract

Plugins are **stateless and single-shot**: the host constructs the
plugin once and calls methods passing `PluginContext` plus a
`credentials` dict per call. Identity plugins mint the OAuth access
token; deployment and lifecycle plugins consume it via
`credentials['access_token']` (with a `'token'` fallback) and send it as
a `Bearer` header. A `401` response is converted to
`PluginAuthenticationFailed` by an httpx response hook so the host's
retry layer can refresh the actor's identity once before failing the
user-visible request.

### Behaviors that span multiple files / aren't obvious from one method

- **Deployment uses the GitHub Deployments API**, not
  `workflow_dispatch`: Imbi's `Environment` maps 1:1 to GitHub's
  `environment` so protection rules apply server-side. `trigger_deployment`
  sends `auto_merge=False` and `required_contexts=[]` deliberately.
  Promote behavior (semver tag → Deployment vs. raw SHA → tag + Release)
  is decided **host-side** in imbi-api, not here. Per-environment workflow
  inputs ride on the `USES_PLUGIN` graph edge as `env_payloads` and arrive
  as `ctx.environment_config`.
- **`/check-runs` 403 cache** in `deployment.py`: a process-wide,
  TTL'd cache (keyed by a hash of token+host+repo) suppresses repeated
  403s when the token lacks scope or Actions is disabled, so opening a
  deploy dialog doesn't fire one wasted 403 per commit.
- **Lifecycle archive-with-transfer dance** (`lifecycle.py`): when
  `archive_target_org` is set, archive transfers the repo there first.
  GitHub refuses to transfer an *archived* repo, so an already-archived
  source is briefly unarchived → transferred → re-archived. GitHub's
  transfer is **async** (returns 202, repo briefly 404s at the
  destination), so the post-transfer archive PATCH retries on 404 with a
  bounded backoff (`_TRANSFER_ARCHIVE_BACKOFFS`). Unarchive only flips
  `archived` back at the repo's current location — it never transfers
  back, because the original owner isn't tracked.

## Testing

Tests mock GitHub's HTTP with **respx** (`asyncio_mode = auto`, so async
tests need no decorator). Each test builds a `PluginContext` with a
`github-repository` project link and passes `{'access_token': ...}`
credentials, mirroring how the host calls in. When adding a GitHub API
call, add the matching respx route. Coverage must stay ≥ 85%.

## Dependency Management

`pyproject.toml` pins the package to PyPI (`pypi.org`) with a 7-day
`exclude-newer` holdback on third-party packages; the imbi-common and
`imbi-plugin-*` packages are exempt via `exclude-newer-package` so local
ecosystem changes aren't held back. After changing dependencies, run
`uv sync` and verify `uv.lock`.
