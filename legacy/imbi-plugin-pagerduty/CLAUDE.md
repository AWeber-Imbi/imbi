# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## What This Is

The PagerDuty plugin for the Imbi platform (Plugin Architecture v3),
distributed as a single Python package (`imbi_plugin_pagerduty`). It ships
**one `Plugin`** (`PagerDutyPlugin`, slug `pagerduty`) exposing **three
capabilities** — `lifecycle`, `incidents`, `webhook-actions` — each bound
to a handler class via its `Capability` entry. The package root
`__init__.py` exposes the plugin as the module-level `PLUGIN` attribute;
the Imbi host discovers it by the `imbi_plugin_*` naming convention. There
are **no entry points** — adding a capability means adding a `Capability`
to the manifest.

The REST API key credential and the escalation-policy / gateway options
are declared **once** at the Integration (manifest) level and shared by
every capability. Capabilities read integration options from
`ctx.integration_options` and receive the decrypted credential blob as
their `credentials` argument.

All plugin base classes (`Plugin`, `PluginManifest`, `Capability`,
`LifecycleCapability`, `IncidentsCapability`, `WebhookActionsCapability`,
`PluginContext`, the result / writeback types) come from
`imbi_common.plugins`. Read that module (in the sibling `imbi-common`
repo) before changing a handler's method signatures.

Unlike the GitHub plugin, **PagerDuty is cloud-only**: a single
`api.pagerduty.com` host and one REST API key credential, so there is no
host-flavor base/subclass pattern.

## Commands

```bash
just setup              # uv sync --all-groups --all-extras + pre-commit hooks
just test               # coverage run -m pytest (fails under 85%)
just test tests/test_lifecycle.py                  # one file (no coverage)
just lint               # pre-commit (ruff, ruff-format, tombi, basedpyright)
just format [FILES]     # ruff-format + tombi-format
```

Python is pinned to **3.14**; ruff uses single quotes and a 79-char line
length; type checking is `basedpyright` in **strict** mode over `src`.

## Architecture

- `__init__.py` — the `PagerDutyPlugin` (`Plugin` subclass) and its
  `PluginManifest`: integration-level options + the single `api_key`
  credential, plus the three `Capability` entries binding the handlers.
  Exposes the module-level `PLUGIN = PagerDutyPlugin` the host discovers.
- `_client.py` — the shared PagerDuty REST client factory
  (`api.pagerduty.com`, `Authorization: Token token=<key>`). An httpx
  response hook maps `401` → `PluginAuthenticationFailed` and `429` →
  `PluginRateLimited` (absolute resume epoch from `ratelimit-reset`).
- `_services.py` — resolves a project's PagerDuty service: the
  `pagerduty-service` link first, then an exact-name lookup on the
  project slug (and the pre-rename slug).
- `lifecycle.py` — `PagerDutyLifecycle` (`LifecycleCapability`). Manages
  the service + escalation-policy routing (`team_escalation_policy_mapping`,
  read from `ctx.integration_options`) + a per-service V3 webhook
  subscription. Writes results through `ctx.service_writeback`: the host
  persists the `EXISTS_IN` edge (service id + the **encrypted** webhook
  signing secret the gateway verifies against) and the `pagerduty-service`
  dashboard link. The subscription's signing secret is returned by
  PagerDuty **only once**, at creation, and is encrypted (via
  `imbi_common` `TokenEncryption`) before it leaves the plugin.
  `on_project_deleted` finds the subscription by listing
  `/webhook_subscriptions` and matching `filter.id` (no subscription id is
  persisted).
- `webhook.py` — `PagerDutyWebhookActions` (`WebhookActionsCapability`), a
  v1 stub (`actions() -> []`); incident events are captured by the
  gateway's built-in recording.
- `incidents.py` — `PagerDutyIncidents.list_incidents`
  (`IncidentsCapability`), a paginated live query of `/incidents` for the
  project's service.
- `models.py` — maps PagerDuty incident payloads to `IncidentView`.

### PagerDuty-API assumptions to confirm against a live tenant

- The create-subscription response exposes the signing secret at
  `webhook_subscription.delivery_method.secret`.
- A service's webhook subscriptions are found by listing
  `/webhook_subscriptions` and matching `filter.id` (there is no
  documented server-side service filter).
- `/incidents` paginates via `offset`/`more`; the opaque tab cursor is
  the next `offset`.

## Testing

Tests mock PagerDuty's HTTP with **respx** (`asyncio_mode = auto`, so
async tests need no decorator). Build a `PluginContext` with the relevant
project links and `integration_options`, and pass `{'api_key': ...}`
credentials, mirroring how the host calls in. `test_plugin.py` covers the
aggregate manifest (slug, capabilities, handler bindings, `PLUGIN`).
Coverage must stay ≥ 85%.

## Dependency Management

**NEVER edit `pyproject.toml` dependencies by hand** — use `uv add` /
`uv remove`. The package pins to PyPI with a 7-day `exclude-newer`
holdback; `imbi-common` is tracked from git `main` until 2.11 ships (see
the `[tool.uv.sources]` comment), then the pin moves to `==2.11.x`. After
changing dependencies, run `uv sync` and verify `uv.lock`.
